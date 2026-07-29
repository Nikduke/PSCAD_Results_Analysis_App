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
        )
    return ProjectScanBatch(current_path=current_path, scans=scans)


def scan_projects_cached(
    project_paths: Iterable[str],
    current_path: str | None,
    nonconv_cb_iip_limit: float | None,
    nonconv_cb_iir_limit: float | None,
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

    for project_path in paths:
        if check_cancel is not None:
            check_cancel()
        cached = None if force else project_scan_cache.cached_scan(cache, project_path, limits)
        if cached is None:
            stale_paths.append(project_path)
        else:
            scans[project_path] = cached

    if stale_paths:
        if log is not None:
            action = "Rebuilding" if force else "Scanning changed"
            log(f"{action} project data: {len(stale_paths)} project(s)")
        fresh = scan_projects(
            stale_paths,
            current_path,
            nonconv_cb_iip_limit,
            nonconv_cb_iir_limit,
            check_cancel=check_cancel,
        )
        scans.update(fresh.scans)
    elif log is not None:
        log("Project scan cache valid; reused saved project data.")

    if stale_paths:
        try:
            project_scan_cache.update_project_scans(scans, stale_paths, limits, cache_path)
        except (OSError, TypeError, ValueError) as exc:
            if log is not None:
                log(f"Project scan cache could not be saved: {exc}")
    return ProjectScanBatch(current_path=current_path, scans=scans)
