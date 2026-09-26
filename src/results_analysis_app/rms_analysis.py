"""Project-specific RMS voltage selection and batch-row preparation.

The RMS study uses the already parsed ``MM results.csv`` rows.  New plot
batches restrict those rows to Case/Run/MM/voltage combinations backed by the
project's available run index.  The active project settings provide the
selected MM elements, RMS quantities, and either discrete switching times or
an inclusive switching-time range.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from results_analysis_app.project_config import normalize_voltage

RMS_QUANTITIES = ("LG", "LL")
RMS_BATCH_EVENTS = {"LG": "RMS_LG", "LL": "RMS_LL"}
RMS_TRACE_TYPES = {"LG": "LGr", "LL": "LLr"}
# Increment when the selected Case/Run/MM population or RMS calculations change.
RMS_RESULT_VERSION = 3
RMS_MIN_VALID_PU = 0.05
VOLTAGE_EPSILON_KV = 1e-6
RMS_REPORT_VARIANT_ORDER = ("max", "min")
RMSRowKey = tuple[str, int, str, str]
RMS_SWITCHING_TIME_COLUMNS = (
    "Tswitch_a [s]",
    "Tswitch_b [s]",
    "Tswitch_c [s]",
)
RMS_SWITCHING_TIME_MODE_ALL = "all"
RMS_SWITCHING_TIME_MODE_DISCRETE = "discrete"
RMS_SWITCHING_TIME_MODE_RANGE = "range"
RMS_DISCRETE_SWITCH_TYPES = {"sequential", "none"}
RMS_TIME_EPSILON_S = 1e-9


@dataclass(frozen=True, slots=True)
class RMSSelection:
    quantity: str
    variant: str
    case_name: str
    run_number: int
    element_name: str
    voltage_kv: float
    value_kv: float
    value_pu: float | None
    source_row: Mapping[str, object]

    @property
    def voltage_key(self) -> str:
        return normalize_voltage(self.voltage_kv)


def normalize_rms_quantity(value: object) -> str | None:
    token = str(value or "").strip().upper()
    if token in {"LG", "LGR", "LG_R", "LG RMS"}:
        return "LG"
    if token in {"LL", "LLR", "LL_R", "LL RMS"}:
        return "LL"
    return None


def normalize_switch_type(value: object) -> str:
    """Return a stable switch-type label, treating a blank value as None."""
    text = str(value or "").strip()
    return text or "None"


def switching_time_mode_for_type(value: object) -> str:
    """Map the project's Input_Data switch type to the RMS selector mode."""
    return (
        RMS_SWITCHING_TIME_MODE_DISCRETE
        if normalize_switch_type(value).casefold() in RMS_DISCRETE_SWITCH_TYPES
        else RMS_SWITCHING_TIME_MODE_RANGE
    )


def _normalize_switching_time_mode(value: object) -> str:
    token = str(value or "").strip().casefold()
    aliases = {
        "all": RMS_SWITCHING_TIME_MODE_ALL,
        "discrete": RMS_SWITCHING_TIME_MODE_DISCRETE,
        "list": RMS_SWITCHING_TIME_MODE_DISCRETE,
        "range": RMS_SWITCHING_TIME_MODE_RANGE,
        "window": RMS_SWITCHING_TIME_MODE_RANGE,
    }
    return aliases.get(token, "")


def _normalize_switching_times(value: object) -> list[float]:
    if not isinstance(value, (list, tuple, set)):
        return []
    values: set[float] = set()
    for item in value:
        number = _finite_float(item)
        if number is not None:
            values.add(number)
    return sorted(values)


def normalize_rms_settings(value: object) -> dict[str, Any]:
    """Return the persisted RMS settings in one stable shape."""
    if not isinstance(value, Mapping):
        return {
            "enabled": False,
            "quantities": [*RMS_QUANTITIES],
            "elements": [],
            "switching_time_mode": RMS_SWITCHING_TIME_MODE_ALL,
            "switching_times": [],
            "switching_time_start_s": None,
            "switching_time_end_s": None,
        }
    quantities: list[str] = []
    raw_quantities = value.get("quantities", RMS_QUANTITIES)
    if isinstance(raw_quantities, (list, tuple, set)):
        for item in raw_quantities:
            quantity = normalize_rms_quantity(item)
            if quantity and quantity not in quantities:
                quantities.append(quantity)
    elements: list[str] = []
    element_keys: set[str] = set()
    raw_elements = value.get("elements", [])
    if isinstance(raw_elements, (list, tuple, set)):
        for item in raw_elements:
            element = str(item or "").strip()
            key = element.casefold()
            if element and key not in element_keys:
                element_keys.add(key)
                elements.append(element)
    mode = _normalize_switching_time_mode(value.get("switching_time_mode"))
    if not mode:
        if "switching_times" in value:
            mode = RMS_SWITCHING_TIME_MODE_DISCRETE
        elif "switching_time_start_s" in value or "switching_time_end_s" in value:
            mode = RMS_SWITCHING_TIME_MODE_RANGE
        else:
            mode = RMS_SWITCHING_TIME_MODE_ALL
    return {
        "enabled": bool(value.get("enabled", False)),
        "quantities": [quantity for quantity in RMS_QUANTITIES if quantity in quantities],
        "elements": sorted(elements, key=str.casefold),
        "switching_time_mode": mode,
        "switching_times": _normalize_switching_times(value.get("switching_times")),
        "switching_time_start_s": _finite_float(value.get("switching_time_start_s")),
        "switching_time_end_s": _finite_float(value.get("switching_time_end_s")),
    }


