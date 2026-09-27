# Performance audit

## Scope

This audit uses the run log supplied on 2026-09-26 and the current analysis path in:

- `src/results_analysis_app/actions.py`
- `src/results_analysis_app/voltage_envelope.py`
- `src/results_analysis_app/sustained_sdpf.py`
- `src/results_analysis_app/analysis_engine.py`
- `src/results_analysis_app/envelope_data_cache.py`

The successful run started at `12:52:31`, finished at `13:23:50`, and therefore took
approximately **1,879 seconds (31 minutes 19 seconds)**. The preceding run-data cache
was cold: `0/17,550` valid run records were reused.

## What takes the longest

| Stage | Observed timing | Finding |
| --- | ---: | --- |
| Project scan cache check | about 8 s | Not a useful optimization target for this workload. |
| `O2_Active_faults` envelope build | 1,525 s | Dominant stage. It contains source reads, resonance/Sustained calculations, envelope reduction, workbook creation, and chart refresh. |
| Unlabelled preparation after envelope build | about 120 s | The envelope total was logged at `13:17:56`; plot-batch creation did not start until `13:19:56`. This is the main instrumentation gap. |
| `O2_Active_faults` source reads | about 477 s wall time | Three voltage reads ran concurrently; each processed 5,850 runs, for 17,550 voltage-run reads. |
| `O2_Active_faults` envelope merge/calculation | 250–324 s per voltage | The workbook write itself was only 0.3–0.5 s. The expensive part is calculation before the write. |
| Post-voltage consolidation and cache persistence | at least 407 s before the first Sustained result-save message | The current code writes the cold run-data cache after voltage workers finish, so this interval may be dominated by compressed cache writes. It is not yet isolated from in-memory consolidation. |
| Sustained summary/rank/workbook phase | about 213 s from the first result-save message to the ranked-summary/resonance-workbook messages | The current log does not isolate JSON serialization, ranked-summary generation, and resonance workbook generation. |
| Plot-batch creation | below 1 s in the largest project | Not a target. |
| Plot rendering | about 39 s in the largest project | Worth monitoring, but much smaller than envelope work. |
| Report generation | about 14 s per project | Not a target for the full-run slowdown. |

The three smaller projects completed envelope builds in approximately 57 s, 37 s, and
37 s. The full run is therefore dominated by the 117-case / 50-run project, not by the
number of output reports or dashboard figures.

## Code-level explanation

The current implementation makes one `_read_voltage_runs` pass for each selected
voltage. Each pass submits one worker task per `.inf` file to the shared process pool.
For the large project this means 5,850 tasks for each of 66 kV, 161 kV, and 230 kV.
The same run folders are consequently traversed once per voltage, although the output
files can contain data for multiple voltage buses.

After the reads, `_build_voltage_workbooks` flattens the run data and performs:

1. resonance record extraction and checks;
2. Sustained SDPF candidate reconstruction;
3. `_final_envelope`, including `_reduce_merge` sorting/reduction;
4. the small workbook write.

The log's `merge+write=250–324 s` versus `write=0.3–0.5 s` is strong evidence that
Excel file writing is not the bottleneck. The reduction/check calculations, compressed
cache persistence, and the objects passed between worker processes are the important
targets.

## Existing cache impact

The project-specific incremental run-data cache is present in the current working tree.
It is keyed by the project, voltage, run-file identity, source-file signature, and the
calculation settings that affect derived run data. A changed `.inf`/`.out` source or a
changed calculation setting makes that entry invalid; changing a scope or bus exclusion
can reuse the source-independent run data and apply the new filter during the merge.

The supplied run was cold, so it does not measure the warm-cache benefit. The cache can
remove the waveform-reading and worker-side derived-data work, but it does not remove
the final scope-specific merge, resonance checks, envelope reduction, or report
presentation work. That is why a warm run must be benchmarked separately rather than
assuming the whole application becomes proportionally faster.

