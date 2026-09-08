# PSCAD Results Analysis Methods

Last reviewed: 2026-09-08

This document describes the methods implemented by the current app. It is a code-level description of the data flow and calculations, not a replacement for the PSCAD model specification or an engineering acceptance standard.

The main implementation modules are:

- `src/results_analysis_app/project_config.py` - project timing, frequency, voltage, and `Um` inputs.
- `src/results_analysis_app/scanner.py` - project discovery, NonConv proposals, and PSCAD-log high-voltage proposals.
- `src/results_analysis_app/voltage_envelope.py` - raw waveform reads, high-voltage checks, per-run envelopes, and envelope workbook data.
- `src/results_analysis_app/resonance_checks.py` - Stress, Late Growth, and No-settle Growth checks.
- `src/results_analysis_app/rms_analysis.py` - project-specific RMS selection from the shared MM-results catalog and RMS batch rows.
- `src/results_analysis_app/sustained_sdpf.py` - chronological Sustained SDPF stress assessment, rank-sorted manual-plot summary, and compact result persistence.
- `src/results_analysis_app/sustained_sdpf_heatmap.py` - project-specific incidence aggregation and report-ready heatmap rendering from persisted Sustained SDPF observations.
- `src/results_analysis_app/common.py` - shared cancellation, logging, boolean normalization, and atomic workbook helpers used by workflow stages.
- `src/results_analysis_app/envelope_chart.py` - Excel envelope and resonance charts.
- `src/results_analysis_app/analysis_engine.py` - event and resonance plot batches, embedded waveform rendering, and Excel exports.
- `src/pscad_plotter_app_v3/services/plot_execution.py` and `plot_naming.py` - bounded plot-worker policy/execution and shared time-range filename tokens.
- `src/results_analysis_app/reporting.py` - DOCX report assembly from generated outputs.

## 0. Operating regimes and source of truth

The app has five execution regimes. They share data contracts but are not
interchangeable:

1. **Project/session** restores the UI session and project-keyed settings,
   exclusions, dashboard catalogs/selections, and status.
2. **Scan/catalog** validates the compact project scan cache, discovers changed
   inputs and dashboard figures, and optionally refreshes Excel dashboards.
3. **Envelope/check** reads raw PSCAD data, applies exclusions, creates
   envelopes, performs the High Voltage gate, and calculates the selected
   checks.
4. **Batch/render/report** converts selected results into MM plot batches,
   rendered plots/exports, RMS plots, Sustained heatmaps, and DOCX reports.
5. **Rebuild-only** recreates charts, heatmaps, or reports from valid saved
   artifacts without rerunning unrelated waveform analysis.

`Run analysis` connects regimes 3 and 4 through the existing action functions.
The step buttons expose narrower operations. A later stage must consume the
current output of an earlier stage; it must not silently interpret a missing,
obsolete, or incomplete cache as a valid empty result.

Dashboard Excel refresh is a separate operation: `Dashboards update` calls
Excel `RefreshAll`, whereas `Scan figures` reads/catalogs the saved dashboard
files. `Run analysis` and report rebuilding do not refresh dashboard data.

The source code and focused tests are authoritative. The compact cache
versions currently governing invalidation are: project scan **7**, project
analysis **1**, envelope manifest **3**, Sustained result JSON **19**, Sustained
summary workbook **4**, plot batch manifest **3**, report/report-layout
manifests **2/3**, and embedded plotter SQLite/MM caches **3/2**. No processed
waveform arrays are persisted.

## 1. End-to-end method

For each selected project, scope, and voltage, the app follows this sequence:

1. Read or restore the project scan. The scan identifies `.inf` run descriptors, project timing, frequency, voltage levels, existing outputs, NonConv proposals, and (when available) PSCAD-log high-voltage candidates.
2. Resolve the selected voltage configuration from `Input_Data_PSCAD*.xlsx` and `.inf` signal prefixes. The configuration supplies the MM bus prefix and `Um`.
3. Apply the selected Manual and NonConv exclusions before submitting waveform work. High Voltage rows are checked against raw waveforms during the build itself; an unchecked High Voltage row creates an exact include override.
4. Read the selected raw `.out` channels, check high voltage, and create a chronological rolling envelope for every surviving case/run/bus and measurement type.
5. Merge the per-run phase candidates into the base `MM_<voltage>.xlsx` workbook, preserving the source Case, Run, fault type, and MM name for each phase and for the overall maximum.
6. If enabled, run the Stress/Late/No-settle checks from the chronological per-run envelope data already in memory. If Sustained SDPF is enabled, assess each raw fixed phase/pair from the same loaded worker data; no separate `.out` read is performed. If RMS is enabled, select its project-specific MM elements and LG/LL quantities from the already parsed/cached `Results/MM results.csv` catalog; it does not reread raw `.out` files.
7. Write the base workbook, resonance workbook, combined Excel charts, compact Sustained SDPF JSON metadata, rank-sorted Sustained SDPF summary workbook, plot batches, rendered waveform plots, and DOCX reports through the selected workflow steps. Automatically generated waveform plot batches request Excel exports by default; the Settings option `Create automatic Excel waveform exports` can disable those `.xlsx` writes without changing the PNG plots or analysis results.

