# Codex handoff: PSCAD Results Analysis

Last reviewed: 2026-09-07

This is the short, current handoff for starting a new Codex chat in this
project. It describes the implemented app and its contracts; the source code
and focused tests remain authoritative if this file and the code disagree.

## Read this first

The active app root is this folder (`01_App`). From that folder, read in this
order before making a change:

1. `AGENTS.md` - project rules and validation requirements.
2. `docs/HANDOFF.md` - this short architecture and workflow map.
3. `README.md` - setup, commands, user workflow, and output locations.
4. `docs/CURRENT_CONTEXT.md` - detailed current-state notes, risks, and recent validation.
5. `docs/ANALYSIS_METHODS.md` - the calculation and data-handling contract.
6. `pyproject.toml`, `environment.yml`, then the relevant source and tests.

Always inspect `git status` before editing. The worktree may contain
user-approved changes from an earlier chat. Preserve unrelated changes and do
not use destructive reset/checkout commands.

## Graphify navigation layer

`graphify-out/` is a generated, ignored local graph for repository navigation.
When it exists, use Graphify's `query`, `path`, and `explain` commands to locate
the relevant modules and relationships before opening source files. Rebuild the
code graph after source changes with:

```bat
..\.conda\pscad-results-analysis\Scripts\graphify.exe . --update --code-only
..\.conda\pscad-results-analysis\Scripts\graphify.exe cluster-only .
```

The current graph is a code-navigation layer (1,560 nodes, 4,993 edges, 61
communities, built from commit `619d5656`). It does not override source or
tests, and its inferred relationships should be verified before changing
behavior. The project documentation listed above remains the semantic handoff
for engineering methods and operating rules.

## What the app is

This is a native Windows PySide6 desktop app for analysing PSCAD simulation
results. It can:

- add and cache one or more PSCAD result projects;
- discover cases, runs, fault types, voltages, MM buses/elements, scopes, dashboards, and exclusions;
- build LGp and LLp voltage-envelope workbooks and Excel charts;
- run Stress, Late Growth, No-settle Growth, and peak-envelope Sustained SDPF checks;
- create/render MM waveform plot batches and optional waveform Excel exports;
- create Sustained SDPF incidence heatmaps; and
- assemble DOCX reports from the generated outputs.

The parent folder is reference material, not app source:

- `../Original_examples/` contains original scripts and sample PSCAD data.
- `../02_Backup/` contains backup material.
- `../.conda/pscad-results-analysis/` is the dedicated conda environment.

## Operating regimes

Treat the application as five related but distinct regimes:

1. **Project/session** - add or remove projects, restore the session, select
   the active project, inspect project-specific settings/exclusions, and open
   a project folder.
2. **Scan/catalog** - validate or rebuild the compact project scan cache,
   discover dashboard figures, and optionally refresh Excel dashboards.
3. **Envelope/check** - apply exclusions, read raw PSCAD waveforms, build
   voltage envelopes, perform the all-case High Voltage gate, and run the
   selected Stress/Late/No-settle/Sustained SDPF checks.
4. **Batch/render/report** - create plot batches, render MM plots and optional
   waveform workbooks, render Sustained SDPF heatmaps, and assemble DOCX
   reports.
5. **Rebuild-only** - rebuild charts, heatmaps, or reports from valid saved
   artifacts without repeating unrelated waveform work.

`Run analysis` is the connected path through the envelope/check and
batch/render/report regimes. It passes the already loaded Sustained payload and
one cache-validation result per scope through batch creation, plotting,
heatmaps, and report assembly. The step buttons are narrower and should not
silently redo unrelated stages. It does not refresh Excel dashboards. Use
`Dashboards update` for Excel `RefreshAll`; use `Scan figures` only to discover
or recatalog saved dashboard figures.

## Main source map

