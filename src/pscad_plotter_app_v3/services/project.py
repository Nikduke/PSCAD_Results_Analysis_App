from __future__ import annotations

import csv
import os
import re
import sqlite3
from pathlib import Path

from pscad_plotter_app_v3.models import (
    MMElementRecord,
    ProjectCatalog,
    ProjectContext,
    ProjectMode,
)
from pscad_plotter_app_v3.services.project_conventions import (
    parse_case_run_from_stem,
    parse_manual_run_from_stem,
    safe_float,
)

class ProjectDiscoveryService:
    """Locate project folders and files from a PSCAD project root."""

    SEARCH_UP_DEPTH = 2

    def discover(self, root_dir: str | Path) -> ProjectContext:
        root = self.resolve_project_root(root_dir)
        results_dir = root / "Results"
        case_folder_dir = root / "Case_folder"
        plots_dir = root / "Plots"
        state_dir = plots_dir / ".plottool_v3"
        project_files = self._find_project_files(root)
        project_file = project_files[0] if project_files else None
        workbook = next(root.glob("Input_Data_PSCAD*.xlsx"), None)
        inf_paths_by_dir: dict[Path, list[Path]] = {}
        compiler_output_dirs_by_project = {
            project_path.stem: self._find_compiler_output_dirs_for_project(root, project_path, inf_paths_by_dir)
            for project_path in project_files
        }
        compiler_output_dirs = [
            compiler_dir
            for project_path in project_files
            for compiler_dir in compiler_output_dirs_by_project.get(project_path.stem, [])
        ]
        project_mode = self._detect_project_mode(case_folder_dir, compiler_output_dirs, bool(project_files), inf_paths_by_dir)
        return ProjectContext(
            root_dir=root,
            results_dir=results_dir,
            case_folder_dir=case_folder_dir,
            compiler_output_dirs=compiler_output_dirs,
            compiler_output_dirs_by_project=compiler_output_dirs_by_project,
            inf_paths_by_dir=inf_paths_by_dir,
            plots_dir=plots_dir,
            state_dir=state_dir,
            workbook_path=workbook,
            project_file=project_file,
            project_files=project_files,
            project_mode=project_mode,
        )

    def resolve_project_root(self, root_dir: str | Path) -> Path:
        path = Path(root_dir).resolve()
        if path.is_file():
            path = path.parent
        candidates = [path, *list(path.parents[: self.SEARCH_UP_DEPTH])]
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if self.is_project_root(candidate):
                return candidate
        return path

    def is_project_root(self, path: str | Path) -> bool:
        candidate = Path(path)
        if not candidate.exists() or not candidate.is_dir():
            return False
        if (candidate / "Results").is_dir() and (candidate / "Case_folder").is_dir():
            return True
        if next(candidate.glob("Input_Data_PSCAD*.xlsx"), None) is not None:
            return True
        if next(candidate.glob("*.pscx"), None) is not None:
            return True
        return False

    @staticmethod
    def _find_project_files(root: Path) -> list[Path]:
        project_files = sorted(root.glob("*.pscx"))
        if not project_files:
            return []
        exact_name = root.name.lower()
        return sorted(
            project_files,
            key=lambda path: (
                0 if path.stem.lower() == exact_name else 1,
                len(path.stem),
                path.stem.lower(),
            ),
        )

    @staticmethod
    def _find_compiler_output_dirs_for_project(root: Path, project_file: Path, inf_paths_by_dir: dict[Path, list[Path]]) -> list[Path]:
        project_stem = project_file.stem
        project_prefix = f"{project_stem}."
        project_prefix_lower = project_prefix.lower()
        candidates: list[Path] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if not child.name.lower().startswith(project_prefix_lower):
                continue
            suffix = child.name[len(project_prefix) :]
            inf_paths = ProjectDiscoveryService._inf_paths_for_dir(child, inf_paths_by_dir)
            if ProjectDiscoveryService._is_compiler_output_suffix(suffix) or inf_paths:
                candidates.append(child)
        return sorted(candidates, key=lambda path: (-ProjectDiscoveryService._compiler_dir_sort_key(path, inf_paths_by_dir), path.name.lower()))

    @staticmethod
    def _compiler_dir_sort_key(path: Path, inf_paths_by_dir: dict[Path, list[Path]]) -> float:
        newest = path.stat().st_mtime
        for inf_path in ProjectDiscoveryService._inf_paths_for_dir(path, inf_paths_by_dir):
            try:
                newest = max(newest, inf_path.stat().st_mtime)
            except OSError:
                continue
        return newest

    @staticmethod
    def _is_compiler_output_suffix(suffix: str) -> bool:
        return bool(re.match(r"^if\d+(?:$|[_.-].*)", suffix, re.IGNORECASE))

    @staticmethod
    def _iter_inf_paths(path: Path) -> list[Path]:
        try:
            inf_paths: list[Path] = []
            for directory, _subdirs, names in os.walk(path):
                inf_paths.extend(
                    candidate
                    for name in names
                    if name.casefold().endswith(".inf")
                    for candidate in (Path(directory) / name,)
                    if candidate.is_file()
                )
            return sorted(inf_paths)
        except OSError:
            return []

    @staticmethod
    def _inf_paths_for_dir(path: Path, inf_paths_by_dir: dict[Path, list[Path]]) -> list[Path]:
        if path not in inf_paths_by_dir:
            inf_paths_by_dir[path] = ProjectDiscoveryService._iter_inf_paths(path)
        return inf_paths_by_dir[path]

    @staticmethod
    def _detect_project_mode(
        case_folder_dir: Path,
        compiler_output_dirs: list[Path],
        has_project_files: bool,
        inf_paths_by_dir: dict[Path, list[Path]],
    ) -> ProjectMode:
        if case_folder_dir.is_dir() and ProjectDiscoveryService._inf_paths_for_dir(case_folder_dir, inf_paths_by_dir):
            return ProjectMode.STUDY
        if compiler_output_dirs:
            return ProjectMode.MANUAL
        if case_folder_dir.is_dir():
            return ProjectMode.STUDY
        if has_project_files:
            return ProjectMode.MANUAL
        return ProjectMode.STUDY