The selected voltage levels submit their raw-read jobs concurrently through one shared bounded process pool. The pool cap is shared across voltages, so concurrency does not multiply the configured worker count. The automatic worker setting selects the ceiling of 80% of detected logical CPUs, capped at 60 and reduced when fewer runs exist. A positive manual value remains available when a machine or workload needs a different balance. This scheduling change does not alter envelope, resonance, exclusion, or Sustained SDPF calculations.

### 1.1 Analysis paths and selection rules

The app has several distinct analysis paths. Their inputs, qualification rules, and selection rules must not be mixed:

| Analysis path | What is analysed | Finding/ranking rule | What is selected or written |
|---|---|---|---|
| High Voltage | Every finite raw LG and LL phase/pair sample against `high-voltage factor × Um × sqrt(2)` | Any exceeding phase excludes the complete Case/Run/MM bus from both measurements; this is an exclusion gate, not a severity ranking | Detailed exclusions in the envelope workbook and consolidated UI rows |
| Representative envelope | Per-phase centered half-cycle rolling absolute envelopes, then the ranked cross-case representative rows | Source phase rows are ranked by magnitude and aligned by rank; the merged maximum keeps its source provenance | `MM_<voltage>.xlsx` and combined Excel envelope charts |
| TOV, SFO, and SA event selection | The representative envelope workbook at one configured event time | Select the nearest valid row within `0.001 s` (`LLp` for TOV/SFO, `LGp` for SA); this is plot/report row selection, not a new compliance test | Event batch rows, envelope values, waveform plots, and report text |
| RMS | Shared parsed/cached `Results/MM results.csv` rows for the selected project, voltage, MM elements, and LG/LL quantities | For each selected voltage and quantity, choose one maximum (`LGr`/`LLr`) and one minimum (`LGrm`/`LLrm`) after excluding minimums at or below `0.05 pu`; LG pu uses `voltage / sqrt(3)`, LL pu uses `voltage` | Separate `RMS_LG`/`RMS_LL` batches and max/min annotated plots under `Plots/Generated/<scope>/RMS/LG|LL/`; report section immediately after event sections |
| Post-event Stress | Chronological per-run envelope `E(t)` after release/manual start | Keep positive-area findings and rank by `A_post = integral(max(E - Vlim, 0))` | Top N per `(check, voltage, measurement)` in `Resonance_Checks.xlsx` |
| Late Growth | Smoothed chronological envelope after release/manual start | Positive-slope and relevance gates, then rank by `(sigma, growth ratio, positive fraction, tail p95 / Vlim)` | Top N per `(check, voltage, measurement)` and result plots |
| No-settle Growth | Smoothed post-guard envelope when automatic release is not found | Positive-slope and relevance gates, then rank by `(sigma, positive fraction, longest positive-growth window, growth ratio, end p95 / Vlim, area)` | Top N per `(check, voltage, measurement)` and result plots |
| Sustained SDPF | Each raw fixed LG phase and LL pair independently, using complete-cycle absolute-peak metrics plus a chronological positive/negative full-wave envelope | A candidate must pass both the physical-duration and consecutive-complete-cycle conditions using the maximum absolute peak in each complete cycle. Actual SDPF and Safety-margin-only Case/Run/MM populations are selected independently by three optional views: highest voltage sustained for T, normalized full-wave excess area, and longest continuous full-wave duration | Up to three representatives per population (up to six per voltage) for the report/plot, plus all observations in the compact JSON and ranked summary workbook |
| Sustained SDPF heatmap | Persisted Case/Run/MM flags only; no waveform reread or recalculation | LGp/LLp and all fixed-path flags are OR-merged for one Run × MM observation; heatmap outlines show the largest absolute count but do not select a new engineering finding | Project-specific PNG presentation and report figures |

The `Resonance_Checks.xlsx` Top N selection is independent for each check, voltage, and measurement type. Sustained SDPF selection is independent from TOV/SFO/SA and from the resonance checks: a case selected by one path is not automatically selected by another. A Sustained SDPF summary row can therefore exist for a non-candidate observation, while the DOCX Sustained SDPF section and governing waveform are created only when that voltage has at least one qualifying candidate.

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

