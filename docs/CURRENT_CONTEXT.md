# Current Context

Snapshot date: 2026-09-07.

This folder is the active app root for PSCAD Results Analysis. The parent folder keeps reference examples, backup material, and the existing dedicated conda environment.

For a new Codex chat, start with [`HANDOFF.md`](HANDOFF.md), then read this
file and [`ANALYSIS_METHODS.md`](ANALYSIS_METHODS.md). The handoff is a
concise map; this file contains the more detailed current-state notes.

## Project purpose

Desktop app for PSCAD result analysis:

- collect PSCAD project folders;
- detect scopes, cases, voltage levels, dashboards, and exclusions;
- build voltage envelopes from PSCAD results;
- create envelope charts;
- create waveform plot batch workbooks;
- render waveform plots through the embedded plotting engine;
- generate DOCX reports;
- run optional Stress, Late, and No-settle checks using existing chronological envelope data;
- run optional Sustained SDPF stress on fixed chronological LG phases and LL pairs.

## Operating regimes

The UI and workflow are organized into these regimes:

1. **Project/session** - add/remove projects, restore the session, switch the
   active project, inspect project-specific settings/exclusions, and open the
   project folder.
2. **Scan/catalog** - use the project scan cache, discover dashboard figures,
   and refresh dashboards when requested.
3. **Envelope/check** - apply exclusions, read raw results, build envelopes,
   run the authoritative High Voltage gate, and calculate the selected checks.
4. **Batch/render/report** - create and render MM plot batches, render
   Sustained SDPF heatmaps, and build DOCX reports.
5. **Rebuild-only** - rebuild charts, heatmaps, or reports from valid saved
   artifacts without repeating unrelated raw waveform work.

The connected `Run analysis` action uses the normal stage functions in this
order: envelope/check, plot-batch creation, plot rendering, and report
assembly. It loads and validates Sustained SDPF results once per scope and
passes that payload through dependent stages. Separate buttons are narrower
maintenance or stage actions and should not be assumed to rerun the full path.
`Run analysis` and `Rebuild reports` do not refresh Excel dashboards;
`Dashboards update` performs Excel `RefreshAll`, while `Scan figures` only
discovers saved dashboard figure catalogs.

## Current code organisation

- `src/results_analysis_app/__main__.py` - application startup, Windows identity, icon, and system-theme installation.
- `src/results_analysis_app/main_window.py` - PySide6 UI and worker orchestration.
- `src/results_analysis_app/settings_dialog.py` - Settings dialog construction and settings-to-session updates.
- `src/results_analysis_app/background.py` - cancellable Qt background-task wrapper.
- `src/results_analysis_app/project_scan_runner.py` - project-opening scan and cache wrapper.
- `src/results_analysis_app/project_scan_cache.py` - persistent metadata-validated project scan cache.
- `src/results_analysis_app/exclusions.py` - shared exclusion rules, matching, normalization, and legacy-session migration.
- `src/results_analysis_app/envelope_rows.py` - shared nearest-time envelope row selection for plot batches and report values.
- `src/results_analysis_app/styles.py` - centralized light/dark palette and semantic widget styling.
- `src/results_analysis_app/storage.py` - session paths and JSON persistence.
- `src/results_analysis_app/excel.py` - shared Excel COM application context and targeted automation error types.
- `src/results_analysis_app/actions.py` - high-level workflow actions.
- `src/results_analysis_app/analysis_engine.py` - plot batch creation/rendering bridge.
- `src/results_analysis_app/voltage_envelope.py` - envelope data build.
- `src/results_analysis_app/envelope_chart.py` - Excel envelope chart generation.
- `src/results_analysis_app/resonance_checks.py` - Stress/Late/No-settle checks and check chart workbook output.
- `src/results_analysis_app/sustained_sdpf.py` - Sustained SDPF phase/pair analysis, ranked summary workbook, and compact JSON result metadata.
- `src/results_analysis_app/reporting.py` - DOCX report generation and dashboard figure insertion.
- `src/results_analysis_app/scanner.py` - project scan, dashboard scan, exclusions, high-voltage log scan.
- `src/results_analysis_app/project_config.py` - voltage and frequency config from `Input_Data_PSCAD*.xlsx` and `.inf` files.
- `src/results_analysis_app/models.py` - session model and default settings.
- `src/pscad_plotter_app_v3/` - MM-only embedded plotting, Excel-export, and process execution engine used by report batches.
- `docs/ANALYSIS_METHODS.md` - code-level description of inputs, exclusions, envelope construction, checks, charts, plots, and reports.
- `docs/HANDOFF.md` - concise new-chat architecture, data flow, output contracts, and safe-change checklist.
- `tests/test_plotting.py`, `tests/test_reporting.py`, `tests/test_scanning.py`, `tests/test_envelope.py`, `tests/test_ui_models.py`, `tests/test_resonance.py`, `tests/test_sustained_sdpf.py`, and `tests/test_sustained_sdpf_heatmap.py` - focused contract tests.
- `AGENTS.md` - project-specific development and validation rules.
- `STARTER_PROMPT.md` - onboarding prompt for a new machine or clean task.

## Environment

Use Anaconda with a dedicated environment:

```bat
conda env create --prefix ..\.conda\pscad-results-analysis -f environment.yml
```

