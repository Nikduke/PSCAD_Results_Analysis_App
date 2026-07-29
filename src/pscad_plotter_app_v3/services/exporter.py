from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook

from pscad_plotter_app_v3.models import PlotJob
from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer
from pscad_plotter_app_v3.services.waveform_io import InfDescriptor, WaveformFrame


class ExcelExporter:
    """Write the selected MM waveform channels to an Excel workbook."""

    INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')

    def __init__(self, renderer: MatplotlibRenderer) -> None:
        self.renderer = renderer

    def export(self, job: PlotJob) -> Path:
        inf_path = self.renderer.resolve_inf_path(job.case_name, job.run_number)
        descriptors = self.renderer.load_inf_descriptors(inf_path)
        output_dir = Path(job.output_dir) / "Excel"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / self._filename(job)

        workbook = Workbook()
        workbook.remove(workbook.active)
        try:
            self._write_mm_sheets(workbook, job, inf_path, descriptors)
            workbook.save(output_path)
        finally:
            workbook.close()
        return output_path

    def _write_mm_sheets(
        self,
        workbook: Workbook,
        job: PlotJob,
        inf_path: Path,
        descriptors: list[InfDescriptor],
    ) -> None:
        trace_type = job.trace_type or "Both"
        finders = ("LGp", "LLp") if trace_type == "Both" else (trace_type,)
        for finder in finders:
            frame = self.renderer.load_standardized_group_frame(
                inf_path,
                descriptors,
                job.group_label,
                finder,
            )
            self._write_frame_sheet(
                workbook,
                finder,
                frame.time_window(job.time_start_s, job.time_end_s),
            )

    @staticmethod
    def _write_frame_sheet(
        workbook: Workbook,
        sheet_name: str,
        frame: WaveformFrame,
    ) -> None:
        sheet = workbook.create_sheet(sheet_name[:31])
        for row in frame.rows_for_excel():
            sheet.append(row)

    def _filename(self, job: PlotJob) -> str:
        parts = [job.case_name, job.group_label]
        parts.append(f"{job.run_number:03d}")
        if job.trace_type and job.trace_type not in ("Both", ""):
            parts.append(job.trace_type)
        time_token = self._time_range_filename_token(job.time_start_s, job.time_end_s)
        if time_token:
            parts.append(time_token)
        safe_parts = [self._sanitize_filename_part(part) for part in parts if part]
        return "_".join(safe_parts) + ".xlsx"

    @staticmethod
    def _time_range_filename_token(
        start_s: float | None,
        end_s: float | None,
    ) -> str:
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
