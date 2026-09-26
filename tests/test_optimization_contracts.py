from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _plot_plan(project: Path, inf_path: Path, event_name: str = "SFO"):
    from pscad_plotter_app_v3.models import PlotJob, PlotMode
    from results_analysis_app import analysis_engine

    output_dir = project / "Plots" / "Generated" / "Full" / event_name
    output_dir.mkdir(parents=True, exist_ok=True)
    job = PlotJob(
        mode=PlotMode.MM,
        case_name="C1",
        run_number=1,
        group_label="MM_66_A",
        output_dir=str(output_dir),
        voltage_kv=66.0,
    )
    plan = analysis_engine._PlotBatchPlan(
        project_root=project,
        batch_file=project / "Plots" / "Plot_batch" / f"batch_paste_Full_{event_name}.xlsx",
        event_name=event_name,
        output_dir=output_dir,
        stage_dir=output_dir,
        jobs=[job],
    )
    renderer = SimpleNamespace(run_index={"C1": {1: inf_path}})
    return plan, renderer


def test_plot_source_manifest_tracks_relevant_files_only(tmp_path) -> None:
    from results_analysis_app import analysis_engine

    project = tmp_path / "Project"
    run_dir = project / "Case_folder" / "CaseA"
    run_dir.mkdir(parents=True)
    inf_path = run_dir / "C1_r00001.inf"
    waveform_path = run_dir / "C1_r00001_01.out"
    statistic_path = run_dir / "Statistic1.out"
    unrelated_path = run_dir / "unrelated.out"
    for path in (inf_path, waveform_path, statistic_path, unrelated_path):
        path.write_text(path.name, encoding="utf-8")

    plan, renderer = _plot_plan(project, inf_path)
    manifest = analysis_engine._plot_source_manifest(project, renderer, plan.jobs)
    paths = {entry["path"] for entry in manifest}

    assert paths == {
        inf_path.relative_to(project).as_posix(),
        waveform_path.relative_to(project).as_posix(),
        statistic_path.relative_to(project).as_posix(),
    }

    signature = analysis_engine._plot_signature(plan, renderer)
    unrelated_path.write_text("changed unrelated source", encoding="utf-8")
    assert analysis_engine._plot_signature(plan, renderer) == signature

    waveform_path.write_text("changed waveform source", encoding="utf-8")
    assert analysis_engine._plot_signature(plan, renderer) != signature


def test_plot_source_manifest_cache_scans_a_run_directory_once(tmp_path, monkeypatch) -> None:
    from results_analysis_app import analysis_engine

    project = tmp_path / "Project"
    run_dir = project / "Case_folder" / "CaseA"
    run_dir.mkdir(parents=True)
    inf_path = run_dir / "C1_r00001.inf"
    inf_path.write_text("descriptor", encoding="utf-8")
    (run_dir / "C1_r00001_01.out").write_text("waveform", encoding="utf-8")
    plan, renderer = _plot_plan(project, inf_path)

    original_iterdir = Path.iterdir
    scan_count = 0

    def counted_iterdir(path):
        nonlocal scan_count
        if path == run_dir:
            scan_count += 1
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", counted_iterdir)
    source_manifest_cache = {}

    first = analysis_engine._plot_source_manifest(
        project,
        renderer,
        plan.jobs,
        source_manifest_cache,
    )
    second = analysis_engine._plot_source_manifest(
        project,
        renderer,
        plan.jobs,
        source_manifest_cache,
    )

    assert first == second
    assert scan_count == 1