`Statistic*.out` files are read once per build. Standard numeric tables are parsed through NumPy's text reader; files that do not match that shape use the legacy pandas parser. Parsing is sequential below 1,000 statistic files and uses a separate four-worker maximum pool for larger sets. Their `Case` and `Run#` rows are joined to envelope provenance. The current numeric fault mapping is:

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

Manual rules are Case/Run/Bus matchers. Blank fields are wildcards; a completely blank row is ignored. The editable `Run` and `Bus` cells accept comma-, semicolon-, or newline-separated values. The normalizer expands the listed runs and buses into individual exact rules (the Cartesian product when both fields contain lists), deduplicates them, and keeps the matcher scalar. Run ranges are not inferred. NonConv proposals come from `CB_*.out` summary files:

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

Detected High Voltage rows are reconstructed only from the current project's scan. The session stores only explicit include overrides, and each scan removes overrides whose exact voltage/Case/Run/MM key is no longer present. This prevents a stale session entry from appearing as an `Analysis` finding for another project and keeps detection data in one source of truth.

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

The result also records `T_above_post` as a diagnostic sample-count duration:

```text
T_above_post = count(E(t) > Vlim) × median positive dt
```

It is not an interpolated threshold-crossing duration and is not the ranking metric. Results are ranked by `A_post`.

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

The result must have positive slope and pass the configured relevance gate: sufficient positive fraction and either sufficient level over `Vlim` or sufficient growth ratio and absolute growth delta. Results are ranked by the complete tuple `(sigma, growth ratio, positive fraction, tail p95 / Vlim)` in descending order; the later fields are deterministic tie-breakers, not additional gates.

### 5.5 No-settle Growth

No-settle is considered only when automatic release detection is enabled and no release was found. It compares an early post-guard window with a final tail window using p95, growth ratio, growth delta, positive fraction, positive-window count, log slope, and area above `Vlim`. It uses the same positive-slope and relevance gate as Late Growth, with the full post-guard record used for the positive-fraction calculation. Results are ranked by `(sigma, positive fraction, longest positive-growth window, growth ratio, end p95 / Vlim, area from the guard time)` in descending order. The positive-window count is the longest consecutive run of positive successive smoothed-envelope differences; it is not a duration in seconds.

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

### 5.7 RMS voltage analysis

RMS is a project-specific, optional analysis path. New projects enable the
existing Stress, Late, No-settle, and Sustained SDPF checks by default but keep
RMS disabled until the user selects MM elements. The first Analysis control is
an RMS checkbox plus popup: it is enabled only when the highlighted project is
also checked for the run and its catalog contains MM elements. The popup lists
the available elements alphabetically, with independent LG and LL quantity
checkboxes. A project can select any subset of elements and either quantity;
the choice is restored by canonical project path when the active project
changes.

The source is the already parsed/cached `Results/MM results.csv` catalog. The
bus name is the catalog's existing MM identity, so RMS does not rescan the
input workbook or reread raw waveform `.out` files. For each selected voltage
and enabled quantity, the selector ranks the selected rows and retains one
maximum (`LGr [kV]` or `LLr [kV]`) and one minimum (`LGrm [kV]` or `LLrm [kV]`).
Minimum candidates with a reported or derived value at or below `0.05 pu` are
ignored. When a pu column is missing, LG uses `value / (voltage / sqrt(3))` and
LL uses `value / voltage`. Voltage levels are filtered explicitly; an empty
selection produces no RMS rows.

The selected maximum and minimum rows become separate `RMS_LG` and `RMS_LL`
batch rows using the existing MM renderer. Their plots request the `LGr` or
`LLr` trace and show both global max/min markers; no new plotting engine or
binary waveform format is introduced. Generated files are kept in
`Plots/Generated/<scope>/RMS/LG/` and `RMS/LL/`, with the corresponding batch
workbooks under `Plots/Plot_batch/`. The report writes one `RMS` heading after
the selected SFO/TOV/SA event sections and before Sustained SDPF and resonance
sections. RMS is a diagnostic voltage study; it does not qualify Sustained SDPF
events or alter envelope, exclusion, or resonance calculations.

## 6. Sustained SDPF stress

Sustained SDPF is an optional analysis selected beside Stress, Late, and No-settle. It supplements the ranked representative envelope; it does not change the existing envelope, TOV/SFO/SA, or resonance methods and it does not classify frequency content with an FFT or a 10--500 Hz rule.

The analysis runs while the normal envelope workers already hold the selected raw waveforms. It uses the resolved project fundamental frequency from `Input_Data_PSCAD*.xlsx` (with the existing fallback path) and evaluates one fixed physical path at a time: LG `A-G`, `B-G`, `C-G`, and LL `A-B`, `B-C`, `C-A`. No maximum-across-phases series is used. The configured persistence requirement is a physical duration in milliseconds; the default is **30 ms**. The duration is not rounded to a cycle count. The app derives `required_cycles = ceil(duration × frequency)` and uses it as a minimum complete-cycle condition alongside the physical-duration condition. The setting is independent of the ordinary TOV event time. NaN/missing portions, missing cycles, and sub-threshold envelope intervals all break an event; missing tails are not replaced with zero.