def row_switching_times(row: Mapping[str, object]) -> tuple[float, ...]:
    """Return the available phase switching times for one MM result row."""
    values = tuple(
        value
        for column in RMS_SWITCHING_TIME_COLUMNS
        if (value := _finite_float(row.get(column))) is not None
    )
    if values:
        return values
    event_time = _finite_float(row.get("EventTime"))
    return (event_time,) if event_time is not None else ()


def _row_key(row: Mapping[str, object]) -> RMSRowKey | None:
    case_name = str(row.get("Case name", "") or "").strip()
    element_name = str(row.get("Bus name", "") or "").strip()
    run_number = _finite_float(row.get("Run#"))
    voltage_kv = _finite_float(row.get("Bus voltage [kV]"))
    if (
        not case_name
        or not element_name
        or run_number is None
        or not run_number.is_integer()
        or run_number < 1
        or voltage_kv is None
    ):
        return None
    return (
        case_name.casefold(),
        int(run_number),
        element_name.casefold(),
        normalize_voltage(voltage_kv),
    )


def available_switching_times(
    rows: Iterable[Mapping[str, object]],
    available_keys: Iterable[RMSRowKey] | None = None,
) -> list[float]:
    """Return sorted unique switching times backed by the available run index."""
    available_key_set = set(available_keys) if available_keys is not None else None
    values: set[float] = set()
    for row in rows:
        if available_key_set is not None:
            row_key = _row_key(row)
            if row_key is None or row_key not in available_key_set:
                continue
        values.update(row_switching_times(row))
    return sorted(values)


def row_matches_switching_time(
    row: Mapping[str, object],
    *,
    mode: str = RMS_SWITCHING_TIME_MODE_ALL,
    selected_times: Iterable[float] = (),
    start_s: float | None = None,
    end_s: float | None = None,
) -> bool:
    """Apply the RMS discrete-list or inclusive range switching-time filter."""
    if mode == RMS_SWITCHING_TIME_MODE_ALL:
        return True
    times = row_switching_times(row)
    if not times:
        return False
    if mode == RMS_SWITCHING_TIME_MODE_DISCRETE:
        selected = tuple(_finite_float(value) for value in selected_times)
        selected = tuple(value for value in selected if value is not None)
        return any(
            any(
                math.isclose(time, selected_time, rel_tol=0.0, abs_tol=RMS_TIME_EPSILON_S)
                for selected_time in selected
            )
            for time in times
        )
    if mode == RMS_SWITCHING_TIME_MODE_RANGE:
        if start_s is not None and end_s is not None and start_s > end_s:
            return False
        return any(
            (start_s is None or time >= start_s)
            and (end_s is None or time <= end_s)
            for time in times
        )
    return True


def load_mm_results(project_root: str | Path) -> list[dict[str, object]]:
    """Convenience loader backed by the plotter's shared catalog service."""
    from pscad_plotter_app_v3.services.project import CatalogCache, ResultsCatalogService

    root = Path(project_root).resolve()
    service = ResultsCatalogService()
    source_path = root / "Results" / service.MM_FILENAME
    if not source_path.is_file():
        return []
    cache = CatalogCache(root / "Plots" / ".plottool_v3")
    try:
        return service.load_mm_results(source_path, cache)
    finally:
        cache.close()