class RunAvailabilityService:
    """Build run indexes from .inf files and validate case/run availability."""

    def build_index(self, context: ProjectContext) -> dict[str, dict[int, Path]]:
        index: dict[str, dict[int, Path]] = {}
        if context.project_mode is ProjectMode.STUDY:
            if not context.case_folder_dir.exists():
                return index
            inf_paths = context.inf_paths_by_dir.get(context.case_folder_dir)
            if inf_paths is None:
                inf_paths = ProjectDiscoveryService._iter_inf_paths(context.case_folder_dir)
            for inf_path in inf_paths:
                parsed = parse_case_run_from_stem(inf_path.stem)
                if not parsed:
                    continue
                case_name, run_number = parsed
                index.setdefault(case_name, {})[run_number] = inf_path
            return {case: dict(sorted(runs.items())) for case, runs in sorted(index.items())}

        project_files = context.project_files or ([context.project_file] if context.project_file is not None else [])
        for project_file in project_files:
            project_stem = project_file.stem
            compiler_dirs = context.compiler_output_dirs_by_project.get(project_stem, [])
            for compiler_dir in compiler_dirs:
                compiler_inf_paths = context.inf_paths_by_dir.get(compiler_dir)
                if compiler_inf_paths is None:
                    compiler_inf_paths = ProjectDiscoveryService._iter_inf_paths(compiler_dir)
                parsed_any = False
                for inf_path in compiler_inf_paths:
                    parsed = parse_manual_run_from_stem(inf_path.stem, project_stem)
                    if not parsed:
                        continue
                    parsed_any = True
                    case_name, run_number = parsed
                    index.setdefault(case_name, {}).setdefault(run_number, inf_path)
                if parsed_any:
                    continue
                if len(compiler_inf_paths) == 1:
                    index.setdefault(project_stem, {}).setdefault(1, compiler_inf_paths[0])
        if not project_files:
            for compiler_dir in context.compiler_output_dirs:
                compiler_inf_paths = context.inf_paths_by_dir.get(compiler_dir)
                if compiler_inf_paths is None:
                    compiler_inf_paths = ProjectDiscoveryService._iter_inf_paths(compiler_dir)
                if len(compiler_inf_paths) == 1:
                    index.setdefault(context.root_dir.name, {}).setdefault(1, compiler_inf_paths[0])
        return {case: dict(sorted(runs.items())) for case, runs in sorted(index.items())}

