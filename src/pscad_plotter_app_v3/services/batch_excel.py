from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from pscad_plotter_app_v3.models import (
    CBElementRecord,
    DEFAULT_TOV_WINDOW_COUNT,
    DEFAULT_TOV_WINDOW_S,
    DEFAULT_FFT_BASE_FREQUENCY_HZ,
    DEFAULT_FFT_HARMONICS,
    DEFAULT_FFT_MAX_HARMONIC,
    DEFAULT_FFT_OUTPUTS,
    FFT_MAGNITUDE_PEAK,
    FFT_MAGNITUDE_RMS,
    FFT_OUTPUT_DC,
    FFT_OUTPUT_MAGNITUDES,
    FFT_OUTPUT_PHASE_ANGLES,
    FFT_PHASE_DEGREES,
    FFT_PHASE_RADIANS,
    FFT_REFERENCE_COSINE,
    FFT_REFERENCE_SINE,
    MMElementRecord,
    PlotMode,
    PlotRequest,
    ProjectCatalog,
    SignalReference,
    SignalGroupRecord,
)
from pscad_plotter_app_v3.services.project_conventions import ALL_FAULTS_LABEL
from pscad_plotter_app_v3.services.fft import FFT_MAX_HARMONIC_CHOICES, parse_harmonic_selection
from pscad_plotter_app_v3.services.signal_classification import is_any_rms_signal


@dataclass(slots=True)
class BatchExcelError:
    row_number: int
    message: str
    sheet_name: str = ""


@dataclass(slots=True)
class BatchExcelImportResult:
    requests: list[PlotRequest]
    errors: list[BatchExcelError]