Run:

```bat
start_app.bat
```

Test:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TMP = "$PWD\.tmp"
$env:TEMP = "$PWD\.tmp"
..\.conda\pscad-results-analysis\python.exe -m pytest -q -o cache_dir=.tmp\pytest_cache
```

If environment creation does not install the project in editable mode:

```bat
..\.conda\pscad-results-analysis\python.exe -m pip install -e ".[dev,packaging]"
```

The project-local prefix `../.conda/pscad-results-analysis` is used on this machine so `start_app.bat` and `Create_executable.bat` can run without manual activation. It remains in the parent folder because moving an existing conda prefix can break compiled packages and activation metadata.
Pytest uses `.tmp/` on this machine because the default user temp folder can be unavailable to the current process.

Parent-folder layout:

- `../Original_examples/` - original scripts and small test project used as references.
- `../02_Backup/` - backup material.
- `../.conda/pscad-results-analysis/` - dedicated conda environment.
- `../.pytest_cache/` - generated pytest cache left in place if Windows has it locked.

## Source control

- Git is configured in this app root. The active branch is intentionally not
  hard-coded here; use `git branch --show-current`.
- `origin` points to the project GitHub repository.
- `.gitignore` excludes local environments, `.state/`, sessions, caches, build output, and generated PSCAD analysis output.
- Always inspect the worktree before editing or committing and preserve unrelated changes.

Current source versions that govern invalidation are:

| Artifact | Version | Source owner |
| --- | ---: | --- |
| Project scan cache | 7 | `project_scan_cache.py` |
| Project analysis cache | 1 | `storage.py` |
| Voltage-envelope manifest | 3 | `voltage_envelope.py` |
| Sustained SDPF result JSON | 19 | `sustained_sdpf.py` |
| Sustained SDPF summary workbook | 4 | `sustained_sdpf.py` |
| Plot batch manifest | 2 | `analysis_engine.py` |
| Report/report-layout manifests | 2 / 3 | `reporting.py` |
| Embedded plotter SQLite/MM cache | 2 / 1 | `pscad_plotter_app_v3/services/project.py` |

The app rebuilds obsolete or incomplete artifacts. It does not persist a
processed-waveform cache; project and analysis caches contain compact metadata,
signatures, and output records only.

## Graphify navigation state

The local `graphify-out/` directory is an ignored generated repository graph,
not application output. It currently contains the code graph built from commit
`619d5656`: 1,560 nodes, 4,993 edges, and 61 communities. Use Graphify
`query`, `path`, or `explain` for architecture/navigation questions before
opening source files. Rebuild it after source changes with the two commands in
`docs/HANDOFF.md`; verify important inferred edges against code and tests.

## Current workflow logic

Project scanning:

- User can select one or more PSCAD project folders from the Add dialog. Duplicate folders are ignored, the UI/session are updated once, and only newly added projects are scanned. Saved projects are not rescanned unnecessarily. Mixed cached/stale startup scans only stale projects and preserves valid cached entries.
- In the project tree, double-clicking the project-name cell opens project-specific Settings; double-clicking the status cell opens that project's folder through the operating system.
- Opening validates core `.inf`, NonConv, voltage-input, and targeted PSCAD-log waveform metadata against `.state/project_scan_cache.json`. Dashboard and envelope metadata plus plot/report/result presence are tracked separately. Dashboard-only changes add a `Dashboards changed` notice, envelope-only changes refresh High Voltage proposals, and output-presence changes update status chips without a core rescan. Unchanged entries restore serialized scan data without rewriting the cache; missing, changed, corrupt, or forced core entries run the normal scanner. Ordinary waveform `.out` files are ignored except for runs named by PSCAD-log warning candidates.
- Scanner reads project structure, case counts, project frequency/final duration, dashboard workbooks, available voltage levels, non-convergence proposals, and existing envelope high-voltage proposal files when a cold scan is required. Base `MM_<voltage>.xlsx` workbooks are authoritative; combined chart workbooks are used only when a base workbook is absent. Fresh-scan warnings are logged once instead of being silently retained in cache. If `PSCAD_log.txt` exists, project initialization also uses a bounded pool to read the maximum raw waveform value for every matching case/run/MM bus. Multiple cold project scans stay sequential to avoid nested worker contention.
- The cold scan passes its existing `.inf` inventory to the PSCAD-log high-voltage pass, and envelope builds reuse cached `Um`/bus configs, SDPF limits, and NonConv records from that scan. A direct envelope caller without scan data retains the original fallback reads.
- Project scan cache version 7 stores core inputs, case names, the project-wide `Run#` → `Fault_type` map, cached `Um`/bus configurations and validated `MM_blocks` SDPF limits, the compact per-project dashboard figure catalog, dashboard files, envelope files, output-presence state, and whether each workbook-derived high-voltage row was actually excluded. The fault map, dashboard catalog, and workbook-derived settings are read during the cold scan and reused by Settings and the high-voltage table; no lazy project-data read is needed. Each cold or hot project pass builds the full manifest once. Upgrading from an older cache performs one cold scan.
- Project scan status stores output-presence flags rather than unused full output-file lists. Analysis action completion reuses the validated input manifest and refreshes only output metadata because source PSCAD inputs are not expected to change while the app is open.
- `Rebuild project cache` in Settings is the maintenance-only forced scan for all saved projects. Analysis actions update only affected output flags and cache entries; they do not trigger a full project scan.
- Removing a project purges all of its project-specific settings, exclusions, status, and cached scan so re-adding it starts cleanly.
- Malformed autosave JSON falls back to a default session so startup is not blocked by damaged state.
- Temporary report export images are removed after each scope's DOCX reports are written.
- Unreadable existing envelope workbooks are skipped during project status scanning; the remaining project scan continues.
- Conda runs store autosave under `.state/`; frozen executable runs store `.state/` and `sessions/` beside the executable.
- Voltage levels are detected from `Input_Data_PSCAD_Python_v11.xlsx` where available and from `.inf` signal prefixes. Treated result CSVs and generated plot filenames are not used to define available voltage levels. If `Um` is missing for a detected voltage, the user must fill it in Settings.
- PSCAD `.inf` case/run parsing and `.out` column mapping are shared with the embedded plotter waveform I/O helpers. One case-insensitive parser handles both `_r` and `_R` run markers.
- Envelope builds enumerate `.inf` files once per build, build one shared source-file inventory for manifest fingerprints, and BLAKE2b-hash each selected layout. Identical contents share one parsed descriptor template across scopes and voltages. NonConv summary files and raw voltage runs use bounded process workers; one run is submitted per worker and processed envelope data exists only during the current build, while the parent handles scope merging and output. The single project `.state/analysis_cache.json` stores only the envelope signature and output metadata, so an unchanged complete stage is skipped without persisting waveform arrays. Selected voltage levels submit raw-read jobs concurrently through one shared process pool, so the configured worker cap is not multiplied by the number of voltages. Presentation-only changes can reuse validated calculation workbooks and regenerate charts/autofit outputs without rereading raw waveforms. Envelope workers default to automatic selection: the ceiling of 80% of detected logical CPUs, capped at 60 for Windows process-pool compatibility and reduced when fewer runs exist. Settings expose an `Automatic` checkbox enabled by default; clearing it enables a positive manual override. Raw `.out` waveform reads remain voltage-specific.
- The project analysis cache has one schema version and contains only stage signatures, output paths, sizes, and modification times. The envelope signature includes both the current Sustained SDPF result version and the summary-workbook format version; a summary-only format change therefore rebuilds the envelope/summary outputs while leaving the engineering result schema unchanged. The current result version is included in plot/report signatures, and the current Sustained report-layout version is included in report signatures when Sustained is enabled. Old per-run pickles and folder manifests are ignored and removed during the next relevant build. Sustained plot rendering receives the same project SDPF overrides as detection and preserves SIWL independently.
- Project `Final duration` and frequency are read during initialization and persisted in the project scan cache. `Final duration` caps the configured `Envelope time end`; the final timestamp from each already-loaded raw time column provides a second per-run cap, so no extra `.out` pass or zero padding beyond real waveform data is used.
- `Chart x max` defaults to each project's cached `Final duration`. `Chart x major` defaults to a readable interval near one tenth of the effective range. Optional overrides are project-specific and saved in session state. Envelope and resonance charts share both settings and cap the x maximum at the available generated data duration.
- Envelope high-voltage checks and rolling envelopes reuse the same absolute-value arrays. A run completes its high-voltage scan before rolling envelopes are calculated, so buses excluded by that scan do not perform discarded rolling/interpolation work. Envelope workbooks keep their existing openpyxl table/filter formatting, then use Excel's native AutoFit through the already-packaged Excel automation support.
- Envelope phase candidates use one direct NumPy reduction per phase while preserving source-order ties and Case/Run provenance; the former intermediate dataframe merge chain is gone.
- Sustained SDPF finite-segment discovery and common-grid cycle slicing use vectorized boundary/index operations; the qualifying, area, and duration rules are unchanged.
- The embedded report plotter supports only MM voltage waveform batches. Legacy CB, arbitrary-channel, FFT, combined-mode, and unused catalog branches were deleted; MM plot rendering and Excel waveform exports remain. Automatic waveform Excel exports are enabled by default and controlled by Settings; clearing that option changes generated batch rows to PNG-only while preserving explicit manual batch requests. Its SQLite cache loads only the MM element rows needed for batch validation.
- Sustained SDPF results persist one shared source fingerprint and compact source-directory roots when all voltage inputs are identical. Heatmap rebuilds, plot-batch creation, and report validation check that fingerprint once per scope and reuse the result; pre-version-19 result caches are rebuilt rather than retained. Persisted fixed-path data is finite-validated and the governing path is recomputed on load instead of being duplicated in each cached result. Version 19 stores compact qualifying-event descriptors alongside population-specific fixed-path selection descriptors plus the small selected-result pool; flat aliases and embedded duplicate result objects are not written. Incomplete current-version selection data invalidates the cache instead of silently falling back to the canonical result. Ranking-checkbox changes are project-specific downstream controls and do not invalidate the engineering result cache. Common-grid bus analysis reuses one cycle index across finite phases, while irregular or incomplete phase data uses the general per-phase path. Event-only batch actions leave Sustained SDPF batches and heatmaps untouched. One connected analysis run reuses loaded Sustained SDPF payloads across batch creation, plot rendering, heatmap generation, and report assembly. The project scan cache and project analysis cache are written compactly; session/autosave JSON remains pretty-printed.
- Background-task failures include tracebacks in the app log, while cancellation is emitted as a separate stopped result and is not wrapped as a rendering failure. Report generation checks cancellation between safe project, scope, voltage, export, and figure boundaries. Window close waits for active work to cancel and finish. Envelope process workers check cancellation between completed runs; shared raw `.out` readers retain 4,096-row checks for high-voltage, plot-rendering, and Excel-export reads; Excel and output-writing operations still finish their current operation safely. On cancellation, active parallel plot and heatmap workers are terminated and staged outputs are discarded, so Stop does not wait for every active PNG/export job to finish. Heatmap pages use the shared three-job threshold and four-worker cap, while data preparation and final atomic replacement remain serialized in the parent.
- While a background action is running, all workspace controls remain disabled except the read-only log. The log remains scrollable and copyable, preserves a manually scrolled-up position, and follows new messages only when the view was already at the bottom.
- Malformed `.inf` layouts and unreadable CB or high-voltage proposal files are surfaced as scan/build warnings.
- Project frequency fallback is read from `Input_Data` cell `B16` when available. If automatic frequency detection fails and no input frequency is available, the app uses the configured fallback frequency and logs/notifies the user.
- The bottom-left status bar text is owned by the dedicated status label; native temporary status messages are cleared to avoid duplicate overlapping text during background tasks.
- The application follows the Windows light/dark colour scheme at startup and listens for changes while open. One application palette and stylesheet control panels, tables, headers, tabs, inputs, labels, buttons, selections, disabled controls, status controls, and scrollbars. A shared proxy style draws the same high-contrast checkbox indicators for standalone widgets and checkable list/tree/table items.
- Sustained SDPF cache handoff uses one shared validator for the saved version, current settings, source fingerprint, per-voltage signature, and selected result rows. The source manifest is scanned once per scope and reused by voltage lookups. A stale or settings-mismatched cache is logged with its reason, stale Sustained outputs are removed, and no empty batch is written to represent an invalid cache; a valid cache with no qualifying candidate remains an intentional empty result.
- Dashboard figure-only scans update only the checked projects' dashboard metadata and figure catalogs without triggering a core project scan. Catalogs are restored from the version 7 scan cache on warm open, and a changed dashboard workbook triggers a targeted catalog refresh automatically. `All checked` is enabled by default: the UI shows the union of cached catalogs and persists one shared checked-ID list, which is filtered for each project's report; clearing it stores project-specific selections, which are preserved when shared mode is enabled again. In a mixed multi-project refresh, failed projects retain `Dashboards changed` while successful projects are cleared.

