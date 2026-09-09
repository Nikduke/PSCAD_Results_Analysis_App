# PSCAD Results Analysis

Current working snapshot: 2026-09-08.

For a new Codex chat, read [`docs/HANDOFF.md`](docs/HANDOFF.md) first. It is
the concise architecture and workflow map; then use
[`docs/CURRENT_CONTEXT.md`](docs/CURRENT_CONTEXT.md) and
[`docs/ANALYSIS_METHODS.md`](docs/ANALYSIS_METHODS.md) for detailed contracts.

This is the active app root inside the copied project folder. It contains only the current PSCAD Results Analysis app code, tests, setup files, build outputs, session state, and current documentation.

## Fresh-chat orientation

The application source and focused tests are authoritative. The documentation
has deliberately separated responsibilities so a new chat can recover the
design without reading every module first:

- `docs/HANDOFF.md` is the short architecture and workflow contract.
- `docs/CURRENT_CONTEXT.md` records the current implementation state, cache
  versions, validation evidence, and remaining risks.
- `docs/ANALYSIS_METHODS.md` defines the engineering calculations,
  qualification rules, ranking, heatmap semantics, and report selection.
- `STARTER_PROMPT.md` is the compact instruction set to paste into a clean
  task.
- `graphify-out/` is the local, generated repository-navigation graph. Use
  Graphify queries/path/explain commands before opening source files when the
  task is architectural; the graph is a navigation aid, while source and
  tests remain authoritative.
- This README covers setup, user actions, outputs, state ownership, and
  performance decisions.

## Operating regimes

The app is easier to reason about when its actions are treated as separate
regimes rather than one undifferentiated run:

1. **Project/session** - add/remove projects, restore the session, switch the
   active project, inspect project-specific settings/exclusions, and open a
   project folder.
2. **Scan/catalog** - validate or rebuild compact project metadata, discover
   dashboard figures, and optionally refresh Excel dashboards.
3. **Envelope/check** - apply exclusions, read raw PSCAD waveforms, build
   voltage envelopes, perform the authoritative High Voltage gate, and run the
   selected Stress/Late/No-settle/Sustained SDPF/RMS checks.
4. **Batch/render/report** - create plot batches, render MM plots and optional
   waveform workbooks, create RMS plots and Sustained SDPF heatmaps, and
   assemble DOCX reports.
5. **Rebuild-only** - rebuild charts, heatmaps, or reports from valid saved
   outputs without rereading unrelated raw waveforms.

`Run analysis` is the connected path through regimes 3 and 4. It reuses the
loaded Sustained SDPF payload and one cache validation per scope. The separate
buttons are intentionally narrower: they operate on existing stage outputs
and must not silently rerun unrelated stages. `Run analysis` and `Rebuild
reports` do not call Excel `RefreshAll`; dashboard refresh is explicit through
`Dashboards update`, while `Scan figures` only discovers/catalogs saved figures.

## State and cache ownership

All project-local state is keyed by canonical absolute project path; a project
must never inherit another project's exclusions, dashboard selection, scan
rows, settings, status, or output metadata. Scopes are the exception: the
selected token filters are global and are applied to every selected project.

| State | Location | Purpose | Deliberately not stored |
| --- | --- | --- | --- |
| Session/autosave | app `.state/` or executable directory | UI selections, project settings, exclusions, shared/local dashboard selection | raw waveforms and project scan inventories |
| Project scan cache | app `.state/project_scan_cache.json` | compact per-project discovery metadata and catalogs for warm startup | waveform arrays and full output-file lists |
| Project analysis cache | project `.state/analysis_cache.json` | stage signatures and output metadata for safe skips/rebuilds | engineering results and waveform arrays |
| Sustained result | `Voltage_envelope/<scope>/Sustained_SDpf.json` | compact engineering observations, selection references, heatmap flags, and source freshness | raw samples, plot settings, RMS diagnostics |
| Generated outputs | `Voltage_envelope/`, `Plots/`, `Reports/` | workbooks, PNG/Excel plot outputs, heatmaps, and DOCX reports | source-of-truth metadata beyond the stage cache |

The app intentionally has no persistent processed-waveform cache. The raw
waveform/envelope build is the expensive stage; the saved caches are compact
metadata and engineering results, not copies of the PSCAD `.out` data.

## Current versioned artifact contract

These source constants explain when old generated data must be rebuilt:

| Artifact | Current version | Owner |
| --- | ---: | --- |
| Project scan cache | 7 | `project_scan_cache.py` |
| Project analysis cache | 1 | `storage.py` |
| Voltage-envelope manifest | 3 | `voltage_envelope.py` |
| Sustained SDPF result JSON | 19 | `sustained_sdpf.py` |
| Sustained SDPF summary workbook | 4 | `sustained_sdpf.py` |
| Plot batch manifest | 3 | `analysis_engine.py` |
| Report manifest/layout | 2 / 3 | `reporting.py` |
| Embedded plotter SQLite/MM cache | 3 / 2 | `pscad_plotter_app_v3/services/project.py` |

