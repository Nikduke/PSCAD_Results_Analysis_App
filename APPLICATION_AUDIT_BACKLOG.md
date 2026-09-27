# PSCAD Results Analysis App — Stage-by-Stage Audit

**Audit date:** 2026-09-27

**Scope:** Current `01_App` source, application documentation, tests, the supplied 117-case / 50-run timing log, and the previously recorded isolated optimization experiments in `docs/PERFORMANCE_AUDIT.md`.

**Production-code changes:** The verified run-data cache precision defect is corrected in the working tree. The audit and documentation record the original defect, the implementation, its migration behavior, and validation results.

## Executive result

The measured cold run on the 117-case / 50-run project took about **1,879 s (31 min 19 s)**. Envelope construction for `O2_Active_faults` accounted for **1,525 s (~81%)**; project scan, plot batching, rendering, and report generation are not comparable bottlenecks. The existing incremental run-data cache removes source-reading work on valid warm entries, but does not avoid scope/voltage-specific calculations and result generation.

The prior real-data candidate experiments reject the tested shared-reader, merge-reduction, and batched-cache-write replacements. After correcting run-data precision, the result-cache prototype was re-tested with the screenshot's three resonance checks enabled and semantic cold/warm checks: repeated full-selection rebuilds improved 15.9% on the 150-run sample, narrowing to 161 kV was 2.5% slower, and the isolated 50-run case improved 0.9%. These are test-only in-memory results; persistent storage overhead was not measured. Because the gain applies to an uncommon forced repeat and selection-change performance was negative, do not add a production cache now.

At audit start, the float32 run-data cache had a verified real-data correctness defect: on the available 150-run/three-voltage PSCAD example, warm hits changed envelope selections and resonance output. The working-tree update now stores time and `Max_*` arrays as float64 and increments the cache/signature version. A production cold/warm check reused all 450 run-voltage entries and matched semantic contents across the three voltage-envelope workbooks. The actual 117×50 workload is not present; its exact disk use and speed are not inferred from this smaller example.

Fresh validation completed during this audit: **319 passed, 10 skipped**. The first attempt using pytest's default user-profile temp directory hit Windows `Access is denied`; rerunning with an isolated basetemp under the repository's existing `.tmp` directory completed successfully.

## Runtime stage map

| Stage | Main owners / call path | Inputs and transformations | State, outputs, downstream use |
|---|---|---|---|
| Startup and session restore | `__main__.py` → `MainWindow`; `storage.py` | Initializes Qt/theme and restores the app session/settings. `--smoke` validates session defaults without opening the window. | Session state supplies project paths, selected scopes/voltages/events, settings, and project-specific overrides to actions. |
| Project discovery and scan cache | UI project actions → `project_scan_runner.scan_projects_cached` → `scanner.project_scan_manifest` / `scanner.scan_project` | Scans project files and derives case/configuration, timing, voltage, exclusion, dashboard-figure, and high-voltage catalogs. A valid manifest reuses serialized scan data and refreshes only changed sections. | Global scan cache in `storage.py`; versioned in `project_scan_cache.py`. Cached project metadata is consumed by settings, exclusions, and analysis setup. |
| Envelope and engineering checks | `actions.run_analysis_pipeline` → `voltage_envelope.build_voltage_envelopes` → `_read_voltage_runs` / `_build_voltage_workbooks` | Selects run descriptors; reads statistic and waveform data; applies voltage, scope, exclusion, and non-convergence rules; derives per-run maxima; computes resonance and Sustained SDPF results; reduces and writes voltage-envelope workbooks/charts. | Project-local SQLite run-data cache, envelope output manifest, Sustained result payloads, resonance workbook, and envelope workbooks. These drive plot batch selection and reports. |
| Analysis-data preparation | `actions.run_analysis_pipeline` after envelope/check build | Loads/validates Sustained results and, when enabled, loads or reuses the RMS catalog, filters governing RMS rows by voltage/element/switching-time selections, and prepares selection data for plotting. | Reuses selected catalog/context within the run; supplies RMS selections and validated Sustained payloads to batch creation, rendering, and reports. |
| Plot-batch construction | `actions.create_plot_batches` → `analysis_engine.create_plot_batches` | Reads the generated envelope workbooks to select governing case/run/MM points; prepares event, RMS, and Sustained batch rows; clears stale outputs only for explicitly requested disabled stages. | Batch workbooks under `Plots/Plot_batch`; consumed by the renderer and heatmap builders. |
| Plot and heatmap rendering | `actions.render_plot_batches` → `analysis_engine.render_plot_batches` and embedded `pscad_plotter_app_v3` readers/renderer/exporter | Resolves batch rows to source waveforms, loads selected channels, applies plot time/limit settings, renders plots/Excel exports, and creates configured Sustained heatmaps. | Generated plot directories and heatmaps, committed through staged output handling; those files are indexed by report generation. |
| Report generation | `reporting.build_reports_from_existing_plots` | Reads existing plots and selected dashboard figures, maps images, and builds/skips signed DOCX report outputs. It consumes analysis results; it does not refresh the dashboards. | DOCX reports and report-cache signatures. Dashboard refresh is a separate user action by design. |
| Background work, cancellation, and persistence | `BackgroundTask`; `main_window._start_background_task` / `_on_worker_progress`; `storage.py`; cache/manifest owners above | Runs long actions on a `QThread`, relays log/progress signals, checks a cancellation token at explicit work boundaries, and routes success/cancel/failure back to the UI. | Session, scan, run-data, stage-manifest, and output state. The Stop action waits for an active file/Excel operation to exit; exceptions include a traceback in the failure path. |

