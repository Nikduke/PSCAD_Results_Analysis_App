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

The isolated 50-run case showed the same direction: the shared reader was **0.94%
slower** while retaining about **629 MiB** temporarily, the merge prototype was
**12.9% slower**, and the cache-write prototype was **14.6% slower**.

### Separate Sustained/resonance result-cache re-test

After the run-data cache was corrected to float64, the test-only compressed result cache
was remeasured on fresh disposable overlays. Each timing is the median of three forced
warm rebuilds; the benchmark includes key serialization, compression, decompression,
and deserialization, but uses an in-memory store rather than a production SQLite cache.
The same settings were used in all three cases, matching the checked analysis options in
the screenshot: `Post_Event_Stress`, `Late_Growth`, and `No_Settle_Growth` enabled;
Sustained enabled with a 30 ms duration; and event times `SFO=0.004 s` / `TOV=0.03 s`.
The test covers the envelope/resonance/Sustained stages, not the separate RMS catalog,
plotting, or report stages.

| Scenario | Current result-stage rebuild | With result-cache hits | Measured change | Compressed payload |
| --- | ---: | ---: | ---: | ---: |
| 150-run example, 66/161/230 kV repeated | 13.115 s median | 11.036 s median | **15.9% faster** (2.079 s) | 162,641 bytes (about 159 KiB) |
| Same example, cache primed on all voltages then rebuild only 161 kV | 4.148 s median | 4.251 s median | **2.5% slower** (+0.103 s) | Same three-voltage cache: 162,641 bytes |
| Isolated 50-run `O2_P1_S1_161ONT.if18`, 161 kV | 2.550 s median | 2.527 s median | **0.9% faster** (0.024 s) | 6,047 bytes (about 5.9 KiB) |

The cold output was compared semantically with the current warm baseline when the
voltage selection matched; all candidate outputs also matched their current-build
baseline. The voltage-change case matched the 161-kV current baseline. The small 50-run
example produced no resonance rows, so its measured payload there was almost entirely
Sustained data. A unit test also confirms that changing source-derived record values,
resonance settings, event time, or scope produces a cache miss.

The test-only cache fill took 13.406 s on the 150-run all-check scenario, versus the
current warm-build median of 13.115 s; subsequent repeated full-selection hits measured
15.9% faster. But narrowing the voltage selection with the same checks was 2.5% slower,
and the isolated 50-run case gained only 0.9%. The earlier 24.7% signal is superseded:
it was measured before the run-data cold/warm precision discrepancy was resolved.

The cache does not accelerate a first cold build; an unchanged project already skips the
whole envelope stage through its current manifest; and changed inputs/settings generally
produce a cache miss. The useful case is a forced repeat of a full, unchanged selection,
which appears uncommon in normal use. The measured stage timings do not support applying
the 15.9% to the full app or to the unavailable 117×50 project. The compressed sizes are
payload estimates only: a persistent database/index, disk I/O, peak-memory impact, and
full invalidation/recovery behavior are not implemented or measured. **Do not add this
cache now**; revisit only if real workflow logs show repeated forced full-selection
rebuilds and Sustained/resonance remains a dominant cost.

### Run-data cache precision and real-data parity

A semantic cold/warm comparison was run through the real envelope builder on a
disposable overlay of the available 150-run example project (three voltage levels, 450
run-voltage cache entries, all three resonance checks enabled, Sustained SDPF enabled).
Two uncached builds and the first cache-populating build matched exactly. A subsequent
450/450 warm hit in the current float32 format changed four files: the three voltage
envelope workbooks and `Resonance_Checks.xlsx`. The diff contained 2,271 numeric cells
and 155 selection/text cells; for example, an `MM_161.xlsx` `Run_C` selection changed
from 34 to 32, and an `MM_230.xlsx` `MM_name_B` changed from `MM_230_ONC1` to
`MM_230_ONS1`. This is an actual correctness issue, not only an inconsequential
floating-point serialization difference.

A test-only full-float64 encoder produced exact semantic parity across all six output
workbooks. The production encoder now uses that representation. On this 150-run
reference, the prototype's warm build took **13.44 s** versus **18.76 s**
mean for two uncached builds (**28.4% faster** for this forced envelope-stage rebuild).
The cache-populating build took **23.47 s** in that sample, reflecting the one-time
serialization/write cost. The SQLite file was **16,248,832 bytes (15.50 MiB)** versus
**10,686,080 bytes (10.19 MiB)** for float32: **+5.56 MB (+52.1%)**, not a 2× increase
to the whole cache.

