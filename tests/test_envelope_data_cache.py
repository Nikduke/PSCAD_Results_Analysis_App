from __future__ import annotations

import io
import sqlite3
import time

import numpy as np
import pandas as pd


def _run_data():
    frame = pd.DataFrame(
        {
            "Max_A": [1.1, 2.2],
            "Max_B": [1.3, 2.4],
            "MM_name": ["MM_66_A", "MM_66_A"],
            "Case": ["C1-1", "C1-1"],
        },
        index=np.array([0.0, 0.002]),
    )
    frame.index.name = "Time (s)"
    sustained = [
        {
            "result": {
                "case": "C1",
                "run": 1,
                "mm_name": "MM_66_A",
                "voltage": "66",
            }
        }
    ]
    high_voltage = [
        {
            "Case": "C1",
            "Run": 1,
            "MM_name": "MM_66_A",
            "Measurement": "LGp",
            "Max_abs": 600.0,
        }
    ]
    return ([
        ("LGp", frame),
        ("__Sustained_SDPF__", sustained),
    ], high_voltage)


def test_project_incremental_cache_setting_defaults_on_and_is_project_local(tmp_path) -> None:
    from results_analysis_app import storage

    first = tmp_path / "first"
    second = tmp_path / "second"

    assert storage.project_incremental_run_data_enabled(first)
    assert storage.project_incremental_run_data_enabled(second)

    storage.set_project_incremental_run_data_enabled(first, False)

    assert not storage.project_incremental_run_data_enabled(first)
    assert storage.project_incremental_run_data_enabled(second)
    assert storage.load_project_analysis_cache(first)["settings"] == {
        storage.PROJECT_DATA_CACHE_SETTING: False
    }


def test_run_data_cache_round_trips_and_rejects_stale_source(tmp_path) -> None:
    from results_analysis_app.envelope_data_cache import RunDataCache

    run_data = _run_data()
    with RunDataCache(tmp_path) as cache:
        cache.put("66\0Case_folder/C1/C1_r00001.inf", "calc-1", "source-1", run_data)

    with RunDataCache(tmp_path) as cache:
        restored = cache.get(
            "66\0Case_folder/C1/C1_r00001.inf",
            "calc-1",
            "source-1",
        )
        stale = cache.get(
            "66\0Case_folder/C1/C1_r00001.inf",
            "calc-1",
            "source-2",
        )

    assert restored is not None
    entries, high_voltage = restored
    assert [measurement for measurement, _value in entries] == [
        "LGp",
        "__Sustained_SDPF__",
    ]
    restored_frame = entries[0][1]
    assert isinstance(restored_frame, pd.DataFrame)
    np.testing.assert_allclose(restored_frame["Max_A"].to_numpy(), [1.1, 2.2], rtol=1e-6)
    assert restored_frame["MM_name"].tolist() == ["MM_66_A", "MM_66_A"]
    assert high_voltage == run_data[1]
    assert stale is None


def test_run_data_cache_keeps_compact_float32_precision_contract() -> None:
    from results_analysis_app import voltage_envelope
    from results_analysis_app.envelope_data_cache import _decode_run_data, _encode_run_data

    frame = pd.DataFrame(
        {
            "Max_A": [123.456789, 987.654321],
            "Max_B": [222.345678, 876.543219],
            "MM_name": ["MM_66_A", "MM_66_A"],
            "Case": ["C1-1", "C1-1"],
        },
        index=np.array([0.0, 0.002]),
    )
    frame.index.name = "Time (s)"
    run_data = ([("LGp", frame)], [])

    payload = _encode_run_data(run_data)
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        assert archive["values_0"].dtype == np.dtype(np.float32)

    restored_entries, _high_voltage = _decode_run_data(payload)
    restored = restored_entries[0][1]
    assert isinstance(restored, pd.DataFrame)
    np.testing.assert_allclose(
        restored[["Max_A", "Max_B"]].to_numpy(),
        frame[["Max_A", "Max_B"]].to_numpy(),
        rtol=0.0,
        atol=1e-4,
    )
    pd.testing.assert_frame_equal(
        voltage_envelope._reduce_merge([frame]),
        voltage_envelope._reduce_merge([restored]),
        check_dtype=False,
    )