The project sustained-TOV rule is peak-envelope based. For every complete cycle, the app calculates the positive and negative peak magnitudes and uses their maximum absolute value for screening. Therefore a violating positive peak, a below-limit negative peak, and a later violating positive peak remain a screening candidate when the absolute peak envelope stays consecutive; the lower opposite-polarity peak is retained for the separate full-wave severity calculation. Consecutive qualifying complete cycles form a candidate run. The first and last raw waveform threshold crossings of the run define its physical start, end, and duration; the absolute peak points define the piecewise-linear envelope used for qualification and `V_T`. A sustained event is registered only when the run contains at least `required_cycles` consecutive complete cycles and the interpolated waveform duration is at least the configured physical duration. A short event crossing a cycle boundary therefore cannot qualify solely because it touches two cycle bins. A missing cycle or data gap ends the event; a later run after the gap is separate. Raw sinusoidal zero crossings do not end an event because the sustained test is not applied to instantaneous signed samples. This deliberately rejects isolated fast-decaying events and leaves them to the existing SFO/AFO analysis. RMS is calculated and retained as a supporting diagnostic, but RMS alone cannot register a sustained TOV.

This is an explicit project persistence rule, not a claim that the result is the formal CIGRE TB 913 voltage-based assessment. The SDPF and `SDPF / 1.15` thresholds provide the project voltage criteria; the qualification flag, ranking, heatmap, and selected plots all use the fixed-path peak-envelope rule defined above. This module is intentionally independent of the ordinary TOV/SFO/SA event-row selection and of the Stress/Late/No-settle checks.

`SDPF_LG` and `SDPF_LL` are resolved through the embedded plotter `LimitService` from the `MM_blocks` sheet, one validated row per voltage level (with project plotter overrides applied). The Sustained SDPF Settings table labels these values `Input xlsx`; its RMS cells are editable per project and change the label to `Manual` when overridden. Source values are RMS. The displayed peak is `RMS x sqrt(2)`, and the safety threshold is `SDPF / 1.15` in both RMS and peak units. The analysis and the plotter use these same resolved values and conversions. Missing, invalid, or inconsistent voltage-level values produce a warning and skip that voltage rather than inventing a limit.

For each surviving Case/Run/MM and fixed phase/pair, the app records the raw maximum, the maximum peak and RMS diagnostic in the area-governing sustained event, the actual peak-envelope duration at the SDPF/1.15 threshold, the actual duration at the SDPF threshold, event start/end timestamps, derived cycle coverage, separate absolute and normalized full-wave excess areas for both thresholds, the longest continuous full-wave duration for both thresholds, the highest voltage sustained for the configured physical duration `T` at both thresholds, and the qualifying flags. `V_T` is calculated from the same chronological qualifying piecewise-linear envelope: `max(t0) min(E(t) for t in [t0, t0+T])`. Its cross-path ranking value is `V_T / actual SDPF peak limit`; an RMS-equivalent value is retained for reporting only. A short internal high spike therefore cannot determine `V_T` unless that level is held for all of `T`. The full-wave ranking envelope retains both polarity peak magnitudes with their true timestamps, sorts them chronologically, and connects them linearly. The report's Episode duration is the threshold-crossing duration of the selected qualifying event; the separate `*_longest_continuous_s` fields remain ranking metrics.

Path and result selection are separate levels. A fixed path is classified as `2` for an SDPF-limit candidate, `1` for a safety-margin-only candidate, or `0` for no qualifying sustained event. A Case/Run/MM belongs to Actual SDPF when any fixed path has `sdpf_exceeded = True`; otherwise it belongs to Safety-margin-only when at least one fixed path has `margin_exceeded = True`. A Safety-margin-only result may still contain brief instantaneous SDPF crossings. The relevant area and continuous-duration metric use the SDPF threshold for Actual SDPF and the SDPF/1.15 threshold for Safety-margin-only. The two populations are never compared in representative ranking. Within each population, the app independently selects `Highest voltage sustained for T` by normalized `V_T`, `Worst cumulative stress` by normalized full-wave excess area, and `Longest continuous duration` by full-wave continuous duration. The three controls are enabled by default and only affect representative plots/reports; all metrics and summary rows are always calculated. Case, Run, MM element, measurement, and phase provide deterministic tie-breakers only. If multiple criteria identify one Voltage/Case/Run/MM identity and fixed path, one waveform image is reused; a different fixed path or qualifying event remains a separate report row with its own metric provenance. Areas are calculated per qualifying event and are never summed across phases, LL pairs, or separated events. The rank-sorted summary workbook still contains every Case/Run/MM observation, including `No qualifying sustained TOV` rows, so it is an audit/selection table rather than a candidate-only table. If no phase/pair qualifies, no Sustained SDPF report section or governing plot is selected; short events are not promoted to a sustained finding.