`Run analysis` connects envelope/check construction → analysis-data preparation → batch creation → rendering → reports. It deliberately does **not** refresh dashboards. Standalone rebuild/render/report operations reuse stage services rather than being folded into the connected run.

## Stage audit notes

### Startup, session, and project scan

- The scan path has a versioned persistent project cache and a file manifest. Its signatures use file size and modification time; edits preserving both can remain cached until a force/rebuild action or relevant cache invalidation. This limitation is documented in `docs/CURRENT_CONTEXT.md`.
- The current targeted project walk and section-level refresh avoid a full scan when only dashboard, envelope, or PSCAD-log inputs change. Recorded measurements in `docs/CURRENT_CONTEXT.md` are about **7.8 s cold, 0.48 s warm, and 7.5 s forced** on the development project. This is already a useful cache; no scan rewrite is justified by the 117x50 timing.
- Tests cover changed-input invalidation, output-only status changes, section-specific refresh, force behavior, corrupt cache recovery, and cache round trips.

### Envelope build and the run-data cache

- The supplied cold run records approximately **477 s wall time** for source reads across the selected voltages, then **250–324 s per voltage** in merge/calculation versus only **0.3–0.5 s** for the workbook write. An interval of at least **407 s** before the first Sustained result-save message was not isolated by that older log; it must not be attributed to SQLite writes alone.
- `RunDataCache` stores per-run derived time and `Max_*` arrays plus metadata in compressed SQLite payloads. Cache reuse checks a calculation signature and source signature; filters/exclusions are reapplied during the later selection/merge. A project setting bypasses cache reads/writes without deleting the stored entries. The complete-envelope manifest can skip the stage when its inputs and artifacts are current.
- Source signatures are metadata-based (size and modification time), not content hashes. This is a speed/correctness tradeoff already documented; the force/rebuild path is the current recovery for a suspected same-metadata edit. No real collision was observed in this audit.
- The pre-update float32 cache changed real-data cold/warm semantic outputs; the working-tree correction and regression coverage are recorded in Verified Backlog item P1.

### Preparation, batches, rendering, and reports

- The earlier supplied log had about **120 s** between envelope completion and plot-batch creation. Current code now reports RMS catalog preparation, Sustained result load/validation, and total analysis-data preparation separately; a fresh 117x50 run is needed to locate any remaining material substage.
- Batch creation was below **1 s** in the measured large project. Plot rendering was about **39 s** and reports about **14 s per project**. These numbers do not support optimizing Excel workbook writes, batch generation, or report construction ahead of envelope calculations.
- Rendering already has bounded process concurrency, staged/atomic output handling, and a sequential fallback when process-pool execution fails. Worker-count tuning is explicitly out of scope; no change is recommended.
- Report generation indexes plot images for reuse and validates report signatures to skip unchanged reports. It operates on existing dashboard files; changing dashboard-refresh behavior would be a workflow change, not a performance fix.

## Verified Backlog

### [P1 — IMPLEMENTED AND VERIFIED IN WORKING TREE] Preserve exact envelope and resonance results across run-data cache round-trips

**Stage:** Envelope run-data cache encode/decode → resonance record construction and threshold analysis.

**Original implementation:** `envelope_data_cache._encode_run_data` stored time and `Max_*` arrays as float32. `_decode_run_data` restored them as float64 containers, but could not recover precision already discarded. `resonance_checks.records_from_entries` uses these values before the envelope workbook's final 0.1 kV reduction rounding.

