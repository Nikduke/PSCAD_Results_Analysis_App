from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable

from results_analysis_app.project_config import normalize_voltage


@dataclass(frozen=True, kw_only=True)
class ExclusionRule:
    apply: bool = True
    case: str = ""
    run: int | None = None
    bus: str = ""
    voltage: str = ""

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "apply": self.apply,
            "case": self.case,
            "run": self.run,
            "bus": self.bus,
        }
        if self.voltage:
            data["voltage"] = self.voltage
        return data

    def matches(self, voltage: str, case: str, run: int, bus: str) -> bool:
        return (
            self.apply
            and (not self.voltage or self.voltage == normalize_voltage(voltage))
            and (not self.case or self.case.casefold() == case.strip().casefold())
            and (self.run is None or self.run == int(run))
            and (not self.bus or self.bus.casefold() == bus.strip().casefold())
        )


class ExclusionMatcher:
    def __init__(self, rules: Iterable[ExclusionRule] = ()) -> None:
        self.rules = tuple(rule for rule in normalize_exclusion_rules(list(rules)) if rule.apply)

    def excludes(self, voltage: str, case: str, run: int, bus: str) -> bool:
        return any(rule.matches(voltage, case, run, bus) for rule in self.rules)

    def excludes_run(self, voltage: str, case: str, run: int) -> bool:
        return any(
            not rule.bus and rule.matches(voltage, case, run, "")
            for rule in self.rules
        )


def normalize_exclusion_rules(value: Any) -> list[ExclusionRule]:
    if not isinstance(value, (list, tuple, set)):
        return []

    output: list[ExclusionRule] = []
    positions: dict[tuple[str, int | None, str, str], int] = {}
    for item in value:
        rule = _normalize_exclusion_rule(item)
        if rule is None:
            continue
        key = (
            rule.case.casefold(),
            rule.run,
            rule.bus.casefold(),
            rule.voltage,
        )
        position = positions.get(key)
        if position is None:
            positions[key] = len(output)
            output.append(rule)
        elif rule.apply and not output[position].apply:
            output[position] = rule
    return output


def normalize_project_exclusion_rules(value: Any) -> dict[str, list[ExclusionRule]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, list[ExclusionRule]] = {}
    for project, exclusions in value.items():
        normalized = normalize_exclusion_rules(exclusions)
        if normalized:
            output[str(project)] = normalized
    return output


def migrate_legacy_project_exclusions(
    bus_exclusions_by_project: Any,
    case_run_exclusions_by_project: Any,
) -> dict[str, list[ExclusionRule]]:
    raw_rules: dict[str, list[dict[str, object]]] = {}
    if isinstance(bus_exclusions_by_project, dict):
        for project, by_voltage in bus_exclusions_by_project.items():
            if not isinstance(by_voltage, dict):
                continue
            for buses in by_voltage.values():
                for bus in _legacy_bus_tokens(buses):
                    raw_rules.setdefault(str(project), []).append({"bus": bus})
    if isinstance(case_run_exclusions_by_project, dict):
        for project, exclusions in case_run_exclusions_by_project.items():
            for case, run in normalize_case_run_exclusions(exclusions):
                raw_rules.setdefault(str(project), []).append({"case": case, "run": run})
    return normalize_project_exclusion_rules(raw_rules)


def normalize_case_run_exclusions(value: Any) -> list[tuple[str, int]]:
    if not isinstance(value, (list, tuple, set)):
        return []
    output: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in value:
        case = ""
        run_raw: Any = None
        if isinstance(item, dict):
            case = str(item.get("case", "")).strip()
            run_raw = item.get("run")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            case = str(item[0]).strip()
            run_raw = item[1]
        run = _optional_run(run_raw)
        if not case or run is None:
            continue
        key = (case, run)
        if key not in seen:
            seen.add(key)
            output.append(key)
    return output


def normalize_high_voltage_exclusions(value: Any) -> list[tuple[str, str, int, str]]:
    if not isinstance(value, (list, tuple, set)):
        return []
    output: list[tuple[str, str, int, str]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for item in value:
        voltage = ""
        case = ""
        run_raw: Any = None
        bus = ""
        if isinstance(item, dict):
            voltage = normalize_voltage(item.get("voltage", ""))
            case = str(item.get("case", "")).strip()
            run_raw = item.get("run")
            bus = str(item.get("bus", item.get("MM_name", ""))).strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 4:
            voltage = normalize_voltage(item[0])
            case = str(item[1]).strip()
            run_raw = item[2]
            bus = str(item[3]).strip()
        run = _optional_run(run_raw)
        if not voltage or not case or run is None or not bus:
            continue
        key = (voltage, case, run, bus)
        if key not in seen:
            seen.add(key)
            output.append(key)
    return output


def normalize_project_case_run_exclusions(value: Any) -> dict[str, list[tuple[str, int]]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, list[tuple[str, int]]] = {}
    for project, exclusions in value.items():
        normalized = normalize_case_run_exclusions(exclusions)
        if normalized:
            output[str(project)] = normalized
    return output


def normalize_project_high_voltage_exclusions(
    value: Any,
) -> dict[str, list[tuple[str, str, int, str]]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, list[tuple[str, str, int, str]]] = {}
    for project, exclusions in value.items():
        normalized = normalize_high_voltage_exclusions(exclusions)
        if normalized:
            output[str(project)] = normalized
    return output


def _normalize_exclusion_rule(value: Any) -> ExclusionRule | None:
    if isinstance(value, ExclusionRule):
        raw = value.to_dict()
    elif isinstance(value, dict):
        raw = value
    else:
        return None

    case = str(raw.get("case", "")).strip()
    bus = str(raw.get("bus", raw.get("MM_name", ""))).strip()
    voltage = normalize_voltage(raw.get("voltage", ""))
    run_raw = raw.get("run")
    run = _optional_run(run_raw)
    if run_raw is not None and str(run_raw).strip() and run is None:
        return None
    if not case and run is None and not bus:
        return None
    return ExclusionRule(
        apply=_apply_value(raw.get("apply", True)),
        case=case,
        run=run,
        bus=bus,
        voltage=voltage,
    )


def _optional_run(value: Any) -> int | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"[rR]\d+", text):
        return int(text[1:])
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not number.is_integer() or number < 0:
        return None
    return int(number)


def _apply_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"0", "false", "no", "off", "unchecked", "none"}:
        return False
    return True


def _legacy_bus_tokens(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = re.split(r"[,;\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw = [str(item) for item in value]
    else:
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        bus = item.strip()
        key = bus.casefold()
        if bus and key not in seen:
            seen.add(key)
            output.append(bus)
    return output
