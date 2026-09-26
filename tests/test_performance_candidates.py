from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import time
from types import SimpleNamespace

import pytest


def _measure(operation, repetitions: int) -> dict[str, object]:
    operation()
    samples: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        operation()
        samples.append(time.perf_counter() - started)
    return {
        "samples_s": samples,
        "median_s": statistics.median(samples),
        "mean_s": statistics.fmean(samples),
        "min_s": min(samples),
        "max_s": max(samples),
    }


def _render_cached_plots(project_root: Path) -> None:
    from results_analysis_app import analysis_engine
    from results_analysis_app.models import ScopeEntry

    analysis_engine.render_plot_batches(
        project_root,
        [ScopeEntry.full()],
        ["SFO", "TOV", "SA"],
        excel_waveform_exports_enabled=True,
    )


def _lazy_plotter_session(
    project_root: Path,
    log=None,
    check_cancel=None,
    catalog_context=None,
):
    """Return the current plotter context without constructing render objects.

    This is a benchmark double for the proposed lazy-session update.  It keeps
    catalog, limits, and run-index work identical to production, while the
    cached-plot path receives only the renderer attribute it needs for
    validation.  A real implementation must construct the renderer/exporter
    if any plot is not cached.
    """
    from pscad_plotter_app_v3.services.limits import LimitService
    from results_analysis_app import analysis_engine

    context_data = catalog_context or analysis_engine.load_plotter_catalog(
        project_root,
        log,
        check_cancel,
    )
    limits = LimitService().load_effective_limits(context_data.context)
    renderer = SimpleNamespace(run_index=context_data.run_index)
    return context_data.catalog, limits, renderer, None


def benchmark_lazy_plotter_session(
    project_root: Path,
    repetitions: int = 5,
) -> dict[str, object]:
    """Compare current warm plot validation with a lazy-session simulation."""
    from results_analysis_app import analysis_engine

    current = _measure(lambda: _render_cached_plots(project_root), repetitions)
    original_loader = analysis_engine._load_embedded_plotter_session
    analysis_engine._load_embedded_plotter_session = _lazy_plotter_session
    try:
        lazy = _measure(lambda: _render_cached_plots(project_root), repetitions)
    finally:
        analysis_engine._load_embedded_plotter_session = original_loader

    current_median = float(current["median_s"])
    lazy_median = float(lazy["median_s"])
    return {
        "current": current,
        "lazy_session_simulation": lazy,
        "median_speedup_percent": (
            (current_median - lazy_median) / current_median * 100.0
            if current_median
            else 0.0
        ),
    }


def _single_run_scope(project_root: Path):
    from results_analysis_app import voltage_envelope
    from results_analysis_app.models import ScopeEntry

    inventory = voltage_envelope._inf_inventory(project_root / "Case_folder")
    if not inventory:
        raise AssertionError("benchmark project has no valid .inf files")
    scope = ScopeEntry(
        name=f"Single run {inventory[0].stem}",
        mode="include",
        tokens=[inventory[0].stem],
    )
    selected = voltage_envelope._selected_inf_paths(inventory, scope)
    if len(selected) != 1:
        raise AssertionError(
            f"single-run benchmark scope selected {len(selected)} .inf files"
        )
    return scope, len(inventory)


def _measure_envelope_source_read(
    project_root: Path,
    inf_paths: list[Path],
    voltages: list[str],
    repetitions: int,
    workers: int | None,
) -> dict[str, object]:
    from results_analysis_app import project_config, voltage_envelope
    from results_analysis_app.exclusions import ExclusionMatcher

    worker_count = workers or voltage_envelope._automatic_worker_count()
    configs = project_config.load_voltage_configs(project_root)
    timing = project_config.load_project_timing(project_root)
    time_end = timing.final_duration or voltage_envelope.TIME_END
    fallback_frequency = timing.frequency or voltage_envelope.DEFAULT_ENVELOPE_FALLBACK_FREQUENCY
    descriptor_cache = voltage_envelope._read_inf_descriptor_cache(
        inf_paths,
        worker_count,
        None,
    )
    matcher = ExclusionMatcher()

    def read_source_runs() -> None:
        for voltage in voltages:
            config = configs.get(voltage)
            if config is None:
                continue
            voltage_envelope._read_voltage_runs(
                inf_paths,
                voltage,
                config.bus_prefix,
                config.um,
                matcher,
                worker_count,
                None,
                None,
                time_step=voltage_envelope.TIME_STEP,
                time_end=time_end,
                fallback_frequency=fallback_frequency,
                inf_descriptor_cache=descriptor_cache,
                process_pool=False,
            )

    return _measure(read_source_runs, repetitions)