Exclusions:

- The `Manual` table uses the shared columns `Apply`, `Case`, `Run`, and `Bus`. New rows are applied by default, editable, and support TSV copy/paste.
- Blank manual fields are wildcards. Case-only, run-only, bus-only, and all two-field combinations are valid; a completely blank row is ignored so it cannot exclude the full dataset.
- `NonConv` and `High Voltage` rows are detected proposals. Their tabs appear only when the active project has corresponding rows. They use the same checkbox visuals and `Apply all` / `Apply none` controls as the Manual table, but their detected data columns remain read-only. High Voltage rows are consolidated by voltage/Case/Run/Bus and show `PSCAD log`, `Analysis`, or `Both` as their source. PSCAD-log rows are checked automatically when a project is added.
- Applied manual, NonConv, and High Voltage rows are normalized into one matching rule set. NonConv rules match Case/Run across all buses. High Voltage rules retain voltage-specific Case/Run/Bus matching. The High Voltage UI also shows the statistic-file fault type when available. Unchecking a High Voltage row stores an explicit include override, allowing that exact item through the automatic threshold check on the next build.
- Whole-run rules are removed from the `.inf` inventory or before worker submission. Bus-specific rules filter matching descriptors before waveform reads.
- Older sessions containing the former per-voltage Bus and Case/Run fields are migrated into Manual rules when loaded. Former Bus entries become bus-only wildcard rules because the universal Manual table has no voltage column.
- PSCAD-log high-voltage initialization reads warning case/MM bus pairs, then scans only matching raw waveform columns for every run and caches one maximum per case/run/bus. The configured high-voltage factor and `Um` classify those maxima into High Voltage rows. Factor/`Um` changes reuse cached maxima; log or matching raw-file changes refresh only this high-voltage cache. No log means no automatic full raw-results fallback. `Build envelope data/checks` remains the authoritative all-case high-voltage check: additional violations are automatically excluded from both LGp and LLp in the same run and shown checked afterward. Each base workbook's `High voltage exclusions` sheet contains only the preselected and analysis-detected exclusions actually applied to that scope/voltage workbook, using the original per-measurement, per-signal, per-file columns; the UI remains the aggregated case/run/bus view with its Source column.