Persisted fixed-path populations are finite-value checked and their governing path is recomputed on load, so a stale or hand-edited governing copy cannot change ranking or plot selection. The JSON/result version is incremented when this method changes, so results from an earlier qualification implementation are not reused.

The complete Sustained SDPF configuration is in the dedicated **Sustained SDPF** Settings tab. It contains the **minimum sustained duration** in milliseconds (default `30 ms`), the three project-specific representative-ranking checkboxes (all enabled by default), resolved LG/LL limits, and the heatmap settings. The effective frequency is taken from valid `Input_Data` project timing when available and otherwise from the configured envelope fallback in Settings; it is not duplicated in the UI. That frequency derives the minimum complete-cycle requirement and reported cycle coverage during analysis. Changing only a ranking checkbox does not invalidate the engineering result cache: the persisted metrics can be reused to rebuild the selected plot batch and report. The limit table shows one LG and one LL row per voltage with editable RMS, calculated peak/margin columns, and a source column. Changing an RMS value changes the related calculated values immediately and requires rerunning the envelope build to recalculate results. Case-name tokens come from the scan's existing `.inf` inventory, while fault grouping uses the project-wide `Run#` → `Fault_type` map read once from the first valid `Statistic*.out` during the project scan.

Compact metadata is saved as `Voltage_envelope/<scope>/Sustained_SDpf.json`, including one source fingerprint plus compact source-directory roots, the physical duration setting, derived cycle coverage, fixed-path area/duration/`V_T` scalars, all six population/criterion references, and the applied settings/exclusion signature. The cache uses result version **19**; pre-version-19 result caches are stale and are rebuilt. It stores one canonical result plus a compact pool of only the additional selected Case/Run/MM fixed-path results and population-specific descriptors; flat selection aliases and embedded duplicate result objects are not persisted. Raw cycle samples, duplicated governing rows, and unused per-result signatures are not persisted; compact qualifying-event descriptors are retained so report metrics stay tied to their physical event. All persisted source paths are normalized relative to the project root with POSIX separators before fingerprinting; validation applies the same normalization on Windows. The same build writes `Sustained_SDpf_summary.xlsx` with two compact sheets: `Ranked cases` contains one row for each Case/Run/MM observation, including no-qualification rows, with a population rank, explicit Actual SDPF/Safety-margin-only population, governing fixed LG/LL measurement and phase, applied threshold, normalized excess area, longest continuous duration, highest sustained `V_T`, sustained peak, event timestamps, qualifying path list, and limit source. A small method block above the table records the result version, persistence duration, project frequency, and derived complete-cycle coverage. `Representative selections` lists the independently selected Case/Run/MM path for highest sustained `V_T`, cumulative stress, and longest continuous duration in each population; it is a selection aid, not a plot manifest. It deliberately does not include waveform arrays, raw source paths, RMS diagnostics, or plot settings. The source fingerprint is recomputed from file metadata once per scope when a later batch/report validates the result. Common-grid bus analysis indexes complete cycles once and reuses those boundaries for all finite phases; phases with gaps or different grids retain the safe general path. Plot batches reuse the existing MM renderer with the same SDPF and SDPF/1.15 peak lines used by the analysis and enable the standard violet TOV-window markers with the normal plot time range and marker spacing; no Sustained-specific `time_start` or `time_end` is added. Sustained batch rendering validates its settings/source and persisted selected rows and automatically rebuilds a stale or incomplete batch from the current persisted selections before rendering; it removes the batch only when no current qualifying selection remains. When a voltage has a qualifying candidate, reports add one concise `Sustained SDPF` section after the SFO/TOV/SA time-domain figures. The section contains a short selection-basis sentence, one compact selected-case table per population, and one plot per unique selected Case/Run/MM with Word figure cross-references and concise captions. If the three criteria select different cases, the table has three rows; if they select the same case and fixed path, the criteria are combined into one row. Valid-cache heatmaps can be rebuilt even when no candidate exists, but they are attached to a DOCX only inside that candidate-backed Sustained SDPF section. Heatmap observation parsing is performed once per voltage and reused for every enabled named heatmap set. During a connected analysis run, the validated payload is also reused across batch creation, plot rendering, heatmaps, and reports. Heatmap methodology and presentation are unchanged by ranking controls. A saved result is ignored when its settings, selected-descriptor structure, or recorded source fingerprint is stale; rerun the envelope/check build after source, limit, frequency, exclusions, or Sustained duration settings change. The result version is incremented whenever the qualification method or persisted result schema changes, so earlier cached results are not reused.

