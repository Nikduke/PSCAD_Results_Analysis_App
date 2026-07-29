from __future__ import annotations

import re
from pathlib import Path


RUN_PATTERN = re.compile(r"^(?P<case>.+?)_r(?P<run>\d+)$")
MANUAL_RUN_PATTERN = re.compile(r"^(?P<base>.+?)(?:_r\d+)?_m(?P<run>\d+)(?:_.+)?$", re.IGNORECASE)
FAULT_CODE_LABELS = {
    "0": "No fault",
    "1": "AG",
    "4": "ABG",
    "7": "ABCG",
    "8": "AB",
    "11": "ABC",
}
KNOWN_FAULT_LABELS = set(FAULT_CODE_LABELS.values()) | {"No fault"}
ALL_FAULTS_LABEL = "All faults"
PREFERRED_STATISTIC_FILE_NAMES = ("statistic_01.out", "statistic_0001.out")


def find_stat_file(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    for name in PREFERRED_STATISTIC_FILE_NAMES:
        preferred = directory / name
        if preferred.is_file():
            return preferred
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.lower().startswith("statistic") and path.suffix.lower() == ".out"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_stat_file_sort_key)[0]


def _stat_file_sort_key(path: Path) -> tuple[int, str]:
    name = path.name.lower()
    try:
        preferred_index = PREFERRED_STATISTIC_FILE_NAMES.index(name)
    except ValueError:
        preferred_index = len(PREFERRED_STATISTIC_FILE_NAMES)
    return preferred_index, name


def parse_case_run_from_stem(stem: str) -> tuple[str, int] | None:
    match = RUN_PATTERN.match(stem)
    if not match:
        return None
    return match.group("case"), int(match.group("run"))


def parse_manual_run_from_stem(stem: str, project_stem: str) -> tuple[str, int] | None:
    parsed = _parse_manual_single_run_stem(stem, project_stem)
    if parsed is not None:
        return parsed
    return _parse_manual_multi_run_stem(stem, project_stem)


def _parse_manual_single_run_stem(stem: str, project_stem: str) -> tuple[str, int] | None:
    if stem.lower() == project_stem.lower():
        return project_stem, 1
    simple_run_match = re.match(rf"^{re.escape(project_stem)}_r(?P<run>\d+)$", stem, re.IGNORECASE)
    if not simple_run_match:
        return None
    return project_stem, int(simple_run_match.group("run"))


def _parse_manual_multi_run_stem(stem: str, project_stem: str) -> tuple[str, int] | None:
    match = MANUAL_RUN_PATTERN.match(stem)
    if not match:
        return None
    return project_stem, int(match.group("run"))


def safe_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, float):
        try:
            if value != value:
                return None
        except TypeError:
            pass
    try:
        result = float(value)
        if result != result:
            return None
        return result
    except (TypeError, ValueError):
        return None


def normalize_fault_raw(value) -> str:
    if value is None:
        return "0"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() == "none":
            return "0"
        return stripped[:-2] if stripped.endswith(".0") else stripped
    if isinstance(value, float):
        try:
            if value != value:
                return "0"
        except TypeError:
            pass
    try:
        float_value = float(value)
        if float_value != float_value:
            return "0"
    except (TypeError, ValueError):
        float_value = None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def normalize_fault_label(value) -> str:
    raw = normalize_fault_raw(value)
    return FAULT_CODE_LABELS.get(raw, raw)


def parse_stat_rows(stat_path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    header_tokens: list[str] | None = None
    with stat_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped:
                continue
            normalized = re.sub(r"\s+", " ", stripped)
            if normalized.lower().startswith("run #") or normalized.lower().startswith("run#"):
                header_tokens = normalized.replace("Run #", "Run#").replace("run #", "Run#").replace("run#", "Run#").split()
                continue
            if "Statistical Summary" in normalized:
                break
            if header_tokens is None:
                continue
            parts = normalized.split()
            if len(parts) < len(header_tokens):
                continue
            row_map = {header_tokens[index]: parts[index] for index in range(len(header_tokens))}
            try:
                run_number = int(row_map["Run#"])
            except ValueError:
                continue

            header_lookup = {token.lower(): token for token in header_tokens}

            def row_value(*candidates: str) -> str | None:
                for candidate in candidates:
                    key = header_lookup.get(candidate.lower())
                    if key:
                        return row_map.get(key)
                return None

            event_times = {
                "a": safe_float(row_value("Tswitch_a", "T_sw_a", "Event_a", "Event_time_a")),
                "b": safe_float(row_value("Tswitch_b", "T_sw_b", "Event_b", "Event_time_b")),
                "c": safe_float(row_value("Tswitch_c", "T_sw_c", "Event_c", "Event_time_c")),
            }
            event_times = {phase: value for phase, value in event_times.items() if value is not None}
            event_time = safe_float(row_value("Tswitch", "T_sw", "Event", "Event_time"))
            if event_time is None:
                event_time = safe_float(row_value("Tswitch_a", "Tswitch_b", "Tswitch_c", "T_sw_a"))
            fault_value = row_value("Fault_type", "Fault", "FaultType", "Fault_code")
            fault_label = normalize_fault_label(fault_value)

            if fault_label not in KNOWN_FAULT_LABELS and len(parts) >= 4:
                legacy_event_time = safe_float(parts[2])
                legacy_fault_value = parts[3]
                legacy_fault_label = normalize_fault_label(legacy_fault_value)
                if legacy_fault_label in KNOWN_FAULT_LABELS:
                    event_time = legacy_event_time
                    event_times = {}
                    fault_value = legacy_fault_value
                    fault_label = legacy_fault_label

            rows.append(
                {
                    "run_number": run_number,
                    "fault_raw": normalize_fault_raw(fault_value),
                    "fault_label": fault_label,
                    "event_time_s": event_time,
                    "event_times_s": event_times,
                }
            )
    return rows


def load_run_event_info(stat_path: Path, run_number: int) -> dict[str, object] | None:
    for row in parse_stat_rows(stat_path):
        if int(row["run_number"]) == int(run_number):
            return row
    return None
