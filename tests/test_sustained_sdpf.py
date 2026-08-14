from __future__ import annotations


def test_sustained_sdpf_uses_one_continuous_window() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import analyze_phase_amplitude

    time = np.arange(0.0, 0.2, 0.001)
    amplitude = np.where((time >= 0.02) & (time < 0.04), 2.0, 0.0)
    result = analyze_phase_amplitude(time, amplitude, "LGp", "A-G", 1.0, 0.03)

    assert abs(result.longest_margin_s - 0.0198) < 1e-5
    assert result.longest_sdpf_s < 0.02
    assert result.classification.startswith("No SDPF")


def test_sustained_sdpf_does_not_add_separate_windows_or_phases() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import (
        analyze_phase_amplitude,
        classify_rows,
        longest_duration_above,
    )

    time = np.arange(0.0, 0.2, 0.001)
    first = np.where((time >= 0.01) & (time < 0.03), 2.0, 0.0)
    second = np.where((time >= 0.05) & (time < 0.08), 2.0, 0.0)
    assert longest_duration_above(time, first + second, 1.0) == 0.03

    phase_a = analyze_phase_amplitude(time, first, "LGp", "A-G", 1.0, 0.04)
    phase_b = analyze_phase_amplitude(time, second, "LGp", "B-G", 1.0, 0.04)
    case = classify_rows("Full", "66", "C1", 1, "MM_66_A", [phase_a, phase_b], 0.04)
    assert case is not None
    assert case.governing.phase in {"A-G", "B-G"}
    assert case.governing.longest_margin_s < 0.04


def test_sustained_sdpf_uses_separate_lg_and_ll_limits() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import (
        SDPFVoltageLimits,
        analyze_bus_waveforms,
    )

    time = np.arange(0.0, 0.3, 0.0002)
    values = [np.sin(2 * np.pi * 50.0 * time) * 2.0]
    limits = SDPFVoltageLimits(66.0, 1.0, 3.0)
    lg = analyze_bus_waveforms("LGp", [time], values, ["MM_LGp_a"], limits, "C1", 1, "MM_66_A", 0.03, 50.0)
    ll = analyze_bus_waveforms("LLp", [time], values, ["MM_LLp_a"], limits, "C1", 1, "MM_66_A", 0.03, 50.0)

    assert lg[0]["sdpf_rms_kv"] == 1.0
    assert ll[0]["sdpf_rms_kv"] == 3.0


def test_sustained_sdpf_50_and_60_hz_tracks_are_frequency_aware() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import analyze_waveform

    for frequency in (50.0, 60.0):
        time = np.arange(0.0, 0.5, 0.0002)
        waveform = np.sin(2 * np.pi * frequency * time) * 2.0
        result = analyze_waveform(time, waveform, "LGp", "A-G", 1.0, 0.1, frequency)
        assert result.sustained_peak_kv > 1.9
        assert result.sustained_ratio > 1.3


def test_sustained_sdpf_settings_follow_tov_without_overwriting_custom_value() -> None:
    from results_analysis_app.sustained_sdpf import SustainedSDPFSettings

    settings = SustainedSDPFSettings(enabled=True, use_tov_setting=True, duration_s=0.02)
    assert settings.effective_duration({"TOV": 0.03}) == 0.03
    independent = SustainedSDPFSettings(enabled=True, use_tov_setting=False, duration_s=0.02)
    assert independent.effective_duration({"TOV": 0.03}) == 0.02


def test_sustained_sdpf_does_not_stitch_nan_gap() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import analyze_waveform

    time = np.arange(0.0, 0.12, 0.001)
    waveform = np.full_like(time, 2.0)
    waveform[(time >= 0.04) & (time < 0.06)] = np.nan
    result = analyze_waveform(time, waveform, "LGp", "A-G", 1.0, 0.07, 50.0)

    assert result.longest_margin_s < 0.07
    assert result.classification.startswith("No SDPF")


def test_sustained_sdpf_does_not_treat_short_tail_as_full_duration() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import highest_sustained_level

    time = np.arange(0.0, 1.01, 0.1)
    values = np.ones_like(time)
    values[-2:] = 100.0

    assert highest_sustained_level(time, values, 0.5) == 1.0