| Area | Module | Responsibility |
| --- | --- | --- |
| Startup | `src/results_analysis_app/__main__.py` | App entry point, Windows identity, icon, and theme setup |
| UI/orchestration | `src/results_analysis_app/main_window.py` | Main window, project/scope selection, background actions, status, and stop handling |
| Settings | `src/results_analysis_app/settings_dialog.py` | Settings dialog construction and session updates |
| Models/state | `src/results_analysis_app/models.py`, `storage.py` | Session schema, defaults, normalization, persistence paths |
| Scanning | `scanner.py`, `project_scan_runner.py`, `project_scan_cache.py`, `project_config.py` | Project discovery, metadata cache, timing/frequency/voltage inputs, fault map, proposals |
| Exclusions | `exclusions.py` | Manual, NonConv, High Voltage normalization and matching |
| Envelopes | `voltage_envelope.py`, `envelope_chart.py`, `envelope_rows.py` | Raw reads, exclusions, envelopes, Excel workbooks/charts, shared nearest-time selection |
| Checks | `resonance_checks.py`, `sustained_sdpf.py` | Existing envelope checks and project-defined Sustained SDPF persistence |
| Heatmaps | `sustained_sdpf_heatmap.py` | Persisted Run x MM aggregation and heatmap rendering |
| Plot bridge | `analysis_engine.py`, `src/pscad_plotter_app_v3/` | Batch creation, MM plotting, process execution, and waveform Excel export |
| Plotter conventions | `pscad_plotter_app_v3/services/project_conventions.py` | Case/run filename parsing, statistic-file selection, fault-label normalization, and statistic-row parsing |
| Plotter waveform I/O | `pscad_plotter_app_v3/services/waveform_io.py` | `.inf` descriptor parsing, PGB-to-`.out` mapping, raw waveform reads, and waveform-frame operations; it does not own case/run parsing |
| Shared workflow helpers | `common.py`, `plot_naming.py`, `plot_execution.py` | Shared cancellation/logging, atomic workbook writes, filename tokens, and bounded plot-worker policy |
| Reports | `reporting.py` | DOCX report assembly and figure insertion |
| UI theme | `styles.py` | System-aware light/dark semantic styles |

The embedded plotting engine is MM-only. Do not reintroduce the old CB,
arbitrary-channel, FFT, combined-mode, or unused catalog branches.

## State ownership and cache contract

Canonical absolute project paths are the identity boundary. Project scan data,
settings, exclusions, dashboard metadata/selections, analysis outputs, and
status must never be looked up by project name or list position. `Scopes` are
the intentional exception: their token filters are global and are applied to
every selected project.

| Artifact | Scope and content | Not stored |
| --- | --- | --- |
| Session/autosave | app-level UI selections plus project-keyed settings and overrides | raw waveform arrays |
| `.state/project_scan_cache.json` | compact discovery metadata, input timing/voltage/MM data, proposals, and dashboard catalogs | full `.out` inventory and waveform data |
| project `.state/analysis_cache.json` | one compact stage-signature/output-metadata cache | engineering result payloads and waveform arrays |
| `Sustained_SDpf.json` | compact Sustained observations, selection references, heatmap flags, and source fingerprint | raw cycle samples, plot settings, RMS diagnostics |
| generated folders | authoritative current workbooks, PNG/Excel outputs, and DOCX reports | duplicate cache manifests in every output folder |

Current source versions are: project scan cache **7**, project analysis cache
**1**, voltage-envelope manifest **3**, Sustained result JSON **19**, Sustained
summary workbook **4**, plot-batch manifest **2**, and report/report-layout
manifests **2/3**. The embedded plotter's SQLite/MM caches are **2/1**.
Obsolete or incomplete artifacts are rebuilt; they are not treated as valid
empty results. The app deliberately does not persist a processed-waveform
cache.

## Function ownership rules

The source is intentionally split by responsibility. A function is not kept
as a compatibility alias merely because an older import path happened to work.
The current ownership rules are:

- `project_conventions.parse_case_run_from_stem` is the pure parser for the
  standard `<case>_r<run>` stem. `case_run_from_inf_path` is only its `.inf`
  path adapter: it reads the filename stem, does not open the file, and raises
  a clear error when the standard convention is absent. `parse_manual_run_from_stem`
  handles the separate manual-project naming convention.
- `waveform_io` owns waveform data only: descriptor parsing, PGB/file mapping,
  `.out` loading, and `WaveformFrame` operations. It no longer re-exports
  `case_run_from_inf_path`; callers import the parser from
  `project_conventions`, where its purpose is visible.
- `common.as_float` is the application-wide finite-number parser used by
  scanning, report, cache, chart, and batch code. `project_conventions.safe_float`
  remains local to the standalone plotter-convention layer, where it is also
  used by statistic/catalog parsing. Positive setting values use the single
  `models.normalize_positive_float` helper; envelope building does not carry a
  second `_positive_float` implementation.
- `actions.py` contains project-loop/UI orchestration. The calculation and
  output implementations remain in `voltage_envelope.py`, `analysis_engine.py`,
  and the other domain modules; the action functions do not duplicate those
  algorithms.
- `sustained_sdpf.py` owns qualification, ranking, cache serialization, and
  cache validation. `sustained_sdpf_heatmap.py` owns Run × MM aggregation and
  rendering. Reports consume those results and do not reimplement qualification.
- `project_scan_runner.py` owns scan/cache sequencing; `scanner.py` owns the
  actual project scan; `project_scan_cache.py` owns serialization and metadata
  validation. The runner does not duplicate cache rules.

Small methods such as `from_mapping`, `to_mapping`, and `to_dict` are model
serialization methods, not duplicate workflow implementations. Process-pool
initializers and worker functions may have no ordinary call site because they
are passed to `ProcessPoolExecutor`; they are retained deliberately and are
covered by plotting tests.

## Runtime data flow

1. **Add/open projects.** `project_scan_runner.scan_projects_cached` restores a
   valid entry from `.state/project_scan_cache.json` or calls
   `scanner.scan_project` for a missing/changed project. A cold scan inventories
   `.inf` descriptors, project timing/frequency, voltage/MM configuration,
   NonConv information, outputs, and PSCAD-log candidates. The first valid
   `Statistic*.out` supplies the project-wide `Run# -> Fault_type` map. The
   scan keeps compact UI metadata, not full output-file lists.
   In the project tree, double-click the project-name cell to open project-
   specific Settings, or double-click the status cell to open the project
   folder through the operating system. Project-specific scan data and UI state
   are keyed by the canonical project path. Tree refreshes block intermediate
   selection signals and the exclusions panel is reloaded only for the active
   row with a current scan; otherwise it is cleared rather than using another
   checked project as a fallback. Detected High Voltage rows come only from
   that project's scan. The session stores only explicit include overrides and
   reconciles them with the current scan, so an orphaned row from another
   project cannot reappear as an `Analysis` finding.
2. **High-voltage proposals.** PSCAD-log warning case/MM pairs are checked
   against matching raw waveform channels for every run and cached. A changed
   factor or `Um` reclassifies cached maxima; it does not reread those files.
   A changed log or matching raw input refreshes the targeted cache. No log does
   not trigger a full raw-results scan.
3. **Select work.** The UI passes selected projects, scopes, voltages, envelopes,
   settings, exclusions, and include overrides to the functions in `actions.py`.
   Voltage levels are selected through the `Voltages` popup: `All voltages`
   is the tri-state master checkbox and the entries below it are the individual
   levels.
