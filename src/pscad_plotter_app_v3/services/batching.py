from __future__ import annotations

from uuid import uuid4

from pscad_plotter_app_v3.models import (
    DEFAULT_TOV_WINDOW_COUNT,
    DEFAULT_TOV_WINDOW_S,
    FFT_OUTPUT_DC,
    FFT_OUTPUT_MAGNITUDES,
    FFT_OUTPUT_PHASE_ANGLES,
    PlotBatch,
    PlotJob,
    PlotMode,
    PlotRequest,
    SignalReference,
    VoltageLimitSet,
)
from pscad_plotter_app_v3.services.project_conventions import ALL_FAULTS_LABEL


class BatchBuilderService:
    """Expand UI requests into concrete plot jobs and user-visible batches."""

    @staticmethod
    def display_trace_type(trace_type: str | None) -> str:
        if trace_type == "Both":
            return "Combined LGp&LLp"
        return trace_type or ""

    def build_batch(self, request: PlotRequest, limits: VoltageLimitSet | None = None) -> PlotBatch:
        jobs = self.expand_request(request, limits)
        summary = self._build_summary(request)
        return PlotBatch.create(
            mode=request.mode,
            case_name=request.case_name,
            summary=summary,
            jobs=jobs,
            request=request,
        )

    def expand_request(self, request: PlotRequest, limits: VoltageLimitSet | None = None) -> list[PlotJob]:
        jobs: list[PlotJob] = []
        if request.mode is PlotMode.MM:
            for element_name in request.elements:
                for run_number in request.run_numbers:
                    jobs.append(
                        PlotJob(
                            job_id=uuid4().hex,
                            mode=request.mode,
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
                        )
                    )
        elif request.mode is PlotMode.CB:
            for element_name in request.elements:
                for run_number in request.run_numbers:
                    jobs.append(
                        PlotJob(
                            job_id=uuid4().hex,
                            mode=request.mode,
                            case_name=request.case_name,
                            run_number=run_number,
                            group_label=element_name,
                            output_dir=request.output_dir,
                            trace_type="IIp",
                            show_three_phase_overview=request.show_three_phase_overview,
                            show_tov_windows=request.show_tov_windows,
                            tov_window_s=request.tov_window_s,
                            tov_window_count=request.tov_window_count,
                            legends_left=request.legends_left,
                            excel_export=request.excel_export,
                            time_start_s=request.time_start_s,
                            time_end_s=request.time_end_s,
                        )
                    )
        elif request.mode is PlotMode.ANY:
            for run_number in request.run_numbers:
                for signal_name in request.signals:
                    jobs.append(
                        PlotJob(
                            job_id=uuid4().hex,
                            mode=request.mode,
                            case_name=request.case_name,
                            run_number=run_number,
                            group_label=request.any_group or "",
                            output_dir=request.output_dir,
                            show_three_phase_overview=request.show_three_phase_overview,
                            show_tov_windows=request.show_tov_windows,
                            tov_window_s=request.tov_window_s,
                            tov_window_count=request.tov_window_count,
                            legends_left=request.legends_left,
                            annotate_max=request.annotate_max,
                            annotate_min=request.annotate_min,
                            signal_name=signal_name,
                            signal_view=request.any_signal_view,
                            custom_y_axis_name=request.custom_y_axis_name,
                            excel_export=request.excel_export,
                            time_start_s=request.time_start_s,
                            time_end_s=request.time_end_s,
                        )
                    )
        elif request.mode is PlotMode.FFT:
            for run_number in request.run_numbers:
                for signal_name in request.signals:
                    for fft_output in request.fft_outputs:
                        jobs.append(
                            PlotJob(
                                job_id=uuid4().hex,
                                mode=request.mode,
                                case_name=request.case_name,
                                run_number=run_number,
                                group_label=request.any_group or "",
                                output_dir=request.output_dir,
                                signal_name=signal_name,
                                signal_view="individual",
                                fft_output=fft_output,
                                fft_base_frequency_hz=request.fft_base_frequency_hz,
                                fft_max_harmonic=request.fft_max_harmonic,
                                fft_harmonics=request.fft_harmonics,
                                fft_magnitude=request.fft_magnitude,
                                fft_phase_units=request.fft_phase_units,
                                fft_phase_reference=request.fft_phase_reference,
                                custom_y_axis_name=request.custom_y_axis_name,
                                excel_export=request.excel_export,
                                time_start_s=request.time_start_s,
                                time_end_s=request.time_end_s,
                            )
                        )
        elif request.mode is PlotMode.COMB:
            if any(signal.has_source for signal in request.combined_signals):
                run_numbers = [request.run_numbers[0] if request.run_numbers else request.combined_signals[0].run_number]
            else:
                run_numbers = request.run_numbers
            for run_number in run_numbers:
                jobs.append(
                    PlotJob(
                        job_id=uuid4().hex,
                        mode=request.mode,
                        case_name=request.case_name,
                        run_number=run_number,
                        group_label=self._combined_target_summary(request.combined_signals),
                        output_dir=request.output_dir,
                        signal_view="individual",
                        custom_y_axis_name=request.custom_y_axis_name,
                        custom_y_axis_name_right=request.custom_y_axis_name_right,
                        combined_signals=list(request.combined_signals),
                        excel_export=request.excel_export,
                        time_start_s=request.time_start_s,
                        time_end_s=request.time_end_s,
                    )
                )
        return jobs

    def reconcile_batch(self, batch: PlotBatch) -> None:
        batch.request = self._request_from_jobs(batch)
        if batch.request is not None:
            batch.summary = self._build_summary(batch.request)
            return
        batch.summary = self._build_custom_summary(batch)

    def _build_summary(self, request: PlotRequest) -> str:
        run_text = self._run_summary(request)
        fault_text = f" | {request.fault_filter}" if request.fault_filter and request.fault_filter != ALL_FAULTS_LABEL else ""
        if request.mode is PlotMode.MM:
            voltage_text = f" | {request.voltage_kv:g} kV" if request.voltage_kv is not None else ""
            trace_text = self.display_trace_type(request.trace_type or "Both")
            target_text = self._target_summary(request.elements, "MM element")
            option_text = self._option_summary_mm(request)
            return f"MM | {request.case_name}{fault_text} | {run_text}{voltage_text} | {target_text} | {trace_text}{option_text}"
        if request.mode is PlotMode.CB:
            target_text = self._target_summary(request.elements, "CB element")
            option_text = self._option_summary_non_mm(request)
            return f"CB | {request.case_name}{fault_text} | {run_text} | {target_text}{option_text}"
        if request.mode is PlotMode.FFT:
            group_text = request.any_group or ""
            signal_text = self._target_summary(request.signals, "signal")
            option_text = self._option_summary_fft_request(request)
            return f"FFT | {request.case_name}{fault_text} | {run_text} | {group_text} | {signal_text}{option_text}"
        if request.mode is PlotMode.COMB:
            signal_text = self._combined_target_summary(request.combined_signals)
            source_text = self._combined_source_summary(request.combined_signals, request.case_name, request.run_numbers)
            excel_text = " | Excel export" if request.excel_export else ""
            return f"Comb | {source_text}{fault_text} | {signal_text}{excel_text}{self._time_range_option_suffix(request.time_start_s, request.time_end_s)}"
        group_text = request.any_group or ""
        signal_text = self._target_summary(request.signals, "signal")
        option_text = self._option_summary_any(request)
        return f"Any | {request.case_name}{fault_text} | {run_text} | {group_text} | {signal_text}{option_text}"

    def _run_summary(self, request: PlotRequest) -> str:
        if len(request.run_numbers) == 1:
            return f"Run {request.run_numbers[0]}"
        return f"{len(request.run_numbers)} runs"

    def _request_from_jobs(self, batch: PlotBatch) -> PlotRequest | None:
        if not batch.jobs:
            return None
        first = batch.jobs[0]
        if any(job.mode is not batch.mode or job.case_name != batch.case_name for job in batch.jobs):
            return None

        fallback_request = batch.request
        fault_filter = fallback_request.fault_filter if fallback_request else ALL_FAULTS_LABEL
        output_dir = first.output_dir
        if batch.mode is PlotMode.MM:
            if any(
                job.output_dir != output_dir
                or job.trace_type != first.trace_type
                or job.show_three_phase_overview != first.show_three_phase_overview
                or job.voltage_kv != first.voltage_kv
                or job.show_limits != first.show_limits
                or job.show_tov_windows != first.show_tov_windows
                or abs(job.tov_window_s - first.tov_window_s) > 1e-9
                or job.tov_window_count != first.tov_window_count
                or job.legends_left != first.legends_left
                or job.excel_export != first.excel_export
                or not self._same_time_range(job, first)
                for job in batch.jobs
            ):
                return None
            elements = sorted({job.group_label for job in batch.jobs})
            runs = sorted({int(job.run_number) for job in batch.jobs})
            if not self._jobs_form_cross_product(batch.jobs, elements, runs, lambda job: (job.group_label, int(job.run_number))):
                return None
            return PlotRequest(
                mode=PlotMode.MM,
                case_name=batch.case_name,
                run_numbers=runs,
                elements=elements,
                fault_filter=fault_filter,
                voltage_kv=first.voltage_kv,
                trace_type=first.trace_type,
                show_three_phase_overview=first.show_three_phase_overview,
                show_limits=first.show_limits,
                show_tov_windows=first.show_tov_windows,
                tov_window_s=first.tov_window_s,
                tov_window_count=first.tov_window_count,
                legends_left=first.legends_left,
                excel_export=first.excel_export,
                time_start_s=first.time_start_s,
                time_end_s=first.time_end_s,
                output_dir=output_dir,
            )

        if batch.mode is PlotMode.CB:
            if any(
                job.output_dir != output_dir
                or job.show_three_phase_overview != first.show_three_phase_overview
                or job.show_tov_windows != first.show_tov_windows
                or abs(job.tov_window_s - first.tov_window_s) > 1e-9
                or job.tov_window_count != first.tov_window_count
                or job.legends_left != first.legends_left
                or job.excel_export != first.excel_export
                or not self._same_time_range(job, first)
                for job in batch.jobs
            ):
                return None
            elements = sorted({job.group_label for job in batch.jobs})
            runs = sorted({int(job.run_number) for job in batch.jobs})
            if not self._jobs_form_cross_product(batch.jobs, elements, runs, lambda job: (job.group_label, int(job.run_number))):
                return None
            return PlotRequest(
                mode=PlotMode.CB,
                case_name=batch.case_name,
                run_numbers=runs,
                elements=elements,
                fault_filter=fault_filter,
                show_three_phase_overview=first.show_three_phase_overview,
                show_tov_windows=first.show_tov_windows,
                tov_window_s=first.tov_window_s,
                tov_window_count=first.tov_window_count,
                legends_left=first.legends_left,
                excel_export=first.excel_export,
                time_start_s=first.time_start_s,
                time_end_s=first.time_end_s,
                output_dir=output_dir,
            )

        if batch.mode is PlotMode.FFT:
            groups = {job.group_label for job in batch.jobs}
            signals = sorted({job.signal_name for job in batch.jobs if job.signal_name})
            runs = sorted({int(job.run_number) for job in batch.jobs})
            outputs = [output for output in self._ordered_fft_outputs({job.fft_output or FFT_OUTPUT_MAGNITUDES for job in batch.jobs})]
            if len(groups) != 1 or any(job.output_dir != output_dir or not job.signal_name for job in batch.jobs):
                return None
            if any(
                abs(job.fft_base_frequency_hz - first.fft_base_frequency_hz) > 1e-9
                or job.fft_max_harmonic != first.fft_max_harmonic
                or job.fft_harmonics != first.fft_harmonics
                or job.fft_magnitude != first.fft_magnitude
                or job.fft_phase_units != first.fft_phase_units
                or job.fft_phase_reference != first.fft_phase_reference
                or job.custom_y_axis_name != first.custom_y_axis_name
                or job.excel_export != first.excel_export
                or not self._same_time_range(job, first)
                for job in batch.jobs
            ):
                return None
            if not self._jobs_form_cross_product(
                batch.jobs,
                [f"{signal}|{output}" for signal in signals for output in outputs],
                runs,
                lambda job: (f"{job.signal_name}|{job.fft_output or FFT_OUTPUT_MAGNITUDES}", int(job.run_number)),
            ):
                return None
            return PlotRequest(
                mode=PlotMode.FFT,
                case_name=batch.case_name,
                run_numbers=runs,
                elements=[],
                fault_filter=fault_filter,
                any_group=next(iter(groups)),
                signals=signals,
                any_signal_view="individual",
                fft_outputs=outputs,
                fft_base_frequency_hz=first.fft_base_frequency_hz,
                fft_max_harmonic=first.fft_max_harmonic,
                fft_harmonics=first.fft_harmonics,
                fft_magnitude=first.fft_magnitude,
                fft_phase_units=first.fft_phase_units,
                fft_phase_reference=first.fft_phase_reference,
                custom_y_axis_name=first.custom_y_axis_name,
                excel_export=first.excel_export,
                time_start_s=first.time_start_s,
                time_end_s=first.time_end_s,
                output_dir=output_dir,
            )

        if batch.mode is PlotMode.COMB:
            if len(first.combined_signals) < 2:
                return None
            if any(
                job.output_dir != output_dir
                or job.combined_signals != first.combined_signals
                or job.custom_y_axis_name != first.custom_y_axis_name
                or job.custom_y_axis_name_right != first.custom_y_axis_name_right
                or job.excel_export != first.excel_export
                or not self._same_time_range(job, first)
                for job in batch.jobs
            ):
                return None
            if any(signal.has_source for signal in first.combined_signals):
                return PlotRequest(
                    mode=PlotMode.COMB,
                    case_name=first.case_name,
                    run_numbers=[first.run_number],
                    elements=[],
                    fault_filter=fault_filter,
                    combined_signals=list(first.combined_signals),
                    custom_y_axis_name=first.custom_y_axis_name,
                    custom_y_axis_name_right=first.custom_y_axis_name_right,
                    excel_export=first.excel_export,
                    time_start_s=first.time_start_s,
                    time_end_s=first.time_end_s,
                    output_dir=output_dir,
                )
            runs = sorted({int(job.run_number) for job in batch.jobs})
            if not self._jobs_form_cross_product(batch.jobs, ["combined"], runs, lambda job: ("combined", int(job.run_number))):
                return None
            return PlotRequest(
                mode=PlotMode.COMB,
                case_name=batch.case_name,
                run_numbers=runs,
                elements=[],
                fault_filter=fault_filter,
                combined_signals=list(first.combined_signals),
                custom_y_axis_name=first.custom_y_axis_name,
                custom_y_axis_name_right=first.custom_y_axis_name_right,
                excel_export=first.excel_export,
                time_start_s=first.time_start_s,
                time_end_s=first.time_end_s,
                output_dir=output_dir,
            )

        groups = {job.group_label for job in batch.jobs}
        signals = sorted({job.signal_name for job in batch.jobs if job.signal_name})
        runs = sorted({int(job.run_number) for job in batch.jobs})
        signal_views = {job.signal_view or "bundle" for job in batch.jobs}
        if len(groups) != 1 or len(signal_views) != 1 or any(job.output_dir != output_dir or not job.signal_name for job in batch.jobs):
            return None
        if any(
            job.show_three_phase_overview != first.show_three_phase_overview
            or job.show_tov_windows != first.show_tov_windows
            or abs(job.tov_window_s - first.tov_window_s) > 1e-9
            or job.tov_window_count != first.tov_window_count
            or job.legends_left != first.legends_left
            or job.annotate_max != first.annotate_max
            or job.annotate_min != first.annotate_min
            or job.custom_y_axis_name != first.custom_y_axis_name
            or job.excel_export != first.excel_export
            or not self._same_time_range(job, first)
            for job in batch.jobs
        ):
            return None
        if not self._jobs_form_cross_product(batch.jobs, signals, runs, lambda job: (str(job.signal_name), int(job.run_number))):
            return None
        return PlotRequest(
            mode=PlotMode.ANY,
            case_name=batch.case_name,
            run_numbers=runs,
            elements=[],
            fault_filter=fault_filter,
            any_group=next(iter(groups)),
            signals=signals,
            any_signal_view=next(iter(signal_views)),
            custom_y_axis_name=first.custom_y_axis_name,
            show_three_phase_overview=first.show_three_phase_overview,
            show_tov_windows=first.show_tov_windows,
            tov_window_s=first.tov_window_s,
            tov_window_count=first.tov_window_count,
            legends_left=first.legends_left,
            annotate_max=first.annotate_max,
            annotate_min=first.annotate_min,
            excel_export=first.excel_export,
            time_start_s=first.time_start_s,
            time_end_s=first.time_end_s,
            output_dir=output_dir,
        )

    @staticmethod
    def _jobs_form_cross_product(
        jobs: list[PlotJob],
        axis_a: list[str],
        runs: list[int],
        key_builder,
    ) -> bool:
        expected = len(axis_a) * len(runs)
        if len(jobs) != expected:
            return False
        keys = {key_builder(job) for job in jobs}
        return len(keys) == expected

    @staticmethod
    def _same_time_range(left: PlotJob, right: PlotJob) -> bool:
        return left.time_start_s == right.time_start_s and left.time_end_s == right.time_end_s

    def _build_custom_summary(self, batch: PlotBatch) -> str:
        first = batch.jobs[0]
        fallback_request = batch.request
        fault_text = ""
        if fallback_request and fallback_request.fault_filter and fallback_request.fault_filter != ALL_FAULTS_LABEL:
            fault_text = f" | {fallback_request.fault_filter}"
        if batch.mode is PlotMode.MM:
            voltage_text = f" | {first.voltage_kv:g} kV" if first.voltage_kv is not None else ""
            trace_text = self.display_trace_type(first.trace_type) if first.trace_type else "Mixed trace"
            target_text = self._job_target_summary(batch)
            option_text = self._job_option_summary(first, include_limits=True)
            return f"MM | {batch.case_name}{fault_text} | Custom subset{voltage_text} | {target_text} | {trace_text}{option_text}"
        if batch.mode is PlotMode.CB:
            target_text = self._job_target_summary(batch)
            option_text = self._job_option_summary(first, include_limits=False)
            return f"CB | {batch.case_name}{fault_text} | Custom subset | {target_text}{option_text}"
        if batch.mode is PlotMode.FFT:
            group_text = first.group_label or "Custom subset"
            target_text = self._job_target_summary(batch)
            option_text = self._job_option_summary(first, include_limits=False, include_overview=False)
            return f"FFT | {batch.case_name}{fault_text} | Custom subset | {group_text} | {target_text}{option_text}"
        if batch.mode is PlotMode.COMB:
            target_text = self._combined_target_summary(first.combined_signals)
            source_text = self._combined_source_summary(first.combined_signals, batch.case_name, [first.run_number])
            excel_text = " | Excel export" if first.excel_export else ""
            return f"Comb | {source_text}{fault_text} | Custom subset | {target_text}{excel_text}{self._time_range_option_suffix(first.time_start_s, first.time_end_s)}"
        group_text = first.group_label or "Custom subset"
        target_text = self._job_target_summary(batch)
        option_text = self._job_option_summary(first, include_limits=False, include_overview=(first.signal_view or "bundle") == "bundle")
        return f"Any | {batch.case_name}{fault_text} | Custom subset | {group_text} | {target_text}{option_text}"

    @staticmethod
    def _tov_summary(show_tov_windows: bool, tov_window_s: float, tov_window_count: int) -> str:
        if not show_tov_windows:
            return " | no TOV lines"
        details: list[str] = []
        if abs(float(tov_window_s) - DEFAULT_TOV_WINDOW_S) > 1e-9:
            details.append(f"{float(tov_window_s):.4f} s")
        if int(tov_window_count) != DEFAULT_TOV_WINDOW_COUNT:
            details.append(f"{int(tov_window_count)} windows")
        if details:
            return " | TOV " + ", ".join(details)
        return ""

    @staticmethod
    def _target_summary(targets: list[str], singular_label: str) -> str:
        if len(targets) == 1:
            return str(targets[0])
        return f"{len(targets)} {singular_label}s"

    def _option_summary_mm(self, request: PlotRequest) -> str:
        parts: list[str] = []
        if not request.show_three_phase_overview:
            parts.append("no overview")
        if request.show_three_phase_overview:
            tov_text = self._tov_summary(request.show_tov_windows, request.tov_window_s, request.tov_window_count)
            if tov_text:
                parts.append(tov_text.removeprefix(" | "))
        if not request.show_limits:
            parts.append("no limits")
        if request.legends_left:
            parts.append("legends left")
        if request.excel_export:
            parts.append("Excel export")
        time_text = self._time_range_summary(request.time_start_s, request.time_end_s)
        if time_text:
            parts.append(time_text)
        return "".join(f" | {part}" for part in parts)

    def _option_summary_non_mm(self, request: PlotRequest) -> str:
        parts: list[str] = []
        if not request.show_three_phase_overview:
            parts.append("no overview")
        if request.show_three_phase_overview:
            tov_text = self._tov_summary(request.show_tov_windows, request.tov_window_s, request.tov_window_count)
            if tov_text:
                parts.append(tov_text.removeprefix(" | "))
        if request.legends_left:
            parts.append("legends left")
        if request.excel_export:
            parts.append("Excel export")
        time_text = self._time_range_summary(request.time_start_s, request.time_end_s)
        if time_text:
            parts.append(time_text)
        return "".join(f" | {part}" for part in parts)

    def _option_summary_any(self, request: PlotRequest) -> str:
        parts: list[str] = []
        if request.any_signal_view == "bundle":
            if not request.show_three_phase_overview:
                parts.append("no overview")
            if request.show_three_phase_overview:
                tov_text = self._tov_summary(request.show_tov_windows, request.tov_window_s, request.tov_window_count)
                if tov_text:
                    parts.append(tov_text.removeprefix(" | "))
        if request.legends_left:
            parts.append("legends left")
        if request.annotate_max:
            parts.append("annotate max")
        if request.annotate_min:
            parts.append("annotate min")
        if request.excel_export:
            parts.append("Excel export")
        time_text = self._time_range_summary(request.time_start_s, request.time_end_s)
        if time_text:
            parts.append(time_text)
        return "".join(f" | {part}" for part in parts)

    def _option_summary_fft_request(self, request: PlotRequest) -> str:
        outputs = self._format_fft_outputs(request.fft_outputs)
        return (
            f" | {outputs}"
            f" | {request.fft_base_frequency_hz:g} Hz"
            f" | H {request.fft_harmonics}"
            f" | max H{request.fft_max_harmonic}"
            f"{' | Excel export' if request.excel_export else ''}"
            f"{self._time_range_option_suffix(request.time_start_s, request.time_end_s)}"
        )

    @classmethod
    def _time_range_option_suffix(cls, start_s: float | None, end_s: float | None) -> str:
        text = cls._time_range_summary(start_s, end_s)
        return f" | {text}" if text else ""

    def _job_target_summary(self, batch: PlotBatch) -> str:
        first = batch.jobs[0]
        if batch.mode is PlotMode.COMB:
            return self._combined_target_summary(first.combined_signals)
        if batch.mode is PlotMode.FFT:
            signal_names = sorted({job.signal_name for job in batch.jobs if job.signal_name})
            output_names = {job.fft_output or FFT_OUTPUT_MAGNITUDES for job in batch.jobs}
            if len(signal_names) == 1:
                return f"{signal_names[0]} | {self._format_fft_outputs(output_names)}"
            return f"{len(signal_names)} signals | {self._format_fft_outputs(output_names)}"
        if batch.mode is PlotMode.ANY:
            signal_names = sorted({job.signal_name for job in batch.jobs if job.signal_name})
            if len(signal_names) == 1:
                return signal_names[0]
            return f"{batch.plot_count} signals"
        group_labels = sorted({job.group_label for job in batch.jobs if job.group_label})
        if len(group_labels) == 1:
            return group_labels[0]
        suffix = "MM elements" if batch.mode is PlotMode.MM else "CB elements"
        return f"{len(group_labels)} {suffix}"

    def _job_option_summary(self, job: PlotJob, *, include_limits: bool, include_overview: bool = True) -> str:
        parts: list[str] = []
        if job.mode is PlotMode.FFT:
            parts.append(f"{job.fft_base_frequency_hz:g} Hz")
            parts.append(f"H {job.fft_harmonics}")
            parts.append(f"max H{job.fft_max_harmonic}")
            if job.excel_export:
                parts.append("Excel export")
            time_text = self._time_range_summary(job.time_start_s, job.time_end_s)
            if time_text:
                parts.append(time_text)
            return "".join(f" | {part}" for part in parts)
        if include_overview and not job.show_three_phase_overview:
            parts.append("no overview")
        if include_overview and job.show_three_phase_overview:
            tov_text = self._tov_summary(job.show_tov_windows, job.tov_window_s, job.tov_window_count)
            if tov_text:
                parts.append(tov_text.removeprefix(" | "))
        if include_limits and not job.show_limits:
            parts.append("no limits")
        if job.legends_left:
            parts.append("legends left")
        if job.annotate_max:
            parts.append("annotate max")
        if job.annotate_min:
            parts.append("annotate min")
        if job.excel_export:
            parts.append("Excel export")
        time_text = self._time_range_summary(job.time_start_s, job.time_end_s)
        if time_text:
            parts.append(time_text)
        return "".join(f" | {part}" for part in parts)

    @staticmethod
    def _time_range_summary(start_s: float | None, end_s: float | None) -> str:
        if start_s is None and end_s is None:
            return ""
        if start_s is None:
            return f"time <= {float(end_s):g}s"
        if end_s is None:
            return f"time >= {float(start_s):g}s"
        return f"time {float(start_s):g}-{float(end_s):g}s"

    @staticmethod
    def _ordered_fft_outputs(outputs: set[str]) -> list[str]:
        order = [FFT_OUTPUT_MAGNITUDES, FFT_OUTPUT_PHASE_ANGLES, FFT_OUTPUT_DC]
        return [output for output in order if output in outputs]

    @classmethod
    def _format_fft_outputs(cls, outputs) -> str:
        labels = {
            FFT_OUTPUT_MAGNITUDES: "magnitudes",
            FFT_OUTPUT_PHASE_ANGLES: "phase angles",
            FFT_OUTPUT_DC: "DC",
        }
        ordered = cls._ordered_fft_outputs(set(outputs))
        return ", ".join(labels.get(output, output) for output in ordered) or "no outputs"

    @classmethod
    def _combined_target_summary(cls, signals: list[SignalReference]) -> str:
        if len(signals) == 1:
            return signals[0].label
        if len(signals) == 2:
            return " & ".join(signal.label for signal in signals)
        return f"{len(signals)} signals"

    @staticmethod
    def _combined_source_summary(signals: list[SignalReference], fallback_case_name: str, fallback_runs: list[int]) -> str:
        sources = {
            (
                signal.case_name if signal.has_source else fallback_case_name,
                signal.run_number if signal.has_source else (fallback_runs[0] if fallback_runs else 0),
            )
            for signal in signals
        }
        case_names = sorted({case_name for case_name, _run_number in sources if case_name})
        run_numbers = sorted({run_number for _case_name, run_number in sources if run_number})
        if len(case_names) == 1 and len(run_numbers) == 1:
            return f"{case_names[0]} | Run {run_numbers[0]}"
        if len(case_names) == 1:
            return f"{case_names[0]} | {len(run_numbers)} runs"
        return f"{len(case_names)} cases | {len(sources)} case-run sources"
