# PSCAD Results Analysis Methods

Last reviewed: 2026-08-14

This document describes the methods implemented by the current app. It is a code-level description of the data flow and calculations, not a replacement for the PSCAD model specification or an engineering acceptance standard.

The main implementation modules are:

- `src/results_analysis_app/project_config.py` - project timing, frequency, voltage, and `Um` inputs.
- `src/results_analysis_app/scanner.py` - project discovery, NonConv proposals, and PSCAD-log high-voltage proposals.
- `src/results_analysis_app/voltage_envelope.py` - raw waveform reads, high-voltage checks, per-run envelopes, and envelope workbook data.
- `src/results_analysis_app/resonance_checks.py` - Stress, Late Growth, and No-settle Growth checks.
- `src/results_analysis_app/envelope_chart.py` - Excel envelope and resonance charts.
- `src/results_analysis_app/analysis_engine.py` - event and resonance plot batches, embedded waveform rendering, and Excel exports.
- `src/results_analysis_app/reporting.py` - DOCX report assembly from generated outputs.

## 1. End-to-end method

For each selected project, scope, and voltage, the app follows this sequence:

1. Read or restore the project scan. The scan identifies `.inf` run descriptors, project timing, frequency, voltage levels, existing outputs, NonConv proposals, and (when available) PSCAD-log high-voltage candidates.
2. Resolve the selected voltage configuration from `Input_Data_PSCAD*.xlsx` and `.inf` signal prefixes. The configuration supplies the MM bus prefix and `Um`.
3. Apply the selected Manual and NonConv exclusions before submitting waveform work. High Voltage rows are checked against raw waveforms during the build itself; an unchecked High Voltage row creates an exact include override.
4. Read the selected raw `.out` channels, check high voltage, and create a chronological rolling envelope for every surviving case/run/bus and measurement type.
5. Merge the per-run phase candidates into the base `MM_<voltage>.xlsx` workbook, preserving the source Case, Run, fault type, and MM name for each phase and for the overall maximum.
6. If enabled, run the Stress/Late/No-settle checks from the chronological per-run envelope data already in memory. These checks do not reread raw `.out` files.
7. Write the base workbook, resonance workbook, combined Excel charts, plot batches, rendered waveform plots, and DOCX reports through the selected workflow steps.

Voltage levels are processed sequentially. Runs within one voltage use one shared bounded process pool. The automatic worker setting selects logical CPUs minus one, capped at 60 and reduced when fewer runs exist.

## 2. Input data and identity

### 2.1 Run and channel mapping

Each PSCAD run is represented by an `.inf` file under `Case_folder`. The shared waveform reader parses its `PGB`, `Desc`, `Group`, and `Units` descriptors.

For a descriptor with PGB number `n`, the legacy PSCAD mapping is:

```text
output file number = floor((n - 1) / 10) + 1
output column      = ((n - 1) mod 10) + 1
```

The corresponding output file is `<inf stem>_<file number:02d>.out`. The first `.out` column is time. The app groups all requested columns belonging to one output file and reads that file once for the run. Only the time column and requested signal columns are loaded.

Run identity comes from the `.inf` filename parser and is represented as `(Case, Run)`. A bus identity is the MM `Group`, for example `MM_161_...`. A voltage-specific High Voltage identity is `(voltage, Case, Run, MM bus)`.

### 2.2 Project timing, frequency, and voltage

`Input_Data_PSCAD*.xlsx` is read from the project root:

- `Input_Data` supplies `Frequency` and `Final duration` when present. Cell `B16` is the frequency fallback location.
- `MM_blocks` supplies the voltage/`Un` and `Um` values and identifies the MM bus prefix.

If a project configuration is incomplete, voltage prefixes can still be discovered from `.inf` groups and `Um` can be supplied as a project-specific Settings override. If automatic frequency detection fails, the project frequency is used first, then the Settings fallback (default 50 Hz).

### 2.3 Fault type mapping

`Statistic*.out` files are read once per build. Their `Case` and `Run#` rows are joined to envelope provenance. The current numeric fault mapping is:

| Statistic value | Displayed fault type |
|---:|---|
| `0` | `None` |
| `1` | `AG` |
| `4` | `ABG` |
| `7` | `ABCG` |
| `8` | `AB` |
| `11` | `ABC` |

Unknown or missing mappings remain blank rather than being guessed.

## 3. Exclusions and high-voltage method

### 3.1 Manual and NonConv exclusions

Manual rules are Case/Run/Bus matchers. Blank fields are wildcards; a completely blank row is ignored. NonConv proposals come from `CB_*.out` summary files:

- `CB_IIp` is flagged when `abs(value) > 400` by default.
- `CB_IIr` is flagged when `abs(value) > 200` by default.
- Non-numeric, NaN, and non-finite current values are also reported.

NonConv rules are applied at Case/Run scope across buses. Matching runs are removed before raw voltage workers are submitted.

### 3.2 PSCAD-log proposals

When `PSCAD_log.txt` contains a treated warning matching:

```text
WARNING: <case> - <MM bus> has very high values
```

the project-opening scan locates every matching run, reads only the relevant LGp/LLp waveform columns, and records one maximum per Case/Run/MM bus. The configured limit and `Um` then classify those maxima into High Voltage rows. Therefore `PSCAD log` identifies the origin of the proposal; it is not a text-only decision.

If no PSCAD log exists, no log-derived proposal scan is performed during project opening. The full envelope build still performs its own raw waveform high-voltage check for all selected runs.

### 3.3 Authoritative envelope high-voltage check

During the envelope build, the limit is:

```text
HV limit = high-voltage factor × Um × sqrt(2)
```

The default factor is `5.0`. For every selected run, the app checks both `LGp` and `LLp`, and every phase channel belonging to each bus. For each phase it computes `abs(raw waveform)` and compares every finite sample with the limit.

If any one phase exceeds the limit:

1. a detailed exclusion record is created with measurement, signal, source `.out` file, excluded sample count, maximum absolute value, and limit;
2. the bus is marked high voltage for that Case/Run;
3. that bus is removed from both the LGp and LLp envelope candidates for that Case/Run.

This build-time scan is the authoritative all-case check and can find violations absent from the PSCAD log. The UI consolidates rows by voltage/Case/Run/MM bus and shows `PSCAD log`, `Analysis`, or `Both`. An unchecked UI row stores an exact include override, allowing that voltage/Case/Run/MM bus through the automatic threshold check on the next build.

The workbook sheet `High voltage exclusions` retains the established detailed columns:

```text
Case, Run, Fault_type, MM_name, Measurement, Signal,
File, Excluded_values, Max_abs, Limit
```

The UI source column is intentionally an application-level consolidated view; it is not added to this workbook schema.

## 4. Envelope construction

### 4.1 Per-run waveform preparation

For each surviving run and MM bus, the app gathers phase arrays for `LGp` and `LLp`.

- If all phases share the same time base, NumPy arrays are processed directly.
- If phase time bases differ, they are outer-joined by time and processed through the common DataFrame path.
- A phase with no finite/non-trivial signal is dropped. A bus with no remaining phase data produces no envelope row.

The detected frequency is taken from zero crossings when enough crossings are present. Otherwise the project/Input_Data frequency or Settings fallback is logged and used. The raw sample interval is the median positive time difference.

### 4.2 Rolling and resampling

For each phase, the app first takes the absolute value and applies a centered rolling maximum. The rolling window is one half-cycle:

```text
window samples = max(1, int((1 / (2 × frequency)) / raw dt))
```

The result is sampled onto a regular grid using the configured envelope time step (default `0.002 s`).

The envelope end is automatic by default:

- `Use project duration` uses `Input_Data` `Final duration`.
- Every run is capped again at its own last finite waveform time.
- Clearing the option enables a manual upper limit; the project duration remains an upper cap when it is shorter.

For mixed-length results, a run ending at `0.5 s` contributes only through its available end while a run ending at `1.0 s` contributes through `1.0 s`. Missing tail rows are represented as NaN/missing data, not zeros. The merge ignores those missing rows, so the short run cannot create an artificial zero envelope. When phases within one run have different ends, the common valid time range is used; normal PSCAD output has equal phase lengths.