4. **Build envelopes/checks.** `voltage_envelope.build_voltage_envelopes`
   loads `Statistic*.out` tables through the NumPy fast path (with the legacy
   pandas fallback), using one process below 1,000 files and a separate pool
   capped at four workers for larger sets. It applies Manual and NonConv rules,
   reads voltage-specific raw `.out` data,
   performs the authoritative high-voltage check, creates per-run chronological
   envelope data, merges the selected runs, and writes the base workbook. A
   processed envelope data exists only during the current build, and the
   single project `.state/analysis_cache.json` can skip the complete stage
   when its artifacts are current. Selected voltage levels submit reads
   concurrently through one shared bounded process pool, so the worker cap is
   not multiplied by voltage count. Presentation-only changes can reuse
   validated calculation artifacts without rereading raw waveforms. Stress/Late/No-settle consume
   the envelope data. Sustained SDPF consumes the raw phase/pair arrays already
   loaded by the envelope workers; it must not create a second raw-read pass.
   The project analysis cache is versioned and stores only signatures and
   output metadata. Its envelope signature includes the current Sustained
   SDPF result and summary-workbook format versions; the result version is
   also included in plot/report signatures, so stale algorithm outputs are rebuilt while no
   processed waveform arrays are retained between builds. A shared validator
    checks the saved result version, settings, source fingerprint, and
    per-voltage signature before batches, heatmaps, or reports reuse the
    result. Source paths in that compact manifest are project-relative POSIX
    paths, including on Windows, so the build and later validation hash the
    same metadata. An invalid cache is logged with its reason and cannot
    create an empty Sustained batch that looks like a clean result. Sustained plot
   rendering receives the same project SDPF overrides as detection and leaves
   SIWL values unchanged. During one connected workflow, the loaded Sustained
   payload is reused by batch creation, plot rendering, heatmaps, and reports.
   The connected run also computes one in-memory cache validation per scope and
   passes it through those stages, so the same source fingerprint is not walked
   repeatedly; standalone actions still validate their saved data locally.
   Active parallel plot workers are terminated promptly on Stop.
5. **Post-processing.** The selected action builds combined Excel charts, plot
   batches, rendered plots, heatmaps, and reports. `Rebuild heatmaps` uses the
   saved Sustained SDPF JSON only; it does not reread waveforms. If validation
   reports a stale or mismatched Sustained cache, rerun `Build envelope
   data/checks`; the report log identifies the exact reason instead of
   silently presenting the missing section as no finding. `Rebuild reports`
   regenerates DOCX files from existing outputs.

## Engineering and output contracts

### Exclusions and envelopes

- Manual rules use `Case`, `Run`, and `Bus`; blank fields are wildcards and a
  completely blank row is ignored. Run and Bus cells accept comma-, semicolon-,
  or newline-separated values; normalization expands them into individual exact
  rules, using the Cartesian product when both cells contain lists. Run ranges
  are not inferred.
- The `Scopes` list is intentionally global. A selected token filter is applied
  to every selected project; this is separate from project-specific scans,
  exclusions, settings, output state, and status, which are never shared by
  project name or by list position.
- NonConv and High Voltage proposals use the same checked/unchecked table
  workflow and are shown only when the active project has corresponding rows.
  PSCAD-log High Voltage rows start checked. Unchecking a row stores an exact
  include override for the next envelope build.
- The envelope build is the authoritative all-case High Voltage check. If one
  phase on a case/run/bus exceeds the configured limit, that bus is excluded
  from both LGp and LLp. Newly found exclusions are added to the UI as checked.
- The UI aggregates High Voltage rows by voltage/case/run/bus and shows the
  source (`PSCAD log`, `Analysis`, or `Both`). The workbook keeps the existing
  detailed `High voltage exclusions` table with measurement, signal, source
  file, excluded value, limit, and source columns. Do not replace that workbook
  structure with the UI aggregation.
- `Envelope time end` uses the selected project's `Final duration` by default.
  A manual end time is available. Each run is capped at the timestamp present
  in that run; shorter runs contribute only over their available interval and
  are not zero-padded.

### Envelope events and resonance checks