Envelope workflow:

- `Build envelope data/checks` builds base envelope workbooks for selected projects, selected scopes, and selected voltages.
- `Rebuild heatmaps` regenerates Sustained SDPF heatmap images from the saved JSON result cache without rereading waveform files or rebuilding other plots. Double-click a scope in the scope list to rename it; the separate Rename button is not required.
- Base envelope workbooks are under `Voltage_envelope/<scope>/`.
- Combined envelope chart workbooks are created from the base envelope workbooks.
- The TOV/SFO/SA section has separate buttons for rebuilding charts, creating plot batches, and rendering plots.
- The Analysis section has separate buttons for rebuilding analysis charts, creating analysis plot batches, and rendering analysis plots.
- Step buttons work on selected projects and selected scopes.
- Full `Run analysis` reuses the same envelope, batch, render, and report action functions as the step buttons.

Analysis checks:

- Top-bar analysis checkboxes are `Stress`, `Late`, `No-settle`, and `Sustained SDPF`.
- Checks use chronological envelope data produced during envelope build.
- Raw PSCAD `.out` files are not reread for Stress/Late/No-settle; Sustained SDPF evaluates the raw arrays already loaded by the envelope worker.
- LGp and LLp are evaluated separately for ranking.
- `Vlim` for analysis checks uses nominal voltage level times the configured resonance limit multiplier, not `Um`.
- Stress keeps positive post-start area findings and ranks them by `A_post`; Late Growth ranks gated positive-slope findings by `(sigma, growth ratio, positive fraction, tail p95 / Vlim)`; No-settle ranks gated no-release findings by `(sigma, positive fraction, longest positive-growth window, growth ratio, end p95 / Vlim, area)`.
- Check workbook: `Voltage_envelope/<scope>/Resonance_Checks.xlsx`.
- Sustained SDPF metadata: `Voltage_envelope/<scope>/Sustained_SDpf.json`. The same build also writes `Sustained_SDpf_summary.xlsx` with a compact `Ranked cases` sheet (population rank, explicit population, governing fixed LG/LL measurement and phase, applied threshold, normalized excess area, threshold-specific qualification duration, full-wave continuous duration for ranking, sustained `V_T`, event timestamps, qualifying paths, and limit source). Excel headers use readable ASCII labels such as `kVpeak`. A `Representative selections` sheet lists the independently selected highest-`V_T`, cumulative-stress, and longest-duration rows in each population. The ranked sheet includes a small method block with result version, persistence, frequency, and derived cycle coverage; it is an audit/selection workbook, not a plot manifest.
- Sustained SDPF uses the valid project frequency from `Input_Data` when available, otherwise the configured envelope fallback frequency from Settings, plus the embedded `MM_blocks` SDPF limits. It assesses fixed LG phases and LL pairs independently. Each complete cycle contributes its maximum absolute peak for screening; a positive violation followed by a below-limit negative lobe and another positive violation can therefore remain a screening candidate when the absolute peak envelope stays consecutive. The configured physical duration (30 ms by default) must be covered by that qualifying peak envelope with at least `ceil(duration × frequency)` consecutive complete cycles and no missing-cycle gap. Event start/end use the first/last raw waveform threshold crossings. The positive and negative peak timestamps are then retained separately for the full-wave area and continuous-duration ranking, so a lower opposite-polarity lobe creates a real below-limit gap; `V_T` continues to use the absolute qualification envelope. A short event touching two cycle bins is rejected when its interpolated duration is too short; a later run after a gap remains separate. RMS is retained only as a supporting diagnostic and cannot qualify a sustained TOV alone. The safety threshold is SDPF/1.15, using the same RMS-to-peak conversion as the plotter. `V_T` is the highest level the qualification envelope remains at or above for the full physical duration `T`, and is ranked as `V_T / actual SDPF peak limit`; separate events and fixed paths are never stitched. Case/Run/MM results with any sustained SDPF path form the Actual SDPF population; otherwise a sustained margin path forms Safety-margin-only. The report and plot workflow independently selects the enabled highest sustained-T voltage, normalized full-wave excess area, and longest continuous full-wave duration within each population. If multiple criteria identify the same Voltage/Case/Run/MM and fixed path, its plot is reused with all criterion provenance retained. The summary includes all Case/Run/MM observations, but no candidate means no sustained waveform or DOCX Sustained section; short events remain with SFO/AFO. The minimum duration is independent of the ordinary TOV setting. Saved source-file metadata is checked before later batches/reports use the result.
- Sustained SDPF JSON retains compact merged per-voltage Run/MM flags used by the project heatmap sets; heatmaps never reread `.out` files or recalculate SDPF. Ranking checkboxes do not affect heatmap values, colours, grouping, or eligibility. LGp and LLp findings are ORed for each Run × MM before counting, and any fixed phase/pair can set the observation flag. Each cell counts one eligible Run × MM, with top actual-SDPF-qualified and bottom inclusive-margin-qualified percentages; only a peak-envelope event that passes the same physical-duration and complete-cycle rule can qualify a cell. Eligible zero cells show `0%` on both lines and no-eligible cells are grey with `—`. Short or isolated events are not counted. Colours remain green/amber/red/grey (`green` no qualifying exceedance, `amber` margin-only, `red` actual SDPF, `grey` no eligible data); actual and margin-only intensities use separate percentage scales, `<1%` is used for nonzero sub-percent values, and the largest-absolute-count outline is retained. Heatmap headers keep only voltage, optional human-readable set name, and metric plus a generic split caption such as `Split: <value>`; X groups are shown above the matrix as a dedicated band containing only the selected token value, and residual case labels use their own dedicated band below it when needed. All Y-dimension captions are omitted so the title/set name and row labels provide the grouping context consistently; Y-axis and MM identifiers remain horizontal and wrap only when needed to preserve identity. The figure uses explicit inch-based header, group, matrix, optional label, and footer bands so titles, group tokens, case labels, and legends cannot share a coordinate space. Context tokens are omitted when represented by the selected Y/X/Split dimension or constant in the panel. If no residual identity remains, the label band is omitted and selected tokens are never restored as a fallback. X grouping orders/labels columns; when a token is selected as Y, removing it from the compact identity can intentionally leave multiple cases represented by one visible column, while observations remain separately counted. Repeated compact labels are permitted across distinct visible X-groups or split panels; only a true same-context collision gets an unselected-identity fallback. A page suffix is used only for true continuation pages; distinct split pages are identified by their split title. The technical `MM_HM` name is displayed as **MM elements** in figures and reports.
- Full analysis renders each enabled heatmap set once and reports reuse those images only when the voltage also has a qualifying Sustained candidate. A valid no-candidate cache may still be used by `Rebuild heatmaps` for distribution review, but it does not create a standalone report section. Each set/voltage render stages its images and rolls back the prior voltage images if replacement fails; disabled/renamed set folders and removed-voltage images are cleaned after the current scope render succeeds, so cancellation or render failure does not leave a partial image set.
- The dedicated **Sustained SDPF** Settings tab contains the minimum physical sustained duration in milliseconds (30 ms by default), resolved LG/LL limits, and an ordered list of named heatmap sets. A project with fault classifications starts with **Faults**; a project without faults starts with **Cases by <token>**, grouped by the first varying case-name part (for example, **Cases by S**), or **All cases** when no token varies. **Add heatmap** clones the current set; each set can be renamed, reordered, enabled/disabled, and configured independently with Y grouping, X grouping, Split by, Max cases per heatmap (12 by default, editable up to 500), Panel layout (Separate files, Combined panels, or Automatic), and Max panels per image (4 by default). MM element is an optional Y-only view, not the no-fault default; an explicitly selected MM-element view uses **MM elements** as its default label. The other Y-only engineering dimension is Fault type: a Fault type row aggregates all MM elements, while an MM element row aggregates all fault types. Case-name tokens remain available for Y, X grouping, and Split by; X grouping only orders/labels columns, while a token selected as Y is removed from compact X identities and can make one visible column represent cases differing only in that Y token. Split by retains every observed split figure while restricting each figure to its actual split cases. Combined panels place real panels vertically in one column, share one legend/scale, and paginate without adding synthetic cases. Each enabled set is written under `Plots/Generated/<scope>/Sustained_SDPF_Heatmap/<order>_<name>/` and appended to the existing Sustained SDPF report section only after a governing waveform exists. Reports use the set name as the concise H4 label, then semantic headings such as `Split S: S1` or `Combined panels`; raw heatmap filenames and Y/X configuration strings are not emitted as headings.
- Wide heatmaps use deterministic continuation panels so every case remains recoverable in the report without unreadable labels; the configured maximum controls each panel size. Combined panels keep clear vertical spacing, and continuation order is visible from filenames/page order without adding a competing `part i/n` annotation to each panel.
- Check result tabs are created only when findings exist for that check and voltage type. A workbook with no findings contains only `Settings`.
- Combined Sustained SDPF heatmap panels repeat every Y-group label, including Fault type and MM element, on each panel. They do not add a separate vertical Y-dimension caption; the title/set name and row labels provide the grouping context.
- Project-specific UI state is keyed by canonical absolute project path. The project tree blocks intermediate signals during rebuilds, the active row is passed explicitly into exclusion reloads, and the panel is cleared when no row or no current project scan is active; it never uses another checked project as a fallback. Detected High Voltage rows come only from that project's current scan. The session retains only explicit include overrides and removes orphaned keys after scanning, preventing stale rows from appearing as `Analysis` findings under another project. The `Scopes` list remains intentionally global and is applied to every selected project, while scans, exclusions, settings, output state, and status remain project-local.
- Check plot folders use `Plots/Generated/<scope>/<check>/<voltage_type>/`.
- Generated event/check folders are app-owned authoritative outputs. Rendering uses a staging folder and swaps it into place only after all current plots and Excel exports succeed. Empty valid batches remove the prior event folder, obsolete resonance batches are removed, and partial failure keeps the previous good folder. Manual files must not be stored inside generated event/check folders.
- Combined envelope chart workbooks are also staged and atomically replace the last good workbook only after Excel and OOXML processing succeed. Reports compare base/combined modification times and skip stale combined charts with a rebuild warning.
- Plot batches and report envelope summaries use the same nearest-time helper; midpoint ties select the earlier source row.
- Heading numbering and envelope bullets use separate Word numbering definitions and list IDs, emitted in Word's required definition-before-instance order so both lists render correctly.
- DOCX report contains headers and plots for selected checks. Report styling is embedded in code so generation does not require a real report template: A4 layout, green numbered chapter headings, an unnumbered green plot-heading style, justified body text, green italic captions, report header, and page-number footer.
- DOCX voltage reports use numbered Word headings and field-based figure captions plus clickable cross-references for dashboard, envelope, time-domain, and analysis figures. Sustained SDPF sections also use numbered table captions/cross-references and compact selected-case tables. Cached field values are written into the document and automatic field updating is disabled to avoid Word's external-field update prompt; fields can be refreshed manually with `Ctrl+A`, `F9` after editing. When both sections exist, the envelope is section 1.1 and dashboard figures are section 1.2. Initial-condition dashboard charts appear as `Initial voltages`, `Initial Reactive Power`, then `Initial Active Power`. Reports add a short selected SFO/TOV/SA value list with the reference report's green hollow-circle bullets before each exported envelope figure. SFO and TOV values come from the matching `MM_<voltage>.xlsx` envelope workbook `LLp` sheet, SA comes from `LGp` when SA is selected, and TOV/SA show calculated RMS values with Word-subscripted peak/RMS units. SA time-domain report text uses the line-ground TOV RMS value and the fixed 300 ms duration text for surge arrester selection. RMS overvoltage dashboard titles use `voltage rise`; RMS `dip` and `drop` titles remain unchanged.
- Dashboard figures titled `Initial voltages`, `Initial Active Power`, and `Initial Reactive Power` are exported with the dashboard's saved slicer state for every report voltage. The reactive-power caption is `Initial reactive power at the POC`. Other dashboard figures use the report-voltage slicer filter.
- Generated time-domain and analysis plot figures in DOCX reports get green, unnumbered third-level navigation headings with copyable Case, Run, Element, Fault, and Trace text before the cross-reference sentence. Known fault labels are separated from the element; faultless element labels such as `MM_161_TPC1` remain intact. Envelope figures and dashboard figures are excluded from this plot-heading rule.
- Report image directories are indexed once per project/scope report pass and filtered for each selected voltage.
- Reports store their source/output signatures in the project's `.state/analysis_cache.json` and skip a voltage report when its source figures/workbooks, settings, and existing DOCX output are unchanged.