The automated integration test `test_warm_envelope_build_is_faster_and_keeps_outputs_equivalent`
in `tests/test_envelope_data_cache.py` now exercises the real envelope-build orchestration
with a controlled source-read delay. It verifies that the first build reads the source
once, the warm build reads it zero times, and both builds produce byte-identical workbook
output. On the validation run it measured `0.177 s` cold versus `0.018 s` warm, or a
`90.0%` reduction for the simulated source-read portion. This is a deterministic cache
correctness/plumbing test, not a forecast for the full 117x50 project: the remaining
merge, Sustained, resonance, and presentation work is intentionally still included in
the orchestration but is not made artificially expensive by the fixture.

## Real-project candidate measurements

The proposed updates were tested against disposable overlays of
`Original_examples/03_Test_project_case`, without modifying the 53 GB source tree.
The project contains three populated case folders, 150 `.inf` runs, 12,837 `.out`
files, and the 66/161/230 kV voltage configurations. The same tests also used the
50-run `O2_P1_S1_161ONT.if18` case as an isolated slice. Candidate code was test-only;
no production optimization was enabled by these measurements.

The full-project results were:

| Candidate | Real measurement | Correctness / cost | Decision |
| --- | ---: | --- | --- |
| Current multi-voltage reader | 52.47 s source-read stage; 2,856 load calls for 2,856 unique `.out` files | 0% avoidable file reopenings | Do not replace solely to remove duplicate I/O. |
| Shared raw-column reader prototype | 47.12 s versus 46.72 s at the same one-worker setting (**-0.87%**) | Exact run-data digest; 1.98 GB temporary RAM | Do not implement. |
| Merge/reduction prototype | 0.0565 s versus 0.0476 s for 300 source frames (**-18.9%**) | Exact `DataFrame` equality | Do not implement this algorithm. |
| Batched cache-write prototype | 0.220 s versus 0.206 s for 150 rows (**-6.7%**) | Exact SQLite payload digest; cache size unchanged at 1,417,216 bytes | Do not implement this batching variant. |
| Separate resonance-result cache, repeated full selection | 7.757 s versus 9.133 s (**+15.1%**) | Exact warm output content; 5,821 compressed bytes for three voltage entries | Promising but conditional. |
| Separate Sustained-result cache, repeated full selection | 13.117 s versus 15.769 s (**+16.8%**) | Exact warm output content; 154,905 compressed bytes (about 151 KB) for three voltage entries | Promising but conditional. |
| Resonance-result cache after changing 66/161/230 to 161 kV | 3.261 s versus 3.464 s (**+5.8%**) | Two result-cache hits; exact output content | This is the most realistic positive case. |

The isolated 50-run case showed the same direction: the shared reader was **0.94%
slower** while retaining about **629 MiB** temporarily, the merge prototype was
**12.9% slower**, and the cache-write prototype was **14.6% slower**. The resonance
result-cache prototype measured **9.6% faster** for repeated result-stage builds.

The result-cache percentages are not a claim that every normal build becomes that much
faster. An unchanged build already uses the existing envelope manifest and skips the
whole envelope stage. The result cache matters only when the envelope is rebuilt while
some Sustained/resonance inputs remain reusable—for example, retaining a voltage result
after the selected-voltage set changes, or regenerating outputs after a cache-manifest
loss. The benchmark invalidates only the envelope-output manifest to expose that
specific opportunity while keeping the existing run-data cache warm.

The existing run-data cache stores the derived time and `Max_*` arrays as `float32`, so
cold-source versus warm-cache workbook files can contain small floating-point
serialization differences. The observed worst-case cast error at a 1,000 kV scale was
about `0.00003 kV`, and the final envelope workbook rounds maxima to `0.1 kV`. A
representative compressed array measured about 742 KB as `float32` versus 1.53 MB as
`float64`. The compact representation is therefore retained; `float64` would be a
roughly 2x cache-size increase without a measured engineering-output benefit. The
candidate comparison uses the first warm current build as the reference; the candidate
itself adds no additional difference. Changed-input invalidation is tested separately by
`test_serialized_result_cache_roundtrip_and_invalidation`.