- The base workbook is a representative ranked envelope. TOV and SFO select the
  nearest `LLp` row to their configured times; SA selects the nearest `LGp` row.
  Exact matches win and the tolerance is `0.001 s`; no row within the tolerance
  means no event plot job. These event selections are independent from the
  resonance findings and Sustained SDPF selection.
- Stress uses chronological per-run `E(t) = max(valid phase envelopes)` after
  release/manual start and ranks positive-area findings by `A_post`. Late Growth
  requires positive slope plus the relevance gate and ranks by
  `(sigma, growth ratio, positive fraction, tail p95 / Vlim)`. No-settle is only
  used when automatic release is enabled and no release is found; it uses the
  same gate and ranks by `(sigma, positive fraction, longest positive-growth
  window, growth ratio, end p95 / Vlim, area)`. Top N is selected independently
  for each check, voltage, and LGp/LLp measurement type.

### Sustained SDPF method

The implementation uses the project-defined peak-envelope persistence method:

- fixed LG paths: `A-G`, `B-G`, `C-G`;
- fixed LL paths: `A-B`, `B-C`, `C-A`;
- the default minimum persistence is 30 ms of physical peak-envelope duration;
  the app derives `ceil(duration × frequency)` consecutive complete cycles and
  uses that as a minimum qualification condition as well as a reported coverage
  value;
- every cycle retains its maximum absolute peak and true RMS, with
  NaN/missing segments and sub-threshold cycles splitting the data;
- peak persistence is compared with the SDPF and `SDPF / 1.15` peak
  thresholds; RMS remains a supporting diagnostic and cannot qualify a TOV; and
- no maximum-across-phases series or cross-phase stitching is allowed.

A short threshold excursion touching two cycle bins does not qualify merely
because it occupies both bins. Consecutive qualifying cycle peaks define a
piecewise-linear peak envelope; threshold crossings are interpolated and the
event must last at least the configured physical duration. A sub-threshold,
missing-cycle, or data gap ends that event and a later excursion is kept
separate.

The result category is based on the qualifying peak-envelope event: Actual
SDPF, Safety-margin-only, or no qualifying sustained TOV. A Case/Run/MM is
Actual SDPF when any fixed path has a sustained actual-limit qualification;
otherwise it is Safety-margin-only when at least one fixed path has a
sustained margin qualification. `sdpf_exceeded = False` does not mean that
the waveform never crossed SDPF instantaneously. The physical minimum
duration is configured in milliseconds and is independent of the ordinary TOV
event setting. The new `V_T` metric is the highest level the same
piecewise-linear qualification envelope remains at or above for the full
physical duration T, ranked as `V_T / actual SDPF peak limit`; a lower
opposite-polarity lobe is retained as a full-wave severity gap even when the
absolute peak keeps the screening run consecutive;
separate events,
phases, and pairs are not stitched. For ranking, the full-wave envelope
retains both positive and negative peak magnitudes with true timestamps, so a
lower opposite-polarity peak creates a real below-limit gap. The two
populations are not compared. Within each population, the enabled independent
selections are `Highest voltage sustained for T`, `Worst cumulative stress`,
and `Longest continuous duration`. Areas are not summed across paths or
separated events. The summary workbook includes all Case/Run/MM rows, including
non-candidates, but only a voltage with a candidate receives a Sustained
waveform and DOCX section. If several criteria identify the same
Voltage/Case/Run/MM and fixed path/event, the plot is reused; a different
fixed path or event remains a separate report row. Short events stay with
SFO/AFO.
This is intentionally different from a formal CIGRE TB 913 voltage-based
assessment.

Limits come from the embedded plotter `MM_blocks` reader. Settings show the
resolved LG/LL RMS limits as `Input xlsx`; a project-specific manual RMS edit
changes the source label to `Manual` and recalculates peak and margin values.

### Sustained SDPF persistence and heatmaps

Each selected scope writes:

- `Voltage_envelope/<scope>/Sustained_SDpf.json` - compact version-19 result
  metadata with one shared source fingerprint, fixed-path `V_T`, area and
  duration scalars, independent Actual SDPF and Safety-margin-only selection
  references, and Run x MM observations;
- `Voltage_envelope/<scope>/Sustained_SDpf_summary.xlsx` - a compact workbook
  with `Ranked cases` and `Representative selections` sheets. The ranked
  table keeps one Case/Run/MM observation per row, including no-qualification
  rows, and shows the population rank, Actual SDPF or Safety-margin-only
  population, governing fixed LG/LL measurement/phase, applied threshold,
  normalized excess area, longest continuous duration, highest sustained `V_T`,
  sustained peak, event timestamps, qualifying path list, and limit source.
  A small method block records result version, persistence, frequency, and
  derived cycle coverage. The representative sheet lists the independently
  selected highest-`V_T`, cumulative-stress, and longest-duration rows for each
  population; it is not a plot manifest and contains no waveform data or plot
  settings; and
- `Plots/Generated/<scope>/Sustained_SDPF_Heatmap/<order>_<name>/` - generated
  heatmap PNGs for each enabled named set.

Heatmap rules:

- default set is **Faults** when fault classifications exist, otherwise
  **Cases by <token>**, grouped by the first varying case-name token (for
  example, **Cases by S**), or **All cases** when no token varies;
- **Fault type** and **MM element** are optional Y-only views. Fault rows
  aggregate MM elements; MM rows aggregate fault types. MM is not the no-fault
  fallback;
- X grouping only orders and labels the resulting columns; it does not create
  synthetic cases or change observation membership. When a case token is used
  as Y, it is removed from the compact X identity, so one visible column may
  intentionally represent cases differing only in that Y token while Run × MM
  observations remain separately counted. Split by creates only figures for
  observed split values and filters each figure to its actual cases; it must
  never synthesize duplicate/nonexistent cases;
- Max cases per heatmap defaults to 12 but is editable (up to the persisted UI
  limit). Combined panels are vertical and use one shared legend; Y tick labels
  repeat on every panel, all identifiers remain horizontal, and no separate
  vertical Y-dimension caption is added. A `Page i/n` suffix is used only when
  the same split continues across multiple files;
- heatmap headers keep only plot-local context; split categories are labelled
  from the selected project token as `Split: <value>`, X grouping is
  shown in a dedicated band containing only the selected token value, and case
  labels use a dedicated band below the matrix when residual case identity
  remains. Tokens already
  represented by Y/X/Split or constant in the panel are omitted. Equal labels
  are allowed in different visible X-groups or split panels; only a true
  same-context collision uses an unselected-identity fallback; if no residual
  identity remains, the case-label band is omitted. Continuation order is
  carried by filenames/page order rather than printed `part i/n` text;
- figure positioning uses fixed, named inch-based bands for the header, split
  header, X-group band, matrix, case labels, and footer, so these elements do
  not share coordinates or rely on tight-layout side effects;
- each cell counts each eligible Run x MM observation once after LGp/LLp and
  fixed-path flags are OR-merged. The top percentage is actual SDPF incidence
  and the bottom is inclusive safety-margin incidence; the same qualifying
  peak-envelope duration and complete-cycle rule qualifies the cell. `0%`
  means eligible data with no findings, `<1%` means a nonzero sub-percent
  value, and `—`/grey means no eligible data. Colours are green (no
  qualifying exceedance), amber (margin-only), red (actual SDPF), and grey (no
  eligible data); actual and margin-only intensity use separate percentage
  scales, and the largest absolute-count outline is retained; and
- changing layout/grouping/splitting requires `Rebuild heatmaps`; use
  `Rebuild reports` afterward to put the updated images in DOCX reports.