def test_sustained_sdpf_retains_no_margin_case_for_reporting() -> None:
    import numpy as np

    from results_analysis_app.sustained_sdpf import analyze_phase_amplitude, classify_rows

    time = np.arange(0.0, 0.1, 0.001)
    phase = analyze_phase_amplitude(time, np.full_like(time, 0.1), "LGp", "A-G", 1.0, 0.03)

    result = classify_rows("Full", "66", "C1", 1, "MM_66_A", [phase], 0.03)

    assert result is not None
    assert result.governing.classification.startswith("No SDPF")


def test_sustained_sdpf_governing_selection_uses_normalized_ratio() -> None:
    from results_analysis_app.sustained_sdpf import (
        PhaseStressResult,
        SustainedSDPFResult,
        select_governing,
    )

    def phase(ratio: float, peak: float) -> PhaseStressResult:
        return PhaseStressResult("LGp", "A-G", 1.0, 1.414, 0.85, 1.202, 0.1, 0.1, peak, peak / 2**0.5, ratio, "x")

    low_limit_high_kv = SustainedSDPFResult(
        "Full", "66", "C1", 1, "MM_66_A", "", 0.03, phase(1.1, 110.0), (phase(1.1, 110.0),)
    )
    high_limit_lower_kv = SustainedSDPFResult(
        "Full", "161", "C2", 1, "MM_161_A", "", 0.03, phase(1.4, 70.0), (phase(1.4, 70.0),)
    )

    assert select_governing([low_limit_high_kv, high_limit_lower_kv]) is high_limit_lower_kv


def test_sustained_sdpf_invalid_limit_rows_are_reported(tmp_path) -> None:
    from openpyxl import Workbook

    from results_analysis_app.sustained_sdpf import resolve_project_limits

    project = tmp_path / "Project"
    project.mkdir()
    workbook = Workbook()
    workbook.active.title = "MM_blocks"
    sheet = workbook.active
    sheet.append(["Un", "SDPF_LG", "SDPF_LL"])
    sheet.append([66, 1.0, 2.0])
    sheet.append([66, 1.1, 2.0])
    workbook.save(project / "Input_Data_PSCAD_test.xlsx")
    workbook.close()

    limits, warnings = resolve_project_limits(project)

    assert "66" not in limits
    assert any("Inconsistent" in warning for warning in warnings)


def test_sustained_sdpf_invalid_duplicate_limit_skips_voltage(tmp_path) -> None:
    from openpyxl import Workbook

    from results_analysis_app.sustained_sdpf import resolve_project_limits

    project = tmp_path / "Project"
    project.mkdir()
    workbook = Workbook()
    workbook.active.title = "MM_blocks"
    sheet = workbook.active
    sheet.append(["Un", "SDPF_LG", "SDPF_LL"])
    sheet.append([66, 1.0, 2.0])
    sheet.append([66, "bad", 2.0])
    workbook.save(project / "Input_Data_PSCAD_test.xlsx")
    workbook.close()

    limits, warnings = resolve_project_limits(project)

    assert "66" not in limits
    assert any("Invalid SDPF values for 66 kV" in warning for warning in warnings)


def test_sustained_sdpf_result_manifest_marks_source_change_stale(tmp_path) -> None:
    from results_analysis_app.sustained_sdpf import result_inputs_current

    source = tmp_path / "run.out"
    source.write_text("before", encoding="utf-8")
    stat = source.stat()
    payload = {
        "signature_inputs": {
            "66": {
                "files": [{"path": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}]
            }
        }
    }

    assert result_inputs_current(payload, "66")
    source.write_text("after", encoding="utf-8")
    assert not result_inputs_current(payload, "66")