A partial variant with float64 `Max_*` values but a float32 time index still changed
759 numeric cells in `Resonance_Checks.xlsx` (maximum absolute delta about
`1.06e-6`); it used **15,237,120 bytes**. Exact parity in this test required preserving
both cached values and time as float64. After both production version bumps, a fresh
disposable overlay of the same 150-run example completed a cold/warm comparison: the
cold build took **15.74 s**, the warm build **6.35 s**, and all **450/450** run-voltage
entries were reused. Semantic cell comparison matched all three voltage-envelope
workbooks. This was one envelope-only cold/warm sample with Excel AutoFit excluded; it
is not directly comparable to the earlier six-workbook/28.4% test and is not a precise
speed estimate.
A rough linear cache-size extrapolation to
5,850 runs and three voltages is **about 397 MiB float32 versus 604 MiB float64**
(about **207 MiB extra**), assuming similar signal density and run length. This is a
rough sizing only; workload storage and speed are not claimed from this extrapolation.

The one-pass reader, merge/reduction, and batched SQLite write prototypes remain
negative as shown above. The production float64 correction versions the run-data
signature, and the real-example warm-cache comparison matched semantic envelope
workbook contents. A separate synthetic resonance threshold regression also confirms
that a value just above Vlim remains above Vlim after a cache round-trip. The separate
Sustained/resonance result-cache candidate was then remeasured against this corrected
baseline; the 15.9% repeated full-selection gain is conditional, while the voltage-change
case regressed and the isolated 50-run case was nearly flat. This does not justify a
production cache for the current workflow.

## Speed-up opportunities

| Opportunity | Expected value | Risk / required proof |
| --- | --- | --- |
| Rebuild with a warm run-data cache | The production float64 cache preserved semantic output on the 150-run reference; one envelope-only cold/warm sample was 59.7% faster (15.74 s → 6.35 s). An earlier full-check prototype was 28.4% faster. | Budget about +52% whole-cache storage on the controlled reference; both percentages are workload/sample-specific, not forecasts for 117×50. An unchanged project already skips the whole stage. |
| Read each source run once and extract all selected voltages in one pass | No measured duplicate-I/O opportunity in the supplied project | The full project made 2,856 unique loads for 2,856 unique `.out` files. The tested shared-column prototype was 0.87% slower and used 1.98 GB temporary RAM. Do not implement without a different workload showing repeated files. |
| Optimize `_reduce_merge` allocations and sorting | No evidence for the tested rewrite | The exact-output prototype was 18.9% slower on 300 real source frames and 12.9% slower on the 50-run slice. Keep the current implementation. |
| Change process-pool size | Out of scope | The current worker strategy is retained; no worker-count update is planned. |
| Add a separate Sustained/resonance result cache | With all three resonance checks enabled, the 150-run full-selection forced repeat improved 15.9%; switching to 161 kV was 2.5% slower, and the isolated 50-run case improved 0.9%. | Only a test-only in-memory cache was benchmarked; its 159 KiB / 5.9 KiB compressed payloads omit persistent-store overhead. The benefit is limited to an uncommon repeated full selection; do not add production invalidation/storage complexity now. |
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

The supplied log identifies the bottleneck but cannot predict a speedup on a different
project. The disposable real-project measurements reject the tested reader, merge, and
write variants. The float64 cache prototype is the only measured update that both
improves a forced warm rebuild and preserves exact outputs on the available example;
it trades increased disk use and first-build serialization time for later source-read
savings. The 117×50 project must be benchmarked before claiming its percentage. The
separate result-cache candidate was revalidated on the corrected float64 baseline; its
15.9% full-selection repeat gain is not representative of normal runs, while selection
changes were slower and the isolated 50-run case was nearly flat. Do not implement it
at this point.

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
  comparison, and compares cold and warm output when their voltage selections match.
  It reports current versus cache-hit stage timings, cache hits/misses, raw serialized
  bytes, and compressed payload bytes. The prototype includes result serialization and
  deserialization, but not a final SQLite/index/transaction format, so the reported
  bytes are a sizing measurement rather than a promise of final disk usage.
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

## Follow-up profiling on the available 150-run example (2026-09-27)

The 150-run example was profiled with all three voltage levels, all three resonance
checks, and Sustained SDPF enabled at 30 ms. Candidate measurements ran against a
disposable overlay; no application implementation was changed. Function profiling was
used to find hotspots, followed by repeated unprofiled A/B timings so profiler overhead
did not become the reported speed-up.