The same cache validator is used by Sustained batch creation, plot/heatmap rendering, and report generation. It checks the persisted result version, current settings, shared source fingerprint, per-voltage signature, and selected rows. The shared source fingerprint is checked once per scope and then reused for each voltage lookup. If validation fails, the workflow log states the reason, stale Sustained plot/heatmap outputs are removed, and no empty batch is written to represent the invalid state. A valid cache with no qualifying candidate remains an intentional empty result: the summary and valid-cache heatmap rebuild may still expose observations, but no Sustained plot or DOCX Sustained section is selected. Rerun the envelope/check build after changing source files, limits, frequency, exclusions, or Sustained settings.

### 6.1 Sustained SDPF incidence heatmap

The optional **Create Sustained SDPF heatmap** setting is project-specific and is effective only when the main Sustained SDPF analysis is selected. It does not read `.out` files or recalculate stress: the envelope build persists one compact, merged Run × MM observation per voltage alongside the existing governing result. LGp and LLp rows for the same Run × MM are combined with logical OR flags, so a finding in either measurement is retained.

Each cell represents the merged eligible Run × MM observations assigned to that visible Y/case/split cell. The observation flag is true when any fixed LG phase or LL pair passes the relevant threshold for the configured physical duration; after the flag is set, that Run × MM is counted once, not once per phase, pair, or measurement. LGp and LLp are OR-merged before this count. Eligible cells show two centered percentage lines: the top line is actual SDPF-limit incidence and the bottom line is inclusive safety-margin incidence, where margin means SDPF/1.15 and includes actual SDPF. Short or isolated events are excluded from the heatmap. Each percentage uses the eligible Run × MM count in that cell, so cells with no eligible data are distinct from eligible zero-incidence cells. Green means no qualifying exceedance, amber means margin-only candidates, red means any SDPF-qualified candidate, and grey means no eligible data. Actual-cell colour intensity is scaled separately against the largest nonzero actual percentage in the rendered layout; margin-only intensity is scaled separately against the largest nonzero margin-only percentage. This keeps the two severity channels readable without allowing inclusive actual-margin percentages to distort the margin-only scale. A dark outline marks the largest absolute actual count when any actual cell exists, or the largest margin count when there are no actual violations; ties are marked consistently. Nonzero percentages below 1% are shown as `<1%` rather than `0%`; eligible zero-only cells show `0%` on both lines, while cells with no eligible data show `—`.

Heatmap presentation is saved per project as an ordered list of named sets. A project with fault classifications starts with one enabled **Faults** set; a project without faults starts with one enabled **Cases by <token>** set whose Y grouping is the first varying case-name part (for example, **Cases by S**). If no case-name dimension varies, the fallback is **All cases**. An explicitly selected MM-element view is labelled **MM elements** by default. **Add heatmap** clones the selected set; the name, order, enabled state, Y/X/Split dimensions, panel layout, and case limits can then be edited independently. MM-element grouping is an optional additional view, never the automatic fallback for a no-fault project. Each enabled set is written to a deterministic subfolder such as `01_Faults`, `01_Cases_by_S`, or `02_MM_elements`, and the set name is shown in the report. Renaming or deleting a set removes its obsolete output folder on the next rebuild.

Y grouping contains the engineering dimensions **Fault type** and **MM element**, plus case-name token dimensions and the explicit **None** option. Fault type and MM element are Y-only: they are never offered as X grouping or Split by values. A Fault type row aggregates all MM elements in the matching Case/Run; an MM element row aggregates all fault types in that Case/Run. The per-voltage result naturally contains only the MM elements observed at that voltage. Case-name tokens remain available for X grouping and Split by; when a token is selected as Y, its values become rows and that token is removed from the compact X identity. X grouping only orders and labels the resulting columns; it does not independently change observation membership. Because a Y token is removed from the compact identity, one visible column can intentionally represent cases that differ only in that Y token, while their Run × MM observations remain separate in the cell counts. Split by creates one figure for every observed token value and keeps only the cases belonging to that split, including zero-violation splits. Selecting **None** keeps one ungrouped row.

The generated PNGs are application-owned under `Plots/Generated/<scope>/Sustained_SDPF_Heatmap/<order>_<name>/`. When a governing Sustained candidate exists, they are inserted at the end of the existing Sustained SDPF report section after its governing waveform. After changing layout settings, `Rebuild heatmaps` regenerates these PNGs from a valid saved JSON without rereading waveform files; `Rebuild reports` is still required to update DOCX reports. A valid no-candidate cache may still produce heatmap PNGs for distribution review, but the report does not create a standalone Sustained section for them. The heatmap is supporting distribution information, not a new compliance criterion. Combined pages show a `Page i/n` suffix only when the same split value continues across multiple files; when each file represents a different split, its `Split: <value>` title is sufficient. MM identifiers are rendered horizontally, and the technical `MM_HM` placeholder is presented as **MM elements** in figure and report titles.