**Current implementation:** `_encode_run_data` now writes both arrays as float64. `CACHE_VERSION` is 2 and participates in `_run_data_cache_signature`; old-format entries miss and are overwritten at the same run/voltage primary key. `ENVELOPE_CALCULATION_VERSION` is also 2, invalidating a prior complete-stage manifest so stale outputs cannot skip the one-time correctness rebuild. The project-specific cache toggle and engineering calculations are unchanged.

**Evidence / problem:** The production `analyze_records` path changes a synthetic threshold case: a constant envelope of `100.000001` kV with vnom and Vlim both 100 kV produces one `Post_Event_Stress` result before conversion and zero after float32 round-trip (`100.000001 → 100.0`). More importantly, a disposable overlay of the real example project (150 `.inf` runs, 450 run-voltage entries across 66/161/230 kV) reproduced output drift. Two uncached rebuilds and the cache-populating build matched exactly; after 450/450 float32 cache hits, four files differed: all three `MM_<voltage>.xlsx` workbooks and `Resonance_Checks.xlsx`. The comparison found 2,271 numeric-cell differences and 155 nonnumeric/selection-cell differences; examples include `Run_C` changing from 34 to 32 in `MM_161.xlsx` and `MM_name_B` changing from `MM_230_ONC1` to `MM_230_ONS1` in `MM_230.xlsx`. This is a real output/selection change, not just a tiny serialization delta.

**Hypothesis tested:** Float32 storage is harmless because envelope workbooks round maxima to 0.1 kV, and a higher-precision cache can preserve outputs without excessive disk growth.

**Test / measurement:** Compared semantic cells in all generated workbooks across repeated uncached builds, cache seeding, and warm cache hits on a read-only-junction overlay of the real example data. Then tested a test-only float64 encoder and a smaller variant with float64 `Max_*` values but float32 time indices. All tests used the real `build_voltage_envelopes` and production resonance/Sustained paths; only cache serialization precision was varied.

**Result:** The float32 cache hypothesis is false. A full float64 prototype had no semantic differences across all six output workbooks. On this reference dataset its cache was **16,248,832 bytes (15.50 MiB)** versus **10,686,080 bytes (10.19 MiB)** for float32: **+5,562,752 bytes / +52.1%**. The warm build took **13.44 s**, versus a mean **18.76 s** for two uncached builds (**28.4% faster**); the cache-populating build took **23.47 s**, about **4.70 s above** that uncached mean in this sample. A partial-precision variant (float64 values, float32 time) still changed `Resonance_Checks.xlsx` in **759 numeric cells** (maximum absolute delta about **1.06×10⁻⁶**); its cache was 15,237,120 bytes. Exact parity on the tested data therefore required preserving both the values and time index as float64.

**Update / status:** Implemented in the working tree. Focused tests assert exact float64 round-trip for cached time and values, prove both cache and full-stage versions invalidate prior state (then permit normal stage skipping after rebuilding), and exercise a resonance `Vlim` boundary (`100.000001 kV` vs `100 kV`) through cache encode/decode. On a fresh disposable overlay of the available example, a production cold/warm benchmark reused 450/450 entries and matched semantic contents in all three voltage-envelope workbooks. The run-data cache source and calculations are unchanged apart from precision/version fields; no engineering threshold or tolerance was changed.

**Expected benefit and cost:** Preserve semantic output and governing selections between cold and warm builds. After both production version bumps, one envelope-only sample measured **15.74 s cold vs 6.35 s warm** (**59.7%** faster); a previous full-check float64 prototype measured **28.4%** in a different forced-stage setup. The single-sample envelope timing is not a stable estimate or a forecast for the 117×50 workload or total app. The controlled format comparison showed a **52%** whole-cache increase on the 150-run sample, not a 2× increase. A rough linear estimate for 5,850 runs and three voltages is about **397 MiB float32 vs 604 MiB float64** (+**207 MiB**), but actual size depends on signal density and run lengths; this extrapolation is not a project-specific claim. The initial cache-populating build also pays the serialization/write cost.

**Correctness / regression checks:** Passed: exact frame/time float64 round-trip; just-above-Vlim resonance finding and metrics survive cache serialization; old cache rows and full-stage manifests miss, current rows are written, and subsequent unchanged stages skip; production cold/warm semantic envelope workbook contents match for all three voltages with 450/450 cache hits. Existing tests continue to cover source-signature invalidation, project cache bypass, and pruning. The 117×50 project was not supplied, so no exact per-project size/speed claim is made.