| Candidate | Measured result | Correctness and cost | Decision |
| --- | ---: | --- | --- |
| Reuse the immutable body `Font(name="Arial")` in Sustained summary worksheets | Summary-writer median: 2.2 s → 1.2 s (**45.5% faster**). Entire forced-warm envelope build: 12.459 s → 11.322 s (**9.1% faster**). | Workbook values and styles matched exactly. No persistent cache, disk, or calculation-precision change. openpyxl documents that assigned cell styles are shared and immutable, so reusing this font is supported by its model ([styles documentation](https://openpyxl.readthedocs.io/en/3.1/styles.html)). | Best candidate for a later small update. |
| Memoize repeated path normalization while compacting Sustained signatures | 1.359 s → 0.775 s (**43.0% faster**) for 38,970 entries (12,990 repeated source paths across three voltages). | Exact compact-signature equality. About 0.584 s saved per 150-run build; uses short-lived path metadata in memory, with no persistent disk cost. | Valid but secondary; implement only if the small linear-scale gain is worth the extra code. |
| Use `os.scandir` metadata while validating the Sustained source manifest | 0.542 s → 0.161 s (**70.3% faster**) for 12,990 source files. | Exact file inventory, size/mtime entries, and fingerprint; current-file metadata is still checked, so this does not weaken freshness validation. No disk cost. Python documents that `DirEntry` exposes directory metadata and caches stat results ([`os.scandir`](https://docs.python.org/3.11/library/os.html#os.scandir)). | Valid, low-risk, but small absolute saving. |
| Replace pandas rolling p95 with a NumPy sliding-window quantile | Current median 0.594 s versus 21.254 s (**35.8× slower**) across 4,160 records. | 1,026/4,160 arrays differed bitwise (maximum absolute delta `5.68e-14`). No full build was run for a slower, non-identical candidate. | Reject; keep pandas implementation. |
| Lower run-data cache DEFLATE level to 1 | Cache-write median 1.955 s → 1.805 s (**7.7% faster**) for 450 rows. | SQLite cache increased 4.21% (16,236,544 → 16,920,576 bytes); exact payload round-trip. Linear scaling suggests only about 6 s saved at 17,550 rows, with about 4.2% more cache disk use. | Reject for the compact-cache requirement. Keep float64; this is not a reason to trade away the precision already required for exact selections. |
| Add a separate Sustained/resonance result cache | Latest 150-run forced-repeat median: 17.705 s → 15.898 s (**10.2% faster**); prior run measured 15.9%, showing timing variability. | The test-only compressed payload was about 163 KB; cache fill was about 14.3 s. It does not help a cold first build, and selection-change/small-case tests were flat or slower. | Do not add persistent cache complexity for the current workflow. |

### Quantified hypothesis for 117 cases × 50 runs

The sample contains 150 runs, a 39:1 run-count ratio to 5,850 runs. If the three
positive microbenchmarks above scale linearly with source/run count, their illustrative
savings are about 39 s for summary writing, 23 s for signature compaction, and 15 s for
manifest validation: roughly **77 s (4.1%)** of the historical 1,879 s application
runtime. This is a testable hypothesis, not a forecast: row density, storage behavior,
and per-case overhead may differ on the larger project. These candidates add no
persistent cache data; transient memory for the path memo was not measured.

The old **407 s pre-save interval is not explained by cache writes alone**: the sample's
450-row cold cache write took about 4.6 s, or about 179 s under simple 39:1 scaling.
Likewise, the **213 s result-save-to-summary interval** has not been reproduced on the
large workload. The summary-font change is the only positive candidate directly aimed
at its workbook portion.

The historical **120 s post-envelope preparation gap** also remains unresolved. On the
sample, plotter-catalog loading took 0.217 s cold / 0.077 s warm, legacy selection took
0.021 s, and Real RMS enrichment took 1.946 s for 12 selected rows from 12 source runs.
Those sample measurements do not account for 120 s. The manifest-scan prototype would
save about 15 s under linear scaling, so updated stage logs from that workload are still
needed to identify the remainder. Do not bypass the source freshness check to claim a
larger gain.

Python's documentation distinguishes profiling from timing; this audit used the
profiler to locate call costs and repeated wall-clock comparisons for candidate timing
([profilers](https://docs.python.org/3.10/library/profile.html),
[`timeit`](https://docs.python.org/3.10/library/timeit.html)).