def available_elements(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """Return alphabetized MM element names from parsed result rows."""
    values = {
        str(row.get("Bus name", "") or "").strip()
        for row in rows
        if str(row.get("Bus name", "") or "").strip()
    }
    return sorted(values, key=str.casefold)


def available_mm_row_keys(records: Iterable[object]) -> set[RMSRowKey]:
    """Return the Case/Run/MM/voltage keys backed by available waveforms."""
    keys: set[RMSRowKey] = set()
    for record in records:
        case_name = str(getattr(record, "case_name", "") or "").strip()
        element_name = str(getattr(record, "element_name", "") or "").strip()
        voltage_kv = _finite_float(getattr(record, "voltage_kv", None))
        if not case_name or not element_name or voltage_kv is None:
            continue
        voltage_key = normalize_voltage(voltage_kv)
        for raw_run in getattr(record, "available_runs", ()) or ():
            run_number = _finite_float(raw_run)
            if run_number is None or not run_number.is_integer() or run_number < 1:
                continue
            keys.add(
                (
                    case_name.casefold(),
                    int(run_number),
                    element_name.casefold(),
                    voltage_key,
                )
            )
    return keys


def select_rms_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    selected_elements: Iterable[str],
    selected_quantities: Iterable[str] = RMS_QUANTITIES,
    selected_voltages: Iterable[str] | None = None,
    available_keys: Iterable[RMSRowKey] | None = None,
    switching_time_mode: str = RMS_SWITCHING_TIME_MODE_ALL,
    selected_switching_times: Iterable[float] = (),
    switching_time_start_s: float | None = None,
    switching_time_end_s: float | None = None,
) -> list[RMSSelection]:
    """Select one governing max and min row per voltage and quantity.

    Ranking follows the reference method: max uses the reported RMS peak, min
    uses the reported RMS minimum after excluding values at or below 0.05 pu.
    Duplicate Case/Bus rows are collapsed before selecting one unique case.
    """
    element_keys = {str(item).strip().casefold() for item in selected_elements if str(item).strip()}
    selected_quantity_keys = {
        normalized
        for item in selected_quantities
        if (normalized := normalize_rms_quantity(item))
    }
    quantities = [quantity for quantity in RMS_QUANTITIES if quantity in selected_quantity_keys]
    voltage_keys = None if selected_voltages is None else {
        normalized
        for value in selected_voltages
        if (normalized := normalize_voltage(value))
    }
    available_key_set = set(available_keys) if available_keys is not None else None
    candidates: list[dict[str, object]] = []
    for source in rows:
        row = dict(source)
        element = str(row.get("Bus name", "") or "").strip()
        case_name = str(row.get("Case name", "") or "").strip()
        run_number = _finite_float(row.get("Run#"))
        voltage_kv = _finite_float(row.get("Bus voltage [kV]"))
        if (
            not element
            or not case_name
            or run_number is None
            or not run_number.is_integer()
            or run_number < 1
            or voltage_kv is None
        ):
            continue
        voltage_key = normalize_voltage(voltage_kv)
        if element.casefold() not in element_keys:
            continue
        if voltage_keys is not None and voltage_key not in voltage_keys:
            continue
        if available_key_set is not None and (
            case_name.casefold(),
            int(run_number),
            element.casefold(),
            voltage_key,
        ) not in available_key_set:
            continue
        if not row_matches_switching_time(
            row,
            mode=switching_time_mode,
            selected_times=selected_switching_times,
            start_s=switching_time_start_s,
            end_s=switching_time_end_s,
        ):
            continue
        row["Run#"] = int(run_number)
        row["Bus voltage [kV]"] = float(voltage_kv)
        candidates.append(row)

    output: list[RMSSelection] = []
    for voltage_kv in sorted(
        {_finite_float(row.get("Bus voltage [kV]")) for row in candidates},
        reverse=True,
    ):
        if voltage_kv is None:
            continue
        voltage_rows = [
            row
            for row in candidates
            if abs(float(row["Bus voltage [kV]"]) - voltage_kv) <= VOLTAGE_EPSILON_KV
        ]
        for quantity in quantities:
            max_col, max_pu_col, min_col, min_pu_col = _columns(quantity)
            max_rows = _rank_unique_case_bus(voltage_rows, max_col, reverse=True)
            if max_rows:
                output.append(_selection_from_row(max_rows[0], quantity, "max", max_col, max_pu_col))
            min_rows = [
                row
                for row in voltage_rows
                if (_pu_value(row, min_col, min_pu_col, quantity) or 0.0) > RMS_MIN_VALID_PU
            ]
            min_ranked = _rank_unique_case_bus(min_rows, min_col, reverse=False)
            if min_ranked:
                output.append(_selection_from_row(min_ranked[0], quantity, "min", min_col, min_pu_col))
    return output


def select_rms_rows_from_catalog(
    catalog: object,
    settings: object,
    selected_voltages: Iterable[str] | None = None,
) -> list[RMSSelection]:
    """Select RMS rows from an authoritative plotter catalog."""
    parsed = normalize_rms_settings(settings)
    if not parsed["enabled"]:
        return []
    available_keys = available_mm_row_keys(getattr(catalog, "mm_elements", ()))
    return select_rms_rows(
        getattr(catalog, "mm_results", ()),
        selected_elements=parsed["elements"],
        selected_quantities=parsed["quantities"],
        selected_voltages=selected_voltages,
        available_keys=available_keys,
        switching_time_mode=parsed["switching_time_mode"],
        selected_switching_times=parsed["switching_times"],
        switching_time_start_s=parsed["switching_time_start_s"],
        switching_time_end_s=parsed["switching_time_end_s"],
    )