When a matrix has many case columns, the renderer emits deterministic continuation panels rather than shrinking labels until they are unreadable. The project-specific **Max cases per heatmap** setting controls the panel size and defaults to 12; it is a practical default, not a fixed limit, so a project with 13 useful columns can set 13 (up to the persisted UI limit of 500). **Separate files** preserves one panel per PNG. **Combined panels** puts the real split/continuation panels into one vertical, paginated figure with one common legend and scale; each panel retains its own X-axis. The main header keeps only the voltage, optional set name, metric, and a compact split caption such as `Split: <value>`; project and scope are report-caption context. Every figure uses a fixed, named inch-based layout: header, optional split-panel header, optional X-group band, matrix, optional case-label band, and footer. X grouping shows only the selected token value above the matrix; it is not repeated in the main header or case labels. Split categories are rendered from the selected project token as `Split: <value>` and never as an equality. Long Y-axis and MM labels wrap at readable widths within the fixed tick-label band. Case labels are drawn in a dedicated band below the heatmap and omit tokens represented by Y/X/Split or constant in that panel. If no residual case identity remains, the case-label band is omitted because the row and X-group labels already identify the column; selected grouping tokens are never restored as a fallback. Equal compact labels are allowed in different visible X-groups or split panels; only a true collision within the same visible context invokes an unselected-identity fallback. Continuation order is communicated by the output filename and page order, so `part i/n` is not printed inside the figure. **Automatic** combines only a small panel set (up to the configured **Max panels per image**, default 4) and uses separate files for larger sets. No case is synthesized by stacking: every panel is derived from the same filtered case columns as separate mode. Each set/voltage render stages its images and transactionally rolls back the prior voltage images if replacement fails; disabled/renamed set folders and removed voltage outputs are cleaned only after the current scope render succeeds. A full analysis renders the enabled sets once and the report consumes those images; report-only mode regenerates them when requested. Event-only batch creation/rendering does not clear these outputs when Sustained SDPF was not selected.


Combined heatmap panels repeat every Y-group value on each panel, including Fault type, MM element, and case-token rows, so each panel remains independently readable. No separate vertical Y-dimension caption is added: the named view in the horizontal title and the row labels provide the grouping context consistently for every view.

## 7. Event plots and reports

The event selection method uses envelope workbook rows to choose representative Case/Run/MM points:

| Event | Source sheet | Trace |
|---|---|---|
| `TOV` | `LLp` | Both |
| `SFO` | `LLp` | Both |
| `SA` | `LGp` | LGp |

The selected row is the nearest time to the configured event time. Exact matches are preferred; a nearest match is accepted within `0.001 s`. If no valid row is within that tolerance, no plot job is created for that event/case. Defaults are SFO `0.004 s`, TOV `0.030 s`, and SA `0.100 s`.

Those Case/Run/MM selections are written to plot batch workbooks. The embedded MM plotting engine then reads the raw waveform data for the requested plot/export. Resonance plot batches are built from the already-selected Top N rows in the result tabs of `Resonance_Checks.xlsx`, not by re-running the checks. App-generated event, resonance, and Sustained SDPF plot rows request the standard limits and violet TOV-window markers (`tov_window_count = 4`). They do not add a Sustained-specific plot start or end time; the normal available waveform range is used unless a manually edited batch row explicitly supplies one.

During rendering, the app first expands every valid selected scope/event batch into concrete MM jobs for the project. Three or more jobs with at least two cache-local Case/Run groups share one bounded Windows process pool, capped at four workers; related jobs are submitted in chunks of up to eight so each child can reuse its process-local waveform data. A single group or smaller batch remains sequential because process startup is more expensive than the work. Each worker creates its own embedded renderer and waveform Excel exporter, reads only the time plus requested waveform columns, and uses a write-only workbook for raw waveform exports. A pool-start or child-worker failure retries the same plans sequentially. The parent process retains the per-event staging and atomic replacement contract: a generated event/check directory is replaced only after all of its jobs succeed, while a failed or cancelled uncommitted stage is removed. Successful folders contain only PNG/Excel outputs; the project's single `.state/analysis_cache.json` stores the normalized job/source signature and compact output metadata. A later render skips the event when that entry and the output file set still match; any changed source, batch row, export setting, or manifest version causes a normal rerender. The pool is project-scoped because each project has a different run index; envelope building, batch creation, heatmaps, and report assembly remain separate dependent stages.