### 4.3 Representative envelope merge

The per-run phase envelopes are merged separately for phase A, B, and C. The current method follows the original representative-envelope algorithm:

1. sort each source phase envelope by descending magnitude;
2. align the ranked source rows by the synthetic envelope index;
3. take the maximum across sources at each ranked position;
4. carry the Case, Run, MM name, and mapped fault type from the source that supplied that maximum.

The workbook `Time (s)` column is therefore the regular representative-envelope index (`row × envelope time step`) after this ranking operation. It is not the original timestamp of one individual case/run. The intermediate per-run data used by the resonance checks remains chronological.

`Max_all` is the row-wise maximum of `Max_A`, `Max_B`, and `Max_C`; its Case/Run/fault/MM provenance comes from the phase that supplied `Max_all`. Ties retain the existing stable source-order behavior.

### 4.4 Envelope workbook and charts

Each selected scope/voltage writes:

```text
Voltage_envelope/<scope>/MM_<voltage>.xlsx
```

The base workbook contains `LGp`, `LLp`, `NonConv cases`, and `High voltage exclusions`. Headers are frozen/filtered and the existing workbook structure is kept. Excel's native AutoFit is applied to used columns through the already-packaged Excel automation support.

The combined chart workbook is a copy of the base workbook with an Excel XY chart. It plots `Max_all` from the LGp and LLp sheets and adds event labels for SFO/TOV (and optionally SA). Chart x limits are the smaller of the configured/project chart limit and the available generated data duration. Envelope chart settings are separate from envelope-build duration, although both default to project duration when automatic mode is enabled.

## 5. Stress, Late Growth, and No-settle checks

### 5.1 Common analysis data

Checks run immediately after the per-run rolling envelopes are created and before the representative workbook merge. For each bus/run and each voltage type (`LGp` and `LLp`), the app forms a chronological envelope:

```text
E(t) = max(valid phase envelope values at time t)
```

Raw `.out` files are not reread. Each record retains its Case, Run, MM bus, voltage type, nominal voltage, time vector, and `E(t)`.

The analysis limit is:

```text
Vlim = nominal voltage × resonance limit multiplier
```

The default multiplier is `sqrt(3) = 1.7321`. This is intentionally based on the nominal voltage level, not the High Voltage `Um` limit.

The analysis guard time is:

```text
t_guard = SFO time + TOV time
```

with defaults `0.004 s + 0.030 s = 0.034 s`.

Before the checks, `E(t)` is smoothed with a trailing rolling 95th percentile. The window is the larger of the configured time window (default `0.020 s`) converted to samples and the minimum sample count (default `10`).

### 5.2 Release/recovery detection

With automatic release enabled (default):

1. search for the post-guard peak, preferring the first configured fraction of the post-guard interval (default `25%`);
2. after a candidate peak, search for a hold window (default `0.050 s`) where the smoothed level falls below `0.80 × peak` and does not rebound above `0.95 × peak`;
3. the first qualifying time is the release time and becomes `t_start` for Stress and Late Growth.

If no release is found, the No-settle check may be evaluated. With automatic release disabled, the manual analysis start time is used instead and No-settle is removed from the effective checks.

### 5.3 Post-event Stress

Stress is evaluated from `t_start` to the end of the available chronological record. It is reported only when the area above `Vlim` is positive:

```text
A_post = integral(max(0, E(t) - Vlim), t_start, t_end)
```

The result also records time above the limit and the post-start peak. Results are ranked by `A_post`.

### 5.4 Late Growth

Late Growth divides the post-start data into adjacent previous and tail windows. The window length is the larger of:

```text
growth window fraction × (t_end - t_start)
minimum sample count × median dt
```

The check computes the previous/tail p95 values, tail growth ratio, tail growth delta, fraction of positive successive changes, and a log-linear slope:

```text
sigma = slope of log(max(smoothed E(t), log floor)) versus time
```

The result must have positive slope and pass the configured relevance gate: sufficient positive fraction and either sufficient level over `Vlim` or sufficient growth ratio and absolute growth delta. Results are ranked primarily by positive tail slope.