An obsolete or incomplete generated artifact is invalidated and rebuilt from
current inputs. It must not be interpreted as a clean empty result.

## What the app does

- Native Windows desktop app for PSCAD result post-analysis.
- Scans PSCAD project folders, dashboard workbooks, result files, scopes, voltage levels, and exclusions.
- Builds voltage envelopes and combined envelope charts for selected scopes and voltages.
- Creates TOV/SFO/SA and project-specific RMS plot batches, renders waveform plots with the embedded plotting engine, and builds DOCX reports.
- RMS uses the already parsed/cached `Results/MM results.csv` catalog. For each selected voltage and enabled quantity (`LG` or `LL`), it selects one maximum and one valid minimum across the chosen alphabetized `MM_` elements, renders one value-only `[kV]` annotation per plot through the shared plotter, and writes outputs under separate `RMS/LG` and `RMS/LL` folders. New projects enable the existing analysis checks and Sustained SDPF by default; RMS is disabled until elements are selected. The RMS section is written first among analysis sections, immediately after SFO/TOV/SA event sections. RMS report subsections use semantic headings for Line-to-Ground/Line-to-Line Voltage Rise/Dip and include the percentage relative to `LLs [kV]` (or `LLs [kV] / sqrt(3)` for LG).
- Runs optional analysis checks: Stress, Late, No-settle, and Sustained SDPF. Stress/Late/No-settle use chronological envelope data from envelope building and do not reread raw waveforms; their findings use separate check/voltage/measurement groups and their documented area/slope ranking rules. Sustained SDPF uses the already loaded raw phase/pair data. Its screening event uses the maximum absolute peak in each complete cycle, must satisfy both the 30 ms physical duration default and the derived `ceil(duration × frequency)` consecutive-complete-cycle condition, and retains the positive/negative peak sequence separately for full-wave severity metrics. It then persists compact version-19 JSON metadata plus a two-sheet audit/selection summary workbook. Actual SDPF and Safety-margin-only populations are selected independently. Within each population, the three optional representative views are highest voltage sustained for the configured duration `T`, normalized full-wave excess area, and longest continuous full-wave duration. Current result caches are validated for settings, source freshness, finite values, and complete population-specific selected paths; obsolete versions are rebuilt. Ranking checkbox changes reuse the persisted engineering metrics and do not rebuild raw waveform results. A connected analysis run reuses the loaded Sustained payload and one in-memory source-fingerprint validation per scope across batch creation, plotting, heatmaps, and reports; standalone actions validate their saved data locally. Event-only batch actions leave valid Sustained SDPF batches and heatmaps untouched. `Resonance_Checks.xlsx` omits empty result tabs and retains only `Settings` when no findings exist.
- The optional project-specific Sustained SDPF incidence heatmaps reuse compact persisted Run × MM flags (LGp/LLp are merged for each Run × MM). A project with fault classifications starts with one enabled **Faults** set; a project without faults starts with **Cases by <token>**, using the first varying case-name part for Y grouping. Additional named sets can be cloned, reordered, enabled, and configured independently. Fault type and MM element are optional Y-only groupings: fault rows aggregate all MM elements, while MM rows aggregate all fault types. MM element is not selected automatically for no-fault projects. Case-name tokens remain available for Y, X grouping, and Split by. Each set uses separate or combined PNGs; combined panels are arranged vertically with one shared legend and repeated Y rows on every panel. All Y-dimension captions are omitted: the named view in the horizontal title and the row labels provide the context, while MM identifiers stay horizontal. The human-readable **MM elements** view name is used in figure/report titles. Heatmap figures use fixed, named inch-based bands: a large header, an optional X-group band containing only the selected group token, the matrix, an optional case-label band when residual identity remains, and a compact legend/footer. Split values are rendered generically as `Split: <value>` from the selected project token; no equality-style or `X group:` captions are generated. Long Y-axis and MM labels wrap at readable widths without changing their identity. Grouping/split tokens are not repeated in case labels, and selected tokens are never restored when no residual identity remains. Actual and margin-only colours use separate incidence scales. A page suffix is shown only when the same split continues across multiple combined files; distinct split pages are identified by their `Split: <value>` title. Case labels remain compact and unambiguous within each visible group. Valid-cache heatmaps can be rebuilt without waveform reads; they are appended to the existing Sustained SDPF report section only when that voltage has a governing candidate.
- Supports high-voltage proposal import from envelope output and from `PSCAD_log.txt` plus fast raw waveform maxima for matching case/MM buses.
- Uses `Input_Data_PSCAD*.xlsx` and `.inf` files as the project-opening voltage sources; treated result CSVs and generated plot filenames are not used to define available voltages.

## Folder layout