Plotting:

- Waveform plots come from the embedded plotting engine and batch workbooks.
- Envelope charts are Excel charts in envelope/check workbooks.
- Do not duplicate plotting code unless existing engine cannot support the needed output.
- The renderer keeps bounded in-process caches for parsed `.inf` descriptors, statistic-file discovery, parsed event rows for all runs in each statistic file, selected `.out` columns, and standardized Case/Run group frames during one render session. Raw selected-column data is limited by 256 cached files and a 1 GiB byte budget per renderer process; standardized group frames have a separate 256-frame/512 MiB budget. Excel waveform exports use write-only workbooks and consume the same cached frames as PNG rendering.
- One project render pass prepares all concrete jobs from the selected scope/event batches before execution. Three or more jobs use one bounded Windows `spawn` process pool capped at four workers when at least two cache-local Case/Run groups are available; related jobs are submitted in chunks of up to eight so each child can reuse its local waveform cache. A single group remains sequential, and a pool-start or child-worker failure retries sequentially.
- A successfully committed event/check folder contains only generated PNG/Excel outputs. Its normalized job/source signature and output metadata are stored in the project's `.state/analysis_cache.json`; matching entries skip unchanged batches, while source, batch, export, or renderer-version changes invalidate the skip.
- Jobs are ordered by Case, Run, MM element, trace, and time range for process submission. Each event/check folder still has an independent staging directory; it is committed atomically when all jobs for that folder succeed. A failed or cancelled uncommitted batch is removed without replacing its previous output. Queued process jobs are cancelled when possible, and active parallel workers are terminated on Stop so cancellation does not wait for every active render/export job.

