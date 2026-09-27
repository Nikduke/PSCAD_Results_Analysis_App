"""Project-specific RMS selection and plot-batch preparation.

The project catalog remains authoritative for the governing Case/Run/MM rows.
When Real RMS is enabled, those selected rows carry metadata that makes the
plotter recompute their visible traces from instantaneous ``LGp``/``LLp``
waveforms.  The explicit legacy path keeps using the reported ``LGr``/``LLr``
catalog traces.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from collections.abc import Callable
from typing import Any, Iterable, Mapping

from results_analysis_app.project_config import normalize_voltage
from results_analysis_app import real_rms

RMS_QUANTITIES = ("LG", "LL")
RMS_BATCH_EVENTS = {"LG": "RMS_LG", "LL": "RMS_LL"}
RMS_TRACE_TYPES = {"LG": "LGr", "LL": "LLr"}
# Increment when the selected Case/Run/MM population or RMS calculations change.
RMS_RESULT_VERSION = 5
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
    real_rms: bool = False
    frequency_hz: float | None = None

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
            "real_rms": True,
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
        "real_rms": bool(value.get("real_rms", True)),
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


def _filtered_rms_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    selected_elements: Iterable[str],
    selected_voltages: Iterable[str] | None,
    available_keys: Iterable[RMSRowKey] | None,
    switching_time_mode: str,
    selected_switching_times: Iterable[float],
    switching_time_start_s: float | None,
    switching_time_end_s: float | None,
) -> list[dict[str, object]]:
    """Apply the shared MM-element, voltage, run, and switch-time filters."""
    element_keys = {str(item).strip().casefold() for item in selected_elements if str(item).strip()}
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
    return candidates


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
    selected_quantity_keys = {
        normalized
        for item in selected_quantities
        if (normalized := normalize_rms_quantity(item))
    }
    quantities = [quantity for quantity in RMS_QUANTITIES if quantity in selected_quantity_keys]
    candidates = _filtered_rms_rows(
        rows,
        selected_elements=selected_elements,
        selected_voltages=selected_voltages,
        available_keys=available_keys,
        switching_time_mode=switching_time_mode,
        selected_switching_times=selected_switching_times,
        switching_time_start_s=switching_time_start_s,
        switching_time_end_s=switching_time_end_s,
    )

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


def apply_real_rms_to_selections(
    selections: Iterable[RMSSelection],
    *,
    run_index: Mapping[str, Mapping[int, Path]],
    frequency_hz: float | None = None,
    check_cancel: Callable[[], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[RMSSelection]:
    """Recompute only the already-selected rows from instantaneous waveforms.

    The catalog selector deliberately remains the source of governing-row
    identity.  Raw data is used only for the selected plot/report rows, so
    enabling Real RMS cannot change which Case/Run/MM was selected or require
    a full scan of every eligible source run.
    """
    selected = list(selections)
    if not selected:
        if log is not None:
            log(
                "RMS Real RMS enrichment: selected rows=0; source runs=0; "
                "computed source runs=0; enriched rows=0; fallback rows=0"
            )
        return []

    try:
        resolved_frequency = float(
            frequency_hz or real_rms.DEFAULT_REAL_RMS_FREQUENCY_HZ
        )
    except (TypeError, ValueError):
        resolved_frequency = real_rms.DEFAULT_REAL_RMS_FREQUENCY_HZ
    if not math.isfinite(resolved_frequency) or resolved_frequency <= 0:
        resolved_frequency = real_rms.DEFAULT_REAL_RMS_FREQUENCY_HZ

    case_index = {
        str(case_name).casefold(): runs
        for case_name, runs in run_index.items()
    }
    groups_by_source: dict[tuple[str, int], tuple[str, set[str]]] = {}
    for selection in selected:
        source_key = (selection.case_name.casefold(), int(selection.run_number))
        if source_key not in groups_by_source:
            groups_by_source[source_key] = (selection.case_name, set())
        groups_by_source[source_key][1].add(selection.element_name)

    computed: dict[tuple[str, int, str, str], real_rms.RealRMSResult] = {}
    computed_sources: set[tuple[str, int]] = set()
    missing_paths = 0
    failed_sources = 0
    failure_samples: list[str] = []
    quantities = sorted({selection.quantity for selection in selected})
    for (case_key, run_number), (case_name, group_labels) in groups_by_source.items():
        if check_cancel is not None:
            check_cancel()
        inf_path = case_index.get(case_key, {}).get(run_number)
        if inf_path is None:
            missing_paths += 1
            continue
        try:
            group_results = real_rms.compute_groups_real_rms(
                inf_path,
                group_labels,
                quantities,
                resolved_frequency,
                check_cancel=check_cancel,
            )
        except (OSError, ValueError, IndexError) as exc:
            failed_sources += 1
            if len(failure_samples) < 3:
                failure_samples.append(
                    f"{case_name} Run {run_number}: {type(exc).__name__}: {exc}"
                )
            continue
        if not group_results:
            failed_sources += 1
            if len(failure_samples) < 3:
                failure_samples.append(
                    f"{case_name} Run {run_number}: no computable selected LGp/LLp groups"
                )
            continue
        computed_sources.add((case_key, run_number))
        for (group_label, quantity), result in group_results.items():
            computed[(case_key, run_number, group_label.casefold(), quantity)] = result

    output: list[RMSSelection] = []
    enriched_rows = 0
    fallback_rows = 0
    for selection in selected:
        result = computed.get(
            (
                selection.case_name.casefold(),
                int(selection.run_number),
                selection.element_name.casefold(),
                selection.quantity,
            )
        )
        if result is None:
            output.append(selection)
            fallback_rows += 1
            continue
        value_kv = result.max_kv if selection.variant == "max" else result.min_kv
        reference_kv = selection.voltage_kv / (
            math.sqrt(3.0) if selection.quantity == "LG" else 1.0
        )
        value_pu = value_kv / reference_kv if reference_kv > 0 else None
        source_row = dict(selection.source_row)
        max_col, max_pu_col, min_col, min_pu_col = _columns(selection.quantity)
        value_col = max_col if selection.variant == "max" else min_col
        pu_col = max_pu_col if selection.variant == "max" else min_pu_col
        source_row[value_col] = value_kv
        source_row[pu_col] = value_pu
        output.append(
            RMSSelection(
                quantity=selection.quantity,
                variant=selection.variant,
                case_name=selection.case_name,
                run_number=selection.run_number,
                element_name=selection.element_name,
                voltage_kv=selection.voltage_kv,
                value_kv=float(value_kv),
                value_pu=value_pu,
                source_row=source_row,
                real_rms=True,
                frequency_hz=resolved_frequency,
            )
        )
        enriched_rows += 1

    if log is not None:
        log(
            "RMS Real RMS enrichment: "
            f"selected rows={len(selected)}; "
            f"source runs={len(groups_by_source)}; "
            f"computed source runs={len(computed_sources)}; "
            f"enriched rows={enriched_rows}; "
            f"fallback rows={fallback_rows}; "
            f"missing source paths={missing_paths}; "
            f"failed sources={failed_sources}"
        )
        for failure in failure_samples:
            log(f"RMS raw source failure: {failure}")
    return output


def select_rms_rows_from_catalog(
    catalog: object,
    settings: object,
    selected_voltages: Iterable[str] | None = None,
    *,
    run_index: Mapping[str, Mapping[int, Path]] | None = None,
    frequency_hz: float | None = None,
    check_cancel: Callable[[], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[RMSSelection]:
    """Select RMS rows from an authoritative plotter catalog."""
    parsed = normalize_rms_settings(settings)
    if not parsed["enabled"]:
        return []
    mm_elements = getattr(catalog, "mm_elements", ()) or ()
    available_keys = available_mm_row_keys(mm_elements)
    selected_voltage_values = (
        None if selected_voltages is None else list(selected_voltages)
    )
    # Report-only rebuilds may have the catalog CSV but no surviving .inf
    # inventory.  Preserve the catalog fallback in that case; a populated
    # MM inventory still constrains rows to available Case/Run/MM/voltage keys.
    if not mm_elements:
        available_keys = None
    selections = select_rms_rows(
        getattr(catalog, "mm_results", ()),
        selected_elements=parsed["elements"],
        selected_quantities=parsed["quantities"],
        selected_voltages=selected_voltage_values,
        available_keys=available_keys,
        switching_time_mode=parsed["switching_time_mode"],
        selected_switching_times=parsed["switching_times"],
        switching_time_start_s=parsed["switching_time_start_s"],
        switching_time_end_s=parsed["switching_time_end_s"],
    )
    quantity_text = ",".join(parsed["quantities"]) or "none"
    element_count = len(parsed["elements"])
    if element_count <= 8:
        element_text = ",".join(parsed["elements"]) or "none"
    else:
        element_text = f"{element_count} selected"
    if selected_voltage_values is None:
        voltage_text = "all"
    else:
        voltage_keys = sorted(
            {
                normalized
                for value in selected_voltage_values
                if (normalized := normalize_voltage(value))
            },
            key=str,
        )
        voltage_text = ",".join(voltage_keys) or "none"
    switching_mode = parsed["switching_time_mode"]
    if switching_mode == RMS_SWITCHING_TIME_MODE_DISCRETE:
        switching_text = "discrete[" + ",".join(
            f"{value:g}" for value in parsed["switching_times"]
        ) + "]"
    elif switching_mode == RMS_SWITCHING_TIME_MODE_RANGE:
        start = parsed["switching_time_start_s"]
        end = parsed["switching_time_end_s"]
        switching_text = f"range[{start:g}..{end:g}]" if start is not None and end is not None else "range[invalid]"
    else:
        switching_text = "all"
    if log is not None:
        log(
            "RMS filters: "
            f"quantities={quantity_text}; elements={element_text}; "
            f"voltages={voltage_text}; switching={switching_text}"
        )
    if parsed["real_rms"] and run_index is not None:
        if log is not None:
            log(
                "RMS catalog selection: method=MM results.csv; "
                f"selected rows={len(selections)}; Real RMS enrichment=on"
            )
        return apply_real_rms_to_selections(
            selections,
            run_index=run_index,
            frequency_hz=frequency_hz,
            check_cancel=check_cancel,
            log=log,
        )
    if log is not None:
        method = (
            "MM results.csv"
            if not parsed["real_rms"]
            else "MM results.csv fallback (raw run index unavailable)"
        )
        log(f"RMS catalog selection: method={method}; selected rows={len(selections)}")
    return selections


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
                "real_rms": bool(selection.real_rms),
                "real_rms_frequency_hz": selection.frequency_hz,
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
