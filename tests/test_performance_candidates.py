from __future__ import annotations

import json
import math
import os
from pathlib import Path
import statistics
import sqlite3
import threading
import tempfile
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

    def read_source_runs():
        results = {}
        for voltage in voltages:
            config = configs.get(voltage)
            if config is None:
                continue
            results[voltage] = voltage_envelope._read_voltage_runs(
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
        return results

    return _measure(read_source_runs, repetitions)


def _source_run_data_digest(project_root: Path, data_by_voltage) -> str:
    """Create a deterministic semantic digest for worker-count comparisons."""
    import hashlib

    import pandas as pd

    digest = hashlib.sha256()
    for voltage in sorted(data_by_voltage):
        digest.update(str(voltage).encode("utf-8"))
        for inf_path in sorted(data_by_voltage[voltage]):
            digest.update(str(inf_path.relative_to(project_root)).encode("utf-8"))
            entries, high_voltage = data_by_voltage[voltage][inf_path]
            for measurement, value in entries:
                digest.update(str(measurement).encode("utf-8"))
                if isinstance(value, pd.DataFrame):
                    digest.update(json.dumps(list(value.columns)).encode("utf-8"))
                    digest.update(pd.util.hash_pandas_object(value, index=True).to_numpy().tobytes())
                else:
                    digest.update(json.dumps(value, sort_keys=True, default=str).encode("utf-8"))
            digest.update(json.dumps(high_voltage, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


def _read_source_runs_with_process_pool(
    project_root: Path,
    voltages: list[str],
    worker_count: int,
):
    from concurrent.futures import ProcessPoolExecutor

    from results_analysis_app import project_config, voltage_envelope
    from results_analysis_app.exclusions import ExclusionMatcher

    inf_paths = voltage_envelope._inf_inventory(project_root / "Case_folder")
    configs = project_config.load_voltage_configs(project_root)
    timing = project_config.load_project_timing(project_root)
    time_end = timing.final_duration or voltage_envelope.TIME_END
    fallback_frequency = timing.frequency or voltage_envelope.DEFAULT_ENVELOPE_FALLBACK_FREQUENCY
    descriptor_cache = voltage_envelope._read_inf_descriptor_cache(
        inf_paths,
        worker_count,
        None,
    )
    results = {}
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        for voltage in voltages:
            config = configs.get(voltage)
            if config is None:
                continue
            results[voltage] = voltage_envelope._read_voltage_runs(
                inf_paths,
                voltage,
                config.bus_prefix,
                config.um,
                ExclusionMatcher(),
                worker_count,
                None,
                None,
                time_step=voltage_envelope.TIME_STEP,
                time_end=time_end,
                fallback_frequency=fallback_frequency,
                inf_descriptor_cache=descriptor_cache,
                executor=executor,
                process_pool=True,
                retain_high_voltage_buses=True,
            )
    return results


def benchmark_multivoltage_source_read_opportunity(
    project_root: Path,
    repetitions: int = 1,
    voltages: list[str] | None = None,
    workers: int | None = None,
) -> dict[str, object]:
    """Measure current multi-voltage reads and repeated `.out` file loads.

    This deliberately benchmarks the current implementation only. It provides
    the baseline and duplicate-I/O evidence needed before implementing a
    one-pass multi-voltage reader.
    """
    from results_analysis_app import project_config, voltage_envelope
    from results_analysis_app.exclusions import ExclusionMatcher

    selected_voltages = voltages or ["66", "161", "230"]
    inf_paths = voltage_envelope._inf_inventory(project_root / "Case_folder")
    configs = project_config.load_voltage_configs(project_root)
    timing = project_config.load_project_timing(project_root)
    time_end = timing.final_duration or voltage_envelope.TIME_END
    fallback_frequency = timing.frequency or voltage_envelope.DEFAULT_ENVELOPE_FALLBACK_FREQUENCY
    worker_count = workers or voltage_envelope._automatic_worker_count()
    descriptor_cache = voltage_envelope._read_inf_descriptor_cache(
        inf_paths,
        worker_count,
        None,
    )
    lock = threading.Lock()
    load_calls = 0
    requested_files: set[Path] = set()
    requested_file_columns: set[tuple[Path, tuple[int, ...]]] = set()
    original_loader = voltage_envelope.load_out_columns

    def observed_loader(out_path, columns, check_cancel=None):
        nonlocal load_calls
        normalized_columns = tuple(int(column) for column in columns)
        with lock:
            load_calls += 1
            requested_files.add(Path(out_path))
            requested_file_columns.add((Path(out_path), normalized_columns))
        return original_loader(out_path, normalized_columns, check_cancel)

    def read_source_runs() -> None:
        for voltage in selected_voltages:
            config = configs.get(voltage)
            if config is None:
                continue
            voltage_envelope._read_voltage_runs(
                inf_paths,
                voltage,
                config.bus_prefix,
                config.um,
                ExclusionMatcher(),
                worker_count,
                None,
                None,
                time_step=voltage_envelope.TIME_STEP,
                time_end=time_end,
                fallback_frequency=fallback_frequency,
                inf_descriptor_cache=descriptor_cache,
                process_pool=False,
            )

    voltage_envelope.load_out_columns = observed_loader
    try:
        read_source_runs()
        with lock:
            load_calls = 0
            requested_files.clear()
            requested_file_columns.clear()
        samples: list[float] = []
        for _ in range(max(1, repetitions)):
            started = time.perf_counter()
            read_source_runs()
            samples.append(time.perf_counter() - started)
        operation = {
            "samples_s": samples,
            "median_s": statistics.median(samples),
            "mean_s": statistics.fmean(samples),
            "min_s": min(samples),
            "max_s": max(samples),
        }
    finally:
        voltage_envelope.load_out_columns = original_loader
    return {
        "voltages": selected_voltages,
        "workers": worker_count,
        "current_source_read": operation,
        "load_calls": load_calls,
        "unique_out_files": len(requested_files),
        "unique_file_column_requests": len(requested_file_columns),
        "avoidable_file_reopen_fraction_percent": (
            (load_calls - len(requested_files)) / load_calls * 100.0
            if load_calls
            else 0.0
        ),
    }


def _shared_column_loader_benchmark(
    project_root: Path,
    voltages: list[str],
    workers: int,
    repetitions: int,
) -> dict[str, object]:
    """Compare current source reads with a test-only cross-voltage column cache."""
    from results_analysis_app import project_config, voltage_envelope
    from results_analysis_app.exclusions import ExclusionMatcher

    inf_paths = voltage_envelope._inf_inventory(project_root / "Case_folder")
    configs = project_config.load_voltage_configs(project_root)
    timing = project_config.load_project_timing(project_root)
    time_end = timing.final_duration or voltage_envelope.TIME_END
    fallback_frequency = timing.frequency or voltage_envelope.DEFAULT_ENVELOPE_FALLBACK_FREQUENCY
    descriptor_cache = voltage_envelope._read_inf_descriptor_cache(inf_paths, workers, None)

    def read_source_runs():
        results = {}
        for voltage in voltages:
            config = configs.get(voltage)
            if config is None:
                continue
            results[voltage] = voltage_envelope._read_voltage_runs(
                inf_paths,
                voltage,
                config.bus_prefix,
                config.um,
                ExclusionMatcher(),
                workers,
                None,
                None,
                time_step=voltage_envelope.TIME_STEP,
                time_end=time_end,
                fallback_frequency=fallback_frequency,
                inf_descriptor_cache=descriptor_cache,
                process_pool=False,
            )
        return results

    def measure(operation, before_operation=None) -> dict[str, object]:
        if before_operation is not None:
            before_operation()
        operation()
        samples: list[float] = []
        last_result = None
        for _ in range(max(1, repetitions)):
            if before_operation is not None:
                before_operation()
            started = time.perf_counter()
            last_result = operation()
            samples.append(time.perf_counter() - started)
        return {
            "samples_s": samples,
            "median_s": statistics.median(samples),
            "mean_s": statistics.fmean(samples),
            "min_s": min(samples),
            "max_s": max(samples),
            "result_digest": _source_run_data_digest(project_root, last_result),
        }

    current = measure(read_source_runs)
    original_loader = voltage_envelope.load_out_columns
    lock = threading.Lock()
    shared_columns: dict[Path, dict[int, object]] = {}
    shared_load_calls = 0
    shared_column_count = 0

    def reset_shared_cache() -> None:
        nonlocal shared_columns, shared_load_calls, shared_column_count
        shared_columns = {}
        shared_load_calls = 0
        shared_column_count = 0

    def shared_loader(out_path, columns, check_cancel=None):
        nonlocal shared_load_calls, shared_column_count
        path = Path(out_path)
        requested = tuple(dict.fromkeys(int(column) for column in columns))
        with lock:
            cached = shared_columns.setdefault(path, {})
            missing = [column for column in requested if column not in cached]
            if missing:
                loaded = original_loader(path, missing, check_cancel)
                cached.update(loaded)
                shared_load_calls += 1
                shared_column_count += len(missing)
            return {column: cached[column] for column in requested}

    voltage_envelope.load_out_columns = shared_loader
    try:
        shared = measure(read_source_runs, reset_shared_cache)
    finally:
        voltage_envelope.load_out_columns = original_loader
    shared_bytes_retained = sum(
        int(getattr(values, "nbytes", 0))
        for columns_by_file in shared_columns.values()
        for values in columns_by_file.values()
    )
    return {
        "voltages": voltages,
        "workers": workers,
        "current": current,
        "shared_column_cache": shared,
        "shared_load_calls": shared_load_calls,
        "shared_unique_out_files": len(shared_columns),
        "shared_columns_retained": shared_column_count,
        "shared_bytes_retained": shared_bytes_retained,
    }


def benchmark_shared_multivoltage_source_reader(
    project_root: Path,
    repetitions: int = 1,
    voltages: list[str] | None = None,
    workers: int | None = None,
) -> dict[str, object]:
    """Benchmark a test-only raw-column cache across voltage reads.

    The source/envelope calculations remain the current implementation. Only
    the raw `.out` column loader is shared, which isolates the I/O opportunity
    before a production one-pass reader is designed.
    """
    selected_voltages = voltages or ["66", "161", "230"]
    worker_count = workers or 1
    result = _shared_column_loader_benchmark(
        project_root,
        selected_voltages,
        worker_count,
        repetitions,
    )
    current_seconds = float(result["current"]["median_s"])
    shared_seconds = float(result["shared_column_cache"]["median_s"])
    if result["current"]["result_digest"] != result["shared_column_cache"]["result_digest"]:
        raise AssertionError("shared raw-column loading changed derived run data")
    result["median_speedup_percent"] = (
        (current_seconds - shared_seconds) / current_seconds * 100.0
        if current_seconds
        else 0.0
    )
    return result


def _candidate_reduce_merge(source_dfs, time_step: float):
    """Test-only merge candidate that avoids two full object matrices."""
    import numpy as np
    import pandas as pd

    from results_analysis_app import voltage_envelope

    phase_suffixes = list(
        dict.fromkeys(
            suffix
            for source_df in source_dfs
            for suffix in voltage_envelope._phase_suffixes(source_df)
        )
    )
    row_count = max(len(source_df) for source_df in source_dfs)
    output = pd.DataFrame({"Time (s)": np.round(np.arange(row_count) * time_step, 6)})
    run_columns: dict[str, pd.Series] = {}

    for suffix in phase_suffixes:
        max_col = f"Max_{suffix}"
        max_arrays: list[np.ndarray] = []
        mm_arrays: list[np.ndarray] = []
        case_arrays: list[np.ndarray] = []
        for source_df in source_dfs:
            if max_col not in source_df.columns:
                continue
            values = source_df[max_col].to_numpy(dtype=float)
            order = np.argsort(np.where(np.isnan(values), -np.inf, values), kind="stable")[::-1]
            max_arrays.append(values[order])
            mm_arrays.append(source_df["MM_name"].to_numpy(dtype=object)[order])
            case_arrays.append(source_df["Case"].to_numpy(dtype=object)[order])

        padded_values = [
            np.pad(values, (0, row_count - len(values)), constant_values=np.nan)
            for values in max_arrays
        ]
        max_matrix = np.column_stack(padded_values)
        comparable = np.where(np.isnan(max_matrix), -np.inf, max_matrix)
        source_indices = comparable.argmax(axis=1)
        row_indices = np.arange(row_count)
        max_values = comparable[row_indices, source_indices]
        valid = max_values != -np.inf
        max_values[~valid] = np.nan
        output[max_col] = np.round(max_values, 1)

        selected_mm = np.full(row_count, np.nan, dtype=object)
        selected_cases = np.full(row_count, np.nan, dtype=object)
        for index, (mm_values, case_values) in enumerate(zip(mm_arrays, case_arrays)):
            rows = np.flatnonzero((source_indices == index) & valid)
            rows = rows[rows < len(mm_values)]
            selected_mm[rows] = mm_values[rows]
            selected_cases[rows] = case_values[rows]
        output[f"MM_name_{suffix}"] = selected_mm
        parts = pd.Series(selected_cases, dtype=object).astype(str).str.split("-", n=1, expand=True)
        output[f"Case_{suffix}"] = parts[0].replace("nan", np.nan)
        run_columns[f"Run_{suffix}"] = pd.to_numeric(
            parts[1] if parts.shape[1] > 1 else np.nan,
            errors="coerce",
        )
    for column, values in run_columns.items():
        output[column] = values
    return output


def benchmark_reduce_merge_candidate(
    project_root: Path,
    voltage: str = "66",
    repetitions: int = 3,
    workers: int | None = None,
) -> dict[str, object]:
    """Compare a test-only merge candidate against the current implementation."""
    import pandas as pd

    from results_analysis_app import voltage_envelope

    worker_count = workers or voltage_envelope._automatic_worker_count()
    source_data = _read_source_runs_with_process_pool(
        project_root,
        [voltage],
        worker_count,
    )[voltage]
    source_dfs = [
        value
        for inf_path in sorted(source_data)
        for measurement, value in source_data[inf_path][0]
        if measurement == "LGp" and isinstance(value, pd.DataFrame)
    ]
    if not source_dfs:
        raise AssertionError(f"benchmark project has no LGp envelope data at {voltage} kV")

    baseline = voltage_envelope._reduce_merge(source_dfs)
    candidate = _candidate_reduce_merge(source_dfs, voltage_envelope.TIME_STEP)
    pd.testing.assert_frame_equal(baseline, candidate, check_exact=True)

    baseline_samples: list[float] = []
    candidate_samples: list[float] = []
    for _ in range(max(1, repetitions)):
        started = time.perf_counter()
        voltage_envelope._reduce_merge(source_dfs)
        baseline_samples.append(time.perf_counter() - started)
        started = time.perf_counter()
        _candidate_reduce_merge(source_dfs, voltage_envelope.TIME_STEP)
        candidate_samples.append(time.perf_counter() - started)
    baseline_median = statistics.median(baseline_samples)
    candidate_median = statistics.median(candidate_samples)
    return {
        "voltage": voltage,
        "source_frame_count": len(source_dfs),
        "baseline": {
            "samples_s": baseline_samples,
            "median_s": baseline_median,
        },
        "candidate": {
            "samples_s": candidate_samples,
            "median_s": candidate_median,
        },
        "median_speedup_percent": (
            (baseline_median - candidate_median) / baseline_median * 100.0
            if baseline_median
            else 0.0
        ),
    }


def _cache_payload_digest(cache_root: Path) -> tuple[int, str]:
    import hashlib

    digest = hashlib.sha256()
    connection = sqlite3.connect(cache_root / ".state" / "envelope_data.sqlite3")
    try:
        rows = connection.execute(
            "SELECT cache_key, calculation_signature, source_signature, payload "
            "FROM run_data_cache ORDER BY cache_key"
        )
        count = 0
        for cache_key, calculation_signature, source_signature, payload in rows:
            digest.update(str(cache_key).encode("utf-8"))
            digest.update(str(calculation_signature).encode("utf-8"))
            digest.update(str(source_signature).encode("utf-8"))
            digest.update(bytes(payload))
            count += 1
    finally:
        connection.close()
    return count, digest.hexdigest()


def benchmark_cache_write_strategies(
    run_data_by_voltage,
    repetitions: int = 1,
) -> dict[str, object]:
    """Compare current per-row puts with one-transaction batched SQL writes."""
    from results_analysis_app import envelope_data_cache

    rows = [
        (
            f"{voltage}\0{inf_path}",
            f"calculation-{voltage}",
            f"source-{inf_path}",
            run_data,
        )
        for voltage, voltage_data in sorted(run_data_by_voltage.items())
        for inf_path, run_data in sorted(voltage_data.items())
    ]
    if not rows:
        raise AssertionError("cache-write benchmark has no run-data rows")

    def measure_current(root: Path) -> float:
        started = time.perf_counter()
        with envelope_data_cache.RunDataCache(root) as cache:
            for cache_key, calculation, source, run_data in rows:
                cache.put(cache_key, calculation, source, run_data)
        return time.perf_counter() - started

    def measure_batched(root: Path) -> float:
        started = time.perf_counter()
        with envelope_data_cache.RunDataCache(root):
            pass
        payloads = (
            (
                cache_key,
                calculation,
                source,
                envelope_data_cache._encode_run_data(run_data),
            )
            for cache_key, calculation, source, run_data in rows
        )
        connection = sqlite3.connect(root / ".state" / "envelope_data.sqlite3")
        try:
            connection.executemany(
                "INSERT INTO run_data_cache("
                "cache_key, calculation_signature, source_signature, payload) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET "
                "calculation_signature=excluded.calculation_signature, "
                "source_signature=excluded.source_signature, "
                "payload=excluded.payload",
                payloads,
            )
            connection.commit()
        finally:
            connection.close()
        return time.perf_counter() - started

    current_samples: list[float] = []
    batched_samples: list[float] = []
    with tempfile.TemporaryDirectory(prefix="pscad-cache-benchmark-") as temp_root:
        temp_root_path = Path(temp_root)
        current_root = temp_root_path / "current"
        batched_root = temp_root_path / "batched"
        for _ in range(max(1, repetitions)):
            current_samples.append(measure_current(current_root))
            batched_samples.append(measure_batched(batched_root))
        current_count, current_digest = _cache_payload_digest(current_root)
        batched_count, batched_digest = _cache_payload_digest(batched_root)
        current_cache_bytes = (
            current_root / ".state" / "envelope_data.sqlite3"
        ).stat().st_size
        batched_cache_bytes = (
            batched_root / ".state" / "envelope_data.sqlite3"
        ).stat().st_size
    current_median = statistics.median(current_samples)
    batched_median = statistics.median(batched_samples)
    return {
        "row_count": len(rows),
        "current": {"samples_s": current_samples, "median_s": current_median},
        "batched": {"samples_s": batched_samples, "median_s": batched_median},
        "current_payload": {"count": current_count, "digest": current_digest},
        "batched_payload": {"count": batched_count, "digest": batched_digest},
        "current_cache_bytes": current_cache_bytes,
        "batched_cache_bytes": batched_cache_bytes,
        "cache_size_delta_bytes": batched_cache_bytes - current_cache_bytes,
        "median_speedup_percent": (
            (current_median - batched_median) / current_median * 100.0
            if current_median
            else 0.0
        ),
    }


class _SerializedResultCache:
    """Test-only compressed memoization for result-stage analysis calls.

    This is deliberately not production code.  It exercises the proposed
    separate Sustained/resonance result-cache boundary with a persistent-cache
    shape: stable input key, compressed serialized result, and deserialization
    on a hit.  The benchmark reports the payload size and hit/miss timings
    before any production cache format is chosen.
    """

    def __init__(self) -> None:
        self._payloads: dict[bytes, bytes] = {}
        self.hits = 0
        self.misses = 0
        self.raw_bytes = 0
        self.compressed_bytes = 0

    @staticmethod
    def _key(args, kwargs) -> bytes:
        import hashlib
        import pickle

        try:
            encoded = pickle.dumps((args, kwargs), protocol=5)
        except (AttributeError, TypeError, ValueError) as exc:
            raise AssertionError(
                "result-cache benchmark inputs must be serializable"
            ) from exc
        return hashlib.blake2b(encoded, digest_size=20).digest()

    def call(self, function, args=(), kwargs=None):
        import pickle
        import zlib

        call_kwargs = kwargs or {}
        key = self._key(args, call_kwargs)
        payload = self._payloads.get(key)
        if payload is not None:
            self.hits += 1
            return pickle.loads(zlib.decompress(payload))

        result = function(*args, **call_kwargs)
        raw = pickle.dumps(result, protocol=5)
        compressed = zlib.compress(raw, level=6)
        self._payloads[key] = compressed
        self.misses += 1
        self.raw_bytes += len(raw)
        self.compressed_bytes += len(compressed)
        return result

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._payloads),
            "hits": self.hits,
            "misses": self.misses,
            "raw_bytes": self.raw_bytes,
            "compressed_bytes": self.compressed_bytes,
        }


def _json_mapping_env(name: str) -> dict[str, object] | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{name} must contain a JSON object or @path") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must contain a JSON object or @path")
    return value