- `src/results_analysis_app/` - main PySide6 app, scanning, envelope build, reporting, settings, UI actions.
- `src/results_analysis_app/settings_dialog.py` - Settings dialog construction and settings-to-session updates.
- `src/results_analysis_app/project_scan_runner.py` - project-opening scan and cache wrapper.
- `src/results_analysis_app/project_scan_cache.py` - persistent metadata-validated project scan cache.
- `src/results_analysis_app/exclusions.py` - shared exclusion rules, matching, normalization, and legacy-session migration.
- `src/results_analysis_app/envelope_rows.py` - shared nearest-time envelope row selection used by batches and reports.
- `src/results_analysis_app/rms_analysis.py` - project-specific RMS selection from the shared MM-results catalog and RMS batch preparation.
- `src/results_analysis_app/sustained_sdpf.py` - fixed-phase/pair sustained SDPF stress calculation and result metadata.
- `src/results_analysis_app/sustained_sdpf_heatmap.py` - Run × MM incidence aggregation, project-specific grouping, and report-ready heatmap rendering.
- `src/results_analysis_app/styles.py` - centralized light/dark palette and semantic widget styling.
- `src/pscad_plotter_app_v3/` - compact MM waveform plotting and Excel-export engine used by report batches.
- `src/pscad_plotter_app_v3/services/project_conventions.py` - PSCAD case/run filename and statistic-file conventions used by scanning and plotting.
- `src/pscad_plotter_app_v3/services/waveform_io.py` - `.inf` descriptor parsing, PGB-to-`.out` mapping, and raw waveform reads; case/run parsing remains in `project_conventions.py`.
- `src/results_analysis_app/assets/` - app icon and packaged assets.
- `tests/` - focused contract tests for current behavior.
- `docs/CURRENT_CONTEXT.md` - current state handover for future Codex work.
- `docs/ANALYSIS_METHODS.md` - code-level description of inputs, exclusions, envelope construction, checks, charts, plots, and reports.
- `docs/HANDOFF.md` - concise new-chat architecture, data flow, output contracts, and safe-change checklist.
- `AGENTS.md` - project-specific development, validation, and documentation rules.
- `STARTER_PROMPT.md` - onboarding prompt for a new machine or clean Codex task.
- `environment.yml` - conda environment definition.
- `PSCADResultsAnalysis.spec` - PyInstaller spec for optional one-file executable build.
- `start_app.bat` - starts the app with the project-local conda environment.
- `Create_executable.bat` and `build_exe.ps1` - optional executable build using the project-local conda environment.

The parent folder keeps non-app material:

- `../Original_examples/` - original scripts and small test project used as references.
- `../02_Backup/` - backup material.
- `../.conda/pscad-results-analysis/` - dedicated conda environment kept outside this folder because conda environments are path-sensitive.
- `../.pytest_cache/` - generated pytest cache left in place if Windows has it locked.

## Requirements

- Windows.
- Anaconda or Miniconda.
- Dedicated conda environment, not `base`.
- Microsoft Excel desktop app for dashboard refresh, Excel chart workflows, and report figure extraction.
- PSCAD result project folders generated by the existing PSCAD/post-processing workflow.

Python 3.11 is recommended for this snapshot. The project metadata allows Python 3.11 or newer, but this clean setup is pinned to 3.11 for portability.

## Conda setup

Run from this app root:

```bat
conda env create --prefix ..\.conda\pscad-results-analysis -f environment.yml
```

If editable install did not run during environment creation, run:

```bat
..\.conda\pscad-results-analysis\python.exe -m pip install -e ".[dev,packaging]"
```

The `environment.yml` file still names the environment `pscad-results-analysis`. This project uses the project-local prefix `../.conda/pscad-results-analysis` on this machine so launcher scripts do not depend on global conda environment registration. The environment remains in the parent folder after the app move because moving an existing conda prefix can break compiled packages and activation metadata.

## Run

Run from this app root:

```bat
start_app.bat
```

Alternative:

```bat
..\.conda\pscad-results-analysis\python.exe -m results_analysis_app
```

## Test

