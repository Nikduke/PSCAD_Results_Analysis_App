from __future__ import annotations

import csv
from hashlib import blake2b
import json
import re
import sqlite3
from pathlib import Path

from pscad_plotter_app_v3.models import (
    CBElementRecord,
    MMElementRecord,
    ProjectCatalog,
    ProjectContext,
    ProjectMode,
    RunMetadata,
    SignalGroupRecord,
)
from pscad_plotter_app_v3.services.project_conventions import (
    cb_voltage_from_name,
    find_stat_file,
    normalize_bundle_signal_name,
    normalize_fault_label,
    normalize_fault_raw,
    parse_case_run_from_stem,
    parse_manual_run_from_stem,
    parse_stat_rows,
    safe_float,
)
from pscad_plotter_app_v3.services.waveform_io import (
    parse_inf_descriptors,
    pgb_to_out_location,
    read_out_time_bounds,
    standard_out_file_path,
)


def _hash_inf_file(inf_path: Path) -> str:
    digest = blake2b(digest_size=16)
    with inf_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            return sorted(child for child in path.rglob("*") if child.is_file() and child.suffix.lower() == ".inf")
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
    CACHE_VERSION = 2

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / self.FILENAME
        self._conn: sqlite3.Connection | None = None
        self._bulk_depth = 0
        self._open()

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        if self._conn is not None:
            if self._bulk_depth:
                self._conn.commit()
                self._bulk_depth = 0
            self._conn.close()
            self._conn = None

    def begin_bulk(self) -> None:
        if self._conn is None:
            return
        if self._bulk_depth == 0:
            self._conn.execute("BEGIN")
        self._bulk_depth += 1

    def commit_bulk(self) -> None:
        if self._conn is None or self._bulk_depth == 0:
            return
        self._bulk_depth -= 1
        if self._bulk_depth == 0:
            self._conn.commit()

    def rollback_bulk(self) -> None:
        if self._conn is None or self._bulk_depth == 0:
            return
        self._conn.rollback()
        self._bulk_depth = 0

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
                INSERT INTO mm_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        source[0],
                        index,
                        row.get("Case name"),
                        row.get("Run#"),
                        row.get("Bus voltage [kV]"),
                        row.get("Bus name"),
                        row.get("LGp [kV]"),
                        row.get("LGr [kV]"),
                        row.get("LLp [kV]"),
                        row.get("LLr [kV]"),
                        row.get("TOV_dur [s]"),
                        row.get("PeakLG"),
                        row.get("PeakLL"),
                        row.get("FaultLabel"),
                        row.get("FaultRaw"),
                        row.get("EventTime"),
                    )
                    for index, row in enumerate(rows)
                ),
            )
            self._replace_source("mm_csv", source, parser_version)
            self._commit_if_needed()
        except sqlite3.DatabaseError:
            self._rollback_if_needed()
            return

    def load_cb_results(self, path: Path, parser_version: int) -> list[dict[str, object]] | None:
        conn = self._conn
        source = self._source_key(path)
        if conn is None or source is None or not self._source_valid("cb_csv", source, parser_version):
            return None
        try:
            return [
                self._cb_row_from_cache(row)
                for row in conn.execute("SELECT * FROM cb_results WHERE path = ? ORDER BY row_index", (source[0],))
            ]
        except sqlite3.DatabaseError:
            return None

    def store_cb_results(
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
            conn.execute("DELETE FROM cb_results WHERE path = ?", (source[0],))
            conn.executemany(
                """
                INSERT INTO cb_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        source[0],
                        index,
                        row.get("Case name"),
                        row.get("Run#"),
                        row.get("CB name"),
                        row.get("IIp [kA]"),
                        row.get("IIr [kA]"),
                        row.get("ZM_a [s]"),
                        row.get("ZM_b [s]"),
                        row.get("ZM_c [s]"),
                        row.get("FaultLabel"),
                        row.get("FaultRaw"),
                        row.get("EventTime"),
                        row.get("VoltageKV"),
                        row.get("Fault_type"),
                    )
                    for index, row in enumerate(rows)
                ),
            )
            self._replace_source("cb_csv", source, parser_version)
            self._commit_if_needed()
        except sqlite3.DatabaseError:
            self._rollback_if_needed()
            return

    def load_inf_hashes(self, paths: list[Path]) -> dict[Path, str]:
        conn = self._conn
        if conn is None or not paths:
            return {}

        resolved_paths = [path.resolve() for path in paths]
        rows_by_path: dict[str, sqlite3.Row] = {}
        try:
            for start in range(0, len(resolved_paths), 500):
                chunk = resolved_paths[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT path, size, mtime_ns, digest FROM inf_hashes WHERE path IN ({placeholders})",
                    tuple(str(path) for path in chunk),
                )
                for row in rows:
                    rows_by_path[str(row["path"])] = row
        except sqlite3.DatabaseError:
            return {}

        cached: dict[Path, str] = {}
        for path in resolved_paths:
            source = self._source_key(path)
            row = rows_by_path.get(str(path))
            if (
                source is not None
                and row is not None
                and int(row["size"]) == source[1]
                and int(row["mtime_ns"]) == source[2]
            ):
                cached[path] = str(row["digest"])
        return cached

    def store_inf_hashes(self, hashes: dict[Path, str]) -> None:
        conn = self._conn
        if conn is None or not hashes:
            return

        rows = []
        for path, digest in hashes.items():
            source = self._source_key(path)
            if source is not None:
                rows.append((source[0], source[1], source[2], str(digest)))
        if not rows:
            return
        try:
            conn.executemany("INSERT OR REPLACE INTO inf_hashes VALUES (?, ?, ?, ?)", rows)
            self._commit_if_needed()
        except sqlite3.DatabaseError:
            self._rollback_if_needed()

    def load_waveform_catalog(
        self,
        case_name: str,
        run_number: int,
        inf_path: Path,
        parser_version: int,
    ) -> tuple[list[SignalGroupRecord], tuple[float, float] | None, Path | None] | None:
        conn = self._conn
        source = self._source_key(inf_path)
        if conn is None or source is None or not self._source_valid("inf", source, parser_version):
            return None
        try:
            records = [
                SignalGroupRecord(
                    case_name=case_name,
                    run_number=run_number,
                    group_name=str(row["group_name"]),
                    signal_name=str(row["signal_name"]),
                    descriptions=[str(item) for item in json.loads(row["descriptions"])],
                    unit=str(row["unit"] or ""),
                    signal_view=str(row["signal_view"]),
                )
                for row in conn.execute("SELECT * FROM inf_signals WHERE path = ? ORDER BY row_index", (source[0],))
            ]
            time_row = conn.execute("SELECT * FROM time_ranges WHERE inf_path = ?", (source[0],)).fetchone()
            if time_row is None:
                return records, None, None
            out_path = Path(str(time_row["out_path"]))
            out_source = self._source_key(out_path)
            if (
                out_source is not None
                and int(time_row["out_size"]) == out_source[1]
                and int(time_row["out_mtime_ns"]) == out_source[2]
                and time_row["start_s"] is not None
                and time_row["end_s"] is not None
            ):
                return records, (float(time_row["start_s"]), float(time_row["end_s"])), out_path
            return records, None, out_path
        except (json.JSONDecodeError, sqlite3.DatabaseError):
            return None

    def store_waveform_catalog(
        self,
        inf_path: Path,
        parser_version: int,
        records: list[SignalGroupRecord],
        out_path: Path | None,
        time_range: tuple[float, float] | None,
    ) -> None:
        conn = self._conn
        source = self._source_key(inf_path)
        if conn is None or source is None:
            return
        try:
            conn.execute("DELETE FROM inf_signals WHERE path = ?", (source[0],))
            conn.executemany(
                "INSERT INTO inf_signals VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        source[0],
                        index,
                        record.group_name,
                        record.signal_name,
                        json.dumps(record.descriptions),
                        record.unit,
                        record.signal_view,
                    )
                    for index, record in enumerate(records)
                ),
            )
            if out_path is not None:
                self._replace_time_range(source[0], out_path, time_range)
            self._replace_source("inf", source, parser_version)
            self._commit_if_needed()
        except sqlite3.DatabaseError:
            self._rollback_if_needed()
            return

    def store_time_range(self, inf_path: Path, out_path: Path, time_range: tuple[float, float] | None) -> None:
        conn = self._conn
        source = self._source_key(inf_path)
        if conn is None or source is None:
            return
        try:
            self._replace_time_range(source[0], out_path, time_range)
            self._commit_if_needed()
        except sqlite3.DatabaseError:
            self._rollback_if_needed()
            return

    def load_stat_rows(self, path: Path, parser_version: int) -> list[dict[str, object]] | None:
        conn = self._conn
        source = self._source_key(path)
        if conn is None or source is None or not self._source_valid("stat", source, parser_version):
            return None
        try:
            return [
                self._stat_row_from_cache(row)
                for row in conn.execute("SELECT * FROM stat_rows WHERE path = ? ORDER BY row_index", (source[0],))
            ]
        except (json.JSONDecodeError, sqlite3.DatabaseError):
            return None

    def store_stat_rows(self, path: Path, parser_version: int, rows: list[dict[str, object]]) -> None:
        conn = self._conn
        source = self._source_key(path)
        if conn is None or source is None:
            return
        try:
            conn.execute("DELETE FROM stat_rows WHERE path = ?", (source[0],))
            conn.executemany(
                "INSERT INTO stat_rows VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        source[0],
                        index,
                        row.get("run_number"),
                        row.get("fault_raw"),
                        row.get("fault_label"),
                        row.get("event_time_s"),
                        json.dumps(row.get("event_times_s") or {}),
                    )
                    for index, row in enumerate(rows)
                ),
            )
            self._replace_source("stat", source, parser_version)
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
                case_name TEXT NOT NULL,
                run_number INTEGER NOT NULL,
                voltage_kv REAL NOT NULL,
                bus_name TEXT NOT NULL,
                lgp REAL,
                lgr REAL,
                llp REAL,
                llr REAL,
                tov REAL,
                peak_lg REAL,
                peak_ll REAL,
                fault_label TEXT,
                fault_raw TEXT,
                event_time REAL,
                PRIMARY KEY (path, row_index)
            );
            CREATE TABLE IF NOT EXISTS cb_results (
                path TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                case_name TEXT NOT NULL,
                run_number INTEGER NOT NULL,
                cb_name TEXT NOT NULL,
                iip REAL,
                iir REAL,
                zm_a REAL,
                zm_b REAL,
                zm_c REAL,
                fault_label TEXT,
                fault_raw TEXT,
                event_time REAL,
                voltage_kv REAL,
                fault_type TEXT,
                PRIMARY KEY (path, row_index)
            );
            CREATE TABLE IF NOT EXISTS inf_signals (
                path TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                group_name TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                descriptions TEXT NOT NULL,
                unit TEXT NOT NULL,
                signal_view TEXT NOT NULL,
                PRIMARY KEY (path, row_index)
            );
            CREATE TABLE IF NOT EXISTS time_ranges (
                inf_path TEXT PRIMARY KEY,
                out_path TEXT NOT NULL,
                out_size INTEGER NOT NULL,
                out_mtime_ns INTEGER NOT NULL,
                start_s REAL,
                end_s REAL
            );
            CREATE TABLE IF NOT EXISTS inf_hashes (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stat_rows (
                path TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                run_number INTEGER NOT NULL,
                fault_raw TEXT NOT NULL,
                fault_label TEXT NOT NULL,
                event_time REAL,
                event_times TEXT NOT NULL,
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

    def _replace_time_range(self, inf_path: str, out_path: Path, time_range: tuple[float, float] | None) -> None:
        out_source = self._source_key(out_path)
        if out_source is None:
            return
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO time_ranges VALUES (?, ?, ?, ?, ?, ?)",
            (
                inf_path,
                out_source[0],
                out_source[1],
                out_source[2],
                time_range[0] if time_range is not None else None,
                time_range[1] if time_range is not None else None,
            ),
        )

    def _commit_if_needed(self) -> None:
        if self._conn is not None and self._bulk_depth == 0:
            self._conn.commit()

    def _rollback_if_needed(self) -> None:
        if self._conn is None:
            return
        self._conn.rollback()
        self._bulk_depth = 0

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
            "Case name": row["case_name"],
            "Run#": int(row["run_number"]),
            "Bus voltage [kV]": float(row["voltage_kv"]),
            "Bus name": row["bus_name"],
            "LGp [kV]": row["lgp"],
            "LGr [kV]": row["lgr"],
            "LLp [kV]": row["llp"],
            "LLr [kV]": row["llr"],
            "TOV_dur [s]": row["tov"],
            "PeakLG": row["peak_lg"],
            "PeakLL": row["peak_ll"],
            "FaultLabel": row["fault_label"],
            "FaultRaw": row["fault_raw"],
            "EventTime": row["event_time"],
        }

    @staticmethod
    def _cb_row_from_cache(row: sqlite3.Row) -> dict[str, object]:
        return {
            "Case name": row["case_name"],
            "Run#": int(row["run_number"]),
            "CB name": row["cb_name"],
            "IIp [kA]": row["iip"],
            "IIr [kA]": row["iir"],
            "ZM_a [s]": row["zm_a"],
            "ZM_b [s]": row["zm_b"],
            "ZM_c [s]": row["zm_c"],
            "FaultLabel": row["fault_label"],
            "FaultRaw": row["fault_raw"],
            "EventTime": row["event_time"],
            "VoltageKV": row["voltage_kv"],
            "Fault_type": row["fault_type"],
        }

    @staticmethod
    def _stat_row_from_cache(row: sqlite3.Row) -> dict[str, object]:
        return {
            "run_number": int(row["run_number"]),
            "fault_raw": str(row["fault_raw"]),
            "fault_label": str(row["fault_label"]),
            "event_time_s": row["event_time"],
            "event_times_s": {str(key): value for key, value in json.loads(row["event_times"]).items()},
        }


class ResultsCatalogService:
    """Load MM and CB element catalogs from Results CSVs."""

    MM_FILENAME = "MM results.csv"
    CB_FILENAME = "CB results.csv"
    MM_NUMERIC_COLUMNS = ("LGp [kV]", "LGr [kV]", "LLp [kV]", "LLr [kV]", "TOV_dur [s]")
    CB_NUMERIC_COLUMNS = ("IIp [kA]", "IIr [kA]", "ZM_a [s]", "ZM_b [s]", "ZM_c [s]")
    MM_CSV_CACHE_VERSION = 1
    CB_CSV_CACHE_VERSION = 1
    STAT_CACHE_VERSION = 1

    def build_catalog(
        self,
        context: ProjectContext,
        run_index: dict[str, dict[int, Path]],
        waveform_service: "WaveformCatalogService",
        cache: CatalogCache | None = None,
    ) -> ProjectCatalog:
        catalog = self.build_base_catalog(context, run_index, cache)
        self.load_waveform_catalog(catalog, run_index, waveform_service, cache)
        return catalog

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
            catalog.mm_elements = self._build_mm_elements(mm_rows, run_index)

        cb_path = context.results_dir / self.CB_FILENAME
        if cb_path.exists():
            cached_cb = cache.load_cb_results(cb_path, self.CB_CSV_CACHE_VERSION) if cache is not None else None
            if cached_cb is None:
                cb_rows = self._load_cb_results(cb_path)
                if cache is not None:
                    cache.store_cb_results(cb_path, self.CB_CSV_CACHE_VERSION, cb_rows)
            else:
                cb_rows = cached_cb
            catalog.cb_elements = self._build_cb_elements(cb_rows, run_index)

        catalog.run_metadata_by_case = self._build_run_metadata(run_index, cache)
        if catalog.run_metadata_by_case:
            catalog.runs_by_case = {
                case_name: sorted(run_map.keys()) for case_name, run_map in catalog.run_metadata_by_case.items()
            }
        return catalog

    def load_waveform_catalog(
        self,
        catalog: ProjectCatalog,
        run_index: dict[str, dict[int, Path]],
        waveform_service: "WaveformCatalogService",
        cache: CatalogCache | None = None,
    ) -> None:
        entries = [
            (case_name, int(run_number), inf_path)
            for case_name, runs in run_index.items()
            for run_number, inf_path in runs.items()
        ]
        channels: dict[str, dict[int, list[SignalGroupRecord]]] = {}
        time_ranges: dict[str, dict[int, tuple[float, float]]] = {}
        if cache is not None:
            cache.begin_bulk()
        try:
            catalog_entries: dict[tuple[str, int], tuple[list[SignalGroupRecord], tuple[float, float] | None]] = {}
            missing_entries: list[tuple[str, int, Path]] = []
            for case_name, run_number, inf_path in entries:
                cached = (
                    cache.load_waveform_catalog(case_name, run_number, inf_path, waveform_service.INF_CACHE_VERSION)
                    if cache is not None
                    else None
                )
                if cached is None:
                    missing_entries.append((case_name, run_number, inf_path))
                    continue
                records, time_range, out_path = cached
                if time_range is None and out_path is not None:
                    time_range = waveform_service._read_time_range(out_path)
                    cache.store_time_range(inf_path, out_path, time_range)
                catalog_entries[(case_name, run_number)] = (records, time_range)

            if missing_entries:
                all_paths = [inf_path.resolve() for _case, _run, inf_path in entries]
                cached_hashes = cache.load_inf_hashes(all_paths) if cache is not None else {}
                paths_to_hash = [path for path in all_paths if path not in cached_hashes]
                refreshed_hashes = {path: _hash_inf_file(path) for path in paths_to_hash}
                if cache is not None:
                    cache.store_inf_hashes(refreshed_hashes)
                hashes_by_path = {**cached_hashes, **refreshed_hashes}

                representative_by_hash: dict[str, Path] = {}
                for inf_path in all_paths:
                    representative_by_hash.setdefault(hashes_by_path[inf_path], inf_path)
                missing_digests = {hashes_by_path[inf_path.resolve()] for _case, _run, inf_path in missing_entries}
                descriptors_by_hash = {
                    digest: parse_inf_descriptors(inf_path)
                    for digest, inf_path in representative_by_hash.items()
                    if digest in missing_digests
                }

                for case_name, run_number, inf_path in missing_entries:
                    descriptors = descriptors_by_hash[hashes_by_path[inf_path.resolve()]]
                    records, time_range, out_path = waveform_service.catalog_entry_from_descriptors(
                        case_name,
                        run_number,
                        inf_path,
                        descriptors,
                    )
                    catalog_entries[(case_name, run_number)] = (records, time_range)
                    if cache is not None:
                        cache.store_waveform_catalog(
                            inf_path,
                            waveform_service.INF_CACHE_VERSION,
                            records,
                            out_path,
                            time_range,
                        )

            for case_name, run_number, _inf_path in entries:
                records, time_range = catalog_entries[(case_name, run_number)]
                channels.setdefault(case_name, {})[run_number] = records
                if time_range is not None:
                    time_ranges.setdefault(case_name, {})[run_number] = time_range
        except Exception:
            if cache is not None:
                cache.rollback_bulk()
            raise
        else:
            if cache is not None:
                cache.commit_bulk()
        catalog.channel_groups_by_case_run = channels
        catalog.time_range_by_case_run = time_ranges
        if not catalog.mm_elements:
            catalog.mm_elements = self._build_waveform_mm_elements(channels)
        if not catalog.cb_elements:
            catalog.cb_elements = self._build_waveform_cb_elements(channels)

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

    def _load_cb_results(
        self,
        path: Path,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                row = self._prepare_cb_result_row(source)
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
        row: dict[str, object] = {
            "Case name": case_name,
            "Run#": int(run_number),
            "Bus voltage [kV]": float(voltage_kv),
            "Bus name": bus_name,
        }
        for column in self.MM_NUMERIC_COLUMNS:
            row[column] = safe_float(source.get(column))
        row["PeakLG"] = self._abs_max(row, ("LGp [kV]", "LGr [kV]"))
        row["PeakLL"] = self._abs_max(row, ("LLp [kV]", "LLr [kV]"))
        row["FaultLabel"] = self.normalize_fault_label(source.get("Fault_type"))
        row["FaultRaw"] = self.normalize_fault_raw(source.get("Fault_type"))
        row["EventTime"] = self._first_available_numeric(source, ["Tswitch_a [s]", "Tswitch_b [s]", "Tswitch_c [s]", "Fault_time [s]"])
        return row

    def _prepare_cb_result_row(self, source: dict[str, object]) -> dict[str, object] | None:
        run_number = safe_float(source.get("Run#"))
        case_name = str(source.get("Case name", "") or "").strip()
        cb_name = str(source.get("CB name", "") or "").strip()
        if run_number is None or not case_name or not cb_name:
            return None
        row: dict[str, object] = {
            "Case name": case_name,
            "Run#": int(run_number),
            "CB name": cb_name,
            "Fault_type": str(source.get("Fault_type", "") or ""),
        }
        for column in self.CB_NUMERIC_COLUMNS:
            row[column] = safe_float(source.get(column))
        row["FaultLabel"] = self.normalize_fault_label(source.get("Fault_type"))
        row["FaultRaw"] = self.normalize_fault_raw(source.get("Fault_type"))
        row["EventTime"] = self._first_available_numeric(source, ["Tswitch_a [s]", "Tswitch_b [s]", "Tswitch_c [s]", "Fault_time [s]"])
        row["VoltageKV"] = cb_voltage_from_name(cb_name)
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

    def _build_cb_elements(self, rows: list[dict[str, object]], run_index: dict[str, dict[int, Path]]) -> list[CBElementRecord]:
        if not rows:
            return []

        grouped: dict[tuple[str, str], set[int]] = {}
        for row in rows:
            case_name = str(row.get("Case name", ""))
            element_name = str(row.get("CB name", ""))
            run_number = int(row.get("Run#", 0))
            if case_name and element_name and run_number in run_index.get(case_name, {}):
                grouped.setdefault((case_name, element_name), set()).add(run_number)
        return self._cb_elements_from_grouped(grouped)

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

    @staticmethod
    def _cb_elements_from_grouped(grouped: dict[tuple[str, str], set[int]]) -> list[CBElementRecord]:
        records: list[CBElementRecord] = []
        for (case_name, element_name), run_numbers in grouped.items():
            valid_runs = sorted(run_numbers)
            if not valid_runs:
                continue
            records.append(
                CBElementRecord(
                    case_name=str(case_name),
                    element_name=str(element_name),
                    available_runs=valid_runs,
                )
            )
        return sorted(records, key=lambda item: (item.case_name, item.element_name))

    def _build_waveform_mm_elements(
        self,
        channels: dict[str, dict[int, list[SignalGroupRecord]]],
    ) -> list[MMElementRecord]:
        grouped: dict[tuple[str, float, str], set[int]] = {}
        for case_name, runs in channels.items():
            for run_number, records in runs.items():
                for group_name in {record.group_name for record in records if record.group_name.startswith("MM_")}:
                    match = re.match(r"^MM_(?P<voltage>\d+(?:\.\d+)?)_", group_name)
                    if not match:
                        continue
                    voltage_kv = float(match.group("voltage"))
                    grouped.setdefault((case_name, voltage_kv, group_name), set()).add(int(run_number))
        return [
            MMElementRecord(
                case_name=case_name,
                voltage_kv=voltage_kv,
                element_name=element_name,
                available_runs=sorted(run_numbers),
            )
            for (case_name, voltage_kv, element_name), run_numbers in sorted(grouped.items())
        ]

    def _build_waveform_cb_elements(
        self,
        channels: dict[str, dict[int, list[SignalGroupRecord]]],
    ) -> list[CBElementRecord]:
        grouped: dict[tuple[str, str], set[int]] = {}
        for case_name, runs in channels.items():
            for run_number, records in runs.items():
                for group_name in {record.group_name for record in records if record.group_name.startswith("CB_")}:
                    grouped.setdefault((case_name, group_name), set()).add(int(run_number))
        return [
            CBElementRecord(
                case_name=case_name,
                element_name=element_name,
                available_runs=sorted(run_numbers),
            )
            for (case_name, element_name), run_numbers in sorted(grouped.items())
        ]

    def _build_run_metadata(
        self,
        run_index: dict[str, dict[int, Path]],
        cache: CatalogCache | None = None,
    ) -> dict[str, dict[int, RunMetadata]]:
        metadata_by_case = {
            case_name: {
                run_number: RunMetadata(case_name=case_name, run_number=run_number)
                for run_number in sorted(runs)
            }
            for case_name, runs in ((case, run_map.keys()) for case, run_map in run_index.items())
        }
        stat_path_by_dir: dict[Path, Path | None] = {}

        for case_name, run_map in metadata_by_case.items():
            stat_rows = self._best_stat_rows_for_case(run_index.get(case_name, {}), set(run_map), stat_path_by_dir, cache)
            if stat_rows:
                self._overlay_run_metadata_from_stats(run_map, stat_rows)
        return {case_name: dict(sorted(run_map.items())) for case_name, run_map in metadata_by_case.items()}

    def _overlay_run_metadata_from_stats(
        self,
        run_map: dict[int, RunMetadata],
        stat_rows: list[dict[str, object]],
    ) -> None:
        for row in stat_rows:
            run_number = int(row["run_number"])
            if run_number not in run_map:
                continue
            meta = run_map[run_number]
            meta.fault_raw = str(row["fault_raw"])
            meta.fault_label = str(row["fault_label"])
            meta.event_time_s = row["event_time_s"]

    def _best_stat_rows_for_case(
        self,
        case_runs: dict[int, Path],
        expected_runs: set[int],
        stat_path_by_dir: dict[Path, Path | None],
        cache: CatalogCache | None = None,
    ) -> list[dict[str, object]]:
        if not case_runs:
            return []
        candidate_path_set: set[Path] = set()
        for inf_path in case_runs.values():
            run_dir = inf_path.parent
            if run_dir not in stat_path_by_dir:
                stat_path_by_dir[run_dir] = find_stat_file(run_dir)
            stat_path = stat_path_by_dir[run_dir]
            if stat_path is not None:
                candidate_path_set.add(stat_path)
        candidate_paths = sorted(candidate_path_set)
        best_rows: list[dict[str, object]] = []
        best_score = -1
        for stat_path in candidate_paths:
            rows = self._load_stat_rows(stat_path, cache)
            overlap = len(expected_runs & {int(row["run_number"]) for row in rows})
            if overlap > best_score:
                best_score = overlap
                best_rows = rows
        return best_rows

    def _load_stat_rows(self, stat_path: Path, cache: CatalogCache | None) -> list[dict[str, object]]:
        cached = cache.load_stat_rows(stat_path, self.STAT_CACHE_VERSION) if cache is not None else None
        if cached is not None:
            return cached
        rows = parse_stat_rows(stat_path)
        if cache is not None:
            cache.store_stat_rows(stat_path, self.STAT_CACHE_VERSION, rows)
        return rows

    @staticmethod
    def _abs_max(row: dict[str, object], columns: tuple[str, ...]) -> float | None:
        values = [abs(value) for column in columns if (value := safe_float(row.get(column))) is not None]
        return max(values) if values else None

    @staticmethod
    def _first_available_numeric(row: dict[str, object], columns: list[str]) -> float | None:
        for column in columns:
            value = safe_float(row.get(column))
            if value is not None:
                return value
        return None

    @staticmethod
    def normalize_fault_raw(value) -> str:
        return normalize_fault_raw(value)

    @classmethod
    def normalize_fault_label(cls, value) -> str:
        return normalize_fault_label(value)

class WaveformCatalogService:
    """Discover signal groups from .inf files for Any Channel browsing."""

    INF_CACHE_VERSION = 2

    def catalog_entry(
        self,
        case_name: str,
        run_number: int,
        inf_path: Path,
        cache: CatalogCache | None = None,
    ) -> tuple[list[SignalGroupRecord], tuple[float, float] | None]:
        cached = cache.load_waveform_catalog(case_name, run_number, inf_path, self.INF_CACHE_VERSION) if cache is not None else None
        if cached is not None:
            records, time_range, out_path = cached
            if time_range is None and out_path is not None:
                time_range = self._read_time_range(out_path)
                cache.store_time_range(inf_path, out_path, time_range)
            return records, time_range

        descriptors = parse_inf_descriptors(inf_path)
        records, time_range, out_path = self.catalog_entry_from_descriptors(
            case_name,
            run_number,
            inf_path,
            descriptors,
        )
        if cache is not None:
            cache.store_waveform_catalog(inf_path, self.INF_CACHE_VERSION, records, out_path, time_range)
        return records, time_range

    def catalog_entry_from_descriptors(
        self,
        case_name: str,
        run_number: int,
        inf_path: Path,
        descriptors,
    ) -> tuple[list[SignalGroupRecord], tuple[float, float] | None, Path | None]:
        records = self._records_from_descriptors(case_name, run_number, descriptors)
        out_path, time_range = self._time_range_from_descriptors(inf_path, descriptors)
        return records, time_range, out_path

    def list_signal_groups(self, case_name: str, run_number: int, inf_path: Path) -> list[SignalGroupRecord]:
        return self._records_from_descriptors(case_name, run_number, parse_inf_descriptors(inf_path))

    def _records_from_descriptors(self, case_name: str, run_number: int, descriptors) -> list[SignalGroupRecord]:
        raw_records: list[tuple[str, str, str]] = []
        bundle_entries: dict[tuple[str, str], dict[str, object]] = {}
        for row in descriptors:
            group_name = str(row.Group)
            description = str(row.Description)
            unit = str(row.Unit)
            raw_records.append((group_name, description, unit))

            normalized = normalize_bundle_signal_name(description)
            if normalized is None:
                continue
            base_signal, phase_token = normalized
            key = (group_name, base_signal)
            payload = bundle_entries.setdefault(key, {"descriptions": [], "units": set(), "phases": set()})
            payload["descriptions"].append(description)  # type: ignore[index]
            payload["units"].add(unit)  # type: ignore[index]
            payload["phases"].add(phase_token)  # type: ignore[index]

        records: list[SignalGroupRecord] = []
        for group_name, description, unit in raw_records:
            records.append(
                SignalGroupRecord(
                    case_name=case_name,
                    run_number=run_number,
                    group_name=group_name,
                    signal_name=description,
                    descriptions=[description],
                    unit=unit,
                    signal_view="individual",
                )
            )

        for (group_name, signal_name), payload in bundle_entries.items():
            descriptions = sorted(payload["descriptions"])  # type: ignore[arg-type]
            phases = {str(phase).lower() for phase in payload["phases"]}  # type: ignore[arg-type]
            units = {str(unit) for unit in payload["units"]}  # type: ignore[arg-type]
            if len(descriptions) != 3:
                continue
            if phases not in ({"1", "2", "3"}, {"a", "b", "c"}):
                continue
            if len(units) != 1:
                continue
            records.append(
                SignalGroupRecord(
                    case_name=case_name,
                    run_number=run_number,
                    group_name=group_name,
                    signal_name=signal_name,
                    descriptions=descriptions,
                    unit=next(iter(units)),
                    signal_view="bundle",
                )
            )
        return sorted(records, key=lambda item: (item.group_name, item.signal_view, item.signal_name))

    def time_range(self, inf_path: Path) -> tuple[float, float] | None:
        try:
            _out_path, time_range = self._time_range_from_descriptors(inf_path, parse_inf_descriptors(inf_path))
            return time_range
        except (OSError, ValueError):
            return None

    def _time_range_from_descriptors(self, inf_path: Path, descriptors) -> tuple[Path | None, tuple[float, float] | None]:
        if not descriptors:
            return None, None
        file_number, _column_number = pgb_to_out_location(descriptors[0].PGB)
        out_path = standard_out_file_path(inf_path, file_number)
        return out_path, self._read_time_range(out_path)

    @staticmethod
    def _read_time_range(out_path: Path) -> tuple[float, float] | None:
        try:
            return read_out_time_bounds(out_path)
        except (OSError, ValueError):
            return None