def test_plot_cache_rejects_changed_source_and_missing_output(tmp_path) -> None:
    from results_analysis_app import analysis_engine

    project = tmp_path / "Project"
    run_dir = project / "Case_folder" / "CaseA"
    run_dir.mkdir(parents=True)
    inf_path = run_dir / "C1_r00001.inf"
    waveform_path = run_dir / "C1_r00001_01.out"
    unrelated_path = run_dir / "unrelated.out"
    inf_path.write_text("descriptor", encoding="utf-8")
    waveform_path.write_text("waveform", encoding="utf-8")
    unrelated_path.write_text("unrelated", encoding="utf-8")

    plan, renderer = _plot_plan(project, inf_path)
    output_path = plan.output_dir / "plot.png"
    output_path.write_bytes(b"plot")
    output = SimpleNamespace(png_path=output_path, excel_path=None)
    analysis_engine._write_plot_manifest(plan, renderer, [output])

    assert analysis_engine._plot_manifest_matches(plan, renderer)

    unrelated_path.write_text("changed unrelated", encoding="utf-8")
    assert analysis_engine._plot_manifest_matches(plan, renderer)

    waveform_path.write_text("changed waveform", encoding="utf-8")
    assert not analysis_engine._plot_manifest_matches(plan, renderer)

    waveform_path.write_text("waveform", encoding="utf-8")
    output_path.write_bytes(b"plot")
    analysis_engine._write_plot_manifest(plan, renderer, [output])
    assert analysis_engine._plot_manifest_matches(plan, renderer)

    output_path.unlink()
    assert not analysis_engine._plot_manifest_matches(plan, renderer)


def test_envelope_cache_skips_valid_build_and_rebuilds_after_source_change(
    tmp_path, monkeypatch
) -> None:
    import pandas as pd

    from results_analysis_app import voltage_envelope
    from results_analysis_app.models import ScopeEntry
    from results_analysis_app.project_config import ProjectTiming

    project = tmp_path / "Project"
    run_dir = project / "Case_folder" / "CaseA"
    run_dir.mkdir(parents=True)
    inf_path = run_dir / "C1_r00001.inf"
    waveform_path = run_dir / "C1_r00001_01.out"
    inf_path.write_text("descriptor", encoding="utf-8")
    waveform_path.write_text("waveform", encoding="utf-8")

    class InlineExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    monkeypatch.setattr(voltage_envelope, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(
        voltage_envelope,
        "_read_stat_files",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(
        voltage_envelope,
        "_read_inf_descriptor_cache",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        voltage_envelope,
        "_selected_inf_paths",
        lambda *_args, **_kwargs: [inf_path],
    )

    class DummyExcelApp:
        def __enter__(self):
            return object()

        def __exit__(self, _exc_type, _exc, _tb) -> bool:
            return False

    monkeypatch.setattr(voltage_envelope, "excel_app", DummyExcelApp)
    monkeypatch.setattr(voltage_envelope, "autofit_workbook", lambda *_args, **_kwargs: None)

    build_calls = 0

    def fake_build(*_args, **_kwargs):
        nonlocal build_calls
        build_calls += 1
        workbook = project / "Voltage_envelope" / "Full" / "MM_66.xlsx"
        workbook.parent.mkdir(parents=True, exist_ok=True)
        workbook.write_bytes(b"calculation workbook")
        return voltage_envelope._VoltageBuildResult([], [], [workbook])

    monkeypatch.setattr(voltage_envelope, "_build_voltage_workbooks", fake_build)
    logs: list[str] = []
    kwargs = {
        "envelope_workers": 1,
        "project_timing": ProjectTiming(final_duration=0.1),
        "voltage_configs": {},
        "nonconv_cases": [],
        "build_charts": False,
        "log": logs.append,
    }

    first = voltage_envelope.build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66"],
        **kwargs,
    )
    second = voltage_envelope.build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66"],
        **kwargs,
    )

    assert first == [project / "Voltage_envelope" / "Full" / "MM_66.xlsx"]
    assert second == first
    assert build_calls == 1

    generated_output = project / "Plots" / "Generated" / "Full" / "unrelated.png"
    generated_output.parent.mkdir(parents=True, exist_ok=True)
    generated_output.write_bytes(b"presentation-only output")
    voltage_envelope.build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66"],
        **kwargs,
    )
    assert build_calls == 1

    presentation_kwargs = {**kwargs, "build_charts": True}
    voltage_envelope.build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66"],
        **presentation_kwargs,
    )
    assert build_calls == 1
    assert any("Reused envelope calculations" in message for message in logs)

    waveform_path.write_text("changed waveform", encoding="utf-8")
    rebuilt = voltage_envelope.build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66"],
        **presentation_kwargs,
    )

    assert rebuilt == []
    assert build_calls == 2
