# Current Context

Snapshot date: 2026-07-29.

This folder is the active app root for PSCAD Results Analysis. The parent folder keeps reference examples, backup material, and the existing dedicated conda environment.

## Project purpose

Desktop app for PSCAD result analysis:

- collect PSCAD project folders;
- detect scopes, cases, voltage levels, dashboards, and exclusions;
- build voltage envelopes from PSCAD results;
- create envelope charts;
- create waveform plot batch workbooks;
- render waveform plots through the embedded plotting engine;
- generate DOCX reports;
- run optional Stress, Late, and No-settle checks using existing chronological envelope data.

## Current code organisation

- `src/results_analysis_app/__main__.py` - application startup, Windows identity, icon, and system-theme installation.
- `src/results_analysis_app/main_window.py` - PySide6 UI and worker orchestration.
- `src/results_analysis_app/settings_dialog.py` - Settings dialog construction and settings-to-session updates.
- `src/results_analysis_app/background.py` - cancellable Qt background-task wrapper.
- `src/results_analysis_app/project_scan_runner.py` - project-opening scan and cache wrapper.
- `src/results_analysis_app/project_scan_cache.py` - persistent metadata-validated project scan cache.
- `src/results_analysis_app/exclusions.py` - shared exclusion rules, matching, normalization, and legacy-session migration.
- `src/results_analysis_app/styles.py` - centralized light/dark palette and semantic widget styling.
- `src/results_analysis_app/storage.py` - session paths and JSON persistence.
- `src/results_analysis_app/excel.py` - shared Excel COM application context and targeted automation error types.
- `src/results_analysis_app/actions.py` - high-level workflow actions.
- `src/results_analysis_app/analysis_engine.py` - plot batch creation/rendering bridge.
- `src/results_analysis_app/voltage_envelope.py` - envelope data build.
- `src/results_analysis_app/envelope_chart.py` - Excel envelope chart generation.
- `src/results_analysis_app/resonance_checks.py` - Stress/Late/No-settle checks and check chart workbook output.
- `src/results_analysis_app/reporting.py` - DOCX report generation and dashboard figure insertion.
- `src/results_analysis_app/scanner.py` - project scan, dashboard scan, exclusions, high-voltage log scan.
- `src/results_analysis_app/project_config.py` - voltage and frequency config from `Input_Data_PSCAD*.xlsx` and `.inf` files.
- `src/results_analysis_app/models.py` - session model and default settings.
- `src/pscad_plotter_app_v3/` - MM-only embedded plotting and Excel-export engine used by report batches.
- `tests/test_plotting.py`, `tests/test_reporting.py`, `tests/test_scanning.py`, `tests/test_envelope.py`, `tests/test_ui_models.py`, and `tests/test_resonance.py` - focused contract tests.
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

- Git is configured in this app root on branch `main`.
- `origin` points to the project GitHub repository.
- `.gitignore` excludes local environments, `.state/`, sessions, caches, build output, and generated PSCAD analysis output.
- Always inspect the worktree before editing or committing and preserve unrelated changes.

## Current workflow logic

Project scanning:

- User adds PSCAD project folders in the UI. Adding a project validates only that new project; saved projects are not rescanned unnecessarily. Mixed cached/stale startup scans only stale projects and preserves valid cached entries.
- Opening validates `.inf`, NonConv, voltage-input, dashboard, envelope, generated-plot, and report file metadata against `.state/project_scan_cache.json`. Unchanged entries restore serialized scan data without rewriting the cache; missing, changed, corrupt, or forced entries run the normal scanner. Cache validation reads metadata only.
- Scanner reads project structure, case counts, dashboard workbooks, available voltage levels, non-convergence proposals, and high-voltage proposal files when a cold scan is required. Reads inside one project scan use a bounded worker pool; multiple cold project scans stay sequential to avoid nested worker contention. NonConv proposal detection remains eager for cold scans. `Scan HV log` uses a separate bounded pool for matching raw runs.
- Project scan status stores output-presence flags rather than unused full output-file lists.
- `Rebuild project cache` in Settings is the maintenance-only forced scan for all saved projects. Analysis actions update only affected output flags and cache entries; they do not trigger a full project scan.
- Malformed autosave JSON falls back to a default session so startup is not blocked by damaged state.
- Temporary report export images are removed after each scope's DOCX reports are written.
- Unreadable existing envelope workbooks are skipped during project status scanning; the remaining project scan continues.
- Conda runs store autosave under `.state/`; frozen executable runs store `.state/` and `sessions/` beside the executable.
- Voltage levels are detected from `Input_Data_PSCAD_Python_v11.xlsx` where available and from `.inf` signal prefixes. Treated result CSVs and generated plot filenames are not used to define available voltage levels. If `Um` is missing for a detected voltage, the user must fill it in Settings.
- PSCAD `.inf` case/run parsing and `.out` column mapping are shared with the embedded plotter waveform I/O helpers.
- Envelope builds enumerate `.inf` files once per build and BLAKE2b-hash each selected layout. Identical contents share one parsed descriptor template across scopes and voltages. One bounded run-read pool is reused for one voltage at a time to avoid uneven per-voltage worker partitions. The default envelope worker count is 4 based on representative storage benchmarks; raw `.out` waveform reads remain voltage-specific.
- Project `Final duration` is read from `Input_Data_PSCAD*.xlsx` and caps the configured `Envelope time end`. The final timestamp from each already-loaded raw time column provides a second per-run cap, so no extra `.out` pass or zero padding beyond real waveform data is used.
- `Chart x max` is a display upper limit for both envelope and resonance charts and is capped by the generated data duration.
- Envelope high-voltage checks and rolling envelopes reuse the same absolute-value arrays. Envelope workbooks are formatted during their initial write, avoiding a second serialization pass.
- Envelope phase candidates use one direct NumPy reduction per phase while preserving source-order ties and Case/Run provenance; the former intermediate dataframe merge chain is gone.
- The embedded report plotter supports only MM voltage waveform batches. Legacy CB, arbitrary-channel, FFT, combined-mode, and unused catalog branches were deleted; MM plot rendering and Excel waveform exports remain. Its SQLite cache loads only the MM element rows needed for batch validation.
- Background-task failures include tracebacks in the app log. Window close waits for active work to cancel and finish, and the raw high-voltage scan checks cancellation within descriptor/channel processing.
- Malformed `.inf` layouts and unreadable CB or high-voltage proposal files are surfaced as scan/build warnings.
- Project frequency fallback is read from `Input_Data` cell `B16` when available. If automatic frequency detection fails and no input frequency is available, the app uses the configured fallback frequency and logs/notifies the user.
- The bottom-left status bar text is owned by the dedicated status label; native temporary status messages are cleared to avoid duplicate overlapping text during background tasks.
- The application follows the Windows light/dark colour scheme at startup and listens for changes while open. One application palette and stylesheet control panels, tables, headers, tabs, inputs, labels, buttons, selections, disabled controls, status controls, and scrollbars. A shared proxy style draws the same high-contrast checkbox indicators for standalone widgets and checkable list/tree/table items.
- Dashboard figure-only scans update dashboard metadata without triggering a project scan. Dashboard refresh updates only dashboard status and cache metadata.

Exclusions:

- The `Manual` table uses the shared columns `Apply`, `Case`, `Run`, and `Bus`. New rows are applied by default, editable, and support TSV copy/paste.
- Blank manual fields are wildcards. Case-only, run-only, bus-only, and all two-field combinations are valid; a completely blank row is ignored so it cannot exclude the full dataset.
- `NonConv` and `High Voltage` rows are detected proposals. They use the same checkbox visuals and `Apply all` / `Apply none` controls as the Manual table, but their detected data columns remain read-only.
- Applied manual, NonConv, and High Voltage rows are normalized into one matching rule set. NonConv rules match Case/Run across all buses. High Voltage rules retain voltage-specific Case/Run/Bus matching.
- Whole-run rules are removed from the `.inf` inventory or before worker submission. Bus-specific rules filter matching descriptors before waveform reads.
- Older sessions containing the former per-voltage Bus and Case/Run fields are migrated into Manual rules when loaded. Former Bus entries become bus-only wildcard rules because the universal Manual table has no voltage column.
- `Scan HV log` reads warning case/MM bus pairs from `PSCAD_log.txt`, then scans only the matching raw waveform columns for every run of those cases. It uses the configured high-voltage factor and `Um` values to prefill High Voltage proposal rows from specific case/run/MM bus matches.

Envelope workflow:

- `Build envelope data/checks` builds base envelope workbooks for selected projects, selected scopes, and selected voltages.
- Base envelope workbooks are under `Voltage_envelope/<scope>/`.
- Combined envelope chart workbooks are created from the base envelope workbooks.
- The TOV/SFO/SA section has separate buttons for rebuilding charts, creating plot batches, and rendering plots.
- The Analysis section has separate buttons for rebuilding analysis charts, creating analysis plot batches, and rendering analysis plots.
- Step buttons work on selected projects and selected scopes.
- Full `Run analysis` reuses the same envelope, batch, render, and report action functions as the step buttons.

Analysis checks:

- Top-bar analysis checkboxes are `Stress`, `Late`, and `No-settle`.
- Checks use chronological envelope data produced during envelope build.
- Raw PSCAD `.out` files are not reread for these checks.
- LGp and LLp are evaluated separately for ranking.
- `Vlim` for analysis checks uses nominal voltage level times the configured resonance limit multiplier, not `Um`.
- Check workbook: `Voltage_envelope/<scope>/Resonance_Checks.xlsx`.
- Check result tabs are created only when findings exist for that check and voltage type. A workbook with no findings contains only `Settings`.
- Check plot folders use `Plots/Generated/<scope>/<check>/<voltage_type>/`.
- Generated plot folders are created by the renderer only when a batch contains plots; workflow setup does not pre-create empty event/check folders.
- Heading numbering and envelope bullets use separate Word numbering definitions and list IDs, emitted in Word's required definition-before-instance order so both lists render correctly.
- DOCX report contains headers and plots for selected checks. Report styling is embedded in code so generation does not require a real report template: A4 layout, green numbered chapter headings, an unnumbered green plot-heading style, justified body text, green italic captions, report header, and page-number footer.
- DOCX voltage reports use numbered Word headings and field-based figure captions plus clickable cross-references for dashboard, envelope, time-domain, and analysis figures. Cached field values are written into the document and automatic field updating is disabled to avoid Word's external-field update prompt; fields can be refreshed manually with `Ctrl+A`, `F9` after editing. Dashboard figures are placed before envelope and waveform figures so their figure numbers follow the report order. Reports add a short selected SFO/TOV/SA value list with the reference report's green hollow-circle bullets before each exported envelope figure. SFO and TOV values come from the matching `MM_<voltage>.xlsx` envelope workbook `LLp` sheet, SA comes from `LGp` when SA is selected, and TOV/SA show calculated RMS values with Word-subscripted peak/RMS units. SA time-domain report text uses the line-ground TOV RMS value and the fixed 300 ms duration text for surge arrester selection. RMS overvoltage dashboard titles use `voltage rise`; RMS `dip` and `drop` titles remain unchanged.
- Dashboard figures titled `Initial voltages`, `Initial Active Power`, and `Initial Reactive Power` are exported with the dashboard's saved slicer state for every report voltage. Other dashboard figures use the report-voltage slicer filter.
- Generated time-domain and analysis plot figures in DOCX reports get green, unnumbered third-level navigation headings with copyable Case, Run, Element, Fault, and Trace text before the cross-reference sentence. Known fault labels are separated from the element; faultless element labels such as `MM_161_TPC1` remain intact. Envelope figures and dashboard figures are excluded from this plot-heading rule.
- Report image directories are indexed once per project/scope report pass and filtered for each selected voltage.