## Settings that matter

- Selected voltages and events.
- Event times for SFO/TOV/SA.
- Envelope time step and time end.
- Fallback frequency.
- Project-specific automatic/manual envelope and resonance x-axis limits, plus voltage-specific y-axis limits.
- Envelope chart size and placement.
- High-voltage factor.
- Detected voltage `Um` values.
- Resonance limit multiplier.
- Resonance Top-N.
- Auto release/recovery detection or manual analysis start time.
- Release/growth thresholds in the Settings dialog.
- Envelope worker count.
- Sustained SDPF minimum physical peak-envelope duration (30 ms by default); derived complete-cycle coverage is reported for context and is independent of the TOV event setting.
- Sustained SDPF limits table: one validated LG and LL row per voltage with editable RMS, calculated peak, SDPF/1.15 safety-threshold values, and `Input xlsx`/`Manual` source labels. Manual RMS overrides are project-specific and persisted in session state.

## Known risks

- `main_window.py` remains large because it owns UI construction and worker orchestration, although Settings dialog code is now isolated in `settings_dialog.py` and exclusion logic is isolated in `exclusions.py`.
- Settings editing is still session-coupled through the main window instance. Resonance settings conversion is centralised in `src/results_analysis_app/resonance_checks.py`.
- Excel COM workflows are inherently machine-sensitive and require installed Microsoft Excel.
- PyInstaller one-file builds can fail on another machine if built from an inconsistent Python environment. Conda run mode is easier to debug.
- The existing `dist/PSCADResultsAnalysis.exe` must be rebuilt after source changes; `--smoke` does not validate the full UI, Excel, plotting, or report workflow.
- The PyInstaller spec explicitly bundles conda runtime DLLs required by Python startup modules, including `ffi-8.dll` for `_ctypes`.
- Full-project envelope runs are resource-heavy. Runs from selected voltage levels are read concurrently through one shared bounded process pool; the single cap prevents voltage-level concurrency from multiplying worker count.
- The `.inf` descriptor cache reduces repeated parsing. Processed envelope DataFrames are not persisted between builds; Excel/report output work uses the single project analysis cache for small signatures and output metadata. Plot workers intentionally keep separate process-local caches; the 1 GiB selected-column budget plus 512 MiB group-frame budget per worker and four-worker cap still bound pathological memory use while allowing the normal 128 GiB workstation configuration to retain larger working sets.
- High-voltage log scan depends on the exact PSCAD log warning format and the matching raw PSCAD `.inf`/`.out` files.
- Project scan and project analysis cache validation uses file size and modification time. An external edit that preserves both can remain cached until the relevant stage is forced or its generated cache is removed.

