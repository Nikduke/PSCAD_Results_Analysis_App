from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from results_analysis_app import scanner


CancelFn = Callable[[], None]


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