Run from this app root:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TMP = "$PWD\.tmp"
$env:TEMP = "$PWD\.tmp"
..\.conda\pscad-results-analysis\python.exe -m pytest -q -o cache_dir=.tmp\pytest_cache
```

Dependency smoke test:

```bat
..\.conda\pscad-results-analysis\python.exe -c "import PySide6.QtCore, pandas, openpyxl, docx, win32com.client, matplotlib, numpy, pyexpat; import results_analysis_app; print('ok')"
```

The latest recorded local source-level validation for this snapshot passed
**257 tests**. Run the command and use its current output rather than relying
on this number alone.

## Build executable

Executable build is optional. Prefer running from conda during development.

Run from this app root:

```bat
Create_executable.bat
```

Expected output:

```text
dist/PSCADResultsAnalysis.exe
```

Test the built executable on the target machine before relying on it. If the target machines already have Anaconda, running from the dedicated conda environment is the more transparent development path.

The packaged executable stores autosave and manually saved sessions beside `PSCADResultsAnalysis.exe`. The `--smoke` check validates startup imports and default session construction, but it does not replace a real UI, Excel, plotting, or report workflow test.

The build spec explicitly bundles conda runtime DLLs used by Python startup modules, including `ffi-8.dll` for `_ctypes`. Missing these DLLs can make PyInstaller fail on another machine before the app window opens.

## Source control

Git is configured in this app root with `origin` pointing to the project GitHub
repository. The active branch is intentionally not hard-coded in documentation;
check it with `git branch --show-current`. Generated state, environments,
caches, build output, and project output folders are excluded by `.gitignore`.

Inspect `git status` before editing or committing. Preserve unrelated worktree changes and do not use destructive reset or checkout commands to discard them.

## Main workflow

1. Add one or more PSCAD project folders in one selection. Duplicate folders are ignored and only newly added projects are scanned. Existing saved projects validate core `.inf`, NonConv, voltage-input, and targeted PSCAD-log waveform metadata; dashboard, envelope, plot, and report outputs are tracked separately so output-only changes do not trigger a core rescan. Unchanged scans are restored from `.state/project_scan_cache.json`. On a cold scan, `PSCAD_log.txt` warning candidates are checked automatically against raw waveform maxima for every matching run.
   In the project list, double-click the project name to open its project-specific Settings; double-click its Status cell to open the project folder.
2. Select projects and scopes. The `Voltages` popup lists the discovered voltage levels; its `All voltages` checkbox selects or clears every level, while individual entries allow a partial selection. Choose TOV/SFO/SA envelopes and optional analysis checks, including SDPF. RMS is the first analysis control: its project-specific popup lists LG/LL quantities and alphabetized MM elements and is enabled only for a checked project with discovered MM elements.
3. Review exclusions for the current project. The `Manual` table accepts `Case`, `Run`, and `Bus`; blank cells are wildcards, while a completely blank row is ignored. `NonConv` and `High Voltage` appear only when the active project has corresponding detected proposals, and use the same `Apply` checkbox workflow. PSCAD-log High Voltage rows are checked automatically when the project is added. High Voltage rows show the mapped fault type when statistic data provide it, identify whether they came from the PSCAD log, analysis, or both, and can be unchecked to force that exact voltage/Case/Run/Bus back into the next build. The panel always follows the highlighted project row; it never falls back to another checked project while the tree is being refreshed. Project scans, proposals, exclusions, settings, and output status are keyed by the canonical project path, so one project cannot populate another project's panel.
4. Use `Scan figures` or `Dashboards update`.
5. Use `Build envelope data/checks` to build the base envelope workbooks and checks. This remains the authoritative high-voltage check across every selected case, bus, and run, including cases not proposed by the PSCAD log. Newly detected violations are excluded from both LGp and LLp in that same build and appear checked afterward. The `High voltage exclusions` sheet contains the exclusions actually applied to that specific workbook.
6. Use the TOV/SFO/SA or Analysis step buttons to rebuild charts, create batches, or render plots without rerunning all steps. An enabled RMS selection creates separate LG and LL max/min batches from the cached `MM results.csv` catalog.
7. Use `Rebuild reports` to regenerate reports from existing outputs.
8. After changing Sustained SDPF heatmap layout settings, use `Rebuild heatmaps` to regenerate only the heatmap images from the saved analysis results; use `Rebuild reports` afterward if the DOCX reports also need updating.

While a background action is running, the workspace controls remain locked and only the read-only log stays interactive. The log continues receiving messages, follows new messages only when already at the bottom, and preserves the user's position when scrolled up.

Heading numbering and envelope bullets use separate Word numbering definitions and list IDs, emitted in Word's required definition-before-instance order so both lists render correctly.

Use `Rebuild project cache` in Settings when project metadata needs a forced fresh scan. Normal startup and adding a project scan only missing or changed projects. Analysis actions update affected status flags and cache entries directly; they do not trigger a full project scan.

Reports use numbered Word headings and add field-based figure captions plus clickable cross-references for dashboard, envelope, time-domain, RMS, and analysis figures. Cached field values are written into the document and automatic field updating is disabled, so opening a report does not show Word's external-field update prompt; fields can still be refreshed manually with `Ctrl+A`, `F9` after editing. The envelope section is written first as section 1.1 and dashboard figures follow as section 1.2 when both are available. Initial-condition dashboard charts are ordered as `Initial voltages`, `Initial Reactive Power`, then `Initial Active Power`. A short selected SFO/TOV/SA list with the reference report's green hollow-circle bullets is placed before each exported envelope figure. SFO and TOV use the matching `LLp` envelope rows, SA uses the matching `LGp` row when SA is selected, and TOV/SA show calculated RMS values with Word-subscripted peak/RMS units. SA time-domain reports use the line-ground TOV RMS value and the fixed 300 ms duration text for surge arrester selection. Dashboard figures titled `Initial voltages`, `Initial Active Power`, and `Initial Reactive Power` keep the dashboard's saved slicer state; other dashboard figures are filtered per report voltage. RMS overvoltage dashboard titles are reported as `voltage rise`; RMS `dip` and `drop` titles remain unchanged. For each voltage, report analysis sections are ordered as the selected SFO/TOV/SA event sections, then RMS, then Sustained SDPF and resonance checks. Generated time-domain and analysis figures in reports place their green Case, Run, Element, Fault, and Trace plot headings before the cross-reference text; these headings are unnumbered third-level navigation entries. Known fault labels are separated from the element, while faultless element labels such as `MM_161_TPC1` remain intact. Reports embed the reference report's typography in code: A4 layout, green numbered chapter headings, green third-level plot headings, justified body text, green italic captions, report header, and page-number footer. A real report template is not required.

Outputs are written inside each selected PSCAD project, normally under:

- `Voltage_envelope/<scope>/`
- `.state/analysis_cache.json` (one small project-local stage-fingerprint cache; it contains no waveform arrays)
- `Voltage_envelope/<scope>/Sustained_SDpf.json` when Sustained SDPF is enabled (versioned compact metadata with one shared source fingerprint)
- `Voltage_envelope/<scope>/Sustained_SDpf_summary.xlsx` when Sustained SDPF is enabled (a compact `Ranked cases` sheet for population ranking plus a `Representative selections` sheet for the independently selected sustained-T, cumulative-stress, and continuous-duration rows; it is an audit/selection workbook, not a plot manifest)
- `Plots/Generated/<scope>/RMS/LG/` and `Plots/Generated/<scope>/RMS/LL/` for selected RMS maximum/minimum figures
- `Plots/Plot_batch/batch_paste_<scope>_RMS_LG.xlsx` and `batch_paste_<scope>_RMS_LL.xlsx` for the corresponding RMS jobs
- `Plots/Generated/<scope>/Sustained_SDPF_Heatmap/<order>_<name>/` for each enabled named Sustained SDPF heatmap set
- `Plots/Plot_batch/`
- `Plots/Generated/<scope>/` only for event/check folders that contain rendered plots
- `Reports/<scope>/`

## Notes

- Session autosave data is saved under `.state/` when running from conda. The packaged executable stores `.state/` and `sessions/` beside the executable. A small header above the top bar identifies the active project; its tooltip contains the full path.
- Project-specific UI state is keyed by canonical absolute project path. Tree rebuilds block intermediate selection signals, clear the exclusion panel when there is no active row or no current project scan, and reload it only for the active project. Analysis selections and RMS quantity/MM-element choices are also project-specific. New projects enable Stress, Late, No-settle, and Sustained SDPF by default; RMS remains disabled until the user selects elements. The RMS control is disabled when the highlighted project is not checked or has no discovered MM elements. The Manual table remains available for user-entered rules; detected NonConv and High Voltage tabs appear only when the active project has corresponding rows. Detected High Voltage rows are derived only from that project's current scan; the session stores only explicit include overrides, which are discarded when their exact voltage/Case/Run/Bus key is absent from the current scan. Dashboard figure metadata is cached per project, while the dashboard list defaults to the union of all cached project figures. The short `All checked` checkbox is enabled by default and applies one selected figure set to every checked project; clearing it exposes the current project's list and stores local overrides. When shared mode is enabled again, the active project's list becomes the shared selection and local selections are preserved. A figure absent from a project is skipped harmlessly during that project's report. The `Scopes` list is intentionally global: selected token filters are applied to every selected project, while each project's scan data, exclusions, settings, outputs, and status remain isolated.
- The UI follows the Windows light/dark colour scheme at startup and while the app is open. Panels, tables, headers, tabs, inputs, labels, buttons, selections, disabled controls, status controls, checkboxes, and scrollbars share one semantic application theme. Widget and item-view checkboxes use the same high-contrast indicator states throughout the app.
- Manual exclusions use one `Apply / Case / Run / Bus` table. Any blank field matches all values for that field: a run-only rule applies that run number across all cases and buses, a bus-only rule applies that bus across all cases and runs, and a fully blank row is never applied. Run and Bus cells accept comma-, semicolon-, or newline-separated values; the app expands them into individual exact rules, using the Cartesian product when both cells contain lists. Run ranges are not inferred. New rows are checked by default. The table supports TSV copy/paste; all exclusion tabs use `Apply all` and `Apply none`.
- Applied manual, NonConv, and High Voltage rows are normalized into one matcher before envelope reads. Whole-run rules are removed before worker submission; bus-specific rules filter matching `.inf` descriptors. Sessions containing the former per-voltage Bus and Case/Run fields are migrated when loaded; former Bus entries become bus-only wildcard rules because the universal Manual table has no voltage column.
- Test commands use `.tmp/` so pytest does not depend on the user temp folder.
- Project opening validates a persistent metadata cache first. Only missing, changed, or forced core project scans read project contents; unchanged hot-start entries are not rewritten. Mixed hot/cold startup scans only stale projects, and adding one project does not rescan the existing list. Cache validation builds one targeted manifest per project pass, uses `os.scandir`/`DirEntry.stat()` for case-file metadata, and filters names before reading metadata. Ordinary waveform `.out` files are ignored except for runs named by current PSCAD-log warning candidates. Dashboard-only changes reuse the project scan and show `Dashboards changed`; `Scan figures` or `Dashboards update` clears the notice. Envelope-only changes refresh their High Voltage proposals without a core rescan, while plot/report/result presence only updates status chips. NonConv proposal detection remains eager for actual scans. Reads inside one project scan use a bounded worker pool; multiple cold project scans stay sequential to avoid nested worker contention.
- The version 7 project scan cache stores serialized per-project scan data, project timing, relative core-input metadata, case/fault metadata, cached `Um`/bus configurations and validated `MM_blocks` SDPF limits, the compact dashboard figure catalog, separate dashboard/envelope metadata, output-presence flags, PSCAD-log candidate maxima, and the settings used to classify those maxima. Detected High Voltage rows are reconstructed from this scan data; they are not duplicated in session autosave. During a cold scan, case-name information comes from the existing `.inf` inventory and the project-wide `Run#` → `Fault_type` map is read from the first valid `Statistic*.out`; the map, dashboard figure catalog, and workbook-derived settings are reused by Settings and the high-voltage table without lazy project-data reads. Upgrading from an older cache causes one cold scan. Hot validation reads PSCAD-log warning lines and file metadata; it does not parse `.inf`, `.out`, Excel, plot, or report contents when inputs are unchanged. If dashboard workbook metadata changes, only that project's chart catalog is rescanned with the targeted XML reader; unchanged catalogs remain a warm-start cache hit. Analysis action completion preserves the validated input manifest and refreshes only output metadata because source PSCAD inputs are not expected to change while the app is open.
- Project scans keep only the status flags needed by the UI instead of retaining full output-file lists.
- Removing a project clears its project-specific x-axis settings, `Um` overrides, exclusions, status, and cached scan. Re-adding it starts with clean project-specific state.
- Project opening automatically reads PSCAD-log warning case/MM pairs and uses a bounded pool to find one raw waveform maximum per matching case/run/bus. These maxima are cached. Changing only the high-voltage factor or `Um` reclassifies cached maxima without rereading waveforms. A changed log, matching `.inf`, or matching raw `.out` file refreshes only the log-derived high-voltage data. Projects without a log do not trigger a full raw-results scan.
- Envelope builds enumerate `.inf` files once per build, build one shared source-file inventory for manifest fingerprints, and index output-name prefixes so every `.inf` manifest avoids rescanning its directory. Files with identical content share one parsed descriptor template across scopes and voltages. NonConv summary files and raw voltage runs are processed through bounded process workers; one run is submitted per worker and processed envelope data exists only for the current build. Voltage levels submit raw-read jobs concurrently through one shared process pool, so the configured worker cap is not multiplied by the number of voltage levels. There is no persistent processed-waveform cache. The single project `.state/analysis_cache.json` stores only the envelope signature and generated-output metadata, allowing an unchanged complete envelope stage to be skipped. Presentation-only changes can reuse validated calculation workbooks and regenerate charts/autofit outputs without rereading raw waveforms. Envelope workers default to automatic selection: the ceiling of 80% of detected logical CPUs, capped at 60 for Windows process-pool compatibility and reduced when fewer runs exist. Settings expose an `Automatic` checkbox enabled by default; clearing it enables a positive manual override. Raw `.out` waveform reads remain voltage-specific.
- The project analysis cache has one explicit schema version and stores only stage signatures, output paths, sizes, and modification times. Its envelope entry includes both the current Sustained SDPF result version and the summary-workbook format version, so summary-only layout changes force the envelope/summary outputs to rebuild while leaving the engineering result schema unchanged. Its plot entries include the current Sustained SDPF result version, while Sustained report entries also include the current Sustained report-layout version, so obsolete outputs are regenerated without storing per-folder JSON manifests. Obsolete per-run pickle caches and folder manifests are ignored and removed during the next relevant build. Sustained plot rendering receives the same project SDPF overrides as detection and changes only the SDPF fields; SIWL values remain those loaded by the plotter from the workbook/plotter override source. Sustained result version 19 persists the compact fixed-path sustained-T metric, qualifying-event descriptors, and independent population-specific representative references without flat aliases or embedded duplicate results.
- `Envelope time end` uses the selected project's `Final duration` automatically by default. Clearing `Use project duration` enables a manual upper limit. Each run is capped again by the final timestamp already loaded with its raw waveform columns. No separate `.out` scan is performed and no zero-valued samples are generated after a run ends.
- Sustained SDPF uses the project frequency from `Input_Data` when it is present and valid; otherwise it uses the configured envelope fallback frequency from Settings. It also uses the embedded plotter's per-voltage `MM_blocks` SDPF limits. The dedicated Settings table labels workbook-derived values, allows per-project RMS overrides with immediately recalculated peak/margin values, and labels edited rows `Manual`. It evaluates fixed LG phases and LL pairs independently: each complete cycle contributes its maximum absolute peak to screening, so a positive violation → negative non-violation → positive violation sequence can remain a candidate when the absolute peak run is consecutive. The first and last raw waveform threshold crossings define the physical event duration. The positive/negative peak sequence is retained for full-wave area and continuous-duration ranking, where the lower opposite-polarity lobe creates a real below-limit gap; `V_T` uses the absolute qualification envelope. A short continuous excursion crossing a cycle boundary is rejected when its interpolated duration is too short; a missing-cycle gap ends the event and a later excursion remains separate. RMS remains a supporting diagnostic and cannot qualify a sustained TOV alone. The analysis and plotter use the same RMS-to-peak conversion and SDPF/1.15 threshold. Short decaying events are excluded from the sustained result and remain with SFO/AFO. The cross-path `V_T` value is normalized by the actual SDPF peak limit, so a short high spike cannot determine the sustained-T metric. Actual SDPF candidates and Safety-margin-only candidates are never compared with one common severity rank. Each population independently selects the enabled highest sustained-T voltage, highest normalized full-wave excess area (`Worst cumulative stress`), and longest continuous full-wave duration (`Longest continuous duration`). Areas are never summed across phases, LL pairs, or separate events. The app writes compact result JSON plus a two-sheet `Sustained_SDpf_summary.xlsx`: `Ranked cases` is an audit table with one row per Case/Run/MM observation, explicit population rank and threshold, normalized excess area, qualification duration, full-wave continuous duration for ranking, sustained `V_T`, event timestamps, qualifying paths, and limit source; `Representative selections` lists the selected row for each criterion and population. A method block records result version, persistence, effective frequency, and cycle coverage. The workbook contains no waveform data, raw paths, RMS diagnostics, or plot settings. The persistence duration is independent of the ordinary TOV event setting. Result freshness uses one source fingerprint plus compact source-directory roots rather than a full raw-file metadata list.
- Project `Final duration` and frequency are read during project initialization and stored in the project scan cache. `Chart x max` defaults to that project-specific duration; `Chart x major` defaults to a readable interval near one tenth of the effective range. Both can be overridden per project in Settings and are saved in `.state`. Envelope and resonance charts share these values and remain capped by the available generated data duration.
- Envelope waveform absolute values are reused between high-voltage checks and envelope rolling. Rolling envelopes are calculated only after a run's high-voltage scan, so automatically excluded buses do not perform work that will be discarded. Envelope workbooks keep the existing openpyxl table/filter formatting, then use Excel's native AutoFit through the already-packaged Excel automation support.
- Envelope phase candidates are reduced directly with NumPy while preserving the existing source-order tie rule and Case/Run attribution; intermediate dataframe merge chains are no longer built.
- Sustained SDPF finite-segment discovery and common-grid cycle slicing use vectorized boundary/index operations; the qualifying, area, and duration rules are unchanged.
- Report plot batches support only the MM waveform mode used by this app. Legacy CB, arbitrary-channel, FFT, combined-mode, and unused catalog branches were removed; MM Excel waveform exports remain supported. The embedded SQLite cache now loads only the MM element rows needed to validate these batches.
- Automatic waveform Excel export is enabled by default in Settings. Clearing `Create automatic Excel waveform exports` keeps PNG plot generation and the analysis unchanged while avoiding the per-plot `.xlsx` writes; manually edited batch rows can still request an export explicitly.
- Plot rendering prepares all jobs from the selected scope/event batch files for one project before execution. Eligible batches with at least `3` jobs and at least two cache-local Case/Run groups use one bounded Windows process pool capped at `4` workers; related jobs are grouped in chunks of up to `8` so a worker can reuse its renderer cache. If one Case/Run group contains the whole batch, the parent keeps it sequential because another process would only add startup overhead. Each worker owns its renderer and performs the PNG render plus any requested waveform Excel export. Smaller batches remain sequential to avoid process startup overhead. Each event/check folder keeps its own staging directory and is atomically replaced only after all of its jobs succeed. A stop request cancels queued work and terminates active plot workers, discarding uncommitted staging output; a process-pool startup or child-worker failure falls back to the sequential path.
- Successful event/check folders contain only the generated PNG/Excel outputs. Their normalized job/source signature and output metadata are stored in the project's `.state/analysis_cache.json`; a later render skips an unchanged batch when that entry and its outputs still match. Changing a source file, batch row, export setting, or renderer version forces regeneration.
- During one render session, each statistic file is discovered and parsed once; event rows for all runs are then served from the bounded renderer cache. Plot reads request only the time column and selected waveform columns, and standardized Case/Run group frames are reused by neighboring plots and their Excel exports. Raw selected-column data is limited to 256 files and 1 GiB per renderer; standardized group frames have a separate 256-frame/512 MiB cap. Excel waveform exports use openpyxl write-only workbooks, avoiding a second in-memory workbook tree without changing the sheet contents.
- Envelope builds reuse the validated project-scan `Um`/bus configurations, Sustained SDPF limits, and NonConv proposals when available; the PSCAD-log high-voltage pass reuses the `.inf` inventory collected during the same cold scan.
- Background cancellation has a separate stopped state and is preserved through plot rendering and reporting. Reports check for Stop between projects, scopes, voltages, exports, and figures. Closing the window during active work requests cancellation and waits for the worker to finish. Envelope process workers check cancellation between completed runs; plot-rendering and Excel-export readers retain 4,096-row checks. Excel and output-writing operations still finish their current operation safely; active parallel plot workers are terminated on Stop so the UI does not wait for every active job.
- Invalid `.inf` layouts, unreadable CB summaries, and unreadable high-voltage proposal workbooks are reported in scan/build warnings instead of being silently discarded.
- Malformed autosave and cache field shapes are normalized or ignored safely. An invalid manually selected session leaves the active session unchanged and shows an error.
- Dashboard figure-only scans update only the checked projects' figure catalogs without triggering a core project scan. The catalogs are also populated during a cold scan and restored from the version 7 project scan cache on warm open; changed dashboard workbooks trigger a targeted catalog refresh automatically. Dashboard refresh updates only dashboard status and catalog metadata; failed project refreshes keep the `Dashboards changed` notice. The default `All checked` selection is persisted as one compact shared ID list and is filtered per project at report time; clearing the checkbox persists project-specific selections, which are restored when shared mode is disabled again.
- Report image directories are indexed once per project/scope report pass and reused across selected voltages. Report signatures and DOCX output metadata share the same project analysis cache; unchanged source figures, workbooks, settings, and output metadata allow a later report pass to skip that voltage report.
- Plot rendering treats each selected scope/event folder under `Plots/Generated` as app-owned output. It renders into a staging directory and replaces the previous folder only after complete success; an empty valid batch removes the previous event folder. Do not store manual files in these generated event/check folders.
- Report-only export images are removed after each scope's DOCX reports are written.
- PSCAD `.inf` case/run parsing and `.out` column mapping are shared with the embedded plotter waveform I/O helpers. Lowercase `_r` and uppercase `_R` run markers use the same parser.
- Base envelope workbooks are the authoritative high-voltage proposal source; combined chart workbooks are compatibility fallbacks only. Combined workbooks are built at a temporary path and replace the last good chart atomically. Reports skip a combined chart older than its base workbook and log that chart rebuilding is required.
- Batch creation and report summaries share one nearest-time selector. Exact midpoint ties use the earlier source row, so the plotted candidate and reported envelope value stay aligned.
- Fresh cold-scan warnings are written to the app log once; cached historical warnings are not replayed on every hot start.
- Full `Run analysis` reuses the same envelope, batch, render, and report action functions as the step buttons. Completed actions update only affected project output status and cache entries.
- Documentation uses relative paths only. Update docs after meaningful behavior or workflow changes.
- Git is used for source control; generated outputs and local state remain excluded from commits.

