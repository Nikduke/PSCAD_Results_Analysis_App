from __future__ import annotations

from pscad_plotter_app_v3.models import PlotJob, PlotMode, PlotRequest, VoltageLimitSet


def build_mm_jobs(
    request: PlotRequest,
    limits: VoltageLimitSet | None = None,
) -> list[PlotJob]:
    """Expand one supported MM request into concrete render jobs."""
    if request.mode is not PlotMode.MM:
        raise ValueError(f"Unsupported plot mode: {request.mode.value}")
    plot_variant = request.plot_variant
    if not plot_variant:
        if request.annotate_max and not request.annotate_min:
            plot_variant = "max"
        elif request.annotate_min and not request.annotate_max:
            plot_variant = "min"
    return [
        PlotJob(
            mode=PlotMode.MM,
            case_name=request.case_name,
            run_number=run_number,
            group_label=element_name,
            output_dir=request.output_dir,
            trace_type=request.trace_type,
            show_three_phase_overview=request.show_three_phase_overview,
            show_limits=request.show_limits,
            show_tov_windows=request.show_tov_windows,
            tov_window_s=request.tov_window_s,
            tov_window_count=request.tov_window_count,
            legends_left=request.legends_left,
            excel_export=request.excel_export,
            time_start_s=request.time_start_s,
            time_end_s=request.time_end_s,
            voltage_kv=request.voltage_kv,
            limits=limits,
            annotate_max=request.annotate_max,
            annotate_min=request.annotate_min,
            plot_variant=plot_variant,
        )
        for element_name in request.elements
        for run_number in request.run_numbers
    ]