Reports use the configured heatmap-set name as the concise subsection label,
followed by semantic headings such as `Split S: S1` or `Combined panels`.
Raw PNG filenames and technical Y/X configuration strings are not used as
report headings. A valid no-candidate cache may still render heatmaps through
`Rebuild heatmaps`, but reports attach them only when the voltage has a
governing Sustained candidate. The report's main hierarchy is one voltage assessment heading
followed by concise sections such as `Voltage Envelope`, `SFO`, `TOV`,
`Sustained SDPF`, and `Post-event Stress`.

### Main output tree

```text
.state/
  analysis_cache.json       # compact envelope/plot/report stage metadata
Voltage_envelope/
  <scope>/
    MM_<voltage>.xlsx
    MM_<voltage>_with_combined_plot.xlsx
    Resonance_Checks.xlsx
    Sustained_SDpf.json
    Sustained_SDpf_summary.xlsx
Plots/Plot_batch/
Plots/Generated/<scope>/
Reports/<scope>/
```

Base envelope workbook sheets and table formatting are an existing output
contract. Excel native AutoFit is applied through the already packaged Excel
automation support; do not create a second formatting system.

## Settings and user actions

Settings are edited in the dedicated dialog and committed to the session when
the dialog is accepted. Project-specific values are kept per project. In
particular, heatmap set names/order/grouping/splitting/layout, Sustained SDPF
limit overrides, Sustained SDPF physical duration, the three Sustained SDPF
representative-ranking checkboxes, envelope duration mode, chart axes, exclusions, and worker
mode must survive closing and reopening Settings; changing a ranking checkbox
does not invalidate the engineering result cache, and changing a heatmap layout
does not require another project scan.

Dashboard figure metadata is cached by canonical project path. The UI shows
the union of the cached catalogs by default, with the short `All checked`
checkbox applying one shared checked-ID list to every checked project. Clearing
it exposes the active project's list and stores local selections. When shared
mode is enabled again, the active project's selection becomes the shared source
and local selections are preserved. The report builder still receives a
separate filtered ID list per project, so a figure missing from a project is
skipped harmlessly. Former project-specific or global dashboard selections are
migrated once into the shared selection format.

The normal action order is: **Build envelope data/checks** for new or changed
waveform/threshold inputs; the event or Analysis step buttons for selected
plot work; **Rebuild heatmaps** after heatmap layout changes; and **Rebuild
reports** after any generated figure change that must appear in DOCX. Changing
chart axes only needs chart rebuilding; changing an analysis threshold or
Sustained SDPF duration needs the corresponding data/check build.

## Important settings and performance decisions

- Envelope workers: `Automatic` is on by default. It selects the ceiling of
  80% of detected logical CPUs, capped at 60 and reduced when fewer runs exist.
  The cap is shared across concurrently submitted voltage levels. Clearing
  Automatic enables a positive manual override. This is a measured SSD-oriented
  default, not a promise that all machines scale with every core.
- Envelope duration: automatic project duration by default; manual end time is
  supported for targeted studies.
- Automatic waveform Excel exports are enabled by default. Clearing the option
  keeps PNG plots and analysis unchanged and avoids generated `.xlsx` writes;
  manually edited batch rows may still request an export explicitly.
- Plot rendering prepares all concrete jobs from one project's selected
  scope/event batch files before execution. At `3+` jobs with at least two
  cache-local Case/Run groups, one bounded Windows `spawn` pool capped at four
  workers renders the PNG and optional Excel output in the same process-local
  renderer/exporter. Related jobs are grouped in chunks of up to eight; a
  single group stays sequential because a second process would not add useful
  parallelism. Smaller batches stay sequential.
  Output folders remain independently staged and atomically committed per
  scope/event; a failed or cancelled batch does not replace its previous good
  output. A pool-start or child-worker failure falls back to sequential
  rendering. Each successful event/check folder contains only generated
  outputs; normalized job/source signatures and output metadata are stored in
  the single project analysis cache, so unchanged batches are skipped on later
  renders.
- The centralized plot and report signatures include the current Sustained
  SDPF result version; Sustained report signatures also include the current
  Sustained report-layout version, so render-only or report-only actions rebuild
  outputs that came from an obsolete Sustained algorithm.
