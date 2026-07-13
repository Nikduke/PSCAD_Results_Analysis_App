from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook

from pscad_plotter_app_v3.models import PlotJob, PlotMode, SignalReference
from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer
from pscad_plotter_app_v3.services.waveform_io import InfDescriptor, WaveformFrame


class ExcelExporter:
    """Write selected PSCAD waveform channels to .xlsx files."""

    INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')

    def __init__(self, renderer: MatplotlibRenderer) -> None:
        self.renderer = renderer

    def export(self, job: PlotJob) -> Path:
        inf_path = self.renderer.resolve_inf_path(job.case_name, job.run_number)
        desc_df = self.renderer.load_inf_descriptors(inf_path)
        output_dir = Path(job.output_dir) / "Excel"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / self._filename(job)

        workbook = Workbook()
        workbook.remove(workbook.active)
        if job.mode is PlotMode.MM:
            self._write_mm_sheets(workbook, job, inf_path, desc_df)
        elif job.mode is PlotMode.CB:
            cb_frame = self._load_standardized_mm_cb_frame(job, inf_path, desc_df, "IIp")
            cb_frame = cb_frame.time_window(job.time_start_s, job.time_end_s)
            self._write_frame_sheet(workbook, "IIp", cb_frame)
        elif job.mode is PlotMode.COMB:
            self._write_combined_sheets(workbook, job)
        else:
            self._write_any_sheets(workbook, job, inf_path, desc_df)
        workbook.save(output_path)
        return output_path

    def _write_mm_sheets(self, workbook: Workbook, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor]) -> None:
        if (job.trace_type or "Both") == "Both":
            lg_frame = self._load_standardized_mm_cb_frame(job, inf_path, desc_df, "LGp")
            ll_frame = self._load_standardized_mm_cb_frame(job, inf_path, desc_df, "LLp")
            self._write_frame_sheet(workbook, "LGp", lg_frame.time_window(job.time_start_s, job.time_end_s))
            self._write_frame_sheet(workbook, "LLp", ll_frame.time_window(job.time_start_s, job.time_end_s))
            return

        trace_type = job.trace_type or "LGp"
        frame = self._load_standardized_mm_cb_frame(job, inf_path, desc_df, trace_type)
        self._write_frame_sheet(workbook, trace_type, frame.time_window(job.time_start_s, job.time_end_s))

    def _write_any_sheets(self, workbook: Workbook, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor]) -> None:
        if not job.signal_name:
            raise ValueError(f"Missing signal selection for export {job.group_label}")
        signal_view = job.signal_view or "bundle"
        if signal_view == "individual":
            rows = self.renderer.select_any_signal_rows(desc_df, job.group_label, job.signal_name, "individual")
            frame = self.renderer.load_any_signal_frame(inf_path, rows)
            frame = frame.renamed([str(frame.columns[0]), job.signal_name])
            frame = frame.time_window(job.time_start_s, job.time_end_s)
            self._write_frame_sheet(workbook, "Data", frame)
            return

        rows = self.renderer.select_any_signal_rows(desc_df, job.group_label, job.signal_name, "bundle")
        frame = self.renderer.load_any_signal_frame(inf_path, rows)
        frame = frame.renamed([str(frame.columns[0])] + [str(row.Description) for row in rows])
        frame = frame.time_window(job.time_start_s, job.time_end_s)
        self._write_frame_sheet(workbook, "Data", frame)

    def _write_combined_sheets(self, workbook: Workbook, job: PlotJob) -> None:
        if len(job.combined_signals) < 2:
            raise ValueError("Combined Excel export requires at least 2 signals.")
        for index, signal in enumerate(job.combined_signals, start=1):
            source = signal if signal.has_source else SignalReference(
                signal.group_name,
                signal.signal_name,
                signal.unit,
                job.case_name,
                job.run_number,
            )
            inf_path = self.renderer.resolve_inf_path(source.case_name, source.run_number)
            desc_df = self.renderer.load_inf_descriptors(inf_path)
            rows = self.renderer.select_any_signal_rows(desc_df, source.group_name, source.signal_name, "individual")
            frame = self.renderer.load_any_signal_frame(inf_path, rows)
            label = source.label if source.case_name == job.case_name and source.run_number == job.run_number else f"{source.case_name} R{source.run_number} {source.label}"
            frame = frame.renamed([str(frame.columns[0]), label])
            frame = frame.time_window(job.time_start_s, job.time_end_s)
            self._write_frame_sheet(workbook, f"{index}_{source.group_name}_{source.signal_name}", frame)

    def _load_standardized_mm_cb_frame(
        self,
        job: PlotJob,
        inf_path: Path,
        desc_df: list[InfDescriptor],
        finder: str,
    ) -> WaveformFrame:
        return self.renderer.load_standardized_group_frame(inf_path, desc_df, job.group_label, finder)

    def _write_frame_sheet(self, workbook: Workbook, sheet_name: str, frame: WaveformFrame) -> None:
        sheet = self._create_sheet(workbook, sheet_name)
        for row in frame.rows_for_excel():
            sheet.append(row)

    def _create_sheet(self, workbook: Workbook, sheet_name: str):
        name = self._sheet_name(sheet_name)
        if name not in workbook.sheetnames:
            return workbook.create_sheet(name)
        base = name[:28]
        suffix = 2
        while True:
            candidate = f"{base}_{suffix}"[:31]
            if candidate not in workbook.sheetnames:
                return workbook.create_sheet(candidate)
            suffix += 1

    def _filename(self, job: PlotJob) -> str:
        parts = [job.case_name, job.group_label]
        if job.mode is PlotMode.ANY and job.signal_name:
            parts.append(job.signal_name)
        if job.fault_label and job.fault_label != "No fault":
            parts.append(job.fault_label)
        parts.append(f"{job.run_number:03d}")
        if job.mode is PlotMode.MM and job.trace_type and job.trace_type not in ("Both", ""):
            parts.append(job.trace_type)
        time_token = self._time_range_filename_token(job.time_start_s, job.time_end_s)
        if time_token:
            parts.append(time_token)
        safe_parts = [self._sanitize_filename_part(part) for part in parts if part]
        return "_".join(safe_parts) + ".xlsx"

    @staticmethod
    def _time_range_filename_token(start_s: float | None, end_s: float | None) -> str:
        if start_s is None and end_s is None:
            return ""
        if start_s is None:
            return f"Tto{float(end_s):g}s"
        if end_s is None:
            return f"Tfrom{float(start_s):g}s"
        return f"T{float(start_s):g}-{float(end_s):g}s"

    def _sanitize_filename_part(self, value: str) -> str:
        cleaned = self.INVALID_FILENAME_CHARS.sub("_", str(value).strip())
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned.strip("._") or "export"

    @staticmethod
    def _sheet_name(value: str) -> str:
        cleaned = re.sub(r"[\[\]\*:/\\?]+", "_", value).strip()
        return (cleaned or "Data")[:31]