**Changed and verified areas:** `src/results_analysis_app/envelope_data_cache.py`, `tests/test_envelope_data_cache.py`, `tests/test_performance_benchmark.py`, `tests/test_performance_candidates.py`, and cache documentation. `voltage_envelope._run_data_cache_signature` and resonance consumers were verified without changing their calculation logic.

### [P3] Synchronize progress and validation documentation with the current implementation

**Stage:** Background progress reporting and repository validation notes.

**Current implementation:** `run_analysis_pipeline` assigns five 100-point stage intervals per project and forwards progress from its known-work loops. `MainWindow._on_worker_progress` displays a determinate range whenever `total > 0`, and switches to indeterminate only for unknown/nonpositive totals.

**Evidence / problem:** `UI_UX_AUDIT.md` F-05 still says the app's progress range is explicitly `0, 0` and recommends adding determinate progress. That no longer describes the code. The stale test count in `docs/CURRENT_CONTEXT.md` has been updated to **319 passed, 10 skipped** during this work.

**Hypothesis tested:** These findings still describe the current application and test state.

**Test / measurement:** Compared the documented F-05 behavior with `main_window._on_worker_progress` and pipeline progress callbacks; ran the full suite with a repository-local pytest basetemp.

**Result:** F-05 remains stale; the documented test count is now current. The latest full suite passed: **319 passed, 10 skipped in 30.71 s**. Default pytest temp setup was blocked by Windows access to the profile temp directory; the isolated repository-local rerun succeeded.

**Recommended update:** In a separate documentation pass, mark F-05 as implemented/partially implemented and document what remains (e.g. progress is stage/work-count progress, not an ETA; some opaque operations may remain indeterminate). Keep this as documentation-only work.

**Expected benefit:** Avoids repeating completed UI work or presenting stale validation status as current. No runtime speed increase.

**Correctness / regression checks:** Confirm the docs distinguish determinate known-work progress from indeterminate opaque work; rerun the documented test command and ensure the reported count matches.

**Affected areas:** `UI_UX_AUDIT.md`, `docs/CURRENT_CONTEXT.md`.

## Hypotheses Requiring Validation

### Isolate the remaining long envelope/preparation intervals on the 117x50 workload

**Observation:** The historical log isolates source reads and per-voltage merge/calculation but leaves at least 407 s before Sustained result-save messages and about 120 s in analysis-data preparation. The current implementation has added more detailed stage timings, but those timings have not yet been collected on a fresh run of this workload.

**Hypothesis:** A currently hidden substage may still dominate enough time to justify a local optimization; the old timing gaps alone do not identify it.

**Proposed experiment:** Run the current version against a disposable copy of the same 117x50 project with the same scopes, voltages, exclusions, settings, and worker count. Retain all current timing logs. Repeat enough times to separate cold cache, warm run-data cache, and valid complete-envelope-manifest behavior; do not use the source project as a benchmark target.

**Metrics:** Stage wall time and call counts for source parsing, per-voltage calculation, consolidation, run-data serialization/SQLite commit, Sustained ranking/persistence, resonance workbook generation, RMS catalog/selection, plotting, reports, peak RSS, and cache size.

**Correctness checks:** Compare semantic outputs to a clean baseline: envelope values/rows/order, resonance and Sustained results, generated file list, and report/plot selection. Track source reads and cache hits so time savings are attributed to the correct stage.

**Acceptance criterion:** Only create an implementation item if a substage is a repeatable material share of end-to-end time (at least 5%), a minimal candidate improves end-to-end time, and all relevant outputs remain semantically identical. Keep worker count unchanged.

## No-Change Findings

- **Project scan cache:** Warm validation is already about 0.48 s on the recorded development project; force and section-refresh behavior are tested. No scan rewrite is supported by the large-project timing.
- **Source reads across voltage levels:** The reference measurement loaded 2,856 `.out` files for 2,856 unique paths; the shared raw-column prototype was 0.87% slower at one worker and retained about 1.98 GB temporarily. No duplicate-open optimization is justified for that input.
- **Envelope merge/reduction:** The test-only candidate was 18.9% slower on 300 source frames (12.9% slower on the 50-run slice) despite exact DataFrame equality. Keep the current path.
- **Cache-write batching:** The prototype was 6.7% slower on the 150-run reference and 14.6% slower on the 50-run slice, with identical SQLite size/payload digest. Keep the current write strategy.
- **Plot batching, workbook output, and reports:** Measured at below 1 s, 0.3–0.5 s per envelope workbook write, and about 14 s/report respectively. They are not first-order targets for a 31-minute cold run.
- **Plot worker policy:** Existing bounded parallel rendering and sequential recovery are appropriate; changing worker count is explicitly out of scope and unsupported by a demonstrated need.
- **Run-analysis stage boundaries:** Dashboard refresh is intentionally separate. Do not add it to the connected run or repeat unrelated analysis work as a speed “optimization.”
- **Output safety:** Plot/report generation uses cache/signature checks and staged output replacement. Existing tests cover failure, cancellation, and stale-output cleanup; no redesign is indicated.
- **Float32 cache safety:** The pre-update real-data comparison disproved semantic equivalence. The production float64 correction, version invalidation, tests, measured tradeoff, and current validation status are captured in P1.