- Project opening is cache-first. Use `Rebuild project cache` when source files
  changed in a way that size/mtime validation cannot detect.
- Raw waveform reading is the dominant cost. Do not add lazy settings scans,
  repeated project scans, or a second Sustained SDPF waveform read without a
  benchmark and an explicit design reason. Warm project validation uses one
  `os.scandir`/`DirEntry.stat()` walk for the targeted case files, and envelope
  source manifests reuse an indexed directory listing plus binary-searched
  output prefixes; these changes add no persistent files or dependencies.
- Plot process workers do not receive Qt objects or the parent renderer. They
  rebuild process-local renderer/exporter state from the simple run index;
  each renderer loads only requested waveform columns, reuses standardized
  Case/Run frames, and limits selected-column data to 256 files/1 GiB plus a
  256-frame/512 MiB group-frame cache. Excel exports use write-only workbooks.
  Queued work can be cancelled, and active parallel workers are terminated on
  Stop; a broken pool is retried sequentially. The current uncommitted staging
  directory is discarded, so a cancelled batch cannot replace the previous
  good output.
- Heatmap rendering uses the same bounded process policy for independent PNG
  pages: it switches at three or more pages, uses Windows `spawn` with the
  shared four-worker cap and queue bound, and falls back to sequential rendering
  if the pool cannot start or a worker dies. Each worker writes only its own
  private staged image; heatmap data preparation and the final atomic replacement
  of the complete set remain in the parent. Cancellation terminates active
  heatmap workers and removes the uncommitted stage.

## How to run and validate

From this app root, use the dedicated environment (never `base`):

```bat
start_app.bat
```

```bat
..\.conda\pscad-results-analysis\python.exe -m results_analysis_app
```

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TMP = "$PWD\.tmp"
$env:TEMP = "$PWD\.tmp"
..\.conda\pscad-results-analysis\python.exe -m pytest -q -o cache_dir=.tmp\pytest_cache
```

The latest recorded local source-level validation for this snapshot passed
**248 tests**. Run the command and report its actual result rather than relying
on the number. Also run the dependency import smoke check when packaging/setup
is touched, and `Create_executable.bat` only when the executable itself is
being validated.

Measured reference timings on the development machine are approximately **7.8
s cold / 0.48 s warm** for the persistent project scan of
`../Original_examples/03_Test_project_case`; raw envelope reads across
66/161/230 kV were about **53 s** in one run. Plotter catalog/indexing and
temporary batch creation were below **0.04 s** and **0.3 s**, respectively, so
raw waveform/envelope processing remains the main optimization target. Excel
COM work remains shared and sequential. Plot and heatmap rendering use the
existing three-job threshold and four-worker cap; do not change that policy
without a representative benchmark.

## Safe change checklist for a new chat

1. Confirm the request is a behavior change, a presentation change, or a
   documentation-only change.
2. Read the current source and the focused tests before proposing a fix.
3. Preserve the existing envelope workbook structure and report workflow unless
   the user explicitly approves an output-contract change.
4. Reuse the existing scanner, exclusions, waveform reader, envelope rows,
   plotter, and report helpers. Delete or simplify before adding abstractions.
5. Keep raw reads cancellation-aware and avoid work on the Qt GUI thread.
6. Add focused tests for changed calculations, persistence, output formatting,
   and UI-model normalization as applicable.
7. Run the narrow tests, then the full contract suite if practical. Use `.tmp/`
   for caches and preserve user project outputs.
8. Update `README.md`, `docs/CURRENT_CONTEXT.md`, and
   `docs/ANALYSIS_METHODS.md` when setup, workflow, calculation, output, or
   risk information changes.

If a requirement is ambiguous, inspect the repository and reference examples
first. Ask before changing engineering thresholds, file formats, or required
functionality; do not silently introduce a parallel implementation.
