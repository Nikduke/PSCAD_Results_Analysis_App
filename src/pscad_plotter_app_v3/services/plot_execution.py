from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pscad_plotter_app_v3.models import PlotJob
from pscad_plotter_app_v3.services.exporter import ExcelExporter
from pscad_plotter_app_v3.services.renderer import MatplotlibRenderer

MIN_PARALLEL_PLOT_JOBS = 3
MAX_PLOT_PROCESS_WORKERS = 4
PLOT_PROCESS_QUEUE_MULTIPLIER = 2
PLOT_JOB_GROUP_SIZE = 8


@dataclass(frozen=True, slots=True)
class PlotExecutionOutput:
    png_path: Path
    excel_path: Path | None = None


def automatic_plot_worker_count(job_count: int) -> int:
    """Choose a conservative process count for a concrete plot batch."""
    if job_count < MIN_PARALLEL_PLOT_JOBS:
        return 1
    available_cpus = max(1, (os.cpu_count() or 1) - 1)
    return max(1, min(job_count, MAX_PLOT_PROCESS_WORKERS, available_cpus))


def execute_plot_job(
    renderer: MatplotlibRenderer,
    exporter: ExcelExporter | None,
    job: PlotJob,
) -> PlotExecutionOutput:
    """Render one job and, when requested, export its waveform workbook."""
    png_path = renderer.render(job)
    excel_path = None
    if job.excel_export:
        if exporter is None:
            raise ValueError("Excel export requested, but exporter is unavailable.")
        excel_path = exporter.export(job)
    return PlotExecutionOutput(png_path=png_path, excel_path=excel_path)


_PROCESS_RENDERER: MatplotlibRenderer | None = None
_PROCESS_EXPORTER: ExcelExporter | None = None


def initialize_plot_process(run_index: dict[str, dict[int, Path]]) -> None:
    """Create process-local plotting and export state for Windows spawn workers."""
    global _PROCESS_RENDERER, _PROCESS_EXPORTER
    _PROCESS_RENDERER = MatplotlibRenderer(run_index)
    _PROCESS_EXPORTER = ExcelExporter(_PROCESS_RENDERER)


def execute_plot_job_in_process(job: PlotJob) -> PlotExecutionOutput:
    if _PROCESS_RENDERER is None or _PROCESS_EXPORTER is None:
        raise RuntimeError("Plot process was not initialized")
    return execute_plot_job(_PROCESS_RENDERER, _PROCESS_EXPORTER, job)


def execute_plot_job_group_in_process(
    jobs: tuple[PlotJob, ...],
) -> tuple[PlotExecutionOutput, ...]:
    """Execute related jobs serially so one worker can reuse waveform frames."""
    return tuple(execute_plot_job_in_process(job) for job in jobs)
