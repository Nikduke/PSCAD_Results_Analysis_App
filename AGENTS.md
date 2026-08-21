# Project Instructions

## Scope

These instructions apply to the PSCAD Results Analysis app under this folder.
The parent folders `../Original_examples/` and `../02_Backup/` are reference and backup material, not app source. Change them only when the task explicitly requires it.

## Working mode

Work silently by default. Do not send progress messages, implementation plans, or partial status updates while working. Respond only when the task is complete, a blocking clarification is required, a logic change requires approval, a destructive or broad change requires approval, or validation cannot continue without user input.

## Grounding and inspection

- Read `README.md`, `docs/HANDOFF.md`, `docs/CURRENT_CONTEXT.md`, `docs/ANALYSIS_METHODS.md`, `pyproject.toml`, `environment.yml`, and the relevant source and test files before editing.
- Verify documentation against the current source; do not treat the handover document as authoritative when code differs.
- Git is configured for this app. Inspect the current worktree before editing, preserve unrelated changes, and do not depend on history to understand current behavior.
- Use evidence from the current files, tests, logs, or explicit user requirements. Do not invent project facts.

## Change policy

- Make the smallest targeted change that satisfies the request.
- Do not change engineering, parsing, filtering, sorting, calculation, report, or workflow logic unless the user explicitly requests it or the intended behavior has been agreed first.
- Prefer deletion or simplification over new abstractions and duplicated helpers.
- Avoid broad rewrites, style-only changes, speculative cleanup, compatibility layers, and generated clutter.
- Before deleting files or making a broad or hard-to-reverse structural change, stop and ask for approval.
- Preserve existing behavior outside the requested change and work with any existing user changes.
- Use `apply_patch` for manual edits. Keep source files ASCII unless the existing file clearly requires other characters.

## Project structure and workflow

- `src/results_analysis_app/` contains the PySide6 application, scanning, envelope building, analysis checks, settings, actions, and reporting.
- `src/results_analysis_app/settings_dialog.py` owns Settings dialog construction and session updates; keep settings UI out of `main_window.py`.
- `src/results_analysis_app/project_scan_cache.py` and `project_scan_runner.py` provide metadata-validated hot-start project scans.
- `src/results_analysis_app/exclusions.py` owns shared Manual, NonConv, and High Voltage exclusion normalization and matching.
- `src/results_analysis_app/envelope_rows.py` owns nearest-time envelope row selection shared by plot batches and reports.
- `src/results_analysis_app/styles.py` owns the system-aware light/dark palette and semantic widget styles. Do not add fixed light-only styles directly to UI widgets.
- `src/pscad_plotter_app_v3/` contains the MM-only embedded waveform plotting and Excel-export engine used by report batches.
- `src/pscad_plotter_app_v3/services/waveform_io.py` owns shared `.inf`/`.out` parsing. Keep raw waveform reads cancellation-aware by passing the current cancellation callback through scanner, envelope, renderer, and exporter call paths.
- `tests/` contains focused plotting, reporting, scanning, envelope, UI-model, and resonance contract tests.
- `docs/HANDOFF.md` is the concise new-chat handoff; `docs/CURRENT_CONTEXT.md` is the detailed current-state record. Both must stay aligned with the implementation.
- `../Original_examples/` is outside this app folder and contains reference scripts and sample PSCAD data.

The main workflow is: add one or more cached PSCAD projects, select scopes and analysis options, review exclusions, scan or refresh inputs, build envelope data and checks, create and render plot batches, and rebuild DOCX reports.

## Environment and commands

Use the dedicated Anaconda environment only; never install project dependencies into `base`.

From this app folder, the environment is defined by `environment.yml` and uses the project-local prefix `../.conda/pscad-results-analysis`:

```bat
conda env create --prefix ..\.conda\pscad-results-analysis -f environment.yml
```

Run the app:

```bat
start_app.bat
```

Equivalent direct run:

```bat
..\.conda\pscad-results-analysis\python.exe -m results_analysis_app
```

Run tests with the project-local temporary directory:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TMP = "$PWD\.tmp"
$env:TEMP = "$PWD\.tmp"
..\.conda\pscad-results-analysis\python.exe -m pytest -q -o cache_dir=.tmp\pytest_cache
```

Run the dependency smoke check:

```bat
..\.conda\pscad-results-analysis\python.exe -c "import PySide6.QtCore, pandas, openpyxl, docx, win32com.client, matplotlib, numpy, pyexpat; import results_analysis_app; print('ok')"
```

Build the optional executable with `Create_executable.bat`. Rebuild it after source changes before relying on `dist/PSCADResultsAnalysis.exe`; the executable's `--smoke` check does not replace a real UI, Excel, plotting, or report workflow test.

## Validation and cleanup

- Validate every meaningful change with the narrowest relevant tests, plus compile/import checks when Python modules or packaging are affected.
- Use the actual project sample data or workflow when behavior depends on PSCAD files, Excel, plotting, or DOCX output.
- Remove generated test caches under `.tmp/` after validation. Do not remove user data, project outputs, `.state/`, `build/`, or `dist/` unless explicitly requested.
- Report anything that could not be validated and any remaining risk.

## Documentation

Update `README.md`, `docs/CURRENT_CONTEXT.md`, and any affected setup or starter documentation when setup, commands, dependencies, paths, workflow behavior, or known risks change. Use relative paths in project documentation.
