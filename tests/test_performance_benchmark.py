from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import statistics
import time

import pytest


def _semantic_file_digests(project_root: Path, outputs: list[Path]) -> dict[str, str]:
    from test_performance_candidates import _semantic_output_digests

    return _semantic_output_digests(project_root, outputs)


def _envelope_stage_timings(messages: list[str]) -> dict[str, list[float]]:
    timings: dict[str, list[float]] = {}

    def add(name: str, value: str) -> None:
        timings.setdefault(name, []).append(float(value))

    for message in messages:
        if "Envelope source read finished:" in message:
            match = re.search(r"\|\s*([0-9]+(?:\.[0-9]+)?)s$", message)
            if match:
                add("source_read_s", match.group(1))
        if "merge+write=" in message:
            merge = re.search(r"merge\+write=([0-9]+(?:\.[0-9]+)?)s", message)
            write = re.search(r"(?:^|,\s*)write=([0-9]+(?:\.[0-9]+)?)s", message)
            if merge:
                add("merge_write_s", merge.group(1))
            if write:
                add("workbook_write_s", write.group(1))
        for marker, name in (
            ("Envelope run-data cache write finished:", "cache_write_s"),
            ("Sustained SDPF result saved:", "sustained_persist_s"),
            ("Sustained SDPF ranked summary saved:", "sustained_summary_s"),
            ("Resonance workbook phase finished:", "resonance_workbook_s"),
            ("Envelope build total:", "envelope_total_s"),
        ):
            if marker in message:
                match = re.search(r"([0-9]+(?:\.[0-9]+)?)s$", message)
                if match:
                    add(name, match.group(1))
    return timings