Sustained SDPF heatmap pages use the same three-job threshold, Windows `spawn`
process policy, four-worker cap, bounded queue, prompt cancellation, and
sequential fallback. The parent builds the compact heatmap layout once per
configured set and voltage, workers render only independent staged PNG pages,
and the parent atomically replaces the complete voltage/set output after all
pages succeed. This changes rendering concurrency only; it does not change
grouping, split, incidence, or selection logic.

Envelope builds do not retain processed waveform DataFrames between runs. Raw arrays and processed envelope frames exist only during the current build, while the project `.state/analysis_cache.json` keeps one small envelope signature and generated-output record so an unchanged complete stage can be skipped.

The project analysis cache has one explicit schema version and stores only stage signatures, output paths, sizes, and modification times. Its envelope signature includes both the current Sustained result version and the summary-workbook format version, so a summary-only layout change rebuilds the envelope/summary outputs while leaving the engineering result schema unchanged. Sustained plot jobs apply the same project SDPF RMS overrides used by detection and retain the workbook SIWL fields unchanged; the plot signature includes the resulting effective limits and current Sustained result version.

The Sustained result version is also included in the centralized plot and report signatures. A plot or DOCX produced from an obsolete Sustained result cannot be accepted by a later report-only/render-only action; the affected output is regenerated from the current result JSON.

Reports reuse the generated dashboard, envelope, waveform, and resonance plot outputs. Envelope summary values use the same nearest-time helper as plot batch selection, so reports and event batches do not implement separate time-selection rules. Report generation records its source/output signature in the project's `.state/analysis_cache.json`; a voltage DOCX is skipped only when the selected source figure/workbook metadata, report settings, and existing output metadata still match.

Dashboard figure metadata is cached per canonical project path. The UI combines the cached catalogs into one union by default; `All checked` applies one compact checked-ID list to every checked project, while clearing it exposes and persists the current project's selection. When shared mode is enabled again, the active project's selection becomes the shared source and existing local selections are preserved. The report builder still receives a separate dashboard-ID list for each project, so a figure absent from a project is skipped and a figure selected for one project is not inserted into another project's report. Existing project-specific or former global selections are migrated into the shared selection once and saved in the current format.

## 8. Settings that change the method

The following values are persisted in the session and passed into the build/check functions:

| Setting | Default/current behavior |
|---|---|
| Envelope time step | `0.002 s` |
| Envelope time end | Project `Final duration` automatically; manual positive cap when automatic mode is cleared; `1.0 s` fallback if timing is unavailable |
| Envelope workers | Automatic ceiling of 80% of logical CPUs, capped at `60`; manual override available |
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
| Sustained SDPF minimum persistence | `30 ms` peak-envelope duration |
| Sustained SDPF derived cycle coverage | `ceil(duration × project frequency)` minimum consecutive complete cycles, also reported with the result |
| Sustained SDPF safety threshold | `SDPF / 1.15` (fixed) |

Changing envelope-build duration or High Voltage settings requires running the envelope build again to regenerate the affected workbook data. Changing chart-axis settings only requires rebuilding charts. Changing resonance thresholds requires rebuilding the checks; rebuilding only the charts does not recalculate findings.

## 9. Important interpretation limits

- The High Voltage threshold and the resonance `Vlim` are different calculations and use different configured quantities.
- The base envelope workbook is a ranked representative envelope. The resonance checks use chronological per-run envelopes retained during the same build.
- TOV/SFO/SA event rows are nearest-time selections from the representative workbook; they are independent from the resonance findings and Sustained SDPF candidate selection.
- A short run is not extended with zeros. Missing tail samples are ignored during merge.
- A High Voltage finding for one phase excludes the whole Case/Run/bus from both LGp and LLp, unless the exact UI include override is active.
- Sustained SDPF is an insulation-stress duration check only; it is not an IEC/TOV frequency-content classifier.
- Sustained SDPF summary rows include all Case/Run/MM observations for audit and manual selection. The ranked workbook includes both the threshold-specific qualification duration and the separate full-wave continuous duration used for ranking; its Excel headers use readable ASCII labels such as `kVpeak`. Only a voltage with at least one qualifying fixed path produces a governing Sustained plot and DOCX Sustained SDPF section; a valid no-candidate cache is not an error.
- The Sustained SDPF JSON is versioned compact metadata, not a replacement for the representative envelope workbook or a persisted waveform cache. It stores the merged heatmap flags and governing report result; source freshness is represented by one fingerprint and compact source-directory roots shared by all voltage levels. The two-sheet summary workbook is regenerated during the envelope/check build from the same in-memory observations and does not trigger another raw waveform read; it is an audit/selection workbook, not a plot manifest.
- Excel COM is required for workbook AutoFit, chart creation, dashboard refresh, and some report figure workflows.
- The methods describe the current implementation; changes to source modules or settings should be reflected here and in `docs/CURRENT_CONTEXT.md`.
