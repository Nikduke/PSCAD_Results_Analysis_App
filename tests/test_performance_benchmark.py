from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import time

import pytest


def _render_cached_plots(project_root: Path) -> None:
    from results_analysis_app import analysis_engine
    from results_analysis_app.models import ScopeEntry

    analysis_engine.render_plot_batches(
        project_root,
        [ScopeEntry.full()],
        ["SFO", "TOV", "SA"],
        excel_waveform_exports_enabled=True,
    )


def _measure_cached_plots(project_root: Path, repetitions: int) -> dict[str, object]:
    _render_cached_plots(project_root)
    samples: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        _render_cached_plots(project_root)
        samples.append(time.perf_counter() - started)
    return {
        "samples_s": samples,
        "median_s": statistics.median(samples),
        "mean_s": statistics.fmean(samples),
        "min_s": min(samples),
        "max_s": max(samples),
    }


def benchmark_warm_plot_render(project_root: Path, repetitions: int = 5) -> dict[str, object]:
    """Compare cache-hit plot validation with and without source reuse.

    The caller supplies an isolated, writable project fixture. The first render
    is a warm-up so the reported samples measure repeated cache validation rather
    than initial output creation. The legacy run disables only the new
    source-manifest reuse, making the comparison an A/B measurement of this
    update rather than a comparison against a different fixture or machine.
    """
    from results_analysis_app import analysis_engine

    updated = _measure_cached_plots(project_root, repetitions)
    original_matches = analysis_engine._plot_manifest_matches

    def legacy_matches(plan, renderer, _source_manifest_cache=None):
        return original_matches(plan, renderer)

    analysis_engine._plot_manifest_matches = legacy_matches
    try:
        legacy = _measure_cached_plots(project_root, repetitions)
    finally:
        analysis_engine._plot_manifest_matches = original_matches

    legacy_median = float(legacy["median_s"])
    updated_median = float(updated["median_s"])
    return {
        "updated": updated,
        "legacy_without_reuse": legacy,
        "median_speedup_percent": (
            (legacy_median - updated_median) / legacy_median * 100.0
            if legacy_median
            else 0.0
        ),
    }


@pytest.mark.skipif(
    not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason="set PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the real-project benchmark",
)
def test_warm_plot_render_benchmark() -> None:
    project_root = Path(os.environ["PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"]).resolve()
    assert (project_root / "Case_folder").is_dir()
    repetitions = max(1, int(os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_REPETITIONS", "5")))
    result = benchmark_warm_plot_render(project_root, repetitions)
    for key in ("updated", "legacy_without_reuse"):
        samples = result[key]["samples_s"]
        assert samples
        assert all(math.isfinite(value) and value >= 0 for value in samples)
    assert float(result["median_speedup_percent"]) > 0.0
    print(json.dumps(result, indent=2))