def test_run_data_cache_prunes_removed_source_runs(tmp_path) -> None:
    from results_analysis_app.envelope_data_cache import RunDataCache

    run_data = _run_data()
    with RunDataCache(tmp_path) as cache:
        cache.put("keep", "calc", "source", run_data)
        cache.put("remove", "calc", "source", run_data)
        cache.prune({"keep"})

    with RunDataCache(tmp_path) as cache:
        assert cache.get("keep", "calc", "source") is not None
        assert cache.get("remove", "calc", "source") is None

    with RunDataCache(tmp_path) as cache:
        cache.prune(set())

    with RunDataCache(tmp_path) as cache:
        assert cache.get("keep", "calc", "source") is None


def test_corrupt_run_data_cache_is_treated_as_a_miss(tmp_path) -> None:
    from results_analysis_app.envelope_data_cache import RunDataCache

    with RunDataCache(tmp_path) as cache:
        cache.put("corrupt", "calc", "source", _run_data())

    with sqlite3.connect(tmp_path / ".state" / "envelope_data.sqlite3") as connection:
        connection.execute(
            "UPDATE run_data_cache SET payload = ? WHERE cache_key = ?",
            (b"not an npz archive", "corrupt"),
        )
        connection.commit()

    with RunDataCache(tmp_path) as cache:
        assert cache.get("corrupt", "calc", "source") is None


def test_cached_run_data_reapplies_bus_and_high_voltage_filters(tmp_path) -> None:
    from results_analysis_app import voltage_envelope
    from results_analysis_app.exclusions import ExclusionMatcher, ExclusionRule

    def frame(bus: str) -> pd.DataFrame:
        result = pd.DataFrame(
            {"Max_A": [1.0], "MM_name": [bus], "Case": ["C1-1"]},
            index=np.array([0.0]),
        )
        result.index.name = "Time (s)"
        return result

    inf_path = tmp_path / "C1_r00001.inf"
    cached = {
        inf_path: (
            [
                ("LGp", frame("MM_66_A")),
                ("LLp", frame("MM_66_A")),
                ("LGp", frame("MM_66_B")),
                ("LLp", frame("MM_66_B")),
            ],
            [
                {
                    "Case": "C1",
                    "Run": 1,
                    "MM_name": "MM_66_A",
                    "Measurement": "LGp",
                }
            ],
        )
    }

    filtered = voltage_envelope._filter_cached_run_data(
        cached,
        "66",
        ExclusionMatcher([ExclusionRule(bus="MM_66_B")]),
        set(),
    )
    entries, high_voltage = filtered[inf_path]
    assert [value["MM_name"].iloc[0] for _measurement, value in entries] == []
    assert high_voltage[0]["MM_name"] == "MM_66_A"

    included = voltage_envelope._filter_cached_run_data(
        cached,
        "66",
        ExclusionMatcher(),
        {voltage_envelope._high_voltage_key("66", "C1", 1, "MM_66_A")},
    )
    entries, high_voltage = included[inf_path]
    assert [value["MM_name"].iloc[0] for _measurement, value in entries] == [
        "MM_66_A",
        "MM_66_A",
        "MM_66_B",
        "MM_66_B",
    ]
    assert high_voltage == []