## Current validation state

- Latest recorded full source-level test run: **243 passed**. The test command
  uses `.tmp/` for pytest output and does not touch user project data.
- Contract tests cover peak-envelope Sustained SDPF qualification, short boundary-crossing episode protection, strict heatmap flags, standard TOV-window batch markers, centered case-label coverage, compact context-aware case-label coverage, ranked-summary workbook coverage, stale-summary invalidation coverage, selected-column/group-frame reuse, complete-stage and centralized-cache skipping, compact Sustained source fingerprints including the Windows build-to-validation-to-batch round trip, manual plot-limit propagation, waveform-cache bounds, and process-plot fallback coverage.
- Automatic project-opening HV scan on `../Original_examples/03_Test_project_case`: 300 cached case/run/bus maxima and 92 proposals at factor 5; the measured persistent-cache timings were about 7.8 seconds cold, 0.48 seconds warm, and 7.5 seconds forced on the development machine. Warm validation avoids waveform parsing.
- Dependency import check: passed.
- Application `--smoke` check: passed.
- Envelope reduction equivalence benchmark: direct NumPy reduction matched the former dataframe result and was 10.3x faster for 100 synthetic sources with 1,200 rows each.
- Sustained source-fingerprint validation checks file metadata without persisting the full raw-file list in the result JSON.
- Envelope raw-read benchmark: representative 66/161/230 kV reads took about 19.2/6.4/27.6 seconds, or 53.2 seconds total, when voltage levels were processed sequentially. A shared concurrent-voltage prototype completed the same reads in about 12.2 seconds at 16 workers with matching envelopes and merged tables; the raw waveform/envelope stage remains the dominant cost and Sustained SDPF still reuses the loaded raw data.
- Envelope worker policy: automatic mode uses the ceiling of 80% of detected logical CPUs, capped at 60 and reduced when fewer runs exist. The worker cap is shared across concurrently submitted voltage levels; manual worker settings remain available for machine-specific tuning.
- Envelope source-inventory benchmark: one directory inventory reduced repeated source-manifest metadata scans from roughly 6.7–9.3 seconds to 0.66–0.76 seconds on the reference project while producing identical source records.
- In a connected analysis run, Sustained SDPF fingerprint validation is performed once per scope and the small in-memory validation result is reused by batch creation, multi-voltage plot/heatmap rendering, and report generation. Standalone actions validate their saved data locally. The project scan and analysis caches write compact JSON; session/autosave data remains readable JSON.
- Reference-project descriptor benchmark: 150 `.inf` paths reduced to 2 parsed templates in 0.442 s without reading raw `.out` waveforms.
- Plotter catalog/indexing was below 0.04 seconds and temporary plot-batch creation was below 0.3 seconds in the same audit; Excel chart creation remained sequential because it uses one COM process.
- Representative plot benchmark: ten real MM jobs with waveform Excel exports completed in 16.2 s sequentially and 6.1 s with four plot workers; all 10 PNGs and 10 workbooks were produced in both runs. Exact gains depend on waveform size, storage, and the selected number of jobs.
- Main window and Settings dialog: rendered and visually inspected in forced light and dark themes.
- Runtime theme-change callback: exercised with a Qt colour-scheme change signal.
- Pytest output is directed to `.tmp/` (and `.pytest_tmp*/` is ignored) so validation artifacts do not become repository files.

## Pending work

- Run a representative full envelope/plot/report workflow after the latest exclusion, reporting, and UI changes.
- Rebuild and validate the packaged executable on the development machine and at least one target machine.
- Manually toggle the actual Windows theme while the normal desktop app is open; automated theme switching and forced-theme renders have already passed.
- Continue reducing `main_window.py` only along existing responsibility boundaries when related UI/worker code is changed.
- Keep documentation current after meaningful behavior changes.

## First files to read before editing

1. `AGENTS.md`
2. `docs/HANDOFF.md`
3. `README.md`
4. `docs/CURRENT_CONTEXT.md`
5. `docs/ANALYSIS_METHODS.md`
6. `pyproject.toml` and `environment.yml`
7. The specific module related to the requested change.
8. The focused test module matching the changed behavior under `tests/`.

Before editing, verify docs against code. Do not trust this context file over current source.