def benchmark_incremental_envelope_opportunity(
    project_root: Path,
    repetitions: int = 2,
    voltages: list[str] | None = None,
    workers: int | None = None,
) -> dict[str, object]:
    """Measure full source read versus one-run source read as a cache proxy.

    The current application has no per-run cache, so this does not claim an
    implemented speedup.  It measures the waveform/envelope work that a future
    cache would need to preserve for one changed run, after descriptor setup.
    """
    from results_analysis_app import voltage_envelope

    selected_voltages = voltages or ["66", "161", "230"]
    single_scope, inf_count = _single_run_scope(project_root)
    inventory = voltage_envelope._inf_inventory(project_root / "Case_folder")
    single_paths = voltage_envelope._selected_inf_paths(inventory, single_scope)
    full = _measure_envelope_source_read(
        project_root,
        inventory,
        selected_voltages,
        repetitions,
        workers,
    )
    single = _measure_envelope_source_read(
        project_root,
        single_paths,
        selected_voltages,
        repetitions,
        workers,
    )
    full_median = float(full["median_s"])
    single_median = float(single["median_s"])
    return {
        "inf_count": inf_count,
        "selected_voltages": selected_voltages,
        "full_source_read": full,
        "single_run_source_read": single,
        "estimated_avoidable_fraction_percent": (
            (full_median - single_median) / full_median * 100.0
            if full_median
            else 0.0
        ),
    }


def _benchmark_project() -> Path:
    raw_path = os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT")
    if not raw_path:
        raise RuntimeError("benchmark project environment variable is not set")
    project_root = Path(raw_path).resolve()
    if not (project_root / "Case_folder").is_dir():
        raise AssertionError(f"benchmark project has no Case_folder: {project_root}")
    return project_root


@pytest.mark.skipif(
    not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason="set PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run candidate benchmarks",
)
def test_lazy_plotter_session_benchmark() -> None:
    project_root = _benchmark_project()
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_CANDIDATE_REPETITIONS", "5")),
    )
    result = benchmark_lazy_plotter_session(project_root, repetitions)
    for key in ("current", "lazy_session_simulation"):
        samples = result[key]["samples_s"]
        assert samples
        assert all(math.isfinite(value) and value >= 0 for value in samples)
    print(json.dumps({"lazy_plotter_session": result}, indent=2))


@pytest.mark.skipif(
    not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason="set PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run candidate benchmarks",
)
def test_incremental_envelope_opportunity_benchmark() -> None:
    project_root = _benchmark_project()
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_ENVELOPE_REPETITIONS", "2")),
    )
    workers_value = int(os.environ.get("PSCAD_RESULTS_ANALYSIS_ENVELOPE_WORKERS", "0"))
    voltages = [
        value.strip()
        for value in os.environ.get(
            "PSCAD_RESULTS_ANALYSIS_BENCHMARK_VOLTAGES",
            "66,161,230",
        ).split(",")
        if value.strip()
    ]
    result = benchmark_incremental_envelope_opportunity(
        project_root,
        repetitions,
        voltages,
        workers_value or None,
    )
    for key in ("full_source_read", "single_run_source_read"):
        samples = result[key]["samples_s"]
        assert samples
        assert all(math.isfinite(value) and value > 0 for value in samples)
    print(json.dumps({"incremental_envelope": result}, indent=2))
