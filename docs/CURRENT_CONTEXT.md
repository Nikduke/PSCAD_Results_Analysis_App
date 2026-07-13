# Current Context

Snapshot date: 2026-07-13.

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

- `src/results_analysis_app/main_window.py` - PySide6 UI and worker orchestration.
- `src/results_analysis_app/project_scan_runner.py` - project-opening scan wrapper.
- `src/results_analysis_app/actions.py` - high-level workflow actions.
- `src/results_analysis_app/analysis_engine.py` - plot batch creation/rendering bridge.
- `src/results_analysis_app/voltage_envelope.py` - envelope data build.
- `src/results_analysis_app/envelope_chart.py` - Excel envelope chart generation.
- `src/results_analysis_app/resonance_checks.py` - Stress/Late/No-settle checks and check chart workbook output.
- `src/results_analysis_app/reporting.py` - DOCX report generation and dashboard figure insertion.
- `src/results_analysis_app/scanner.py` - project scan, dashboard scan, exclusions, high-voltage log scan.
- `src/results_analysis_app/project_config.py` - voltage and frequency config from `Input_Data_PSCAD*.xlsx` and `.inf` files.
- `src/results_analysis_app/models.py` - session model and default settings.
- `src/pscad_plotter_app_v3/` - embedded plotting engine used by batch rendering.
- `tests/test_core_contracts.py` - focused tests for current contracts.

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

## Current workflow logic

Project scanning:

- User adds PSCAD project folders in the UI.
- Scanner reads project structure, case counts, dashboard workbooks, available voltage levels, non-convergence proposals, and high-voltage proposal files when present. Reads inside one project scan use a bounded worker pool; multiple project opening stays sequential to avoid nested worker contention. NonConv proposal detection remains eager at opening.
- Project scan status stores output-presence flags rather than unused full output-file lists.
- Malformed autosave JSON falls back to a default session so startup is not blocked by damaged state.
- Temporary report export images are removed after each scope's DOCX reports are written.
- Unreadable existing envelope workbooks are skipped during project status scanning; the remaining project scan continues.
- Conda runs store autosave under `.state/`; frozen executable runs store `.state/` and `sessions/` beside the executable.
- Voltage levels are detected from `Input_Data_PSCAD_Python_v11.xlsx` where available and from `.inf` signal prefixes. Treated result CSVs and generated plot filenames are not used to define available voltage levels. If `Um` is missing for a detected voltage, the user must fill it in Settings.
- PSCAD `.inf` case/run parsing and `.out` column mapping are shared with the embedded plotter waveform I/O helpers.
- Envelope builds parse each selected `.inf` file once per build and share the descriptor cache across voltage workers. Raw `.out` waveform reads remain voltage-specific.
- Embedded plotter catalog builds persist BLAKE2b `.inf` hashes with path, size, and modification metadata. Identical contents are parsed once per catalog rebuild; unchanged per-file catalog entries continue to use the SQLite cache.
- Project frequency fallback is read from `Input_Data` cell `B16` when available. If automatic frequency detection fails and no input frequency is available, the app uses the configured fallback frequency and logs/notifies the user.
- The bottom-left status bar text is owned by the dedicated status label; native temporary status messages are cleared to avoid duplicate overlapping text during background tasks.

Exclusions:

- Bus exclusions are configured per voltage level.
- Manual Case/Run exclusions are user-controlled.
- NonConv rows are detected proposals and applied only according to visible checked state.
- High Voltage rows are proposals and applied only according to visible checked state.
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
- Check plot folders use `Plots/Generated/<scope>/<check>/<voltage_type>/`.
- DOCX report contains headers and plots for selected checks.
- DOCX voltage reports add a short selected SFO/TOV/SA value list before each exported envelope figure. SFO and TOV values come from the matching `MM_<voltage>.xlsx` envelope workbook `LLp` sheet, SA comes from `LGp` when SA is selected, and TOV/SA show calculated RMS values with Word-subscripted peak/RMS units.
- Generated plot figures in DOCX reports get copyable Case, Run, Element, Fault, and Trace headings. Envelope figures and dashboard figures are excluded from this plot-heading rule.

Plotting:

- Waveform plots come from the embedded plotting engine and batch workbooks.
- Envelope charts are Excel charts in envelope/check workbooks.
- Do not duplicate plotting code unless existing engine cannot support the needed output.
- Plot catalog parsing is content-deduplicated for identical `.inf` files; `.out` time-range reads remain per run because their paths and contents are run-specific.

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

- `main_window.py` is still large and mixes UI construction with workflow orchestration.
- Settings plumbing is still broad in the UI layer, but resonance settings conversion is centralised in `src/results_analysis_app/resonance_checks.py`.
- Excel COM workflows are inherently machine-sensitive and require installed Microsoft Excel.
- PyInstaller one-file builds can fail on another machine if built from an inconsistent Python environment. Conda run mode is easier to debug.
- The existing `dist/PSCADResultsAnalysis.exe` must be rebuilt after source changes; `--smoke` does not validate the full UI, Excel, plotting, or report workflow.
- The PyInstaller spec explicitly bundles conda runtime DLLs required by Python startup modules, including `ffi-8.dll` for `_ctypes`.
- Full-project envelope runs are slow by nature. Parallel voltage processing and worker settings exist, but large PSCAD data still requires patience.
- The new `.inf` descriptor cache reduces repeated parsing, but it does not remove voltage-specific waveform processing or Excel/report work.
- High-voltage log scan depends on the exact PSCAD log warning format and the matching raw PSCAD `.inf`/`.out` files.

## Pending work

- Manual full-run validation on large real projects after latest layout and high-voltage log scan updates.
- Rebuild and validate the packaged executable after the latest source changes.
- Revisit further performance work only after real project startup remains noticeably slow.
- Consider reducing `main_window.py` only when touching related UI/worker code.
- Keep documentation current after meaningful behavior changes.
- Session autosave data is stored in `.state/` for conda runs; frozen executable runs store `.state/` and `sessions/` beside the executable.
- App code, tests, docs, build scripts, `.state/`, `build/`, and `dist/` now live under this app root.

## First files to read before editing

1. `README.md`
2. `docs/CURRENT_CONTEXT.md`
3. `pyproject.toml`
4. The specific module related to the requested change.
5. `tests/test_core_contracts.py`

Before editing, verify docs against code. Do not trust this context file over current source.