## Speed-up opportunities

| Opportunity | Expected value | Risk / required proof |
| --- | --- | --- |
| Re-run unchanged project with the incremental cache warm | High confidence, lowest implementation risk | Measure cold versus warm wall time and cache read time. Verify byte-level or numeric equivalence of generated result tables. |
| Read each source run once and extract all selected voltages in one pass | No measured duplicate-I/O opportunity in the supplied project | The full project made 2,856 unique loads for 2,856 unique `.out` files. The tested shared-column prototype was 0.87% slower and used 1.98 GB temporary RAM. Do not implement without a different workload showing repeated files. |
| Optimize `_reduce_merge` allocations and sorting | No evidence for the tested rewrite | The exact-output prototype was 18.9% slower on 300 real source frames and 12.9% slower on the 50-run slice. Keep the current implementation. |
| Change process-pool size | Out of scope | The current worker strategy is retained; no worker-count update is planned. |
| Isolate cache persistence, Sustained SDPF persistence, and ranking | Result cache is the only positive candidate measured so far | A separate serialized Sustained/resonance result cache saved 15.1–16.8% in forced recalculation tests, and 5.8% when changing the selected voltage set. It also costs about 5.8 KB for resonance or 151 KB for the tested Sustained payload. Implement only with complete source/settings/scope/voltage signatures and an explicit invalidation policy. |
| Reduce repeated fallback/log UI updates | Low to medium | The log contains many repeated frequency-fallback messages. Coalescing them may improve UI responsiveness, but it will not explain the 25-minute calculation stage and should be treated separately. |

Excel autofit, chart creation, plot-batch creation, and report generation should not be
optimized first for this workload. Their measured times are too small to produce a
meaningful full-run improvement.

## Instrumentation added for the next benchmark

The pipeline now emits progress and timing boundaries for:

- envelope source-file progress and per-voltage merge progress;
- the analysis-data preparation gap after envelope generation;
- RMS/plotter catalog preparation;
- Sustained result loading and cache validation;
- envelope run-data cache writes, Sustained JSON/summary persistence, and resonance workbook writing;
- plot-batch creation and plot rendering.

This keeps the progress range stable while allowing the UI to move during a long source
read or merge stage instead of remaining at one stage number for many minutes.

## Benchmark required before an optimization claim

Use the same machine, copied project, selected scopes, selected voltages, settings, and
worker count. Run each candidate at least three times after one warm-up. Record median
wall time, peak memory, cache size, and the detailed stage timings. Use:

```text
speed-up (%) = (baseline_seconds - candidate_seconds) / baseline_seconds * 100
```

The supplied log alone was sufficient to identify the bottleneck, but not to claim a
candidate percentage. The disposable real-project measurements above now provide that
evidence for the tested prototypes, using the same scopes, voltages, settings, worker
count, and output-equivalence checks. They show that the reader, merge, and write
variants should not be promoted; only the separate result-cache idea has a positive,
workflow-dependent signal.

The opt-in real-project test is `test_warm_envelope_cache_benchmark` in
`tests/test_performance_benchmark.py`. It requires a disposable copy with no envelope
manifest or run-data cache and runs the actual envelope build once cold, then several
warm builds with a different full-scope name. The changed name prevents the complete
envelope manifest from short-circuiting the test, while the per-run cache remains
reusable. It compares output file SHA-256 digests and reports the cold time, warm median,
cache-hit log messages, and median speed-up. Example PowerShell setup:

```powershell
$env:PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT = 'D:\\Bench\\Project-copy'
$env:PSCAD_RESULTS_ANALYSIS_RUN_ENVELOPE_CACHE_BENCHMARK = '1'
& '.conda\\pscad-results-analysis\\python.exe' -m pytest tests/test_performance_benchmark.py -q -s
```

Do not point this test at the working production project: the cold run writes the normal
derived envelope outputs and cache into the supplied copy.

The other candidate updates are now measured separately, without changing production
behavior first:

- `test_multivoltage_source_read_opportunity_benchmark` measures the current reader's
  elapsed time and counts repeated `.out` file loads across voltage levels. This gives a
  measured lower-bound opportunity before implementing a one-pass multi-voltage reader;
  it does not pretend that reader exists yet.
- `test_shared_multivoltage_reader_benchmark` adds a test-only cross-voltage raw-column
  cache on top of the current reader. It requires identical semantic run-data digests
  and reports the I/O-only speed-up plus the number of retained raw columns, making the
  temporary-RAM tradeoff visible before changing production code.
- `test_reduce_merge_candidate_benchmark` compares the current `_reduce_merge` with a
  test-only candidate and requires exact `DataFrame` equality before reporting timing.
- `test_cache_write_strategy_benchmark` compares current per-row cache writes with a
  one-transaction batched SQL prototype and requires identical payload counts and
  digests; it also reports the SQLite file-size delta, so a write optimization is not
  accepted if it makes the compact cache materially larger.
- `test_separate_result_cache_benchmark` runs the real envelope build with the
  requested Sustained and/or resonance settings, then compares the current repeated
  result-stage calculations with a test-only compressed serialized-result cache. It
  requires identical output sets and semantic JSON/XLSX cell content for every warm
  comparison, and reports current versus cache-hit stage timings, cache hits/misses,
  raw serialized bytes, and compressed payload bytes. The prototype includes result
  serialization and deserialization, but not a final SQLite/index/transaction format,
  so the reported bytes are a sizing measurement rather than a promise of final disk
  usage.
- `test_separate_result_cache_voltage_selection_benchmark` repeats the same experiment
  after changing the selected voltage set (66/161/230 to 161 kV), which tests the
  practical reuse case rather than only repeated identical builds.
- The real cache benchmark records source-read, merge, cache-write, Sustained, resonance,
  and total envelope timings for both cold and warm runs, so a cache-write or
  post-voltage-consolidation regression is visible rather than hidden in one total.

These candidate benchmarks are opt-in because they execute against real PSCAD data and
may take many minutes. They are intentionally measurement-only: a candidate should be
implemented only after its baseline result, output-equivalence contract, and expected
benefit are recorded.

For the separate-result-cache experiment, provide the exact settings used by the app.
The values may be inline JSON or `@path-to-json-file`:

```powershell
$env:PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT = 'D:\Bench\Project-copy'
$env:PSCAD_RESULTS_ANALYSIS_RUN_RESULT_CACHE_BENCHMARK = '1'
$env:PSCAD_RESULTS_ANALYSIS_RESONANCE_SETTINGS_JSON = '{"enabled_checks":["Post_Event_Stress"]}'
$env:PSCAD_RESULTS_ANALYSIS_SUSTAINED_SETTINGS_JSON = '{"enabled":true,"duration_ms":30}'
$env:PSCAD_RESULTS_ANALYSIS_EVENT_TIMES_JSON = '{"SFO":0.004,"TOV":0.03}'
& '.conda\pscad-results-analysis\python.exe' -m pytest tests/test_performance_candidates.py -q -s
```

To measure reuse after changing the selected voltage set, use the same settings and
replace the opt-in flag with:

```powershell
$env:PSCAD_RESULTS_ANALYSIS_RUN_RESULT_CACHE_SELECTION_BENCHMARK = '1'
$env:PSCAD_RESULTS_ANALYSIS_BENCHMARK_VOLTAGES = '66,161,230'
$env:PSCAD_RESULTS_ANALYSIS_RESULT_CACHE_COMPARISON_VOLTAGES = '161'
& '.conda\pscad-results-analysis\python.exe' -m pytest 'tests/test_performance_candidates.py::test_separate_result_cache_voltage_selection_benchmark' -q -s
```

The candidate test deliberately does not require the cache-hit percentage to be
positive. A negative result is useful evidence that serialization, invalidation, or
remaining workbook work costs more than the avoided analysis, and is a reason not to
implement the update.
