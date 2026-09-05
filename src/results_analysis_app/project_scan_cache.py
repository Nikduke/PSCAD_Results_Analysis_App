from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from results_analysis_app import scanner, storage, sustained_sdpf
from results_analysis_app.common import as_float
from results_analysis_app.project_config import VoltageConfig


CACHE_VERSION = 7


def _empty_cache() -> dict[str, Any]:
    return {"version": CACHE_VERSION, "projects": {}}


def load(path: Path = storage.PROJECT_SCAN_CACHE_PATH) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return _empty_cache()
    if data.get("version") != CACHE_VERSION or not isinstance(data.get("projects"), dict):
        return _empty_cache()
    return data


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _path_from_cache(value: Any, root: Path) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _serialize_scan(scan: scanner.ProjectScan, root: Path) -> dict[str, Any]:
    return {
        "exists": scan.exists,
        "chips": list(scan.chips),
        "messages": list(scan.messages),
        "case_infos": [
            {"name": item.name, "inf_path": _relative_path(item.inf_path, root)}
            for item in scan.case_infos
        ],
        "nonconv_cases": [
            {
                "case": item.case,
                "run": item.run,
                "fault_type": item.fault_type,
                "source": item.source,
                "signal": item.signal,
                "reason": item.reason,
                "value": item.value,
                "file": item.file,
            }
            for item in scan.nonconv_cases
        ],
        "high_voltage_exclusions": [
            {
                "voltage": item.voltage,
                "case": item.case,
                "run": item.run,
                "bus": item.bus,
                "fault_type": item.fault_type,
                "measurement": item.measurement,
                "signal": item.signal,
                "file": item.file,
                "excluded_values": item.excluded_values,
                "max_abs": item.max_abs,
                "limit": item.limit,
                "source": item.source,
                "excluded": item.excluded,
            }
            for item in scan.high_voltage_exclusions
        ],
        "high_voltage_log_measurements": [
            {
                "voltage": item.voltage,
                "case": item.case,
                "run": item.run,
                "bus": item.bus,
                "measurement": item.measurement,
                "signal": item.signal,
                "file": item.file,
                "max_abs": item.max_abs,
            }
            for item in scan.high_voltage_log_measurements
        ],
        "fault_types_by_run": {
            str(run): fault_type
            for run, fault_type in scan.fault_types_by_run.items()
        },
        "available_voltages": list(scan.available_voltages),
        "voltage_configs": {
            voltage: {
                "voltage": config.voltage,
                "bus_prefix": config.bus_prefix,
                "um": config.um,
            }
            for voltage, config in scan.voltage_configs.items()
        },
        "sustained_sdpf_limits": {
            voltage: limit.to_dict()
            for voltage, limit in scan.sustained_sdpf_limits.items()
        },
        "sustained_sdpf_limit_warnings": list(scan.sustained_sdpf_limit_warnings),
        "project_frequency": scan.project_frequency,
        "final_duration": scan.final_duration,
        "has_dashboards": scan.has_dashboards,
        "dashboard_figures": [
            {
                "id": figure.id,
                "workbook": figure.workbook,
                "sheet": figure.sheet,
                "chart_index": figure.chart_index,
                "title": figure.title,
            }
            for figure in scan.dashboard_figures
        ],
        "dashboard_changed": scan.dashboard_changed,
        "has_envelopes": scan.has_envelopes,
        "has_plots": scan.has_plots,
        "has_reports": scan.has_reports,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _payload_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _deserialize_scan(project_path: str, payload: Any) -> scanner.ProjectScan | None:
    if not isinstance(payload, dict):
        return None
    root = Path(project_path).resolve()

    case_infos: list[scanner.CaseInfo] = []
    for item in _payload_list(payload, "case_infos"):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        case_infos.append(
            scanner.CaseInfo(
                name=str(item["name"]),
                inf_path=_path_from_cache(item.get("inf_path", ""), root),
            )
        )

    nonconv_cases: list[scanner.NonConvergentCase] = []
    for item in _payload_list(payload, "nonconv_cases"):
        if not isinstance(item, dict):
            continue
        run = _as_int(item.get("run"))
        case = str(item.get("case", "")).strip()
        if run is None or not case:
            continue
        nonconv_cases.append(
            scanner.NonConvergentCase(
                case=case,
                run=run,
                fault_type=str(item.get("fault_type", "")),
                source=str(item.get("source", "")),
                signal=str(item.get("signal", "")),
                reason=str(item.get("reason", "")),
                value=str(item.get("value", "")),
                file=str(item.get("file", "")),
            )
        )

    high_voltage_exclusions: list[scanner.HighVoltageExclusion] = []
    for item in _payload_list(payload, "high_voltage_exclusions"):
        if not isinstance(item, dict):
            continue
        run = _as_int(item.get("run"))
        case = str(item.get("case", "")).strip()
        bus = str(item.get("bus", "")).strip()
        if run is None or not case or not bus:
            continue
        high_voltage_exclusions.append(
            scanner.HighVoltageExclusion(
                voltage=str(item.get("voltage", "")),
                case=case,
                run=run,
                bus=bus,
                fault_type=str(item.get("fault_type", "")),
                measurement=str(item.get("measurement", "")),
                signal=str(item.get("signal", "")),
                file=str(item.get("file", "")),
                excluded_values=str(item.get("excluded_values", "")),
                max_abs=str(item.get("max_abs", "")),
                limit=str(item.get("limit", "")),
                source=str(item.get("source", "")),
                excluded=bool(item.get("excluded", False)),
            )
        )

    high_voltage_log_measurements: list[scanner.HighVoltageMeasurement] = []
    for item in _payload_list(payload, "high_voltage_log_measurements"):
        if not isinstance(item, dict):
            continue
        run = _as_int(item.get("run"))
        try:
            max_abs = float(item.get("max_abs"))
        except (TypeError, ValueError):
            continue
        case = str(item.get("case", "")).strip()
        bus = str(item.get("bus", "")).strip()
        if run is None or not case or not bus:
            continue
        high_voltage_log_measurements.append(
            scanner.HighVoltageMeasurement(
                voltage=str(item.get("voltage", "")),
                case=case,
                run=run,
                bus=bus,
                measurement=str(item.get("measurement", "")),
                signal=str(item.get("signal", "")),
                file=str(item.get("file", "")),
                max_abs=max_abs,
            )
        )

    fault_types_by_run: dict[int, str] = {}
    raw_fault_types = payload.get("fault_types_by_run")
    if isinstance(raw_fault_types, dict):
        for raw_run, raw_fault_type in raw_fault_types.items():
            try:
                run = int(raw_run)
            except (TypeError, ValueError):
                continue
            fault_types_by_run[run] = str(raw_fault_type)

    voltage_configs: dict[str, VoltageConfig] = {}
    raw_voltage_configs = payload.get("voltage_configs")
    if isinstance(raw_voltage_configs, dict):
        for raw_voltage, item in raw_voltage_configs.items():
            if not isinstance(item, dict):
                continue
            voltage = str(item.get("voltage", raw_voltage)).strip()
            bus_prefix = str(item.get("bus_prefix", "")).strip()
            um = as_float(item.get("um"))
            if voltage and bus_prefix and um is not None and um > 0:
                voltage_configs[str(raw_voltage)] = VoltageConfig(voltage, bus_prefix, um)

    sustained_sdpf_limits: dict[str, sustained_sdpf.SDPFVoltageLimits] = {}
    raw_sustained_limits = payload.get("sustained_sdpf_limits")
    if isinstance(raw_sustained_limits, dict):
        for raw_voltage, item in raw_sustained_limits.items():
            if not isinstance(item, dict):
                continue
            voltage = as_float(item.get("voltage_kv"))
            sdpf_lg = as_float(item.get("sdpf_lg_rms"))
            sdpf_ll = as_float(item.get("sdpf_ll_rms"))
            if (
                voltage is not None
                and sdpf_lg is not None
                and sdpf_ll is not None
                and voltage > 0
                and sdpf_lg > 0
                and sdpf_ll > 0
            ):
                sustained_sdpf_limits[str(raw_voltage)] = sustained_sdpf.SDPFVoltageLimits(
                    voltage,
                    sdpf_lg,
                    sdpf_ll,
                    str(item.get("source", "workbook")),
                )

    dashboard_figures: list[scanner.DashboardFigure] = []
    seen_dashboard_figure_ids: set[str] = set()
    for item in _payload_list(payload, "dashboard_figures"):
        if not isinstance(item, dict):
            continue
        figure_id = str(item.get("id", "")).strip()
        workbook = str(item.get("workbook", "")).strip()
        sheet = str(item.get("sheet", "")).strip()
        chart_index = _as_int(item.get("chart_index"))
        if (
            not figure_id
            or figure_id in seen_dashboard_figure_ids
            or not workbook
            or not sheet
            or chart_index is None
            or chart_index < 1
        ):
            continue
        seen_dashboard_figure_ids.add(figure_id)
        dashboard_figures.append(
            scanner.DashboardFigure(
                id=figure_id,
                workbook=workbook,
                sheet=sheet,
                chart_index=chart_index,
                title=str(item.get("title", "")).strip(),
            )
        )

    chips = [str(value) for value in _payload_list(payload, "chips")]
    return scanner.ProjectScan(
        path=root,
        exists=bool(payload.get("exists", root.is_dir())),
        chips=chips,
        messages=[str(value) for value in _payload_list(payload, "messages")],
        case_infos=case_infos,
        nonconv_cases=nonconv_cases,
        high_voltage_exclusions=high_voltage_exclusions,
        high_voltage_log_measurements=high_voltage_log_measurements,
        fault_types_by_run=fault_types_by_run,
        available_voltages=[str(value) for value in _payload_list(payload, "available_voltages")],
        voltage_configs=voltage_configs,
        sustained_sdpf_limits=sustained_sdpf_limits,
        sustained_sdpf_limit_warnings=[
            str(value)
            for value in _payload_list(payload, "sustained_sdpf_limit_warnings")
        ],
        project_frequency=as_float(payload.get("project_frequency")),
        final_duration=as_float(payload.get("final_duration")),
        has_dashboards=bool(payload.get("has_dashboards", False)),
        dashboard_figures=dashboard_figures,
        dashboard_changed=bool(
            payload.get("dashboard_changed", "Dashboards changed" in chips)
        ),
        has_envelopes=bool(payload.get("has_envelopes", False)),
        has_plots=bool(payload.get("has_plots", False)),
        has_reports=bool(payload.get("has_reports", False)),
    )


def _cache_entry(
    project_path: str,
    scan: scanner.ProjectScan,
    nonconv_limits: tuple[float | None, float | None],
    high_voltage_limit_factor: float | None = None,
    voltage_um_overrides: dict[str, float] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_path).resolve()
    return {
        "manifest": manifest or scanner.project_scan_manifest(root),
        "nonconv_limits": [nonconv_limits[0], nonconv_limits[1]],
        "high_voltage_settings": _high_voltage_settings(
            high_voltage_limit_factor,
            voltage_um_overrides,
        ),
        "scan": _serialize_scan(scan, root),
    }


def _high_voltage_settings(
    high_voltage_limit_factor: float | None,
    voltage_um_overrides: dict[str, float] | None,
) -> dict[str, Any] | None:
    if high_voltage_limit_factor is None:
        return None
    return {
        "limit_factor": float(high_voltage_limit_factor),
        "um_overrides": {
            str(voltage): float(value)
            for voltage, value in sorted((voltage_um_overrides or {}).items())
        },
    }


def _manifest_section(manifest: Any, key: str) -> Any:
    if not isinstance(manifest, dict):
        return None
    value = manifest.get(key)
    if key == "output_state":
        return value if isinstance(value, dict) else None
    return value if isinstance(value, list) else None


def manifest_section_changed(
    data: dict[str, Any],
    project_path: str,
    current_manifest: dict[str, Any],
    key: str,
) -> bool:
    entry = data.get("projects", {}).get(str(Path(project_path).resolve()))
    stored_manifest = entry.get("manifest") if isinstance(entry, dict) else None
    return _manifest_section(stored_manifest, key) != _manifest_section(current_manifest, key)


def cached_scan(
    data: dict[str, Any],
    project_path: str,
    nonconv_limits: tuple[float | None, float | None],
    *,
    current_manifest: dict[str, Any] | None = None,
) -> scanner.ProjectScan | None:
    root = Path(project_path).resolve()
    entry = data.get("projects", {}).get(str(root))
    if not isinstance(entry, dict):
        return None
    stored_manifest = entry.get("manifest")
    current_manifest = current_manifest or scanner.project_scan_manifest(root)
    if (
        not isinstance(stored_manifest, dict)
        or stored_manifest.get("exists") != current_manifest.get("exists")
        or _manifest_section(stored_manifest, "files")
        != _manifest_section(current_manifest, "files")
    ):
        return None
    expected_limits = [nonconv_limits[0], nonconv_limits[1]]
    if entry.get("nonconv_limits") != expected_limits:
        return None
    scan = _deserialize_scan(str(root), entry.get("scan"))
    if scan is None:
        return None
    scanner.apply_project_output_state(scan, current_manifest.get("output_state"))
    current_dashboards = _manifest_section(current_manifest, "dashboard_files")
    if _manifest_section(stored_manifest, "dashboard_files") != current_dashboards:
        scanner.mark_dashboard_changed(scan)
    return scan


def high_voltage_cache_state(
    data: dict[str, Any],
    project_path: str,
    current_manifest: dict[str, Any],
    high_voltage_limit_factor: float,
    voltage_um_overrides: dict[str, float] | None,
) -> str:
    entry = data.get("projects", {}).get(str(Path(project_path).resolve()))
    if not isinstance(entry, dict):
        return "files"
    stored_manifest = entry.get("manifest")
    stored_files = (
        stored_manifest.get("high_voltage_files")
        if isinstance(stored_manifest, dict)
        else None
    )
    if stored_files != current_manifest.get("high_voltage_files", []):
        return "files"
    expected_settings = _high_voltage_settings(
        high_voltage_limit_factor,
        voltage_um_overrides,
    )
    if entry.get("high_voltage_settings") != expected_settings:
        return "settings"
    return "valid"


def update_project_scans(
    scans: dict[str, scanner.ProjectScan],
    project_paths: Iterable[str],
    nonconv_limits: tuple[float | None, float | None],
    path: Path = storage.PROJECT_SCAN_CACHE_PATH,
    *,
    high_voltage_limit_factor: float | None = None,
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    manifests_by_project: dict[str, dict[str, Any]] | None = None,
    preserve_input_manifest: bool = False,
) -> None:
    data = load(path)
    projects = data["projects"]
    for project_path in project_paths:
        key = str(Path(project_path).resolve())
        scan = scans.get(project_path) or scans.get(key)
        if scan is None:
            projects.pop(key, None)
            continue
        manifest = (manifests_by_project or {}).get(key)
        if manifest is None and preserve_input_manifest:
            stored_entry = projects.get(key)
            stored_manifest = (
                stored_entry.get("manifest")
                if isinstance(stored_entry, dict)
                else None
            )
            if (
                isinstance(stored_manifest, dict)
                and isinstance(stored_manifest.get("files"), list)
                and isinstance(stored_manifest.get("high_voltage_files"), list)
            ):
                manifest = {
                    "exists": Path(key).is_dir(),
                    "files": stored_manifest["files"],
                    "high_voltage_files": stored_manifest["high_voltage_files"],
                    **scanner.project_output_manifest(key),
                }
        projects[key] = _cache_entry(
            key,
            scan,
            nonconv_limits,
            high_voltage_limit_factor,
            (voltage_um_overrides_by_project or {}).get(key, {}),
            manifest,
        )
    # This machine-generated cache can contain thousands of file entries.  It
    # does not need session-style pretty-printing, so keep writes compact.
    storage.write_json(path, data, indent=None)


def remove_projects(project_paths: Iterable[str], path: Path = storage.PROJECT_SCAN_CACHE_PATH) -> None:
    data = load(path)
    projects = data["projects"]
    changed = False
    for project_path in project_paths:
        changed = projects.pop(str(Path(project_path).resolve()), None) is not None or changed
    if changed:
        storage.write_json(path, data, indent=None)


def clear(path: Path = storage.PROJECT_SCAN_CACHE_PATH) -> None:
    if path.exists():
        path.unlink()
