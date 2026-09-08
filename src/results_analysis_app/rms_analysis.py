"""Project-specific RMS voltage selection and batch-row preparation.

The RMS study uses the already parsed ``MM results.csv`` rows.  It deliberately
does not apply the exploratory script's hard-coded element or time-window
filters: the active project settings provide the selected MM elements and RMS
quantities instead.
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
RMS_RESULT_VERSION = 1
RMS_MIN_VALID_PU = 0.05
VOLTAGE_EPSILON_KV = 1e-6


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


def normalize_rms_settings(value: object) -> dict[str, Any]:
    """Return the persisted RMS settings in one stable shape."""
    if not isinstance(value, Mapping):
        return {"enabled": False, "quantities": [*RMS_QUANTITIES], "elements": []}
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
    return {
        "enabled": bool(value.get("enabled", False)),
        "quantities": [quantity for quantity in RMS_QUANTITIES if quantity in quantities],
        "elements": sorted(elements, key=str.casefold),
    }


def available_elements(rows: Iterable[Mapping[str, object]]) -> list[str]:
    values = {
        str(row.get("Bus name", "") or "").strip()
        for row in rows
        if str(row.get("Bus name", "") or "").strip()
    }
    return sorted(values, key=str.casefold)


def select_rms_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    selected_elements: Iterable[str],
    selected_quantities: Iterable[str] = RMS_QUANTITIES,
    selected_voltages: Iterable[str] | None = None,
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
        normalize_voltage(value)
        for value in selected_voltages
        if normalize_voltage(value)
    }
    candidates: list[dict[str, object]] = []
    for source in rows:
        row = dict(source)
        element = str(row.get("Bus name", "") or "").strip()
        case_name = str(row.get("Case name", "") or "").strip()
        run_number = _finite_float(row.get("Run#"))
        voltage_kv = _finite_float(row.get("Bus voltage [kV]"))
        if not element or not case_name or run_number is None or voltage_kv is None:
            continue
        if element.casefold() not in element_keys:
            continue
        if voltage_keys is not None and normalize_voltage(voltage_kv) not in voltage_keys:
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
                "annotate_max": True,
                "annotate_min": True,
                "plot_variant": selection.variant,
            }
        )
    for event in rows:
        rows[event].sort(key=lambda row: (str(row["element"]).casefold(), int(row["run"]), str(row["plot_variant"])))
    return rows


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