def _semantic_output_digests(project_root: Path, outputs: list[Path]) -> dict[str, str]:
    """Digest result content while ignoring volatile workbook metadata."""
    import hashlib

    digests: dict[str, str] = {}
    for path in outputs:
        digest = hashlib.sha256()
        if path.suffix.casefold() == ".json":
            digest.update(
                json.dumps(
                    json.loads(path.read_text(encoding="utf-8")),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
        elif path.suffix.casefold() == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=False)
            try:
                digest.update(json.dumps(workbook.sheetnames).encode("utf-8"))
                for worksheet in workbook.worksheets:
                    for row in worksheet.iter_rows(values_only=True):
                        digest.update(
                            json.dumps(
                                list(row),
                                default=str,
                                ensure_ascii=True,
                            ).encode("utf-8")
                        )
            finally:
                workbook.close()
        else:
            digest.update(path.read_bytes())
        digests[str(path.relative_to(project_root))] = digest.hexdigest()
    return digests


def test_serialized_result_cache_roundtrip_and_invalidation() -> None:
    import numpy as np
    import pickle
    from dataclasses import replace

    from results_analysis_app import resonance_checks, sustained_sdpf

    time_axis = np.linspace(0.0, 0.1, 101)
    record = resonance_checks.ChronologicalEnvelope(
        "Full",
        "66",
        "LGp",
        "C1",
        1,
        "MM_66_C1",
        1.0,
        time_axis,
        np.where(time_axis < 0.02, 0.5, 2.0),
    )
    resonance_settings = resonance_checks.ResonanceSettings(
        enabled_checks=(resonance_checks.POST_EVENT_STRESS,),
        auto_release=False,
        manual_analysis_start=0.02,
        limit_multiplier=1.0,
    )
    resonance_cache = _SerializedResultCache()
    baseline = resonance_checks.analyze_records(
        [record], resonance_settings, event_times={}
    )
    first = resonance_cache.call(
        resonance_checks.analyze_records,
        ([record], resonance_settings, {}),
    )
    second = resonance_cache.call(
        resonance_checks.analyze_records,
        ([record], resonance_settings, {}),
    )
    assert baseline and first and second
    assert pickle.dumps(first, protocol=5) == pickle.dumps(second, protocol=5)
    assert pickle.dumps(baseline, protocol=5) == pickle.dumps(first, protocol=5)

    changed_record = replace(record, envelope=record.envelope * 0.5)
    resonance_cache.call(
        resonance_checks.analyze_records,
        ([changed_record], resonance_settings, {}),
    )
    changed_settings = replace(resonance_settings, limit_multiplier=1.1)
    resonance_cache.call(
        resonance_checks.analyze_records,
        ([record], changed_settings, {}),
    )
    resonance_cache.call(
        resonance_checks.analyze_records,
        ([record], resonance_settings, {"SFO": 0.01}),
    )
    changed_scope = replace(record, scope_folder="Single case")
    resonance_cache.call(
        resonance_checks.analyze_records,
        ([changed_scope], resonance_settings, {}),
    )
    assert resonance_cache.hits == 1
    assert resonance_cache.misses == 5

    phase = sustained_sdpf.PhaseStressResult(
        "LGp",
        "A-G",
        1.0,
        1.5,
        0.9,
        1.4,
        0.03,
        0.03,
        1.5,
        1.0,
        1.06,
        "candidate",
        sdpf_exceeded=True,
    )
    sustained_result = sustained_sdpf.SustainedSDPFResult(
        "Full",
        "66",
        "C1",
        1,
        "MM_66_C1",
        "AG",
        0.03,
        phase,
        (phase,),
        signature="source-signature",
        cycle_coverage=2,
    )
    sustained_cache = _SerializedResultCache()

    def identity(value):
        return value

    sustained_first = sustained_cache.call(identity, (sustained_result,))
    sustained_second = sustained_cache.call(identity, (sustained_result,))
    assert sustained_first == sustained_second == sustained_result
    assert sustained_cache.stats()["compressed_bytes"] > 0


def benchmark_separate_result_cache(
    project_root: Path,
    repetitions: int = 2,
    voltages: list[str] | None = None,
    workers: int | None = None,
    resonance_settings: dict[str, object] | None = None,
    sustained_settings: dict[str, object] | None = None,
    event_times: dict[str, float] | None = None,
    comparison_voltages: list[str] | None = None,
) -> dict[str, object]:
    """Measure a compressed test-only cache around result-stage analysis.

    The source/run-data cache is allowed to warm first.  The baseline then
    repeats the current Sustained/resonance calculations.  The candidate
    repeats the same builds with compressed in-memory payloads standing in for
    a separate on-disk result cache.  Every candidate build must reproduce the
    first warm current-build output exactly.  ``comparison_voltages`` can be
    narrower than ``voltages`` to model a user changing the selected voltage
    set after a previous build.  The result is an upper-bound/format-sizing
    experiment, not a production implementation.
    """
    from test_performance_benchmark import _envelope_stage_timings

    from results_analysis_app import (
        project_config,
        resonance_checks,
        storage,
        sustained_sdpf,
        voltage_envelope,
    )
    from results_analysis_app.models import ScopeEntry

    parsed_resonance = resonance_checks.ResonanceSettings.from_mapping(resonance_settings)
    parsed_sustained = sustained_sdpf.SustainedSDPFSettings.from_mapping(sustained_settings)
    if not parsed_resonance.enabled and not parsed_sustained.enabled:
        raise AssertionError(
            "enable at least one result stage with resonance_settings or sustained_settings"
        )
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
    measured_voltages = [
        voltage
        for voltage in (comparison_voltages or selected_voltages)
        if voltage in configured_voltages
    ]
    if not selected_voltages:
        raise AssertionError("benchmark project has no requested voltage configurations")
    if not measured_voltages:
        raise AssertionError("benchmark project has no requested comparison voltages")
    timing = project_config.load_project_timing(project_root)
    worker_count = workers or None

    def build(
        scope: ScopeEntry,
        messages: list[str],
        build_voltages: list[str],
    ) -> list[Path]:
        from contextlib import nullcontext

        original_excel_app = voltage_envelope.excel_app
        original_autofit = voltage_envelope.autofit_workbook
        voltage_envelope.excel_app = lambda: nullcontext(None)
        voltage_envelope.autofit_workbook = lambda _excel, _path: None
        try:
            return voltage_envelope.build_voltage_envelopes(
                project_root,
                [scope],
                build_voltages,
                log=messages.append,
                envelope_workers=worker_count,
                project_timing=timing,
                voltage_configs=configured_voltages,
                resonance_settings=resonance_settings,
                event_times=event_times or {},
                sustained_sdpf_settings=sustained_settings,
                build_charts=False,
            )
        finally:
            voltage_envelope.excel_app = original_excel_app
            voltage_envelope.autofit_workbook = original_autofit

    cold_messages: list[str] = []
    started = time.perf_counter()
    cold_outputs = build(ScopeEntry.full(), cold_messages, selected_voltages)
    cold_seconds = time.perf_counter() - started
    expected_outputs_by_selection = {
        tuple(selected_voltages): sorted(
            str(path.relative_to(project_root)) for path in cold_outputs
        )
    }
    # Run-data cache arrays preserve float64 precision. This benchmark isolates
    # the proposed result cache and compares later forced builds with the first
    # warm build while avoiding a cold-source baseline in each timed iteration.
    reference_digests_by_selection: dict[tuple[str, ...], dict[str, str]] = {
        tuple(selected_voltages): _semantic_output_digests(project_root, cold_outputs)
    }

    def invalidate_envelope_output_cache() -> None:
        cache = storage.load_project_analysis_cache(project_root)
        cache.pop("envelope", None)
        storage.save_project_analysis_cache(project_root, cache)

    def measured_build(
        label: str,
        build_voltages: list[str],
    ) -> tuple[float, dict[str, list[float]], list[str]]:
        del label
        # Keep the compact run-data cache warm, but force the envelope/result
        # stages to execute for every measurement.  The normal app can skip the
        # whole build when this manifest is valid; that is a separate existing
        # optimization and would hide the result-cache opportunity.
        invalidate_envelope_output_cache()
        messages: list[str] = []
        started = time.perf_counter()
        outputs = build(ScopeEntry.full(), messages, build_voltages)
        elapsed = time.perf_counter() - started
        actual_outputs = sorted(str(path.relative_to(project_root)) for path in outputs)
        selection_key = tuple(build_voltages)
        expected_outputs = expected_outputs_by_selection.setdefault(
            selection_key,
            actual_outputs,
        )
        if actual_outputs != expected_outputs:
            raise AssertionError("result-cache candidate changed the output set")
        actual_digests = _semantic_output_digests(project_root, outputs)
        reference_digests = reference_digests_by_selection.get(selection_key)
        if reference_digests is None:
            reference_digests_by_selection[selection_key] = actual_digests
        elif actual_digests != reference_digests:
            mismatched = sorted(
                path
                for path in set(reference_digests) | set(actual_digests)
                if reference_digests.get(path) != actual_digests.get(path)
            )
            raise AssertionError(
                "result-cache candidate changed generated outputs: "
                + ", ".join(mismatched)
            )
        return elapsed, _envelope_stage_timings(messages), messages

    baseline_samples: list[float] = []
    baseline_stage_timings: list[dict[str, list[float]]] = []
    for index in range(max(1, repetitions)):
        elapsed, stage_timings, _messages = measured_build(
            f"Result baseline {index + 1}",
            measured_voltages,
        )
        baseline_samples.append(elapsed)
        baseline_stage_timings.append(stage_timings)

    resonance_cache = _SerializedResultCache()
    sustained_cache = _SerializedResultCache()
    original_analyze_records = resonance_checks.analyze_records
    original_sustained_results = voltage_envelope._sustained_results_for_scope

    def cached_analyze_records(*args, **kwargs):
        return resonance_cache.call(original_analyze_records, args, kwargs)

    def cached_sustained_results(*args, **kwargs):
        return sustained_cache.call(original_sustained_results, args, kwargs)

    voltage_envelope.resonance_checks.analyze_records = cached_analyze_records
    voltage_envelope._sustained_results_for_scope = cached_sustained_results
    try:
        fill_seconds, fill_stage_timings, _fill_messages = measured_build(
            "Result cache fill",
            selected_voltages,
        )
        hit_samples: list[float] = []
        hit_stage_timings: list[dict[str, list[float]]] = []
        for index in range(max(1, repetitions)):
            elapsed, stage_timings, _messages = measured_build(
                f"Result cache hit {index + 1}",
                measured_voltages,
            )
            hit_samples.append(elapsed)
            hit_stage_timings.append(stage_timings)
    finally:
        voltage_envelope.resonance_checks.analyze_records = original_analyze_records
        voltage_envelope._sustained_results_for_scope = original_sustained_results

    baseline_median = statistics.median(baseline_samples)
    hit_median = statistics.median(hit_samples)
    return {
        "cold_s": cold_seconds,
        "cold_stage_timings": _envelope_stage_timings(cold_messages),
        "selected_voltages": selected_voltages,
        "comparison_voltages": measured_voltages,
        "settings": {
            "resonance_enabled_checks": list(parsed_resonance.effective_enabled_checks),
            "sustained_enabled": parsed_sustained.enabled,
        },
        "baseline_current": {
            "samples_s": baseline_samples,
            "median_s": baseline_median,
            "stage_timings": baseline_stage_timings,
        },
        "serialized_result_cache": {
            "fill_s": fill_seconds,
            "fill_stage_timings": fill_stage_timings,
            "hit_samples_s": hit_samples,
            "hit_median_s": hit_median,
            "hit_stage_timings": hit_stage_timings,
            "resonance": resonance_cache.stats(),
            "sustained": sustained_cache.stats(),
            "compressed_bytes": (
                resonance_cache.compressed_bytes + sustained_cache.compressed_bytes
            ),
        },
        "median_speedup_percent": (
            (baseline_median - hit_median) / baseline_median * 100.0
            if baseline_median
            else 0.0
        ),
        "output_count": len(cold_outputs),
    }


def test_merge_candidate_preserves_current_output() -> None:
    import numpy as np
    import pandas as pd

    from results_analysis_app import voltage_envelope

    first = pd.DataFrame(
        {
            "Max_A": [1.0, 4.0, 2.0],
            "MM_name": ["MM_A", "MM_A", "MM_A"],
            "Case": ["C1-1", "C1-1", "C1-1"],
        },
        index=np.array([0.0, 0.1, 0.2]),
    )
    second = pd.DataFrame(
        {
            "Max_A": [3.0, 2.0],
            "MM_name": ["MM_B", "MM_B"],
            "Case": ["C2-1", "C2-1"],
        },
        index=np.array([0.0, 0.1]),
    )
    expected = voltage_envelope._reduce_merge([first, second], time_step=0.1)
    candidate = _candidate_reduce_merge([first, second], time_step=0.1)

    pd.testing.assert_frame_equal(expected, candidate, check_exact=True)


def test_batched_cache_write_preserves_payloads() -> None:
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame(
        {"Max_A": [1.0, 2.0], "MM_name": ["MM_A", "MM_A"], "Case": ["C1-1", "C1-1"]},
        index=np.array([0.0, 0.1]),
    )
    frame.index.name = "Time (s)"
    result = benchmark_cache_write_strategies(
        {"66": {Path("Case_folder/C1/C1_r00001.inf"): ([ ("LGp", frame) ], [])}},
    )

    assert result["current_payload"] == result["batched_payload"]
    assert result["row_count"] == 1
    assert result["current"]["median_s"] > 0
    assert result["batched"]["median_s"] > 0


def benchmark_incremental_envelope_opportunity(
    project_root: Path,
    repetitions: int = 2,
    voltages: list[str] | None = None,
    workers: int | None = None,
) -> dict[str, object]:
    """Measure full source read versus one-run source read as a cache bound.

    This is a component benchmark, not an implemented-cache comparison. It
    estimates the source-read work that can be avoided when only one run is
    invalidated; the integration test in ``test_envelope_data_cache.py`` tests
    the actual cache path and output equivalence.
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


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_SOURCE_IO_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_SOURCE_IO_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the source-I/O benchmark"
    ),
)
def test_multivoltage_source_read_opportunity_benchmark() -> None:
    project_root = _benchmark_project()
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_SOURCE_IO_REPETITIONS", "1")),
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
    result = benchmark_multivoltage_source_read_opportunity(
        project_root,
        repetitions,
        voltages,
        workers_value or None,
    )
    current = result["current_source_read"]["samples_s"]
    assert current
    assert all(math.isfinite(value) and value > 0 for value in current)
    assert result["load_calls"] >= result["unique_out_files"]
    print(json.dumps({"multivoltage_source_io": result}, indent=2))


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_SHARED_READER_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_SHARED_READER_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the shared-reader benchmark"
    ),
)
def test_shared_multivoltage_reader_benchmark() -> None:
    project_root = _benchmark_project()
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_SOURCE_IO_REPETITIONS", "1")),
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
    result = benchmark_shared_multivoltage_source_reader(
        project_root,
        repetitions,
        voltages,
        workers_value or None,
    )
    assert result["current"]["result_digest"] == result["shared_column_cache"]["result_digest"]
    assert float(result["current"]["median_s"]) > 0
    assert float(result["shared_column_cache"]["median_s"]) > 0
    print(json.dumps({"shared_multivoltage_reader": result}, indent=2))


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_MERGE_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_MERGE_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the merge benchmark"
    ),
)
def test_reduce_merge_candidate_benchmark() -> None:
    project_root = _benchmark_project()
    voltage = os.environ.get("PSCAD_RESULTS_ANALYSIS_MERGE_VOLTAGE", "66")
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_MERGE_REPETITIONS", "3")),
    )
    workers_value = int(os.environ.get("PSCAD_RESULTS_ANALYSIS_ENVELOPE_WORKERS", "0"))
    result = benchmark_reduce_merge_candidate(
        project_root,
        voltage,
        repetitions,
        workers_value or None,
    )
    assert result["source_frame_count"] > 0
    assert float(result["baseline"]["median_s"]) > 0
    assert float(result["candidate"]["median_s"]) > 0
    print(json.dumps({"reduce_merge": result}, indent=2))


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_CACHE_WRITE_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_CACHE_WRITE_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the cache-write benchmark"
    ),
)
def test_cache_write_strategy_benchmark() -> None:
    project_root = _benchmark_project()
    voltage = os.environ.get("PSCAD_RESULTS_ANALYSIS_CACHE_WRITE_VOLTAGE", "66")
    workers_value = int(os.environ.get("PSCAD_RESULTS_ANALYSIS_ENVELOPE_WORKERS", "0"))
    run_data = _read_source_runs_with_process_pool(
        project_root,
        [voltage],
        workers_value or 1,
    )
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_CACHE_WRITE_REPETITIONS", "1")),
    )
    result = benchmark_cache_write_strategies(run_data, repetitions)
    assert result["current_payload"] == result["batched_payload"]
    assert result["row_count"] > 0
    print(json.dumps({"cache_write": result}, indent=2))


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_RESULT_CACHE_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_RESULT_CACHE_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the result-cache benchmark"
    ),
)
def test_separate_result_cache_benchmark() -> None:
    project_root = _benchmark_project()
    resonance_settings = _json_mapping_env(
        "PSCAD_RESULTS_ANALYSIS_RESONANCE_SETTINGS_JSON"
    )
    sustained_settings = _json_mapping_env(
        "PSCAD_RESULTS_ANALYSIS_SUSTAINED_SETTINGS_JSON"
    )
    event_times = _json_mapping_env("PSCAD_RESULTS_ANALYSIS_EVENT_TIMES_JSON")
    if resonance_settings is None and sustained_settings is None:
        pytest.skip(
            "provide resonance or Sustained settings JSON to exercise the result stages"
        )
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_RESULT_CACHE_REPETITIONS", "2")),
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
    result = benchmark_separate_result_cache(
        project_root,
        repetitions,
        voltages,
        workers_value or None,
        resonance_settings,
        sustained_settings,
        event_times,
    )
    baseline = result["baseline_current"]
    candidate = result["serialized_result_cache"]
    assert math.isfinite(float(result["cold_s"])) and float(result["cold_s"]) > 0
    assert baseline["samples_s"]
    assert all(math.isfinite(value) and value > 0 for value in baseline["samples_s"])
    assert candidate["hit_samples_s"]
    assert all(math.isfinite(value) and value > 0 for value in candidate["hit_samples_s"])
    assert int(candidate["compressed_bytes"]) >= 0
    assert int(candidate["resonance"]["hits"]) + int(candidate["sustained"]["hits"]) > 0
    assert math.isfinite(float(result["median_speedup_percent"]))
    print(json.dumps({"separate_result_cache": result}, indent=2))


@pytest.mark.skipif(
    os.environ.get("PSCAD_RESULTS_ANALYSIS_RUN_RESULT_CACHE_SELECTION_BENCHMARK") != "1"
    or not os.environ.get("PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT"),
    reason=(
        "set PSCAD_RESULTS_ANALYSIS_RUN_RESULT_CACHE_SELECTION_BENCHMARK=1 and "
        "PSCAD_RESULTS_ANALYSIS_BENCHMARK_PROJECT to run the voltage-selection benchmark"
    ),
)
def test_separate_result_cache_voltage_selection_benchmark() -> None:
    project_root = _benchmark_project()
    resonance_settings = _json_mapping_env(
        "PSCAD_RESULTS_ANALYSIS_RESONANCE_SETTINGS_JSON"
    )
    sustained_settings = _json_mapping_env(
        "PSCAD_RESULTS_ANALYSIS_SUSTAINED_SETTINGS_JSON"
    )
    event_times = _json_mapping_env("PSCAD_RESULTS_ANALYSIS_EVENT_TIMES_JSON")
    repetitions = max(
        1,
        int(os.environ.get("PSCAD_RESULTS_ANALYSIS_RESULT_CACHE_REPETITIONS", "2")),
    )
    workers_value = int(os.environ.get("PSCAD_RESULTS_ANALYSIS_ENVELOPE_WORKERS", "0"))
    selected_voltages = [
        value.strip()
        for value in os.environ.get(
            "PSCAD_RESULTS_ANALYSIS_BENCHMARK_VOLTAGES",
            "66,161,230",
        ).split(",")
        if value.strip()
    ]
    comparison_voltages = [
        value.strip()
        for value in os.environ.get(
            "PSCAD_RESULTS_ANALYSIS_RESULT_CACHE_COMPARISON_VOLTAGES",
            "161",
        ).split(",")
        if value.strip()
    ]
    if resonance_settings is None and sustained_settings is None:
        pytest.skip(
            "provide resonance or Sustained settings JSON to exercise the result stages"
        )
    result = benchmark_separate_result_cache(
        project_root,
        repetitions,
        selected_voltages,
        workers_value or None,
        resonance_settings,
        sustained_settings,
        event_times,
        comparison_voltages,
    )
    baseline = result["baseline_current"]
    candidate = result["serialized_result_cache"]
    assert baseline["samples_s"]
    assert candidate["hit_samples_s"]
    assert int(candidate["resonance"]["hits"]) + int(candidate["sustained"]["hits"]) > 0
    print(json.dumps({"separate_result_cache_selection": result}, indent=2))