## Removed / Rejected Hypotheses

| Hypothesis | Evidence | Conclusion |
|---|---|---|
| Read all voltages from a shared raw waveform-column cache to avoid repeated source reads. | Current reader made 2,856 loads for 2,856 unique `.out` files; prototype was 0.87% slower with ~1.98 GB temporary RAM (and about 0.94% slower / 629 MiB on the 50-run slice). | Reject this implementation for the measured workload. |
| Replace envelope merge/reduction with the tested alternative. | Exact output equality, but 18.9% slower on the 300-frame case and 12.9% slower on the 50-run slice. | Keep the current reducer. |
| Batch SQLite cache writes as tested. | Identical payload digest and file size; 6.7% slower for 150 runs and 14.6% slower for 50 runs. | Keep current cache writes. |
| Increase/tune worker count as the default speed fix. | User explicitly wants the current policy retained; the measured source/merge/write results do not establish worker count as the cause. | Out of scope; do not change. |
| Add a separate persistent Sustained/resonance result cache now. | With all three resonance checks enabled after float64 parity repair, the test-only cache improved a 150-run forced full-selection repeat by 15.9%, was 2.5% slower when switching from all three voltages to 161 kV, and improved the isolated 50-run case by 0.9%. Compressed payloads were 159 KiB and 5.9 KiB; persistent-store overhead was not measured. | Do not implement now. The useful result is limited to an uncommon forced repeat of identical inputs; the voltage-change scenario regressed and the 50-run case was flat. Reconsider only if representative logs show frequent forced full-selection rebuilds. |

## Validation record

- Full suite after result-cache benchmark-gate changes: `.conda/pscad-results-analysis/python.exe -m pytest -q --basetemp <repo>/.tmp/pytest-result-cache-verification-20260927` → **319 passed, 10 skipped, 30.71 s**; `python -m results_analysis_app --smoke` passed.
- Real-data cache parity: the pre-update warm float32 hit changed four workbooks (2,271 numeric and 155 nonnumeric/selection cells); the full-float64 prototype matched all six. The current production build then reused 450/450 entries and matched semantic contents across all three envelope workbooks. The focused resonance boundary regression also passes with production cache serialization.
- Full-precision real-data measurements: the controlled prototype comparison was 13.44 s warm vs 18.76 s uncached mean (**28.4%**) and 16.25 MB vs 10.69 MB (**+52.1%**). The production envelope-only check after both version bumps was 15.74 s cold vs 6.35 s warm (one sample), with exact semantic workbook content and 450/450 hits. These are different setups and not a forecast for the unavailable 117×50 workload.
- Focused boundary experiment: raw constant `100.000001 kV` with `Vlim=100 kV` → **1** `Post_Event_Stress` finding; the old float32 round-trip (`100.0 kV`) → **0**. The new production-cache regression confirms the float64 round-trip retains the finding and its metrics exactly.
- Result-cache re-test after float64 parity repair, using all three resonance checks shown enabled in the screenshot: 150-run repeated full selection **13.115 s → 11.036 s median (+15.9%)**; switch from all three voltages to 161 kV **4.148 s → 4.251 s (-2.5%)**; isolated 50-run 161-kV case **2.550 s → 2.527 s (+0.9%)**. Cold/current/candidate semantic output comparisons passed. The prototype is in-memory only, so persistent I/O/index overhead remains unmeasured; recommendation is not to implement it now because the gain is limited to repeated identical full selections.
- Shared-reader, merge, and cache-write candidate timings in `docs/PERFORMANCE_AUDIT.md` were previously measured and reviewed but not rerun during this audit.
- Graphify was used to navigate the code and documentation. Its checked-in graph was older than the current source, so graph results were treated as orientation only; all reported behavior was checked against current source, tests, and project documentation.
