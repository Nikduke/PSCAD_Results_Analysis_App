from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from results_analysis_app import project_scan_cache, scanner, storage


CancelFn = Callable[[], None]
LogFn = Callable[[str], None]


@dataclass(frozen=True)
class ProjectScanBatch:
    current_path: str | None
    scans: dict[str, scanner.ProjectScan]


def scan_projects(
    project_paths: Iterable[str],
    current_path: str | None,
    nonconv_cb_iip_limit: float | None,
    nonconv_cb_iir_limit: float | None,
    high_voltage_limit_factor: float,
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    check_cancel: CancelFn | None = None,
) -> ProjectScanBatch:
    paths = list(project_paths)
    scans = {}
    for project_path in paths:
        if check_cancel is not None:
            check_cancel()
        scans[project_path] = scanner.scan_project(
            project_path,
            nonconv_cb_iip_limit=nonconv_cb_iip_limit,
            nonconv_cb_iir_limit=nonconv_cb_iir_limit,
            high_voltage_limit_factor=high_voltage_limit_factor,
            voltage_um_overrides=(voltage_um_overrides_by_project or {}).get(project_path, {}),
            check_cancel=check_cancel,
        )
    return ProjectScanBatch(current_path=current_path, scans=scans)


def scan_projects_cached(
    project_paths: Iterable[str],
    current_path: str | None,
    nonconv_cb_iip_limit: float | None,
    nonconv_cb_iir_limit: float | None,
    high_voltage_limit_factor: float = 1.0,
    voltage_um_overrides_by_project: dict[str, dict[str, float]] | None = None,
    *,
    force: bool = False,
    check_cancel: CancelFn | None = None,
    log: LogFn | None = None,
    cache_path: Path = storage.PROJECT_SCAN_CACHE_PATH,
) -> ProjectScanBatch:
    paths = list(dict.fromkeys(str(Path(path).resolve()) for path in project_paths))
    limits = (nonconv_cb_iip_limit, nonconv_cb_iir_limit)
    cache = project_scan_cache.load(cache_path)
    scans: dict[str, scanner.ProjectScan] = {}
    stale_paths: list[str] = []
    refreshed_paths: list[str] = []
    manifests: dict[str, dict] = {}

    for project_path in paths:
        if check_cancel is not None:
            check_cancel()
        cached_entry = cache.get("projects", {}).get(project_path)
        if force or not isinstance(cached_entry, dict):
            stale_paths.append(project_path)
            continue
        manifest = scanner.project_scan_manifest(project_path)
        manifests[project_path] = manifest
        cached = project_scan_cache.cached_scan(
            cache,
            project_path,
            limits,
            current_manifest=manifest,
        )
        if cached is None:
            stale_paths.append(project_path)
        else:
            envelope_changed = project_scan_cache.manifest_section_changed(
                cache,
                project_path,
                manifest,
                "envelope_files",
            )
            if envelope_changed:
                message_count = len(cached.messages)
                scanner.refresh_project_scan_outputs(
                    cached,
                    refresh_envelopes=True,
                    refresh_high_voltage_exclusions=True,
                    high_voltage_limit_factor=high_voltage_limit_factor,
                    voltage_um_overrides=(voltage_um_overrides_by_project or {}).get(
                        project_path,
                        {},
                    ),
                )
                refreshed_paths.append(project_path)
                if log is not None:
                    log(f"Refreshing envelope high-voltage data: {Path(project_path).name}")
                    for warning in cached.messages[message_count:]:
                        log(warning)
            overrides = (voltage_um_overrides_by_project or {}).get(project_path, {})
            high_voltage_state = project_scan_cache.high_voltage_cache_state(
                cache,
                project_path,
                manifest,
                high_voltage_limit_factor,
                overrides,
            )
            if high_voltage_state == "files":
                if log is not None:
                    log(f"Refreshing PSCAD log high-voltage data: {Path(project_path).name}")
                warnings = scanner.refresh_high_voltage_log_scan(
                    cached,
                    high_voltage_limit_factor,
                    overrides,
                    check_cancel=check_cancel,
                )
                if project_path not in refreshed_paths:
                    refreshed_paths.append(project_path)
                if log is not None:
                    for warning in warnings:
                        log(warning)
            elif high_voltage_state == "settings":
                warnings = scanner.refresh_high_voltage_log_exclusions(
                    cached,
                    high_voltage_limit_factor,
                    overrides,
                )
                if project_path not in refreshed_paths:
                    refreshed_paths.append(project_path)
                if log is not None:
                    for warning in warnings:
                        log(warning)
            scans[project_path] = cached
            if any(
                project_scan_cache.manifest_section_changed(
                    cache,
                    project_path,
                    manifest,
                    key,
                )
                for key in ("dashboard_files", "output_state")
            ) and project_path not in refreshed_paths:
                refreshed_paths.append(project_path)
            if cached.dashboard_changed and log is not None:
                log(
                    f"Dashboard files changed: {Path(project_path).name}. "
                    "Use Scan figures or Dashboards update when needed."
                )

    if stale_paths:
        if log is not None:
            action = "Rebuilding" if force else "Scanning changed"
            log(f"{action} project data: {len(stale_paths)} project(s)")
        fresh = scan_projects(
            stale_paths,
            current_path,
            nonconv_cb_iip_limit,
            nonconv_cb_iir_limit,
            high_voltage_limit_factor,
            voltage_um_overrides_by_project,
            check_cancel=check_cancel,
        )
        scans.update(fresh.scans)
        if log is not None:
            for project_path in stale_paths:
                scan = fresh.scans.get(project_path)
                if scan is None:
                    continue
                for message in dict.fromkeys(scan.messages):
                    log(f"{Path(project_path).name}: {message}")
    elif log is not None and not refreshed_paths:
        log("Project scan cache valid; reused saved project data.")

    changed_paths = [*stale_paths, *refreshed_paths]
    if changed_paths:
        try:
            project_scan_cache.update_project_scans(
                scans,
                changed_paths,
                limits,
                cache_path,
                high_voltage_limit_factor=high_voltage_limit_factor,
                voltage_um_overrides_by_project=voltage_um_overrides_by_project,
                manifests_by_project=manifests,
            )
        except (OSError, TypeError, ValueError) as exc:
            if log is not None:
                log(f"Project scan cache could not be saved: {exc}")
    return ProjectScanBatch(current_path=current_path, scans=scans)