## Measured performance reference

These measurements are representative development-machine evidence, not
guaranteed timings for every PSCAD project:

- On `../Original_examples/03_Test_project_case`, a persistent project-scan
  cache was about **7.8 s cold**, **0.48 s warm**, and **7.5 s forced**. The
  warm path validates metadata without rereading waveforms.
- On the same reference data, raw envelope reads took about **53 s** across
  66/161/230 kV in one sequential run. A shared concurrent-voltage prototype
  completed the same reads in about **12.2 s** at 16 workers with matching
  envelopes and merged tables. This remains the main runtime cost.
- Plotter catalog/index work was below **0.04 s** in the same project, and
  temporary plot-batch creation was below **0.3 s**. Reworking plotter
  indexing is therefore not the primary optimization target.
- Excel chart generation remains a shared COM process and took about **5.1 s
  for three temporary workbooks**. Excel COM work is not parallelized.
- Plot and heatmap rendering switch to bounded parallel workers at **three or
  more independent jobs/pages**, use at most **four** workers, and fall back
  to sequential work when parallel startup is not worthwhile or fails.

## Current validation gaps and risks

- Existing files under `dist/` do not represent the latest source until the executable is rebuilt and tested.
- Excel COM workflows require Microsoft Excel and remain machine-sensitive.
- Full envelope and report workflows should be validated on representative PSCAD projects after material analysis or reporting changes.
- Sustained SDPF engineering tests cover continuous-window handling, no phase stitching, separate LG/LL limits, 50/60 Hz processing, settings persistence, source-result metadata, and the no-extra-workbook contract. A representative end-to-end Sustained SDPF plot/report pass still requires a PSCAD project with valid Excel/plotter inputs.
- The latest source-level cleanup was validated with synthetic MM rendering and Excel export, but not with a full representative PSCAD envelope/plot/report pass.
- Project, envelope, plot, and report cache validation uses file size and modification time. An external edit preserving both values may require a forced rebuild or removal of the corresponding generated cache/manifest.
- Envelope waveform reads are parallel across selected voltage levels through one shared bounded process pool. Heatmap images/pages use the same three-job threshold, Windows spawn pool, four-worker cap, bounded queue, cancellation, and sequential fallback; heatmap data preparation and final atomic file replacement remain in the parent process. Large projects should be evaluated with representative timing because parsing and Python-side processing can be CPU-bound as well as storage-bound.