class CatalogCache:
    """SQLite cache for expensive project-open catalog parsing."""

    FILENAME = "catalog_cache.sqlite"
    CACHE_VERSION = 3

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / self.FILENAME
        self._conn: sqlite3.Connection | None = None
        self._open()

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def load_mm_results(self, path: Path, parser_version: int) -> list[dict[str, object]] | None:
        conn = self._conn
        source = self._source_key(path)
        if conn is None or source is None or not self._source_valid("mm_csv", source, parser_version):
            return None
        try:
            return [
                self._mm_row_from_cache(row)
                for row in conn.execute("SELECT * FROM mm_results WHERE path = ? ORDER BY row_index", (source[0],))
            ]
        except sqlite3.DatabaseError:
            return None

    def store_mm_results(
        self,
        path: Path,
        parser_version: int,
        rows: list[dict[str, object]],
    ) -> None:
        conn = self._conn
        source = self._source_key(path)
        if conn is None or source is None:
            return
        try:
            conn.execute("DELETE FROM mm_results WHERE path = ?", (source[0],))
            conn.executemany(
                """
                INSERT INTO mm_results (
                    path, row_index, unique_id, case_name, run_number, voltage_kv,
                    bus_name, lgp, lgr, lgrm, lgr_pu, lgrm_pu, llp, llr, llrm,
                    llr_pu, llrm_pu, lls, tov, peak_lg, peak_ll, fault_label, fault_raw,
                    event_time, tswitch_a, tswitch_b, tswitch_c
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        source[0],
                        index,
                        row.get("Unique ID"),
                        row.get("Case name"),
                        row.get("Run#"),
                        row.get("Bus voltage [kV]"),
                        row.get("Bus name"),
                        row.get("LGp [kV]"),
                        row.get("LGr [kV]"),
                        row.get("LGrm [kV]"),
                        row.get("LGr [pu]"),
                        row.get("LGrm [pu]"),
                        row.get("LLp [kV]"),
                        row.get("LLr [kV]"),
                        row.get("LLrm [kV]"),
                        row.get("LLr [pu]"),
                        row.get("LLrm [pu]"),
                        row.get("LLs [kV]"),
                        row.get("TOV_dur [s]"),
                        row.get("PeakLG"),
                        row.get("PeakLL"),
                        row.get("FaultLabel"),
                        row.get("FaultRaw"),
                        row.get("EventTime"),
                        row.get("Tswitch_a [s]"),
                        row.get("Tswitch_b [s]"),
                        row.get("Tswitch_c [s]"),
                    )
                    for index, row in enumerate(rows)
                ),
            )
            self._replace_source("mm_csv", source, parser_version)
            self._commit_if_needed()
        except sqlite3.DatabaseError:
            self._rollback_if_needed()
            return

    def _open(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema()
        except sqlite3.DatabaseError:
            self.close()
            try:
                self.path.unlink(missing_ok=True)
                self._conn = sqlite3.connect(self.path)
                self._conn.row_factory = sqlite3.Row
                self._ensure_schema()
            except (OSError, sqlite3.DatabaseError):
                self.close()

    def _ensure_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            PRAGMA synchronous = NORMAL;
            CREATE TABLE IF NOT EXISTS sources (
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                parser_version INTEGER NOT NULL,
                cache_version INTEGER NOT NULL,
                PRIMARY KEY (kind, path)
            );
            CREATE TABLE IF NOT EXISTS mm_results (
                path TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                unique_id TEXT,
                case_name TEXT NOT NULL,
                run_number INTEGER NOT NULL,
                voltage_kv REAL NOT NULL,
                bus_name TEXT NOT NULL,
                lgp REAL,
                lgr REAL,
                lgrm REAL,
                lgr_pu REAL,
                lgrm_pu REAL,
                llp REAL,
                llr REAL,
                llrm REAL,
                llr_pu REAL,
                llrm_pu REAL,
                lls REAL,
                tov REAL,
                peak_lg REAL,
                peak_ll REAL,
                fault_label TEXT,
                fault_raw TEXT,
                event_time REAL,
                tswitch_a REAL,
                tswitch_b REAL,
                tswitch_c REAL,
                PRIMARY KEY (path, row_index)
            );
            """
        )
        expected_columns = {
            "unique_id", "lgrm", "lgr_pu", "lgrm_pu", "llrm", "llr_pu",
            "llrm_pu", "lls", "tswitch_a", "tswitch_b", "tswitch_c",
        }
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(mm_results)")
        }
        if not expected_columns <= columns:
            # Older app versions had a narrower table.  The cache is only an
            # acceleration layer, so rebuilding this one table is safe and
            # forces the shared CSV parser to repopulate the extended fields.
            self._conn.execute("DROP TABLE IF EXISTS mm_results")
            self._conn.execute("DELETE FROM sources WHERE kind = 'mm_csv'")
            self._conn.executescript(
                """
                CREATE TABLE mm_results (
                    path TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    unique_id TEXT,
                    case_name TEXT NOT NULL,
                    run_number INTEGER NOT NULL,
                    voltage_kv REAL NOT NULL,
                    bus_name TEXT NOT NULL,
                    lgp REAL,
                    lgr REAL,
                    lgrm REAL,
                    lgr_pu REAL,
                    lgrm_pu REAL,
                    llp REAL,
                    llr REAL,
                    llrm REAL,
                    llr_pu REAL,
                    llrm_pu REAL,
                    lls REAL,
                    tov REAL,
                    peak_lg REAL,
                    peak_ll REAL,
                    fault_label TEXT,
                    fault_raw TEXT,
                    event_time REAL,
                    tswitch_a REAL,
                    tswitch_b REAL,
                    tswitch_c REAL,
                    PRIMARY KEY (path, row_index)
                );
                """
            )

    def _source_valid(self, kind: str, source: tuple[str, int, int], parser_version: int) -> bool:
        conn = self._conn
        if conn is None:
            return False
        try:
            row = conn.execute("SELECT * FROM sources WHERE kind = ? AND path = ?", (kind, source[0])).fetchone()
        except sqlite3.DatabaseError:
            return False
        return bool(
            row
            and int(row["size"]) == source[1]
            and int(row["mtime_ns"]) == source[2]
            and int(row["parser_version"]) == parser_version
            and int(row["cache_version"]) == self.CACHE_VERSION
        )

    def _replace_source(self, kind: str, source: tuple[str, int, int], parser_version: int) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?)
            """,
            (kind, source[0], source[1], source[2], parser_version, self.CACHE_VERSION),
        )

    def _commit_if_needed(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def _rollback_if_needed(self) -> None:
        if self._conn is None:
            return
        self._conn.rollback()

    @staticmethod
    def _source_key(path: Path) -> tuple[str, int, int] | None:
        try:
            resolved = path.resolve()
            stat = resolved.stat()
        except OSError:
            return None
        return str(resolved), int(stat.st_size), int(stat.st_mtime_ns)

    @staticmethod
    def _mm_row_from_cache(row: sqlite3.Row) -> dict[str, object]:
        return {
            "Unique ID": row["unique_id"],
            "Case name": row["case_name"],
            "Run#": int(row["run_number"]),
            "Bus voltage [kV]": float(row["voltage_kv"]),
            "Bus name": row["bus_name"],
            "LGp [kV]": row["lgp"],
            "LGr [kV]": row["lgr"],
            "LGrm [kV]": row["lgrm"],
            "LGr [pu]": row["lgr_pu"],
            "LGrm [pu]": row["lgrm_pu"],
            "LLp [kV]": row["llp"],
            "LLr [kV]": row["llr"],
            "LLrm [kV]": row["llrm"],
            "LLr [pu]": row["llr_pu"],
            "LLrm [pu]": row["llrm_pu"],
            "LLs [kV]": row["lls"],
            "TOV_dur [s]": row["tov"],
            "PeakLG": row["peak_lg"],
            "PeakLL": row["peak_ll"],
            "FaultLabel": row["fault_label"],
            "FaultRaw": row["fault_raw"],
            "EventTime": row["event_time"],
            "Tswitch_a [s]": row["tswitch_a"],
            "Tswitch_b [s]": row["tswitch_b"],
            "Tswitch_c [s]": row["tswitch_c"],
        }

class ResultsCatalogService:
    """Load the MM element catalog used by report plot batches."""

    MM_FILENAME = "MM results.csv"
    MM_CSV_CACHE_VERSION = 3

    def build_base_catalog(
        self,
        context: ProjectContext,
        run_index: dict[str, dict[int, Path]],
        cache: CatalogCache | None = None,
    ) -> ProjectCatalog:
        catalog = ProjectCatalog()
        catalog.runs_by_case = {case_name: sorted(runs.keys()) for case_name, runs in run_index.items()}

        mm_path = context.results_dir / self.MM_FILENAME
        if mm_path.exists():
            cached_mm = cache.load_mm_results(mm_path, self.MM_CSV_CACHE_VERSION) if cache is not None else None
            if cached_mm is None:
                mm_rows = self._load_mm_results(mm_path)
                if cache is not None:
                    cache.store_mm_results(mm_path, self.MM_CSV_CACHE_VERSION, mm_rows)
            else:
                mm_rows = cached_mm
            catalog.mm_results = list(mm_rows)
            catalog.mm_elements = self._build_mm_elements(mm_rows, run_index)

        return catalog

    def _load_mm_results(
        self,
        path: Path,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                row = self._prepare_mm_result_row(source)
                if row is None:
                    continue
                rows.append(row)
        return rows

    def _prepare_mm_result_row(self, source: dict[str, object]) -> dict[str, object] | None:
        run_number = safe_float(source.get("Run#"))
        voltage_kv = safe_float(source.get("Bus voltage [kV]"))
        case_name = str(source.get("Case name", "") or "").strip()
        bus_name = str(source.get("Bus name", "") or "").strip()
        if run_number is None or voltage_kv is None or not case_name or not bus_name:
            return None
        row = {
            "Unique ID": str(source.get("Unique ID", "") or "").strip(),
            "Case name": case_name,
            "Run#": int(run_number),
            "Bus voltage [kV]": float(voltage_kv),
            "Bus name": bus_name,
        }
        numeric_columns = (
            "LGp [kV]", "LGr [kV]", "LGrm [kV]", "LGr [pu]", "LGrm [pu]",
            "LLp [kV]", "LLr [kV]", "LLrm [kV]", "LLr [pu]", "LLrm [pu]", "LLs [kV]",
            "TOV_dur [s]", "PeakLG", "PeakLL", "EventTime",
            "Tswitch_a [s]", "Tswitch_b [s]", "Tswitch_c [s]",
        )
        for column in numeric_columns:
            row[column] = safe_float(source.get(column))
        row["FaultLabel"] = str(source.get("Fault_type", source.get("FaultLabel", "")) or "").strip()
        row["FaultRaw"] = str(source.get("FaultRaw", source.get("Fault_type", "")) or "").strip()
        # Some result writers omit pu columns.  Preserve their values when
        # present and derive the RMS base-unit ratio using the same nominal
        # LG/LL references used by the legacy selection script.
        for kv_column, pu_column, divisor in (
            ("LGr [kV]", "LGr [pu]", 3 ** 0.5),
            ("LGrm [kV]", "LGrm [pu]", 3 ** 0.5),
            ("LLr [kV]", "LLr [pu]", 1.0),
            ("LLrm [kV]", "LLrm [pu]", 1.0),
        ):
            if row[pu_column] is None and row[kv_column] is not None:
                reference = float(voltage_kv) / divisor
                row[pu_column] = row[kv_column] / reference if reference else None
        return row

    def _build_mm_elements(self, rows: list[dict[str, object]], run_index: dict[str, dict[int, Path]]) -> list[MMElementRecord]:
        if not rows:
            return []

        grouped: dict[tuple[str, float, str], set[int]] = {}
        for row in rows:
            case_name = str(row.get("Case name", ""))
            voltage_kv = safe_float(row.get("Bus voltage [kV]"))
            element_name = str(row.get("Bus name", ""))
            run_number = int(row.get("Run#", 0))
            if voltage_kv is None or not case_name or not element_name:
                continue
            if run_number in run_index.get(case_name, {}):
                grouped.setdefault((case_name, float(voltage_kv), element_name), set()).add(run_number)
        return self._mm_elements_from_grouped(grouped)

    @staticmethod
    def _mm_elements_from_grouped(grouped: dict[tuple[str, float, str], set[int]]) -> list[MMElementRecord]:
        records: list[MMElementRecord] = []
        for (case_name, voltage_kv, element_name), run_numbers in grouped.items():
            valid_runs = sorted(run_numbers)
            if not valid_runs:
                continue
            records.append(
                MMElementRecord(
                    case_name=str(case_name),
                    voltage_kv=float(voltage_kv),
                    element_name=str(element_name),
                    available_runs=valid_runs,
                )
            )
        return sorted(records, key=lambda item: (item.case_name, item.voltage_kv, item.element_name))