def test_envelope_stage_timing_parser() -> None:
    timings = _envelope_stage_timings(
        [
            "Envelope source read finished: P | 477.2s",
            "Envelope merge finished | merge+write=321.6s, write=0.4s",
            "Envelope run-data cache write finished: 17 rows | 407.0s",
            "Sustained SDPF result saved: P | persist=4.2s",
            "Sustained SDPF ranked summary saved: P | write=8.1s",
            "Resonance workbook phase finished: 12.0s",
            "Envelope build total: P | 1525.0s",
        ]
    )
    assert timings == {
        "source_read_s": [477.2],
        "merge_write_s": [321.6],
        "workbook_write_s": [0.4],
        "cache_write_s": [407.0],
        "sustained_persist_s": [4.2],
        "sustained_summary_s": [8.1],
        "resonance_workbook_s": [12.0],
        "envelope_total_s": [1525.0],
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


def benchmark_warm_envelope_cache(
    project_root: Path,
    repetitions: int = 3,
    voltages: list[str] | None = None,
    workers: int | None = None,
) -> dict[str, object]:
    """Compare a cold envelope build with warm run-data-cache builds.

    The caller must provide a disposable project copy with no envelope output
    manifest or run-data cache. Warm builds use different full-scope names so
    the complete-envelope manifest is bypassed while the per-run source cache
    remains reusable. This measures the actual cache-enabled build path,
    including the remaining merge and presentation work.
    """
    from contextlib import nullcontext

    from results_analysis_app import project_config, storage, voltage_envelope
    from results_analysis_app.models import ScopeEntry

    if storage.project_envelope_data_cache_path(project_root).is_file():
        raise AssertionError(
            "benchmark project is not cold: remove .state/envelope_data.sqlite3 "
            "from the disposable copy"
        )
    if storage.load_project_analysis_cache(project_root).get("envelope"):
        raise AssertionError(
            "benchmark project is not cold: remove the envelope entry from "
            ".state/analysis_cache.json in the disposable copy"
        )
    if not storage.project_incremental_run_data_enabled(project_root):
        raise AssertionError("incremental run-data cache is disabled for benchmark project")

    configured_voltages = project_config.load_voltage_configs(project_root)
    selected_voltages = [
        voltage
        for voltage in (voltages or ["66", "161", "230"])
        if voltage in configured_voltages
    ]
    if not selected_voltages:
        raise AssertionError("benchmark project has no requested voltage configurations")
    timing = project_config.load_project_timing(project_root)
    worker_count = workers or None
    original_excel_app = voltage_envelope.excel_app
    original_autofit_workbook = voltage_envelope.autofit_workbook
    voltage_envelope.excel_app = lambda: nullcontext(None)
    voltage_envelope.autofit_workbook = lambda _excel, _path: None

    def build(scope: ScopeEntry, messages: list[str]) -> list[Path]:
        return voltage_envelope.build_voltage_envelopes(
            project_root,
            [scope],
            selected_voltages,
            log=messages.append,
            envelope_workers=worker_count,
            project_timing=timing,
            voltage_configs=configured_voltages,
            build_charts=False,
        )

    try:
        cold_messages: list[str] = []
        started = time.perf_counter()
        cold_outputs = build(ScopeEntry.full(), cold_messages)
        cold_seconds = time.perf_counter() - started
        cold_digests = _semantic_file_digests(project_root, cold_outputs)

        warm_samples: list[float] = []
        warm_cache_messages: list[list[str]] = []
        warm_stage_timings: list[dict[str, list[float]]] = []
        for index in range(max(1, repetitions)):
            warm_messages: list[str] = []
            warm_scope = ScopeEntry(name=f"Full cache reuse {index + 1}", mode="full")
            started = time.perf_counter()
            warm_outputs = build(warm_scope, warm_messages)
            warm_samples.append(time.perf_counter() - started)
            assert [path.relative_to(project_root) for path in warm_outputs] == [
                path.relative_to(project_root) for path in cold_outputs
            ]
            assert _semantic_file_digests(project_root, warm_outputs) == cold_digests
            warm_stage_timings.append(_envelope_stage_timings(warm_messages))
            warm_cache_messages.append(
                [message for message in warm_messages if "Incremental run-data cache:" in message]
            )
    finally:
        voltage_envelope.excel_app = original_excel_app
        voltage_envelope.autofit_workbook = original_autofit_workbook

    warm_median = statistics.median(warm_samples)
    return {
        "cold_s": cold_seconds,
        "warm_samples_s": warm_samples,
        "warm_median_s": warm_median,
        "median_speedup_percent": (cold_seconds - warm_median) / cold_seconds * 100.0
        if cold_seconds
        else 0.0,
        "selected_voltages": selected_voltages,
        "cold_stage_timings": _envelope_stage_timings(cold_messages),
        "warm_stage_timings": warm_stage_timings,
        "cold_cache_messages": [
            message for message in cold_messages if "Incremental run-data cache:" in message
        ],
        "warm_cache_messages": warm_cache_messages,
        "output_count": len(cold_outputs),
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


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_ENVELOPE_CACHE_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_ENVELOPE_CACHE_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the real-project cache benchmark"
    ),
)
def test_warm_envelope_cache_benchmark() -> None:
    project_root = Path(os.environ["PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"]).resolve()
    assert (project_root / "Case_folder").is_dir()
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_ENVELOPE_CACHE_REPETITIONS", "3")),
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
    result = benchmark_warm_envelope_cache(
        project_root,
        repetitions,
        voltages,
        workers_value or None,
    )
    assert math.isfinite(float(result["cold_s"])) and float(result["cold_s"]) > 0
    warm_samples = result["warm_samples_s"]
    assert warm_samples
    assert all(math.isfinite(value) and value > 0 for value in warm_samples)
    cold_cache_messages = result["cold_cache_messages"]
    assert cold_cache_messages
    assert any("0/" in message for message in cold_cache_messages)
    for messages in result["warm_cache_messages"]:
        assert messages
        assert any("/" in message for message in messages)
    assert float(result["median_speedup_percent"]) > 0.0
    print(json.dumps({"warm_envelope_cache": result}, indent=2))
