from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from results_analysis_app import scanner, storage


CACHE_VERSION = 1


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
    high_voltage_rows = [
        row
        for row in scan.high_voltage_exclusions
        if row.file not in scanner.PSCAD_LOG_HIGH_VOLTAGE_SOURCES
    ]
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
            }
            for item in high_voltage_rows
        ],
        "available_voltages": list(scan.available_voltages),
        "has_dashboards": scan.has_dashboards,
        "has_envelopes": scan.has_envelopes,
        "has_plots": scan.has_plots,
        "has_reports": scan.has_reports,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _deserialize_scan(project_path: str, payload: Any) -> scanner.ProjectScan | None:
    if not isinstance(payload, dict):
        return None
    root = Path(project_path).resolve()

    case_infos: list[scanner.CaseInfo] = []
    for item in payload.get("case_infos", []):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        case_infos.append(
            scanner.CaseInfo(
                name=str(item["name"]),
                inf_path=_path_from_cache(item.get("inf_path", ""), root),
            )
        )

    nonconv_cases: list[scanner.NonConvergentCase] = []
    for item in payload.get("nonconv_cases", []):
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
    for item in payload.get("high_voltage_exclusions", []):
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
            )
        )

    return scanner.ProjectScan(
        path=root,
        exists=bool(payload.get("exists", root.is_dir())),
        chips=[str(value) for value in payload.get("chips", [])],
        messages=[str(value) for value in payload.get("messages", [])],
        case_infos=case_infos,
        nonconv_cases=nonconv_cases,
        high_voltage_exclusions=high_voltage_exclusions,
        available_voltages=[str(value) for value in payload.get("available_voltages", [])],
        has_dashboards=bool(payload.get("has_dashboards", False)),
        has_envelopes=bool(payload.get("has_envelopes", False)),
        has_plots=bool(payload.get("has_plots", False)),
        has_reports=bool(payload.get("has_reports", False)),
    )


def _cache_entry(
    project_path: str,
    scan: scanner.ProjectScan,
    nonconv_limits: tuple[float | None, float | None],
) -> dict[str, Any]:
    root = Path(project_path).resolve()
    return {
        "manifest": scanner.project_scan_manifest(root),
        "nonconv_limits": [nonconv_limits[0], nonconv_limits[1]],
        "scan": _serialize_scan(scan, root),
    }


def cached_scan(
    data: dict[str, Any],
    project_path: str,
    nonconv_limits: tuple[float | None, float | None],
) -> scanner.ProjectScan | None:
    root = Path(project_path).resolve()
    entry = data.get("projects", {}).get(str(root))
    if not isinstance(entry, dict):
        return None
    if entry.get("manifest") != scanner.project_scan_manifest(root):
        return None
    expected_limits = [nonconv_limits[0], nonconv_limits[1]]
    if entry.get("nonconv_limits") != expected_limits:
        return None
    return _deserialize_scan(str(root), entry.get("scan"))


def update_project_scans(
    scans: dict[str, scanner.ProjectScan],
    project_paths: Iterable[str],
    nonconv_limits: tuple[float | None, float | None],
    path: Path = storage.PROJECT_SCAN_CACHE_PATH,
) -> None:
    data = load(path)
    projects = data["projects"]
    for project_path in project_paths:
        key = str(Path(project_path).resolve())
        scan = scans.get(project_path) or scans.get(key)
        if scan is None:
            projects.pop(key, None)
            continue
        projects[key] = _cache_entry(key, scan, nonconv_limits)
    storage.write_json(path, data)


def remove_projects(project_paths: Iterable[str], path: Path = storage.PROJECT_SCAN_CACHE_PATH) -> None:
    data = load(path)
    projects = data["projects"]
    changed = False
    for project_path in project_paths:
        changed = projects.pop(str(Path(project_path).resolve()), None) is not None or changed
    if changed:
        storage.write_json(path, data)


def clear(path: Path = storage.PROJECT_SCAN_CACHE_PATH) -> None:
    if path.exists():
        path.unlink()