def rms_batch_rows(
    selections: Iterable[RMSSelection],
    *,
    excel_export: bool = True,
) -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {event: [] for event in RMS_BATCH_EVENTS.values()}
    for selection in selections:
        rows[RMS_BATCH_EVENTS[selection.quantity]].append(
            {
                "case": selection.case_name,
                "run": selection.run_number,
                "element": selection.element_name,
                "trace": RMS_TRACE_TYPES[selection.quantity],
                "overview": False,
                "tov_windows": False,
                "limits": False,
                "legends_left": False,
                "excel_export": bool(excel_export),
                "annotate_max": selection.variant == "max",
                "annotate_min": selection.variant == "min",
            }
        )
    for event in rows:
        rows[event].sort(
            key=lambda row: (
                str(row["element"]).casefold(),
                int(row["run"]),
                0 if row["annotate_max"] else 1,
            )
        )
    return rows


def rms_reference_kv(selection: RMSSelection) -> float | None:
    """Return the nominal RMS reference used for the report percentage."""
    steady_state_ll = _finite_float(selection.source_row.get("LLs [kV]"))
    if steady_state_ll is None or steady_state_ll <= 0:
        return None
    return steady_state_ll / math.sqrt(3.0) if selection.quantity == "LG" else steady_state_ll


def rms_change_percent(selection: RMSSelection) -> float | None:
    """Return rise/dip percentage relative to the MM steady-state reference."""
    reference = rms_reference_kv(selection)
    if reference is None or not math.isfinite(selection.value_kv):
        return None
    if selection.variant == "max":
        return (selection.value_kv - reference) / reference * 100.0
    if selection.variant == "min":
        return (reference - selection.value_kv) / reference * 100.0
    return None


def rms_output_dir(project_root: Path, scope_folder: str, quantity: str) -> Path:
    normalized = normalize_rms_quantity(quantity) or "LG"
    return project_root / "Plots" / "Generated" / scope_folder / "RMS" / normalized


def rms_batch_path(project_root: Path, scope_folder: str, quantity: str) -> Path:
    normalized = normalize_rms_quantity(quantity) or "LG"
    return project_root / "Plots" / "Plot_batch" / f"batch_paste_{scope_folder}_RMS_{normalized}.xlsx"


def _columns(quantity: str) -> tuple[str, str, str, str]:
    if quantity == "LG":
        return "LGr [kV]", "LGr [pu]", "LGrm [kV]", "LGrm [pu]"
    return "LLr [kV]", "LLr [pu]", "LLrm [kV]", "LLrm [pu]"


def _rank_unique_case_bus(
    rows: Iterable[Mapping[str, object]],
    value_col: str,
    *,
    reverse: bool,
) -> list[Mapping[str, object]]:
    ranked = sorted(
        (row for row in rows if _finite_float(row.get(value_col)) is not None),
        key=lambda row: (
            -float(_finite_float(row.get(value_col))) if reverse else float(_finite_float(row.get(value_col))),
            str(row.get("Unique ID", "")),
            str(row.get("Case name", "")),
            int(_finite_float(row.get("Run#")) or 0),
        ),
    )
    seen: set[tuple[str, str]] = set()
    for row in ranked:
        key = (str(row.get("Case name", "")), str(row.get("Bus name", "")))
        if key in seen:
            continue
        seen.add(key)
        # The reference workflow selects TOP_N=1.  Return immediately after
        # the first unique Case/Bus row so lower-ranked rows are not carried
        # through the batch preparation path.
        return [row]
    return []


def _selection_from_row(
    row: Mapping[str, object],
    quantity: str,
    variant: str,
    value_col: str,
    pu_col: str,
) -> RMSSelection:
    return RMSSelection(
        quantity=quantity,
        variant=variant,
        case_name=str(row["Case name"]),
        run_number=int(float(row["Run#"])),
        element_name=str(row["Bus name"]),
        voltage_kv=float(row["Bus voltage [kV]"]),
        value_kv=float(row[value_col]),
        value_pu=_pu_value(row, value_col, pu_col, quantity),
        source_row=row,
    )


def _pu_value(
    row: Mapping[str, object],
    value_col: str,
    pu_col: str,
    quantity: str,
) -> float | None:
    existing = _finite_float(row.get(pu_col))
    if existing is not None:
        return existing
    value = _finite_float(row.get(value_col))
    bus_kv = _finite_float(row.get("Bus voltage [kV]"))
    if value is None or bus_kv is None:
        return None
    divisor = math.sqrt(3.0) if quantity == "LG" else 1.0
    reference = bus_kv / divisor
    return value / reference if reference else None


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