def test_settings_checkbox_persists_project_cache_choice(monkeypatch, tmp_path) -> None:
    from PySide6 import QtWidgets

    from results_analysis_app import settings_dialog, storage
    from results_analysis_app.main_window import MainWindow
    from results_analysis_app.models import AppSession

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    project = str(tmp_path.resolve())
    session = AppSession.default()
    session.add_project(project)
    monkeypatch.setattr(storage, "load_autosave", lambda: session)
    monkeypatch.setattr(storage, "save_autosave", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(MainWindow, "refresh_project_scans", lambda *_args, **_kwargs: None)
    window = MainWindow()
    try:
        window._select_project_path(project)
        observed: list[tuple[bool, bool]] = []

        def dialog_exec(dialog) -> int:
            check = next(
                check
                for check in dialog.findChildren(QtWidgets.QCheckBox)
                if check.text() == "Cache analyzed run data"
            )
            observed.append((check.isEnabled(), check.isChecked()))
            check.setChecked(len(observed) != 1)
            return QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(QtWidgets.QDialog, "exec", dialog_exec)
        settings_dialog.edit_settings(window)
        settings_dialog.edit_settings(window)

        assert observed == [(True, True), (True, False)]
        assert storage.project_incremental_run_data_enabled(project)
    finally:
        window.close()
        app.processEvents()


def test_envelope_build_uses_project_cache_and_can_bypass_it(tmp_path, monkeypatch) -> None:
    from results_analysis_app import storage, voltage_envelope
    from results_analysis_app.models import ScopeEntry
    from results_analysis_app.project_config import ProjectTiming, VoltageConfig

    project = tmp_path / "Project"
    run_dir = project / "Case_folder" / "CaseA"
    run_dir.mkdir(parents=True)
    inf_path = run_dir / "C1_r00001.inf"
    out_path = run_dir / "C1_r00001_01.out"
    inf_path.write_text("descriptor", encoding="utf-8")
    out_path.write_text("waveform", encoding="utf-8")

    class InlineExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    class DummyExcelApp:
        def __enter__(self):
            return object()

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    monkeypatch.setattr(voltage_envelope, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(voltage_envelope, "excel_app", DummyExcelApp)
    monkeypatch.setattr(voltage_envelope, "autofit_workbook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voltage_envelope, "_read_stat_files", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(voltage_envelope, "_read_inf_descriptor_cache", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(voltage_envelope, "_selected_inf_paths", lambda *_args, **_kwargs: [inf_path])

    observed_cache_arguments = []

    def fake_build(*_args, **kwargs):
        observed_cache_arguments.append(kwargs["cached_run_data"])
        scope = _args[1][0]
        workbook = project / "Voltage_envelope" / scope.folder / "MM_66.xlsx"
        workbook.parent.mkdir(parents=True, exist_ok=True)
        workbook.write_bytes(b"workbook")
        frame = pd.DataFrame(
            {"Max_A": [1.0], "MM_name": ["MM_66_A"], "Case": ["C1-1"]},
            index=np.array([0.0]),
        )
        frame.index.name = "Time (s)"
        return voltage_envelope._VoltageBuildResult(
            [],
            [],
            [workbook],
            cache_updates={inf_path: ([("LGp", frame)], [])},
        )

    monkeypatch.setattr(voltage_envelope, "_build_voltage_workbooks", fake_build)
    common = {
        "envelope_workers": 1,
        "project_timing": ProjectTiming(frequency=50.0, final_duration=0.1),
        "voltage_configs": {"66": VoltageConfig("66", "MM_66", 72.5)},
        "nonconv_cases": [],
        "build_charts": False,
    }

    voltage_envelope.build_voltage_envelopes(project, [ScopeEntry.full()], ["66"], **common)
    assert observed_cache_arguments[0] == {}
    assert storage.project_envelope_data_cache_path(project).is_file()

    include_scope = ScopeEntry(name="Only C1", mode="include", tokens=["C1"])
    voltage_envelope.build_voltage_envelopes(project, [include_scope], ["66"], **common)
    assert inf_path in observed_cache_arguments[1]

    storage.set_project_incremental_run_data_enabled(project, False)
    exclude_scope = ScopeEntry(name="No C2", mode="exclude", tokens=["C2"])
    voltage_envelope.build_voltage_envelopes(project, [exclude_scope], ["66"], **common)
    assert observed_cache_arguments[2] is None


def test_warm_envelope_build_is_faster_and_keeps_outputs_equivalent(tmp_path, monkeypatch) -> None:
    """Exercise the build orchestration and measure the cache's saved source work.

    The controlled delay represents expensive waveform/source decoding.  The
    assertion is deliberately relative to the same process, while output
    bytes and source-call counts provide the correctness checks.
    """

    from results_analysis_app import storage, voltage_envelope
    from results_analysis_app.models import ScopeEntry
    from results_analysis_app.project_config import ProjectTiming, VoltageConfig

    project = tmp_path / "Project"
    run_dir = project / "Case_folder" / "CaseA"
    run_dir.mkdir(parents=True)
    inf_path = run_dir / "C1_r00001.inf"
    out_path = run_dir / "C1_r00001_01.out"
    inf_path.write_text("descriptor", encoding="utf-8")
    out_path.write_text("waveform", encoding="utf-8")

    class InlineExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    class DummyExcelApp:
        def __enter__(self):
            return object()

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    monkeypatch.setattr(voltage_envelope, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(voltage_envelope, "excel_app", DummyExcelApp)
    monkeypatch.setattr(voltage_envelope, "autofit_workbook", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(voltage_envelope, "_read_stat_files", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(voltage_envelope, "_read_inf_descriptor_cache", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(voltage_envelope, "_selected_inf_paths", lambda *_args, **_kwargs: [inf_path])

    # Keep the run-data cache in the hot path while disabling the separate
    # complete-envelope manifest, which would otherwise skip the whole stage.
    monkeypatch.setattr(voltage_envelope, "_envelope_manifest_payload", lambda *_args, **_kwargs: None)

    source_reads: list[str] = []
    run_data = _run_data()

    def fake_build(*_args, **kwargs):
        cached_run_data = kwargs["cached_run_data"]
        if cached_run_data:
            restored = cached_run_data[inf_path]
        else:
            source_reads.append(str(inf_path))
            time.sleep(0.15)
            restored = run_data

        scope = _args[1][0]
        workbook = project / "Voltage_envelope" / scope.folder / "MM_66.xlsx"
        workbook.parent.mkdir(parents=True, exist_ok=True)
        workbook.write_bytes(b"stable-workbook-output")
        return voltage_envelope._VoltageBuildResult(
            [],
            [],
            [workbook],
            cache_updates={} if cached_run_data else {inf_path: restored},
        )

    monkeypatch.setattr(voltage_envelope, "_build_voltage_workbooks", fake_build)
    common = {
        "envelope_workers": 1,
        "project_timing": ProjectTiming(frequency=50.0, final_duration=0.1),
        "voltage_configs": {"66": VoltageConfig("66", "MM_66", 72.5)},
        "nonconv_cases": [],
        "build_charts": False,
    }

    started = time.perf_counter()
    voltage_envelope.build_voltage_envelopes(project, [ScopeEntry.full()], ["66"], **common)
    cold_seconds = time.perf_counter() - started
    output_path = project / "Voltage_envelope" / ScopeEntry.full().folder / "MM_66.xlsx"
    cold_output = output_path.read_bytes()

    started = time.perf_counter()
    voltage_envelope.build_voltage_envelopes(project, [ScopeEntry.full()], ["66"], **common)
    warm_seconds = time.perf_counter() - started
    warm_output = output_path.read_bytes()

    speedup_percent = (cold_seconds - warm_seconds) / cold_seconds * 100.0
    print(
        "incremental cache benchmark: "
        f"cold={cold_seconds:.3f}s warm={warm_seconds:.3f}s "
        f"speedup={speedup_percent:.1f}% source_reads={len(source_reads)}"
    )

    assert storage.project_envelope_data_cache_path(project).is_file()
    assert source_reads == [str(inf_path)]
    assert warm_output == cold_output
    assert warm_seconds < cold_seconds
    assert speedup_percent > 0.0
