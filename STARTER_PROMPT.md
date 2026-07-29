# Starter Prompt For A New Machine

You are working in this folder as the active PSCAD Results Analysis app root.

Rules:

- Work silently by default and provide a final report only, unless clarification or approval is required.
- First read `AGENTS.md`, `README.md`, `docs/CURRENT_CONTEXT.md`, `pyproject.toml`, and `environment.yml`.
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

Before editing, establish:

1. the app purpose and current folder structure;
2. the current conda environment and dependencies;
3. the relevant entry points and data flow;
4. the files and tests affected by the request;
5. any mismatch between documentation and code.

Include that understanding in the final report unless it is needed earlier to resolve a blocker.