Plotting:

- Waveform plots come from the embedded plotting engine and batch workbooks.
- Envelope charts are Excel charts in envelope/check workbooks.
- Do not duplicate plotting code unless existing engine cannot support the needed output.
- The renderer keeps bounded in-process caches for parsed `.inf` descriptors, run event metadata, and loaded `.out` frames during one render session.

## Settings that matter

- Selected voltages and events.
- Event times for SFO/TOV/SA.
- Envelope time step and time end.
- Fallback frequency.
- Envelope chart x-axis and y-axis limits.
- Envelope chart size and placement.
- High-voltage factor.
- Detected voltage `Um` values.
- Resonance limit multiplier.
- Resonance Top-N.
- Auto release/recovery detection or manual analysis start time.
- Release/growth thresholds in the Settings dialog.
- Envelope worker count.

## Known risks

- `main_window.py` remains large because it owns UI construction and worker orchestration, although Settings dialog code is now isolated in `settings_dialog.py` and exclusion logic is isolated in `exclusions.py`.
- Settings editing is still session-coupled through the main window instance. Resonance settings conversion is centralised in `src/results_analysis_app/resonance_checks.py`.
- Excel COM workflows are inherently machine-sensitive and require installed Microsoft Excel.
- PyInstaller one-file builds can fail on another machine if built from an inconsistent Python environment. Conda run mode is easier to debug.
- The existing `dist/PSCADResultsAnalysis.exe` must be rebuilt after source changes; `--smoke` does not validate the full UI, Excel, plotting, or report workflow.
- The PyInstaller spec explicitly bundles conda runtime DLLs required by Python startup modules, including `ffi-8.dll` for `_ctypes`.
- Full-project envelope runs are storage-heavy. Runs are read in parallel within one voltage level, but voltage levels are processed sequentially through one shared bounded pool.
- The `.inf` descriptor cache reduces repeated parsing, but it does not remove voltage-specific waveform processing or Excel/report work.
- High-voltage log scan depends on the exact PSCAD log warning format and the matching raw PSCAD `.inf`/`.out` files.
- Cache validation uses file size and modification time. An external edit that preserves both can remain cached until `Rebuild project cache` is used.

## Current validation state

- Contract tests: 62 passed in the dedicated conda environment.
- Dependency import check: passed.
- Application `--smoke` check: passed.
- Envelope reduction equivalence benchmark: direct NumPy reduction matched the former dataframe result and was 10.3x faster for 100 synthetic sources with 1,200 rows each.
- Reference-project descriptor benchmark: 150 `.inf` paths reduced to 2 parsed templates in 0.442 s without reading raw `.out` waveforms.
- Main window and Settings dialog: rendered and visually inspected in forced light and dark themes.
- Runtime theme-change callback: exercised with a Qt colour-scheme change signal.
- Test caches created during the latest validation were removed.

## Pending work

- Run a representative full envelope/plot/report workflow after the latest exclusion, reporting, and UI changes.
- Rebuild and validate the packaged executable on the development machine and at least one target machine.
- Manually toggle the actual Windows theme while the normal desktop app is open; automated theme switching and forced-theme renders have already passed.
- Continue reducing `main_window.py` only along existing responsibility boundaries when related UI/worker code is changed.
- Keep documentation current after meaningful behavior changes.

## First files to read before editing

1. `README.md`
2. `docs/CURRENT_CONTEXT.md`
3. `pyproject.toml`
4. The specific module related to the requested change.
5. The focused test module matching the changed behavior under `tests/`.

Before editing, verify docs against code. Do not trust this context file over current source.
