from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
import math
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

from pscad_plotter_app_v3.models import DEFAULT_TOV_WINDOW_S, PlotJob, PlotMode
from pscad_plotter_app_v3.services.project_conventions import find_stat_file, parse_stat_rows
from pscad_plotter_app_v3.services.waveform_io import (
    InfDescriptor,
    WaveformFrame,
    load_out_frame,
    parse_inf_descriptors,
    pgb_to_out_location,
    standard_out_file_path,
)


class MatplotlibRenderer:
    """Render the MM waveform plots used by the analysis application."""

    FIGSIZE = (15, 8)
    DPI = 300
    PHASE_COLS = [1, 2, 3]
    PHASE_COLOURS = ["red", "green", "blue"]
    LINEWIDTH_GRID = 0.25
    GRID_ALPHA = 0.6
    LINEWIDTH_TRACE = 0.6
    LINEWIDTH_ANNO = 0.7
    LINEWIDTH_LIMIT_THIN = 0.5
    LINEWIDTH_LIMIT_THICK = 1.0
    FONTSIZE_TITLE = 13
    FONTSIZE_ANNO = 10
    FONTSIZE_LEGEND = 9
    PAD_YLIM = 0.07
    WINDOW_MULTIPLIER = 1
    ANNO_X_OFFSET = -0.002
    ANNO_Y_OFFSET = 0.02
    ANNO_Y_LIMIT_PAD = 0.10
    TIGHT_LAYOUT_PAD = 2.0
    SAFETY_MARGIN = 1.15
    TIME_TOV = DEFAULT_TOV_WINDOW_S
    INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')
    MAX_INF_CACHE = 128
    MAX_STAT_FILE_CACHE = 256
    MAX_EVENT_INFO_CACHE = 128
    MAX_OUT_FILE_CACHE = 256

    def __init__(
        self,
        run_index: dict[str, dict[int, Path]],
        check_cancel: Callable[[], None] | None = None,
    ) -> None:
        self.run_index = run_index
        self._check_cancel = check_cancel
        self._inf_cache: OrderedDict[Path, list[InfDescriptor]] = OrderedDict()
        self._stat_file_cache: OrderedDict[Path, Path | None] = OrderedDict()
        self._event_info_cache: OrderedDict[Path, dict[int, dict[str, object]]] = OrderedDict()
        self._out_file_cache: OrderedDict[Path, WaveformFrame] = OrderedDict()

    def render(self, job: PlotJob) -> Path:
        if job.mode is not PlotMode.MM:
            raise ValueError(f"Unsupported plot mode: {job.mode.value}")
        inf_path = self._resolve_inf_path(job.case_name, job.run_number)
        stat_path = self._find_stat_file(inf_path.parent)
        event_info = self._load_event_info(stat_path, job.run_number) if stat_path is not None else None
        descriptors = self._load_inf_descriptors(inf_path)
        output_dir = Path(job.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if job.trace_type == "Both":
            if job.show_limits and job.limits is None:
                raise ValueError(f"No MM limits configured for {job.group_label} ({job.voltage_kv:g} kV)")
            return self._render_mm_combined(job, inf_path, descriptors, event_info, output_dir)
        if job.show_limits and job.limits is None:
            raise ValueError(f"No MM limits configured for {job.group_label} ({job.voltage_kv:g} kV)")
        return self._render_single(
            job,
            inf_path,
            descriptors,
            event_info,
            output_dir,
            finder=job.trace_type or "LGp",
        )
    def resolve_inf_path(self, case_name: str, run_number: int) -> Path:
        return self._resolve_inf_path(case_name, run_number)

    def load_inf_descriptors(self, inf_path: Path) -> list[InfDescriptor]:
        return self._load_inf_descriptors(inf_path)

    def load_standardized_group_frame(
        self,
        inf_path: Path,
        desc_df: list[InfDescriptor],
        group_label: str,
        finder: str,
    ) -> WaveformFrame:
        idx_map = self._filter_signals(desc_df, group_label)
        if finder not in idx_map:
            raise ValueError(f"Signal '{finder}' not available for {group_label}")
        policy = self._get_group_policy()
        frame = self._load_out_files(inf_path, idx_map[finder], {})
        return self._standardize_phase_labels(frame, finder)

    def _resolve_inf_path(self, case_name: str, run_number: int) -> Path:
        try:
            return self.run_index[case_name][run_number]
        except KeyError as exc:
            raise FileNotFoundError(f"Missing .inf file for case '{case_name}' run {run_number}") from exc

    def _render_mm_combined(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path) -> Path:
        idx_map = self._filter_signals(desc_df, job.group_label)
        if "LGp" not in idx_map or "LLp" not in idx_map:
            raise ValueError(f"Combined MM plot requires LGp and LLp for {job.group_label}")

        policy = self._get_group_policy()
        out_cache: dict[int, WaveformFrame] = {}
        bundle_lg = self._process_finder(job, inf_path, idx_map["LGp"], "LGp", "LGp", event_info, policy, out_cache, show_limits=job.show_limits, tov_window_s=job.tov_window_s)
        bundle_ll = self._process_finder(job, inf_path, idx_map["LLp"], "LLp", "LLp", event_info, policy, out_cache, show_limits=job.show_limits, tov_window_s=job.tov_window_s)
        basename, title = self._make_labels(job.case_name, job.group_label, job.run_number, "LGp", event_info, combine=True)

        out = output_dir / f"{basename}_3Ph.png"
        plt.figure(figsize=(self.FIGSIZE[0], 2 * self.FIGSIZE[1]))
        if job.show_three_phase_overview:
            gs = GridSpec(4, 3, height_ratios=[1, 1, 1, 1])

            ax_top_lg = plt.subplot(gs[0, :])
            self._configure_axes(ax_top_lg, bundle_lg["df"], bundle_lg["ylim"], bundle_lg["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_lg, bundle_lg["limits_pack"], legends_left=job.legends_left)

            for index in range(3):
                axis = plt.subplot(gs[1, index])
                self._configure_axes(axis, bundle_lg["df"], bundle_lg["ylim"], bundle_lg["policy"], phase_y=[index + 1], colors=[self.PHASE_COLOURS[index]])
                axis.set_xlim(bundle_lg["xwin_peak"])
                self._render_window_markers_if_enabled(axis, job, bundle_lg["t_peak"])
                self._render_insulation_limits(axis, bundle_lg["limits_pack"])
                if index == bundle_lg["phase_idx"]:
                    self._render_peak_annotation(axis, bundle_lg["t_peak"], bundle_lg["y_peak"], bundle_lg["unit_suffix"], "black")

            ax_top_ll = plt.subplot(gs[2, :])
            self._configure_axes(ax_top_ll, bundle_ll["df"], bundle_ll["ylim"], bundle_ll["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_ll, bundle_ll["limits_pack"], legends_left=job.legends_left)

            for index in range(3):
                axis = plt.subplot(gs[3, index])
                self._configure_axes(axis, bundle_ll["df"], bundle_ll["ylim"], bundle_ll["policy"], phase_y=[index + 1], colors=[self.PHASE_COLOURS[index]])
                axis.set_xlim(bundle_ll["xwin_peak"])
                self._render_window_markers_if_enabled(axis, job, bundle_ll["t_peak"])
                self._render_insulation_limits(axis, bundle_ll["limits_pack"])
                if index == bundle_ll["phase_idx"]:
                    self._render_peak_annotation(axis, bundle_ll["t_peak"], bundle_ll["y_peak"], bundle_ll["unit_suffix"], "black")
        else:
            gs = GridSpec(2, 1)
            ax_top_lg = plt.subplot(gs[0, 0])
            self._configure_axes(ax_top_lg, bundle_lg["df"], bundle_lg["ylim"], bundle_lg["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_lg, bundle_lg["limits_pack"], legends_left=job.legends_left)

            ax_top_ll = plt.subplot(gs[1, 0])
            self._configure_axes(ax_top_ll, bundle_ll["df"], bundle_ll["ylim"], bundle_ll["policy"], legends_left=job.legends_left)
            self._add_limits_if_applicable(ax_top_ll, bundle_ll["limits_pack"], legends_left=job.legends_left)

        self._finalize_plot(out, title)
        return out

    def _render_single(self, job: PlotJob, inf_path: Path, desc_df: list[InfDescriptor], event_info: dict[str, object] | None, output_dir: Path, finder: str) -> Path:
        idx_map = self._filter_signals(desc_df, job.group_label)
        if finder not in idx_map:
            raise ValueError(f"Signal '{finder}' not available for {job.group_label}")
        policy = self._get_group_policy()
        bundle = self._process_finder(job, inf_path, idx_map[finder], finder, finder, event_info, policy, {}, show_limits=job.show_limits, tov_window_s=job.tov_window_s)
        out = output_dir / f"{bundle['basename']}_3Ph.png"

        plt.figure(figsize=self.FIGSIZE)
        self._render_three_phase_signal_axes(
            job,
            bundle["df"],
            bundle["ylim"],
            bundle["policy"],
            bundle,
            limits_pack=bundle["limits_pack"],
        )
        self._finalize_plot(out, bundle["title"])
        return out

    def _render_three_phase_signal_axes(
        self,
        job: PlotJob,
        data: WaveformFrame,
        ylim: tuple[float, float],
        policy: dict[str, Any],
        analysis: dict[str, Any],
        *,
        limits_pack: dict[str, float] | None = None,
    ) -> None:
        if job.show_three_phase_overview:
            gs = GridSpec(2, 3, height_ratios=[1, 1])
            ax_top = plt.subplot(gs[0, :])
            self._configure_axes(ax_top, data, ylim, policy, legends_left=job.legends_left)
            if limits_pack:
                self._add_limits_if_applicable(ax_top, limits_pack, legends_left=job.legends_left)

            for index in range(3):
                axis = plt.subplot(gs[1, index])
                self._configure_axes(axis, data, ylim, policy, phase_y=[index + 1], colors=[self.PHASE_COLOURS[index]])
                axis.set_xlim(analysis["xwin_peak"])
                self._render_window_markers_if_enabled(axis, job, analysis["t_peak"])
                if limits_pack:
                    self._render_insulation_limits(axis, limits_pack)
                if index == analysis["phase_idx"]:
                    self._render_peak_annotation(axis, analysis["t_peak"], analysis["y_peak"], policy["unit_suffix"], "black")
            return

        axis = plt.subplot(111)
        self._configure_axes(axis, data, ylim, policy, legends_left=job.legends_left)
        if limits_pack:
            self._add_limits_if_applicable(axis, limits_pack, legends_left=job.legends_left)

    def _process_finder(
        self,
        job: PlotJob,
        inf_path: Path,
        idx_df: list[InfDescriptor],
        finder: str,
        type_tag: str,
        event_info: dict[str, object] | None,
        policy: dict[str, Any],
        out_cache: dict[int, WaveformFrame],
        show_limits: bool,
        tov_window_s: float,
    ) -> dict[str, Any]:
        data = self._load_out_files(inf_path, idx_df, out_cache)
        group_label = job.group_label
        data = self._standardize_phase_labels(data, finder)
        data = self._crop_to_job_time_range(job, data)
        analysis = self._analyze_data(data, type_tag, policy, job.limits, show_limits, tov_window_s, job.tov_window_count)
        basename, title = self._make_labels(job.case_name, group_label, job.run_number, finder, event_info)
        basename = self._basename_with_time_range(job, basename)
        return {
            "df": data,
            "finder": finder,
            "policy": policy,
            "unit_suffix": policy["unit_suffix"],
            "title": title,
            "basename": basename,
            "ylim": analysis["ylim"],
            "limits_pack": analysis["limits_pack"],
            "t_peak": analysis["t_peak"],
            "y_peak": analysis["y_peak"],
            "phase_idx": analysis["phase_idx"],
            "xwin_peak": analysis["xwin_peak"],
        }

    def _load_inf_descriptors(self, inf_path: Path) -> list[InfDescriptor]:
        if inf_path in self._inf_cache:
            self._inf_cache.move_to_end(inf_path)
            return self._inf_cache[inf_path]
        desc_df = parse_inf_descriptors(inf_path)
        self._remember_cache_item(self._inf_cache, inf_path, desc_df, self.MAX_INF_CACHE)
        return desc_df

    def _load_event_info(self, stat_path: Path, run_number: int) -> dict[str, object] | None:
        if not stat_path.exists():
            return None
        if stat_path in self._event_info_cache:
            self._event_info_cache.move_to_end(stat_path)
            return self._event_info_cache[stat_path].get(int(run_number))
        event_info_by_run: dict[int, dict[str, object]] = {}
        for row in parse_stat_rows(stat_path):
            event_info_by_run.setdefault(int(row["run_number"]), row)
        self._remember_cache_item(
            self._event_info_cache,
            stat_path,
            event_info_by_run,
            self.MAX_EVENT_INFO_CACHE,
        )
        return event_info_by_run.get(int(run_number))

    def _find_stat_file(self, directory: Path) -> Path | None:
        if directory in self._stat_file_cache:
            self._stat_file_cache.move_to_end(directory)
            return self._stat_file_cache[directory]
        stat_path = find_stat_file(directory)
        self._remember_cache_item(
            self._stat_file_cache,
            directory,
            stat_path,
            self.MAX_STAT_FILE_CACHE,
        )
        return stat_path

    def _load_out_frame(self, out_file: Path) -> WaveformFrame:
        if out_file in self._out_file_cache:
            self._out_file_cache.move_to_end(out_file)
            return self._out_file_cache[out_file]
        frame = load_out_frame(out_file, self._check_cancel)
        self._remember_cache_item(self._out_file_cache, out_file, frame, self.MAX_OUT_FILE_CACHE)
        return frame

    def _remember_cache_item(self, cache: OrderedDict, key: Any, value: Any, max_size: int) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)

    def _filter_signals(self, desc_df: list[InfDescriptor], group_label: str) -> dict[str, list[InfDescriptor]]:
        sub = [row for row in desc_df if row.Group == group_label]
        idx_map: dict[str, list[InfDescriptor]] = {}
        for tag in ("LGp", "LLp"):
            pattern = rf"(?:^|[_:]){re.escape(tag)}(?:$|[_:])"
            rows = [row for row in sub if re.search(pattern, str(row.Description))]
            if rows:
                idx_map[tag] = sorted(rows, key=lambda row: row.Description)
        if not idx_map:
            raise ValueError(f"No matching instantaneous signals for {group_label}")
        return idx_map

    def _load_out_files(self, inf_file: Path, idx_df: list[InfDescriptor], out_cache: dict[int, WaveformFrame]) -> WaveformFrame:
        arrays: list[np.ndarray] = []
        columns: list[str] = []
        for row in idx_df:
            pgb = int(row.PGB)
            name = str(row.Description)
            file_number, col_number = pgb_to_out_location(pgb)
            if file_number not in out_cache:
                out_file = standard_out_file_path(inf_file, file_number)
                out_cache[file_number] = self._load_out_frame(out_file)
            data = out_cache[file_number]
            if not arrays:
                arrays.append(data.column_values(0))
                columns.append("Time (s)")
            arrays.append(data.column_values(col_number))
            columns.append(name)
        if len(arrays) < 2:
            raise ValueError(f"Expected at least 2 columns (time + signal), got {len(arrays)}")
        return WaveformFrame(np.column_stack(arrays), columns)

    @staticmethod
    def _get_group_policy() -> dict[str, Any]:
        return {
            "unit_suffix": "kV",
            "draw_limits": True,
            "yaxis_label": "Voltage [kV]",
            "limits_mode": "MM",
        }

    @staticmethod
    def _standardize_phase_labels(df: WaveformFrame, finder: str) -> WaveformFrame:
        phase_cols = df.columns[1:]
        ll_mapping = {"a": "ab", "b": "bc", "c": "ca"}
        new_cols = []
        for col in phase_cols:
            phase = str(col).replace("MM_", "").replace(f"{finder}_", "")
            if "LL" in finder:
                phase = ll_mapping.get(phase, phase)
            new_cols.append(f"V_{phase}")
        return df.renamed([df.columns[0]] + new_cols)

    def _analyze_data(
        self,
        df: WaveformFrame,
        type_tag: str,
        policy: dict[str, Any],
        limits: Any,
        show_limits: bool,
        tov_window_s: float,
        tov_window_count: int,
    ) -> dict[str, Any]:
        limits_pack = self._compute_insulation_limits(type_tag, policy, limits) if show_limits else {}
        t_peak, y_peak, phase_idx = self._compute_peaks(df)
        ylim = self._compute_ylimits(df, limits_pack if policy["draw_limits"] else {})
        xwin_peak = self._window_peak_centered(t_peak, tov_window_s, tov_window_count)
        return {
            "limits_pack": limits_pack if policy["draw_limits"] else {},
            "t_peak": t_peak,
            "y_peak": y_peak,
            "phase_idx": phase_idx,
            "ylim": ylim,
            "xwin_peak": xwin_peak,
        }

    def _compute_insulation_limits(self, type_tag: str, policy: dict[str, Any], limits: Any) -> dict[str, float]:
        if policy.get("limits_mode") != "MM" or limits is None:
            return {}
        result: dict[str, float] = {}
        if type_tag == "LGp":
            result["siwl"] = limits.siwl_lg
            result["sdpf"] = limits.sdpf_lg * math.sqrt(2)
        elif type_tag == "LLp":
            result["siwl"] = limits.siwl_ll
            result["sdpf"] = limits.sdpf_ll * math.sqrt(2)
        else:
            return {}
        result["siwl_margin"] = result["siwl"] / self.SAFETY_MARGIN
        result["sdpf_margin"] = result["sdpf"] / self.SAFETY_MARGIN
        return result

    def _compute_peaks(self, df: WaveformFrame) -> tuple[float, float, int]:
        return df.peak_abs()

    def _compute_ylimits(self, df: WaveformFrame, limits_pack: dict[str, float]) -> tuple[float, float]:
        return df.y_limits(limits_pack, self.PAD_YLIM)

    @staticmethod
    def _crop_to_job_time_range(job: PlotJob, frame: WaveformFrame) -> WaveformFrame:
        return frame.time_window(job.time_start_s, job.time_end_s)

    def _basename_with_time_range(self, job: PlotJob, basename: str) -> str:
        token = self._time_range_filename_token(job.time_start_s, job.time_end_s)
        return f"{basename}_{token}" if token else basename

    @staticmethod
    def _time_range_filename_token(start_s: float | None, end_s: float | None) -> str:
        if start_s is None and end_s is None:
            return ""
        if start_s is None:
            return f"Tto{float(end_s):g}s"
        if end_s is None:
            return f"Tfrom{float(start_s):g}s"
        return f"T{float(start_s):g}-{float(end_s):g}s"

    def _window_peak_centered(self, t_peak: float, tov_window_s: float, tov_window_count: int) -> tuple[float, float]:
        width = float(tov_window_s) * max(1, int(tov_window_count)) * self.WINDOW_MULTIPLIER
        return t_peak - width, t_peak + width

    def _make_labels(self, case_name: str, group_label: str, run_number: int, finder: str, event_info: dict[str, object] | None, combine: bool = False) -> tuple[str, str]:
        group_safe = self._sanitize_filename_token(group_label)
        finder_safe = self._sanitize_filename_token(finder)
        if event_info is not None:
            fault_raw = str(event_info.get("fault_raw", "0"))
            fault_label = str(event_info.get("fault_label", fault_raw or "No fault"))
            event_title = self._format_event_title(event_info)
            if fault_label == "No fault" or fault_raw == "0":
                basename = f"{case_name}_{group_safe}_{run_number:03d}_{finder_safe}"
                title = f"Case: {case_name} | Group: {group_label} | Run: {run_number} | {event_title} | {finder}"
            else:
                fault_safe = self._sanitize_filename_token(fault_label)
                basename = f"{case_name}_{group_safe}_{fault_safe}_{run_number:03d}_{finder_safe}"
                title = f"Case: {case_name} | Group: {group_label} | Run: {run_number} | Fault: {fault_label} | {event_title} | {finder}"
        else:
            basename = f"{case_name}_{group_safe}_{run_number:03d}_{finder_safe}"
            title = f"Case: {case_name} | Group: {group_label} | Run: {run_number} | {finder}"
        if combine:
            basename = re.sub(f"_{re.escape(finder_safe)}$", "_LGp_LLp", basename)
            title = re.sub(f" \\| {re.escape(finder)}$", " | LGp & LLp", title)
        return basename, title

    def _format_event_title(self, event_info: dict[str, object]) -> str:
        phase_values = event_info.get("event_times_s")
        if isinstance(phase_values, dict):
            phase_parts = [
                (phase, self._format_event_time(phase_values.get(phase)))
                for phase in ("a", "b", "c")
                if phase_values.get(phase) is not None
            ]
            if len(phase_parts) > 1 and len({value for _, value in phase_parts}) > 1:
                return " | ".join(f"Tevent_{phase}: {value}" for phase, value in phase_parts)
        return f"Tevent: {self._format_event_time(event_info.get('event_time_s'))}"

    @staticmethod
    def _format_event_time(value: object) -> str:
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.4f}s"
        except (TypeError, ValueError):
            return str(value)

    def _sanitize_filename_token(self, value: str) -> str:
        sanitized = self.INVALID_FILENAME_CHARS.sub("_", value.strip())
        sanitized = re.sub(r"\s+", "_", sanitized)
        sanitized = sanitized.rstrip(". ")
        return sanitized or "value"

    def _render_insulation_limits(self, ax: plt.Axes, limits_pack: dict[str, float]) -> None:
        if "siwl" in limits_pack:
            for value in [limits_pack["siwl"], -limits_pack["siwl"]]:
                ax.axhline(value, color="red", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THIN)
            for value in [limits_pack["siwl_margin"], -limits_pack["siwl_margin"]]:
                ax.axhline(value, color="orange", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THIN)
        if "sdpf" in limits_pack:
            for value in [limits_pack["sdpf"], -limits_pack["sdpf"]]:
                ax.axhline(value, color="red", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THICK)
            for value in [limits_pack["sdpf_margin"], -limits_pack["sdpf_margin"]]:
                ax.axhline(value, color="orange", linestyle="--", linewidth=self.LINEWIDTH_LIMIT_THICK)

    def _render_insulation_limits_legend(self, ax: plt.Axes, limits_pack: dict[str, float], *, legends_left: bool = False) -> None:
        handles = []
        if "siwl" in limits_pack:
            handles.append(plt.Line2D([], [], color="red", ls="--", lw=self.LINEWIDTH_LIMIT_THIN, label="SIWL limit"))
            handles.append(plt.Line2D([], [], color="orange", ls="--", lw=self.LINEWIDTH_LIMIT_THIN, label="SIWL safety margin"))
        if "sdpf" in limits_pack:
            handles.append(plt.Line2D([], [], color="red", ls="--", lw=self.LINEWIDTH_LIMIT_THICK, label="SDPF limit"))
            handles.append(plt.Line2D([], [], color="orange", ls="--", lw=self.LINEWIDTH_LIMIT_THICK, label="SDPF safety margin"))
        if handles:
            ax.legend(handles=handles, loc="lower left" if legends_left else "lower right", fontsize=self.FONTSIZE_LEGEND)

    def _add_limits_if_applicable(self, ax: plt.Axes, limits_pack: dict[str, float], *, legends_left: bool = False) -> None:
        if limits_pack:
            self._render_insulation_limits(ax, limits_pack)
            self._render_insulation_limits_legend(ax, limits_pack, legends_left=legends_left)

    def _render_tov_window(self, ax: plt.Axes, t_peak: float, tov_window_s: float, tov_window_count: int) -> None:
        for index in range(0, max(1, int(tov_window_count)) + 1):
            offset = index * float(tov_window_s)
            ax.axvline(t_peak - offset, color="violet", lw=self.LINEWIDTH_ANNO, ls="--")
            ax.axvline(t_peak + offset, color="violet", lw=self.LINEWIDTH_ANNO, ls="--")

    def _render_window_markers_if_enabled(self, ax: plt.Axes, job: PlotJob, t_peak: float) -> None:
        if not job.show_tov_windows:
            return
        self._render_tov_window(ax, t_peak, job.tov_window_s, job.tov_window_count)

    def _render_peak_annotation(self, ax: plt.Axes, t_peak: float, y_peak: float, unit_suffix: str, color: str) -> None:
        ylim = ax.get_ylim()
        y_range = ylim[1] - ylim[0]
        y_offset = self.ANNO_Y_OFFSET * y_range
        y_text = y_peak + y_offset if y_peak >= 0 else y_peak - y_offset
        vertical_align = "bottom" if y_peak >= 0 else "top"
        self._expand_ylim_for_peak_annotation(ax, y_text, vertical_align, y_range)
        ax.axvline(t_peak, color=color, lw=self.LINEWIDTH_ANNO, ls="--")
        unit = f" {unit_suffix}" if unit_suffix else ""
        ax.annotate(
            f"{y_peak:.1f}{unit} @ {t_peak:.3f} s",
            xy=(t_peak, y_peak),
            xytext=(t_peak + self.ANNO_X_OFFSET, y_text),
            textcoords="data",
            color=color,
            fontsize=self.FONTSIZE_ANNO,
            ha="right",
            va=vertical_align,
        )

    def _expand_ylim_for_peak_annotation(self, ax: plt.Axes, y_text: float, vertical_align: str, y_range: float) -> None:
        bottom, top = ax.get_ylim()
        padding = max(abs(y_range) * self.ANNO_Y_LIMIT_PAD, 1e-9)
        if vertical_align == "bottom" and y_text + padding > top:
            ax.set_ylim(bottom, y_text + padding)
        elif vertical_align == "top" and y_text - padding < bottom:
            ax.set_ylim(y_text - padding, top)

    def _configure_axes(
        self,
        ax: plt.Axes,
        df: WaveformFrame,
        ylim: tuple[float, float],
        policy: dict[str, Any],
        phase_y: list[int] | None = None,
        colors: list[str] | None = None,
        legends_left: bool = False,
    ) -> None:
        phase_y = phase_y or self.PHASE_COLS
        colors = colors or self.PHASE_COLOURS
        ax.set_ylim(ylim)
        ax.set_ylabel(policy["yaxis_label"])
        ax.set_xlabel("Time [s]")
        time_values = df.column_values(0)
        for column_index, color in zip(phase_y, colors):
            ax.plot(
                time_values,
                df.column_values(column_index),
                color=color,
                lw=self.LINEWIDTH_TRACE,
                label=str(df.columns[column_index]),
            )
        ax.grid(True, linewidth=self.LINEWIDTH_GRID, color="gray", linestyle="-", alpha=self.GRID_ALPHA)
        phase_legend = ax.legend(loc="upper left" if legends_left else "upper right", fontsize=self.FONTSIZE_LEGEND)
        ax.add_artist(phase_legend)

    def _finalize_plot(self, out_path: Path, title: str) -> None:
        figure = plt.gcf()
        figure.suptitle(title, fontsize=self.FONTSIZE_TITLE)
        figure.subplots_adjust(top=0.9)
        figure.tight_layout(pad=self.TIGHT_LAYOUT_PAD)
        figure.savefig(out_path, dpi=self.DPI)
        plt.close(figure)