def test_sustained_sdpf_report_section_is_compact() -> None:
    from docx import Document

    from results_analysis_app.reporting import _FigureRegistry, _add_sustained_sdpf_section
    from results_analysis_app.sustained_sdpf import PhaseStressResult, SustainedSDPFResult

    phase = PhaseStressResult(
        "LGp", "A-G", 1.0, 2**0.5, 0.85, 0.85 * 2**0.5,
        0.04, 0.02, 1.5, 1.5 / 2**0.5, 1.5 / 2**0.5, "margin",
    )
    result = SustainedSDPFResult(
        "Full", "66", "C1", 1, "MM_66_A", "AG", 0.03, phase, (phase,)
    )
    document = Document()

    _add_sustained_sdpf_section(document, result, "66", None, _FigureRegistry())

    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Sustained SDPF stress" in text
    assert "Duration criterion" in text
    assert "Highest" in text
    assert "safety margin" in text
    assert len(document.tables) == 1


def test_sustained_sdpf_build_reuses_loaded_run_and_persists_json(tmp_path, monkeypatch) -> None:
    import numpy as np
    from openpyxl import Workbook

    from results_analysis_app.models import ScopeEntry
    from results_analysis_app import voltage_envelope
    from results_analysis_app.voltage_envelope import build_voltage_envelopes

    class DummyExcel:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(voltage_envelope, "excel_app", DummyExcel)
    monkeypatch.setattr(voltage_envelope, "autofit_workbook", lambda *_args: None)

    project = tmp_path / "Project"
    case_folder = project / "Case_folder"
    case_folder.mkdir(parents=True)
    inf_path = case_folder / "C1_r00001.inf"
    inf_path.write_text(
        "\n".join(
            [
                'PGB(1) Output Desc="MM_LGp_a" Group="MM_66_A" Units="kV"',
                'PGB(2) Output Desc="MM_LGp_b" Group="MM_66_A" Units="kV"',
                'PGB(3) Output Desc="MM_LGp_c" Group="MM_66_A" Units="kV"',
                'PGB(4) Output Desc="MM_LLp_a" Group="MM_66_A" Units="kV"',
                'PGB(5) Output Desc="MM_LLp_b" Group="MM_66_A" Units="kV"',
                'PGB(6) Output Desc="MM_LLp_c" Group="MM_66_A" Units="kV"',
            ]
        ),
        encoding="utf-8",
    )
    time = np.arange(0.0, 0.2, 0.0002)
    amplitude = np.where((time >= 0.03) & (time < 0.1), 2.0, 0.4)
    lines = ["header"]
    for index, time_s in enumerate(time):
        values = [time_s]
        values.extend(float(amplitude[index] * np.sin(2 * np.pi * 50 * time_s + phase)) for phase in (0.0, 2.1, 4.2))
        values.extend(float(amplitude[index] * np.sin(2 * np.pi * 50 * time_s + phase)) for phase in (0.0, 2.1, 4.2))
        lines.append(" ".join(f"{value:.12g}" for value in values))
    inf_path.with_name("C1_r00001_01.out").write_text("\n".join(lines), encoding="utf-8")

    workbook = Workbook()
    input_data = workbook.active
    input_data.title = "Input_Data"
    input_data.append(["Frequency", 50.0])
    input_data.append(["Final duration", 0.2])
    mm_blocks = workbook.create_sheet("MM_blocks")
    mm_blocks.append(["Group", "Un", "Um", "SDPF_LG", "SDPF_LL", "SIWL_LG", "SIWL_LL"])
    mm_blocks.append(["MM_66_A", 66.0, 72.5, 1.0, 1.0, 1.0, 1.0])
    workbook.save(project / "Input_Data_PSCAD_test.xlsx")
    workbook.close()

    build_voltage_envelopes(
        project,
        [ScopeEntry.full()],
        ["66"],
        log=None,
        envelope_workers=1,
        build_charts=False,
        sustained_sdpf_settings={"enabled": True, "use_tov_setting": False, "duration_s": 0.03},
    )

    result_path = project / "Voltage_envelope" / "Full" / "Sustained_SDpf.json"
    assert result_path.is_file()
    payload = result_path.read_text(encoding="utf-8")
    assert '"66"' in payload
    assert not list((project / "Voltage_envelope" / "Full").glob("*Sustained*.xlsx"))