class BatchExcelService:
    """Import batch definitions from the user-facing Excel row format."""

    MM_SHEET = "MM"
    CB_SHEET = "CB"
    ANY_SHEET = "ANY"
    FFT_SHEET = "FFT"
    COMB_SHEET = "COMB"
    TIME_RANGE_HEADERS = ["time_start_s", "time_end_s"]
    MM_HEADERS = ["case", "run", "element", "trace", "overview", "tov_windows", "tov_window_s", "tov_window_count", "limits", "legends_left", "excel_export", *TIME_RANGE_HEADERS]
    CB_HEADERS = ["case", "run", "element", "overview", "tov_windows", "tov_window_s", "tov_window_count", "legends_left", "excel_export", *TIME_RANGE_HEADERS]
    ANY_HEADERS = ["case", "run", "group", "signal", "view", "y_axis", "overview", "tov_windows", "tov_window_s", "tov_window_count", "legends_left", "annotate_max", "annotate_min", "excel_export", *TIME_RANGE_HEADERS]
    FFT_HEADERS = ["case", "run", "group", "signal", "outputs", "base_frequency_hz", "max_harmonic", "harmonics", "magnitude", "phase_units", "phase_reference", "y_axis", "excel_export", *TIME_RANGE_HEADERS]
    COMB_HEADERS = ["case", "run", "signals", "y_axis", "y_axis_right", "excel_export", *TIME_RANGE_HEADERS]
    SHEET_DEFINITIONS = {
        MM_SHEET: (PlotMode.MM, MM_HEADERS),
        CB_SHEET: (PlotMode.CB, CB_HEADERS),
        ANY_SHEET: (PlotMode.ANY, ANY_HEADERS),
        FFT_SHEET: (PlotMode.FFT, FFT_HEADERS),
        COMB_SHEET: (PlotMode.COMB, COMB_HEADERS),
    }

    def load_requests(self, path: str | Path, catalog: ProjectCatalog) -> BatchExcelImportResult:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            requests: list[PlotRequest] = []
            errors: list[BatchExcelError] = []
            for sheet_name, (mode, _headers) in self.SHEET_DEFINITIONS.items():
                if sheet_name not in workbook.sheetnames:
                    if sheet_name in {self.FFT_SHEET, self.COMB_SHEET}:
                        continue
                    errors.append(BatchExcelError(1, f"Missing required sheet '{sheet_name}'.", sheet_name))
                    continue
                sheet = workbook[sheet_name]
                rows = list(sheet.iter_rows(values_only=True))
                if not rows:
                    errors.append(BatchExcelError(1, "Missing header row.", sheet_name))
                    continue
                header_map = self._header_map(rows[0])
                missing_headers = [header for header in self._required_headers(mode) if header not in header_map]
                if missing_headers:
                    errors.append(BatchExcelError(1, f"Missing required column(s): {', '.join(missing_headers)}.", sheet_name))
                    continue
                for index, values in enumerate(rows[1:], start=2):
                    if self._row_is_empty(values):
                        continue
                    row = {
                        name: self._cell_text(values[position] if position < len(values) else None)
                        for name, position in header_map.items()
                    }
                    try:
                        requests.append(self._request_from_row(row, catalog, mode))
                    except ValueError as exc:
                        errors.append(BatchExcelError(index, str(exc), sheet_name))
        finally:
            workbook.close()
        return BatchExcelImportResult(requests, errors)

    def _request_from_row(self, row: dict[str, str], catalog: ProjectCatalog, mode: PlotMode) -> PlotRequest:
        case_name = row.get("case", "").strip()
        run_number = self._parse_run(row.get("run", ""))
        if not case_name:
            raise ValueError("Missing case.")
        if case_name not in catalog.runs_by_case:
            raise ValueError(f"Unknown case '{case_name}'.")
        if run_number not in set(catalog.runs_by_case.get(case_name, [])):
            raise ValueError(f"Run {run_number} is not available for case '{case_name}'.")

        if mode is PlotMode.MM:
            return self._mm_request(row, catalog, case_name, run_number)
        if mode is PlotMode.CB:
            return self._cb_request(row, catalog, case_name, run_number)
        if mode is PlotMode.FFT:
            return self._fft_request(row, catalog, case_name, run_number)
        if mode is PlotMode.COMB:
            return self._comb_request(row, catalog, case_name, run_number)
        return self._any_request(row, catalog, case_name, run_number)

    def _mm_request(self, row: dict[str, str], catalog: ProjectCatalog, case_name: str, run_number: int) -> PlotRequest:
        element = row.get("element", "").strip()
        if not element:
            raise ValueError("Missing MM element.")
        record = self._find_mm_record(catalog.mm_elements, case_name, run_number, element)
        if record is None:
            raise ValueError(f"MM element '{element}' is not available for {case_name} Run {run_number}.")
        return PlotRequest(
            mode=PlotMode.MM,
            case_name=case_name,
            run_numbers=[run_number],
            elements=[element],
            voltage_kv=record.voltage_kv,
            trace_type=self._parse_trace(row.get("trace", "")),
            fault_filter=self._fault_filter(catalog, case_name, run_number),
            show_three_phase_overview=self._parse_bool(row.get("overview", ""), default=True),
            show_tov_windows=self._parse_bool(row.get("tov_windows", ""), default=True),
            tov_window_s=self._parse_float(row.get("tov_window_s", ""), default=DEFAULT_TOV_WINDOW_S),
            tov_window_count=self._parse_int(row.get("tov_window_count", ""), default=DEFAULT_TOV_WINDOW_COUNT),
            show_limits=self._parse_bool(row.get("limits", ""), default=True),
            legends_left=self._parse_bool(row.get("legends_left", ""), default=False),
            excel_export=self._parse_bool(row.get("excel_export", ""), default=False),
            **self._time_range_kwargs(row),
        )

    def _cb_request(self, row: dict[str, str], catalog: ProjectCatalog, case_name: str, run_number: int) -> PlotRequest:
        element = row.get("element", "").strip()
        if not element:
            raise ValueError("Missing CB element.")
        if self._find_cb_record(catalog.cb_elements, case_name, run_number, element) is None:
            raise ValueError(f"CB element '{element}' is not available for {case_name} Run {run_number}.")
        return PlotRequest(
            mode=PlotMode.CB,
            case_name=case_name,
            run_numbers=[run_number],
            elements=[element],
            fault_filter=self._fault_filter(catalog, case_name, run_number),
            show_three_phase_overview=self._parse_bool(row.get("overview", ""), default=True),
            show_tov_windows=self._parse_bool(row.get("tov_windows", ""), default=True),
            tov_window_s=self._parse_float(row.get("tov_window_s", ""), default=DEFAULT_TOV_WINDOW_S),
            tov_window_count=self._parse_int(row.get("tov_window_count", ""), default=DEFAULT_TOV_WINDOW_COUNT),
            legends_left=self._parse_bool(row.get("legends_left", ""), default=False),
            excel_export=self._parse_bool(row.get("excel_export", ""), default=False),
            **self._time_range_kwargs(row),
        )

    def _any_request(self, row: dict[str, str], catalog: ProjectCatalog, case_name: str, run_number: int) -> PlotRequest:
        group = row.get("group", "").strip()
        signal = row.get("signal", "").strip()
        if not group:
            raise ValueError("Missing Any group.")
        if not signal:
            raise ValueError("Missing Any signal.")
        record = self._find_signal_record(catalog, case_name, run_number, group, signal, row.get("view", ""))
        if record is None:
            raise ValueError(f"Any signal '{group} / {signal}' is not available for {case_name} Run {run_number}.")
        is_bundle = record.signal_view == "bundle"
        supports_rms_annotations = is_any_rms_signal(group, signal)
        show_overview = self._parse_bool(row.get("overview", ""), default=True) if is_bundle else False
        show_tov_windows = self._parse_bool(row.get("tov_windows", ""), default=True) if is_bundle else False
        return PlotRequest(
            mode=PlotMode.ANY,
            case_name=case_name,
            run_numbers=[run_number],
            elements=[],
            fault_filter=self._fault_filter(catalog, case_name, run_number),
            any_group=group,
            signals=[signal],
            any_signal_view=record.signal_view,
            custom_y_axis_name=self._parse_y_axis(row),
            show_three_phase_overview=show_overview,
            show_tov_windows=show_tov_windows,
            tov_window_s=self._parse_float(row.get("tov_window_s", ""), default=DEFAULT_TOV_WINDOW_S),
            tov_window_count=self._parse_int(row.get("tov_window_count", ""), default=DEFAULT_TOV_WINDOW_COUNT),
            legends_left=self._parse_bool(row.get("legends_left", ""), default=False),
            annotate_max=supports_rms_annotations and not show_overview and self._parse_bool(row.get("annotate_max", ""), default=False),
            annotate_min=supports_rms_annotations and not show_overview and self._parse_bool(row.get("annotate_min", ""), default=False),
            excel_export=self._parse_bool(row.get("excel_export", ""), default=False),
            **self._time_range_kwargs(row),
        )

    def _fft_request(self, row: dict[str, str], catalog: ProjectCatalog, case_name: str, run_number: int) -> PlotRequest:
        group = row.get("group", "").strip()
        signal = row.get("signal", "").strip()
        if not group:
            raise ValueError("Missing FFT group.")
        if not signal:
            raise ValueError("Missing FFT signal.")
        if self._find_individual_signal_record(catalog, case_name, run_number, group, signal) is None:
            raise ValueError(f"FFT signal '{group} / {signal}' is not available for {case_name} Run {run_number}.")
        max_harmonic = self._parse_max_harmonic(row.get("max_harmonic", ""))
        harmonics = row.get("harmonics", "").strip() or DEFAULT_FFT_HARMONICS
        parse_harmonic_selection(harmonics, max_harmonic)
        return PlotRequest(
            mode=PlotMode.FFT,
            case_name=case_name,
            run_numbers=[run_number],
            elements=[],
            fault_filter=self._fault_filter(catalog, case_name, run_number),
            any_group=group,
            signals=[signal],
            any_signal_view="individual",
            fft_outputs=self._parse_fft_outputs(row.get("outputs", "")),
            fft_base_frequency_hz=self._parse_fft_base_frequency(row.get("base_frequency_hz", "")),
            fft_max_harmonic=max_harmonic,
            fft_harmonics=harmonics,
            fft_magnitude=self._parse_fft_magnitude(row.get("magnitude", "")),
            fft_phase_units=self._parse_fft_phase_units(row.get("phase_units", "")),
            fft_phase_reference=self._parse_fft_phase_reference(row.get("phase_reference", "")),
            custom_y_axis_name=self._parse_y_axis(row),
            excel_export=self._parse_bool(row.get("excel_export", ""), default=False),
            **self._time_range_kwargs(row),
        )

    def _comb_request(self, row: dict[str, str], catalog: ProjectCatalog, case_name: str, run_number: int) -> PlotRequest:
        signals = self._parse_combined_signals(row.get("signals", ""), catalog, case_name, run_number)
        if len(signals) < 2:
            raise ValueError("Combined plot requires at least 2 signals.")
        if len({signal.unit.strip() for signal in signals}) > 2:
            raise ValueError("Combined plot supports up to 2 units.")
        return PlotRequest(
            mode=PlotMode.COMB,
            case_name=case_name,
            run_numbers=[run_number],
            elements=[],
            fault_filter=self._fault_filter(catalog, case_name, run_number),
            combined_signals=signals,
            custom_y_axis_name=self._parse_y_axis(row),
            custom_y_axis_name_right=self._parse_y_axis(row, "y_axis_right"),
            excel_export=self._parse_bool(row.get("excel_export", ""), default=False),
            **self._time_range_kwargs(row),
        )

    @staticmethod
    def _parse_y_axis(row: dict[str, str], name: str = "y_axis") -> str | None:
        if name not in row:
            return None
        return row.get(name, "").strip()

    @staticmethod
    def _parse_run(value: str) -> int:
        try:
            run_number = int(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid run '{value}'.")
        if run_number < 1:
            raise ValueError("Run must be 1 or greater.")
        return run_number

    @staticmethod
    def _parse_trace(value: str) -> str:
        token = value.strip()
        if not token:
            return "Both"
        normalized = token.lower().replace(" ", "")
        if normalized in {"both", "combined", "combinedlgp&llp", "combinedlgpllp"}:
            return "Both"
        if normalized == "lgp":
            return "LGp"
        if normalized == "llp":
            return "LLp"
        raise ValueError(f"Invalid MM trace '{value}'. Use Both, LGp, or LLp.")

    @staticmethod
    def _parse_bool(value: str, *, default: bool) -> bool:
        token = value.strip().lower()
        if not token:
            return default
        if token in {"1", "true", "yes", "y", "on"}:
            return True
        if token in {"0", "false", "no", "n", "off"}:
            return False
        raise ValueError(f"Invalid boolean value '{value}'.")

    @staticmethod
    def _parse_float(value: str, *, default: float) -> float:
        token = value.strip()
        if not token:
            return default
        try:
            return float(token)
        except ValueError:
            raise ValueError(f"Invalid numeric value '{value}'.")

    @classmethod
    def _time_range_kwargs(cls, row: dict[str, str]) -> dict[str, float | None]:
        start_s = cls._parse_optional_float(row.get("time_start_s", ""), "time_start_s")
        end_s = cls._parse_optional_float(row.get("time_end_s", ""), "time_end_s")
        if start_s is not None and end_s is not None and end_s <= start_s:
            raise ValueError("time_end_s must be greater than time_start_s.")
        return {"time_start_s": start_s, "time_end_s": end_s}

    @staticmethod
    def _parse_optional_float(value: str, column_name: str) -> float | None:
        token = value.strip()
        if not token:
            return None
        try:
            return float(token)
        except ValueError:
            raise ValueError(f"Invalid numeric value in '{column_name}': '{value}'.")

    @staticmethod
    def _parse_int(value: str, *, default: int) -> int:
        token = value.strip()
        if not token:
            return default
        try:
            parsed = int(float(token))
        except ValueError:
            raise ValueError(f"Invalid integer value '{value}'.")
        if parsed < 1:
            raise ValueError("TOV window count must be 1 or greater.")
        return parsed

    @staticmethod
    def _parse_max_harmonic(value: str) -> int:
        token = value.strip()
        if not token:
            return DEFAULT_FFT_MAX_HARMONIC
        try:
            parsed = int(float(token))
        except ValueError:
            raise ValueError(f"Invalid max harmonic '{value}'.")
        if parsed not in FFT_MAX_HARMONIC_CHOICES:
            raise ValueError(f"Max harmonic must be one of: {', '.join(str(item) for item in FFT_MAX_HARMONIC_CHOICES)}.")
        return parsed

    @staticmethod
    def _parse_fft_outputs(value: str) -> list[str]:
        token = value.strip()
        if not token:
            return DEFAULT_FFT_OUTPUTS.copy()
        aliases = {
            "magnitudes": FFT_OUTPUT_MAGNITUDES,
            "magnitude": FFT_OUTPUT_MAGNITUDES,
            "harmonicmagnitudes": FFT_OUTPUT_MAGNITUDES,
            "harmonic_magnitudes": FFT_OUTPUT_MAGNITUDES,
            "phase": FFT_OUTPUT_PHASE_ANGLES,
            "phases": FFT_OUTPUT_PHASE_ANGLES,
            "phaseangles": FFT_OUTPUT_PHASE_ANGLES,
            "phase_angles": FFT_OUTPUT_PHASE_ANGLES,
            "harmonicphaseangles": FFT_OUTPUT_PHASE_ANGLES,
            "dc": FFT_OUTPUT_DC,
            "dccomponent": FFT_OUTPUT_DC,
            "dc_component": FFT_OUTPUT_DC,
        }
        outputs: list[str] = []
        for part in token.replace(";", ",").split(","):
            key = part.strip().lower().replace(" ", "").replace("-", "_")
            if not key:
                continue
            output = aliases.get(key)
            if output is None:
                raise ValueError(f"Invalid FFT output '{part.strip()}'.")
            if output not in outputs:
                outputs.append(output)
        if not outputs:
            raise ValueError("Select at least one FFT output.")
        return outputs

    @staticmethod
    def _parse_fft_base_frequency(value: str) -> float:
        token = value.strip()
        if not token:
            return DEFAULT_FFT_BASE_FREQUENCY_HZ
        try:
            parsed = float(token)
        except ValueError:
            raise ValueError(f"Invalid FFT base frequency '{value}'. Use 50 or 60.")
        if parsed not in {50.0, 60.0}:
            raise ValueError("FFT base frequency must be 50 or 60 Hz.")
        return parsed

    @staticmethod
    def _parse_fft_magnitude(value: str) -> str:
        token = value.strip().lower()
        if not token:
            return FFT_MAGNITUDE_RMS
        if token == "rms":
            return FFT_MAGNITUDE_RMS
        if token == "peak":
            return FFT_MAGNITUDE_PEAK
        raise ValueError(f"Invalid FFT magnitude '{value}'. Use RMS or Peak.")

    @staticmethod
    def _parse_fft_phase_units(value: str) -> str:
        token = value.strip().lower()
        if not token:
            return FFT_PHASE_DEGREES
        if token in {"degrees", "degree", "deg"}:
            return FFT_PHASE_DEGREES
        if token in {"radians", "radian", "rad"}:
            return FFT_PHASE_RADIANS
        raise ValueError(f"Invalid FFT phase units '{value}'. Use Degrees or Radians.")

    @staticmethod
    def _parse_fft_phase_reference(value: str) -> str:
        token = value.strip().lower()
        if not token:
            return FFT_REFERENCE_SINE
        if token == "sine":
            return FFT_REFERENCE_SINE
        if token == "cosine":
            return FFT_REFERENCE_COSINE
        raise ValueError(f"Invalid FFT phase reference '{value}'. Use Sine or Cosine.")

    @classmethod
    def _parse_combined_signals(
        cls,
        value: str,
        catalog: ProjectCatalog,
        case_name: str,
        run_number: int,
    ) -> list[SignalReference]:
        token = value.strip()
        if not token:
            raise ValueError("Missing combined signals.")
        signals: list[SignalReference] = []
        for part in token.split(";"):
            item = part.strip()
            if not item:
                continue
            pieces = [piece.strip() for piece in item.split("|")]
            if len(pieces) == 2:
                source_case_name = case_name
                source_run_number = run_number
                group_name, signal_name = pieces
            elif len(pieces) == 4:
                source_case_name = pieces[0]
                try:
                    source_run_number = cls._parse_run(pieces[1])
                except ValueError:
                    raise ValueError(f"Invalid combined signal source run '{pieces[1]}'.")
                group_name, signal_name = pieces[2], pieces[3]
            else:
                raise ValueError("Combined signals must use 'Group|Signal' or 'Case|Run|Group|Signal' format.")
            if not source_case_name or not group_name or not signal_name:
                raise ValueError("Combined signals must use 'Group|Signal' or 'Case|Run|Group|Signal' format.")
            if source_case_name not in catalog.runs_by_case:
                raise ValueError(f"Unknown combined signal source case '{source_case_name}'.")
            if source_run_number not in set(catalog.runs_by_case.get(source_case_name, [])):
                raise ValueError(f"Combined signal source run {source_run_number} is not available for case '{source_case_name}'.")
            record = cls._find_individual_signal_record(catalog, source_case_name, source_run_number, group_name, signal_name)
            if record is None:
                raise ValueError(f"Combined signal '{group_name} / {signal_name}' is not available for {source_case_name} Run {source_run_number}.")
            signal_ref = SignalReference(record.group_name, record.signal_name, record.unit, source_case_name, source_run_number)
            if signal_ref not in signals:
                signals.append(signal_ref)
        return signals

    @staticmethod
    def _find_mm_record(records: list[MMElementRecord], case_name: str, run_number: int, element: str) -> MMElementRecord | None:
        for record in records:
            if record.case_name == case_name and record.element_name == element and run_number in set(record.available_runs):
                return record
        return None

    @staticmethod
    def _find_cb_record(records: list[CBElementRecord], case_name: str, run_number: int, element: str) -> CBElementRecord | None:
        for record in records:
            if record.case_name == case_name and record.element_name == element and run_number in set(record.available_runs):
                return record
        return None

    @staticmethod
    def _find_signal_record(
        catalog: ProjectCatalog,
        case_name: str,
        run_number: int,
        group: str,
        signal: str,
        view: str,
    ) -> SignalGroupRecord | None:
        records = [
            record
            for record in catalog.channel_groups_by_case_run.get(case_name, {}).get(run_number, [])
            if record.group_name == group and record.signal_name == signal
        ]
        view_token = view.strip().lower()
        if view_token:
            records = [record for record in records if record.signal_view.lower() == view_token]
        if not records:
            return None
        for record in records:
            if record.signal_view == "bundle":
                return record
        return records[0]

    @staticmethod
    def _find_individual_signal_record(
        catalog: ProjectCatalog,
        case_name: str,
        run_number: int,
        group: str,
        signal: str,
    ) -> SignalGroupRecord | None:
        for record in catalog.channel_groups_by_case_run.get(case_name, {}).get(run_number, []):
            if record.group_name == group and record.signal_name == signal and record.signal_view == "individual":
                return record
        return None

    @staticmethod
    def _fault_filter(catalog: ProjectCatalog, case_name: str, run_number: int) -> str:
        metadata = catalog.run_metadata_by_case.get(case_name, {}).get(run_number)
        if metadata is None or metadata.fault_label == "No fault":
            return ALL_FAULTS_LABEL
        return metadata.fault_label

    @staticmethod
    def _header_map(header_row: tuple[Any, ...]) -> dict[str, int]:
        aliases = {
            "case_name": "case",
            "run_number": "run",
            "any_group": "group",
            "signal_name": "signal",
            "signal_view": "view",
            "custom_y_axis_name": "y_axis",
            "custom_y_axis_name_right": "y_axis_right",
            "right_y_axis": "y_axis_right",
            "y_axis_2": "y_axis_right",
            "show_three_phase_overview": "overview",
            "show_tov_windows": "tov_windows",
            "tov_windows_shown": "tov_window_count",
            "show_limits": "limits",
            "legend_left": "legends_left",
            "legend_side_left": "legends_left",
            "show_max_annotation": "annotate_max",
            "show_min_annotation": "annotate_min",
            "export_excel": "excel_export",
            "excel": "excel_export",
            "fft_outputs": "outputs",
            "fft_base_frequency": "base_frequency_hz",
            "base_frequency": "base_frequency_hz",
            "base_frequency_hz": "base_frequency_hz",
            "number_of_harmonics": "max_harmonic",
            "max_harmonics": "max_harmonic",
            "harmonics_to_plot": "harmonics",
            "magnitude_output": "magnitude",
            "phase_output_units": "phase_units",
            "phase_output_reference": "phase_reference",
            "start_time_s": "time_start_s",
            "plot_start_s": "time_start_s",
            "start_s": "time_start_s",
            "end_time_s": "time_end_s",
            "plot_end_s": "time_end_s",
            "end_s": "time_end_s",
        }
        mapping: dict[str, int] = {}
        for index, value in enumerate(header_row):
            name = BatchExcelService._normalize_header(value)
            if not name:
                continue
            mapping[aliases.get(name, name)] = index
        return mapping

    @staticmethod
    def _normalize_header(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")

    @staticmethod
    def _cell_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).strip()

    @staticmethod
    def _row_is_empty(values: tuple[Any, ...]) -> bool:
        return not any(str(value).strip() for value in values if value is not None)

    @staticmethod
    def _required_headers(mode: PlotMode) -> list[str]:
        if mode is PlotMode.MM:
            return ["case", "run", "element"]
        if mode is PlotMode.CB:
            return ["case", "run", "element"]
        if mode is PlotMode.FFT:
            return ["case", "run", "group", "signal"]
        if mode is PlotMode.COMB:
            return ["case", "run", "signals"]
        return ["case", "run", "group", "signal"]