### 5.5 No-settle Growth

No-settle is considered only when automatic release detection is enabled and no release was found. It compares an early post-guard window with a final tail window using p95, growth ratio, growth delta, positive fraction, positive-window count, log slope, and area above `Vlim`. It uses the same positive-slope and relevance gate as Late Growth, with the full post-guard record used for the positive-fraction calculation.

### 5.6 Ranking and outputs

Results are grouped independently by:

```text
(check, voltage, voltage type)
```

Only the configured Top N results per group are written (default `1`). The workbook is:

```text
Voltage_envelope/<scope>/Resonance_Checks.xlsx
```

It contains `Settings`, result tabs only for checks/voltage types with findings, and one chart-data sheet per result. If there are no findings, `Settings` is retained without empty result tabs.

Resonance charts use the same chart x-axis settings as envelope charts and are capped by each result's actual data end. A chart displaying `0.5 s` can therefore be a chart-axis setting even when the underlying analysis data extend farther; changing the chart x maximum does not rebuild envelope data.

## 6. Event plots and reports

The event selection method uses envelope workbook rows to choose representative Case/Run/MM points:

| Event | Source sheet | Trace |
|---|---|---|
| `TOV` | `LLp` | Both |
| `SFO` | `LLp` | Both |
| `SA` | `LGp` | LGp |

The selected row is the nearest time to the configured event time. Exact matches are preferred; a nearest match is accepted within `0.001 s`. Defaults are SFO `0.004 s`, TOV `0.030 s`, and SA `0.100 s`.

Those Case/Run/MM selections are written to plot batch workbooks. The embedded MM plotting engine then reads the raw waveform data for the requested plot/export. Resonance plot batches are built from the result tabs in `Resonance_Checks.xlsx`, not by re-running the checks.

Reports reuse the generated dashboard, envelope, waveform, and resonance plot outputs. Envelope summary values use the same nearest-time helper as plot batch selection, so reports and event batches do not implement separate time-selection rules.

## 7. Settings that change the method

The following values are persisted in the session and passed into the build/check functions:

| Setting | Default/current behavior |
|---|---|
| Envelope time step | `0.002 s` |
| Envelope time end | Project `Final duration` automatically; manual positive cap when automatic mode is cleared; `1.0 s` fallback if timing is unavailable |
| Envelope workers | Automatic logical CPU selection, capped at `60`; manual override available |
| Frequency fallback | `50 Hz`, superseded by project `Input_Data` frequency when available |
| High Voltage factor | `5.0 × Um × sqrt(2)` |
| NonConv `CB_IIp` / `CB_IIr` | `400` / `200` |
| Resonance Top N | `1` per check/voltage/type |
| Resonance multiplier | `sqrt(3)` |
| Release mode | Automatic by default |
| Rolling p95 window / minimum samples | `0.020 s` / `10` |
| Growth window fraction | `0.20` |
| Minimum positive fraction | `0.60` |
| Minimum growth ratio | `1.05` |
| Minimum level over `Vlim` | `0.50` |
| Minimum growth delta | `0.01 × Vlim` |

Changing envelope-build duration or High Voltage settings requires running the envelope build again to regenerate the affected workbook data. Changing chart-axis settings only requires rebuilding charts. Changing resonance thresholds requires rebuilding the checks; rebuilding only the charts does not recalculate findings.

## 8. Important interpretation limits

- The High Voltage threshold and the resonance `Vlim` are different calculations and use different configured quantities.
- The base envelope workbook is a ranked representative envelope. The resonance checks use chronological per-run envelopes retained during the same build.
- A short run is not extended with zeros. Missing tail samples are ignored during merge.
- A High Voltage finding for one phase excludes the whole Case/Run/bus from both LGp and LLp, unless the exact UI include override is active.
- Excel COM is required for workbook AutoFit, chart creation, dashboard refresh, and some report figure workflows.
- The methods describe the current implementation; changes to source modules or settings should be reflected here and in `docs/CURRENT_CONTEXT.md`.
