# Starter Prompt For A New Machine

You are working in this folder as the active PSCAD Results Analysis app root.

App context:

- This is a native Windows PySide6 post-processing tool for PSCAD simulation
  result projects. It discovers cases/runs/faults/voltages/MM elements and
  dashboards, builds voltage envelopes, applies exclusions and the
  all-case High Voltage gate, runs optional Stress/Late/No-settle/Sustained
  SDPF checks, renders MM plots, creates Sustained SDPF heatmaps, and assembles
  DOCX reports.
- The operating regimes are project/session, scan/catalog, envelope/check,
  batch/render/report, and rebuild-only. `Run analysis` connects the envelope,
  batch, render, and report stages; the step buttons are narrower operations.
- Project state is isolated by canonical project path. Scopes are intentionally
  global token filters. Do not let one project provide another project's
  exclusions, dashboard selection, settings, scan rows, status, or outputs.
- The project scan cache and project analysis cache are compact metadata caches;
  `Sustained_SDpf.json` is compact engineering metadata and heatmap flags. No
  persistent cache stores raw waveform arrays or acts as a replacement for
  source PSCAD `.out` data.
- `graphify-out/` is the generated local repository graph. If it exists, use
  Graphify `query`, `path`, and `explain` as the primary architecture/navigation
  layer before opening source files. Rebuild it after source changes with
  `..\.conda\pscad-results-analysis\Scripts\graphify.exe . --update --code-only`
  followed by `graphify.exe cluster-only .`; verify inferred edges against
  source/tests before changing behavior.

Rules:

- Work silently by default and provide a final report only, unless clarification or approval is required.
- First read `AGENTS.md`, `docs/HANDOFF.md`, `README.md`, `docs/CURRENT_CONTEXT.md`, `docs/ANALYSIS_METHODS.md`, `pyproject.toml`, and `environment.yml`.
- Inspect the actual codebase before making claims or edits; documentation may be stale.
- Git is configured for this app. Inspect the worktree, preserve unrelated changes, and do not rely on history as a substitute for reading current code.
- Use Anaconda Python with the dedicated `../.conda/pscad-results-analysis` environment, never `base`.
- If the environment does not exist, create it from `environment.yml` with the project-local prefix.
- Use only relative paths in project documentation.
- Make small, targeted changes and preserve existing workflow and engineering logic unless a change has been explicitly agreed.
- Prefer deletion, reuse, and simplification over new abstractions or duplicated helpers.
- Keep project scanning, exclusions, envelope building, plotting, reporting, and theme behavior in their existing functional modules.
- Run the relevant tests and import/smoke checks. Use `.tmp/` for test output and remove generated caches afterward.
- Update all affected documentation after meaningful setup, workflow, behavior, or risk changes.

Current entry points:

```bat
start_app.bat
```

```bat
..\.conda\pscad-results-analysis\python.exe -m results_analysis_app
```

Current test command:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TMP = "$PWD\.tmp"
$env:TEMP = "$PWD\.tmp"
..\.conda\pscad-results-analysis\python.exe -m pytest -q -o cache_dir=.tmp\pytest_cache
```

Current output contract:

- Envelopes/checks: `Voltage_envelope/<scope>/`.
- Sustained results: `Sustained_SDpf.json` and
  `Sustained_SDpf_summary.xlsx` in that scope folder.
- Generated plots and heatmaps: `Plots/Generated/<scope>/`.
- Reports: `Reports/<scope>/`.
- Stage signatures/output metadata: the single project-local
  `.state/analysis_cache.json`.

Current invalidation versions are project scan 7, project analysis 1,
envelope manifest 2, Sustained result 17, Sustained summary workbook 2, plot
batch 2, report/report-layout 2/2, and embedded plotter SQLite/MM cache 2/1.
Obsolete or incomplete artifacts must be rebuilt rather than treated as a
valid empty result.

Before editing, establish:

1. the app purpose and current folder structure;
2. the current conda environment and dependencies;
3. the relevant entry points and data flow;
4. the files and tests affected by the request;
5. any mismatch between documentation and code.

Include that understanding in the final report unless it is needed earlier to resolve a blocker.
