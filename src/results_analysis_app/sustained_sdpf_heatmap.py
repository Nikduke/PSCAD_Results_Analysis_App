"""Over-limit incidence heatmaps built from persisted Sustained SDPF observations.

This module deliberately contains no waveform or SDPF calculation.  It turns
the complete ``SustainedSDPFResult`` population into a compact, report-ready
view.  Keeping the aggregation here separate from :mod:`sustained_sdpf` makes
it harder for the presentation feature to acquire a second interpretation of
the engineering calculation.
"""

from __future__ import annotations

import re
import shutil
import textwrap
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeAlias

from results_analysis_app import sustained_sdpf
from results_analysis_app.common import as_bool

HEATMAP_EVENT = "Sustained_SDPF_Heatmap"
NONE_GROUPING = "None"
FAULT_GROUPING = "Fault type"
UNKNOWN_GROUP = "Unknown"
HEATMAP_LAYOUT_SEPARATE = "separate"
HEATMAP_LAYOUT_COMBINED = "combined"
HEATMAP_LAYOUT_AUTO = "auto"
DEFAULT_HEATMAP_MAX_PANELS = 4
MM_GROUPING = "MM element"
# ``Faults`` remains the legacy/default name used when no project metadata is
# available (for example while migrating an older saved session).  A scanned
# project chooses a metadata-aware name instead.
DEFAULT_HEATMAP_SET_NAME = "Faults"
DEFAULT_CASE_HEATMAP_SET_NAME = "All cases"

HEATMAP_CLEAR_COLOR = "#d9ead3"
HEATMAP_INELIGIBLE_COLOR = "#e5e7eb"
HEATMAP_TEXT_DARK = "#111827"
HEATMAP_TEXT_LIGHT = "#ffffff"
# Keep actual violations red and margin-only cells gold/amber.  The custom
# ramps avoid the brown endpoint produced by YlOrBr while preserving severity
# ordering within each category.
HEATMAP_ACTUAL_COLORS = ("#F8B4B4", "#E76F6F", "#C62828", "#8E1B2A")
HEATMAP_MARGIN_COLORS = ("#FFF0B3", "#FFD166", "#F2B134", "#C98200")

# Figure geometry is expressed in inches and assembled as named vertical
# bands.  Keeping the geometry here (rather than mixing GridSpec ratios,
# subplot padding, and ``bbox_inches='tight'``) makes every rendered figure
# use the same predictable coordinate system.
HEATMAP_RENDER_DPI = 150
HEATMAP_LEFT_MARGIN_IN = 1.35
HEATMAP_RIGHT_MARGIN_IN = 0.30
HEATMAP_TOP_MARGIN_IN = 0.22
HEATMAP_BOTTOM_MARGIN_IN = 0.16
HEATMAP_TITLE_BAND_IN = 0.72
HEATMAP_TITLE_LINE_HEIGHT_IN = 0.32
HEATMAP_TITLE_PADDING_IN = 0.28
HEATMAP_GROUP_BAND_IN = 0.32
HEATMAP_PANEL_TITLE_BAND_IN = 0.36
HEATMAP_MATRIX_MIN_HEIGHT_IN = 2.35
HEATMAP_ROW_HEIGHT_IN = 0.50
HEATMAP_FOOTER_BAND_IN = 0.60
HEATMAP_BAND_GAP_IN = 0.06
HEATMAP_PANEL_GAP_IN = 0.14
HEATMAP_MIN_FIG_WIDTH_IN = 8.0
HEATMAP_MAX_FIG_WIDTH_IN = 42.0


@dataclass(frozen=True, slots=True)
class HeatmapObservation:
    """Compact persisted result used only to rebuild heatmaps.

    The detailed SustainedSDPFResult remains the source for reports and the
    governing waveform plot. Heatmap rebuilding only needs the grouping
    identity and the two already-classified peak-envelope persistence flags.
    ``actual`` means the SDPF peak limit was exceeded for the required run;
    ``margin`` means the SDPF/1.15 peak threshold was exceeded for the required
    run and therefore includes ``actual`` observations.
    """

    case: str
    run: int
    mm_name: str
    fault_type: str
    actual: bool
    margin: bool

    @classmethod
    def from_result(cls, result: sustained_sdpf.SustainedSDPFResult) -> HeatmapObservation:
        actual, margin = _phase_flags(result)
        return cls(
            case=str(result.case),
            run=int(result.run),
            mm_name=str(result.mm_name),
            fault_type=str(result.fault_type or ""),
            actual=actual,
            margin=margin or actual,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> HeatmapObservation | None:
        if not isinstance(raw, Mapping) or not {"actual", "margin"}.issubset(raw):
            return None
        try:
            case = str(raw.get("case", "")).strip()
            run = int(float(raw.get("run", 0)))
            mm_name = str(raw.get("mm_name", "")).strip()
        except (TypeError, ValueError):
            return None
        if not case or not mm_name:
            return None
        actual = as_bool(raw.get("actual"), False)
        margin = as_bool(raw.get("margin"), False) or actual
        return cls(case, run, mm_name, str(raw.get("fault_type", "") or ""), actual, margin)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "run": self.run,
            "mm_name": self.mm_name,
            "fault_type": self.fault_type,
            "actual": self.actual,
            "margin": self.margin,
        }


HeatmapItem: TypeAlias = sustained_sdpf.SustainedSDPFResult | HeatmapObservation


def _natural_key(value: Any) -> tuple[Any, ...]:
    parts = re.split(r"(\d+)", str(value))
    output: list[Any] = []
    for part in parts:
        output.append(int(part) if part.isdigit() else part.casefold())
    return tuple(output)


def _clean_group(value: Any) -> str:
    return "" if value is None else str(value).strip()


@dataclass(frozen=True, slots=True)
class HeatmapSettings:
    """Project-specific heatmap presentation settings.

    Empty strings are accepted as the persisted representation of ``None`` so
    old/session JSON remains forgiving.  Public attributes use ``None`` for a
    disabled X/Split dimension.
    """

    enabled: bool = True
    y_grouping: str = "All"
    x_grouping: str | None = None
    split_by: str | None = None
    max_cases_per_heatmap: int = 12
    layout: str = HEATMAP_LAYOUT_SEPARATE
    max_panels_per_heatmap: int = DEFAULT_HEATMAP_MAX_PANELS

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> HeatmapSettings:
        raw = data if isinstance(data, Mapping) else {}
        y_value = _clean_group(raw.get("y_grouping", raw.get("y", "All"))) or "All"
        x_value = _clean_group(raw.get("x_grouping", raw.get("x", ""))) or None
        split_value = _clean_group(raw.get("split_by", raw.get("split", ""))) or None
        try:
            max_cases = int(raw.get("max_cases_per_heatmap", raw.get("max_cases", 12)))
        except (TypeError, ValueError):
            max_cases = 12
        max_cases = max(1, min(max_cases, 500))
        layout = str(raw.get("layout", raw.get("panel_layout", HEATMAP_LAYOUT_SEPARATE))).strip().casefold()
        if layout not in {
            HEATMAP_LAYOUT_SEPARATE,
            HEATMAP_LAYOUT_COMBINED,
            HEATMAP_LAYOUT_AUTO,
        }:
            layout = HEATMAP_LAYOUT_SEPARATE
        try:
            max_panels = int(
                raw.get(
                    "max_panels_per_heatmap",
                    raw.get("max_panels", DEFAULT_HEATMAP_MAX_PANELS),
                )
            )
        except (TypeError, ValueError):
            max_panels = DEFAULT_HEATMAP_MAX_PANELS
        max_panels = max(1, min(max_panels, 12))
        return cls(
            enabled=as_bool(raw.get("enabled", True), True),
            y_grouping=y_value,
            x_grouping=x_value,
            split_by=split_value,
            max_cases_per_heatmap=max_cases,
            layout=layout,
            max_panels_per_heatmap=max_panels,
        )

    def normalized(self, metadata: HeatmapMetadata | None = None) -> HeatmapSettings:
        if metadata is None:
            return self
        y_options = metadata.y_options
        default_y = metadata.default_y
        if self.y_grouping == NONE_GROUPING:
            y = NONE_GROUPING
        else:
            y = self.y_grouping if self.y_grouping in y_options else default_y
        # ``All`` is the neutral fallback for projects without useful
        # dimensions; for a newly configured project it means "auto" and must
        # resolve to Fault type or the first varying case-name token.
        if self.y_grouping in {"", "All"} and default_y != "All":
            y = default_y
        x = self.x_grouping if self.x_grouping in metadata.token_options else None
        split = self.split_by if self.split_by in metadata.token_options else None
        if x == y:
            x = None
        if split in {y, x}:
            split = None
        return HeatmapSettings(
            enabled=self.enabled,
            y_grouping=y,
            x_grouping=x,
            split_by=split,
            max_cases_per_heatmap=self.max_cases_per_heatmap,
            layout=self.layout,
            max_panels_per_heatmap=self.max_panels_per_heatmap,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "y_grouping": self.y_grouping or "All",
            "x_grouping": self.x_grouping,
            "split_by": self.split_by,
            "max_cases_per_heatmap": int(self.max_cases_per_heatmap),
            "layout": self.layout,
            "max_panels_per_heatmap": int(self.max_panels_per_heatmap),
        }


@dataclass(frozen=True, slots=True)
class HeatmapSet:
    """One named, ordered heatmap presentation using shared layout rules."""

    name: str
    settings: HeatmapSettings

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None, index: int = 0) -> HeatmapSet:
        mapping = dict(raw) if isinstance(raw, Mapping) else {}
        nested = mapping.get("settings")
        settings_mapping = nested if isinstance(nested, Mapping) else mapping
        name_value = mapping.get("name", settings_mapping.get("name"))
        name = _clean_group(name_value) or (DEFAULT_HEATMAP_SET_NAME if index == 0 else f"Heatmap {index + 1}")
        return cls(name, HeatmapSettings.from_mapping(settings_mapping))

    def normalized(self, metadata: HeatmapMetadata | None = None) -> HeatmapSet:
        return HeatmapSet(self.name, self.settings.normalized(metadata))

    def to_mapping(self) -> dict[str, Any]:
        return {"name": self.name, **self.settings.to_mapping()}


def display_heatmap_set_name(
    name: Any,
    settings: HeatmapSettings | Mapping[str, Any] | None = None,
) -> str:
    """Return the report/figure label for a configured heatmap set.

    Persisted names remain unchanged so folder names and settings references
    stay stable.  Only the old technical MM placeholder is translated for
    human-facing output.
    """
    text = _clean_group(name)
    if not text:
        return ""
    normalized_name = re.sub(r"[^a-z0-9]+", "", text.casefold())
    parsed_settings = (
        settings
        if isinstance(settings, HeatmapSettings)
        else HeatmapSettings.from_mapping(settings)
        if isinstance(settings, Mapping)
        else None
    )
    is_mm_view = parsed_settings is not None and parsed_settings.y_grouping == MM_GROUPING
    if normalized_name == "mmhm" or (
        is_mm_view and normalized_name in {"mmelement", "mmelements"}
    ):
        return "MM elements"
    return text


def _unique_heatmap_set_name(
    raw_name: Any,
    index: int,
    used_names: set[str],
) -> str:
    name = _clean_group(raw_name) or (
        DEFAULT_HEATMAP_SET_NAME if index == 0 else f"Heatmap {index + 1}"
    )
    base_name = name
    suffix = 2
    while name.casefold() in used_names:
        name = f"{base_name} {suffix}"
        suffix += 1
    used_names.add(name.casefold())
    return name


def heatmap_sets_from_mapping(value: Any) -> tuple[HeatmapSet, ...]:
    """Read new set lists and migrate the former one-mapping format."""
    if isinstance(value, Mapping) and isinstance(value.get("sets"), list):
        raw_sets = value["sets"]
    elif isinstance(value, (list, tuple)):
        raw_sets = value
    elif isinstance(value, Mapping):
        raw_sets = [value]
    else:
        raw_sets = []
    sets: list[HeatmapSet] = []
    used_names: set[str] = set()
    for index, raw in enumerate(raw_sets):
        heatmap_set = raw if isinstance(raw, HeatmapSet) else HeatmapSet.from_mapping(raw, index)
        name = _unique_heatmap_set_name(heatmap_set.name, index, used_names)
        sets.append(HeatmapSet(name, heatmap_set.settings))
    if not sets:
        sets.append(HeatmapSet(DEFAULT_HEATMAP_SET_NAME, HeatmapSettings()))
    return tuple(sets)


def heatmap_sets_to_mapping(value: Iterable[HeatmapSet | Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, raw in enumerate(value):
        heatmap_set = raw if isinstance(raw, HeatmapSet) else HeatmapSet.from_mapping(raw, index)
        name = _unique_heatmap_set_name(heatmap_set.name, index, used_names)
        output.append(HeatmapSet(name, heatmap_set.settings).to_mapping())
    return output


@dataclass(frozen=True, slots=True)
class HeatmapMetadata:
    case_names: tuple[str, ...] = ()
    token_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    token_labels: dict[str, str] = field(default_factory=dict)
    fault_types: tuple[str, ...] = ()
    # The parser keeps token values separate from their raw case-name parts
    # (for example ``P0`` is stored as key ``P``/value ``0``).  The raw values
    # are needed only for unambiguous display, while positional keys keep
    # variant text at one case-name position in one consistent dimension.
    token_raw_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    token_keys_by_position: tuple[str, ...] = ()

    @property
    def fault_types_available(self) -> bool:
        return bool(self.fault_types)

    @property
    def token_options(self) -> tuple[str, ...]:
        return tuple(self.token_values)

    @property
    def y_options(self) -> tuple[str, ...]:
        prefix = (FAULT_GROUPING,) if self.fault_types_available else ()
        return (*prefix, MM_GROUPING, *self.token_options, "All")

    @property
    def default_y(self) -> str:
        if self.fault_types_available:
            return FAULT_GROUPING
        # Case-name dimensions are the normal fallback when a project has no
        # fault classification.  MM grouping is an optional analysis view and
        # must never become the default merely because faults are absent.
        return self.token_options[0] if self.token_options else "All"

    def label(self, key: str) -> str:
        if key == FAULT_GROUPING:
            return FAULT_GROUPING
        if key == MM_GROUPING:
            return MM_GROUPING
        return self.token_labels.get(key, key)


def default_heatmap_set_name(metadata: HeatmapMetadata | None = None) -> str:
    """Return the name for a newly created project's default heatmap set."""
    if metadata is None:
        return DEFAULT_HEATMAP_SET_NAME
    grouping = metadata.default_y
    if grouping == FAULT_GROUPING:
        return DEFAULT_HEATMAP_SET_NAME
    if grouping == MM_GROUPING:
        return "MM elements"
    if grouping in {"", NONE_GROUPING, "All"}:
        return DEFAULT_CASE_HEATMAP_SET_NAME
    return f"Cases by {metadata.label(grouping).split(' — ', 1)[0].strip()}"


def migrate_legacy_default_heatmap_set(
    heatmap_set: HeatmapSet,
    metadata: HeatmapMetadata,
) -> HeatmapSet:
    """Correct the untouched legacy default without changing custom views."""
    legacy_default = HeatmapSet(
        DEFAULT_HEATMAP_SET_NAME,
        HeatmapSettings(y_grouping=MM_GROUPING),
    )
    if metadata.fault_types_available or heatmap_set != legacy_default:
        return heatmap_set
    return HeatmapSet(
        default_heatmap_set_name(metadata),
        HeatmapSettings().normalized(metadata),
    )


@dataclass(frozen=True, slots=True)
class _TokenValue:
    key: str
    label: str
    value: str
    raw: str


def _split_case_name(case_name: str) -> list[str]:
    return [part.strip() for part in str(case_name).split("_") if part.strip()]


def _token_for_part(part: str, position: int) -> tuple[str, str]:
    match = re.match(r"^(?P<prefix>[A-Za-z]+)(?P<value>.*)$", part)
    if match:
        prefix = match.group("prefix")
        value = match.group("value") or part
        return prefix, value
    return f"Token {position + 1}", part


@lru_cache(maxsize=4096)
def case_name_tokens(case_name: str) -> tuple[_TokenValue, ...]:
    """Return positional case-name dimensions without attaching engineering meaning."""
    parts = _split_case_name(case_name)
    occurrence: dict[str, int] = {}
    values: list[_TokenValue] = []
    for position, part in enumerate(parts):
        prefix, value = _token_for_part(part, position)
        normalized_prefix = prefix.casefold()
        occurrence[normalized_prefix] = occurrence.get(normalized_prefix, 0) + 1
        key = prefix if occurrence[normalized_prefix] == 1 else f"{prefix}#{occurrence[normalized_prefix]}"
        label = prefix if occurrence[normalized_prefix] == 1 else f"{prefix} #{occurrence[normalized_prefix]}"
        values.append(_TokenValue(key, label, value, part))
    return tuple(values)


def _fault_value_for_case(
    case: str,
    fault_types: Mapping[Any, Any] | None,
) -> str:
    if not isinstance(fault_types, Mapping):
        return ""
    value = fault_types.get(case)
    if value is None:
        value = fault_types.get(case.casefold())
    if value is None:
        # Support the existing (Case, Run) metadata mapping without requiring a
        # second parser in the settings layer.
        values = [
            raw
            for key, raw in fault_types.items()
            if isinstance(key, tuple) and key and str(key[0]).casefold() == case.casefold()
        ]
        value = next((raw for raw in values if _clean_group(raw)), "")
    value = _clean_group(value)
    return "" if value.casefold() in {"nan", "none"} else value


def metadata_from_cases(
    case_names: Iterable[str],
    fault_types: Mapping[Any, Any] | None = None,
    fault_types_by_run: Mapping[Any, Any] | None = None,
) -> HeatmapMetadata:
    """Build grouping choices from observed case names and optional fault metadata."""
    names: list[str] = []
    seen: set[str] = set()
    for raw in case_names:
        name = _clean_group(raw)
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    token_rows = [case_name_tokens(name) for name in names]
    max_parts = max((len(row) for row in token_rows), default=0)
    dimensions: dict[str, list[str]] = {}
    raw_dimensions: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    # Positional prefixes are used to keep the same dimension key for every
    # case.  Duplicate prefixes receive the same #N suffix as case_name_tokens.
    key_by_position: dict[int, str] = {}
    for position in range(max_parts):
        observed = next((row[position] for row in token_rows if position < len(row)), None)
        if observed is None:
            continue
        key_by_position[position] = observed.key
        dimensions[observed.key] = []
        raw_dimensions[observed.key] = []
        labels[observed.key] = observed.label
    for row in token_rows:
        for position, token in enumerate(row):
            key = key_by_position.get(position, token.key)
            dimensions.setdefault(key, [])
            if token.value not in dimensions[key]:
                dimensions[key].append(token.value)
            raw_dimensions.setdefault(key, [])
            if token.raw not in raw_dimensions[key]:
                raw_dimensions[key].append(token.raw)
    varying = {
        key: tuple(values)
        for key, values in dimensions.items()
        if len({value.casefold() for value in values}) > 1
    }
    varying_labels = {}
    for key, values in varying.items():
        label = labels.get(key, key)
        display_values = [
            _group_display_value(key, value, raw_dimensions.get(key, ()))
            for value in values
        ]
        varying_labels[key] = f"{label} — {', '.join(display_values)}"
    fault_values = []
    for raw in (fault_types_by_run or {}).values():
        value = _clean_group(raw)
        if (
            value
            and value.casefold() not in {"nan", "none"}
            and value.casefold() not in {item.casefold() for item in fault_values}
        ):
            fault_values.append(value)
    for name in names:
        value = _fault_value_for_case(name, fault_types)
        if value and value.casefold() not in {item.casefold() for item in fault_values}:
            fault_values.append(value)
    return HeatmapMetadata(
        tuple(names),
        varying,
        varying_labels,
        tuple(fault_values),
        {key: tuple(values) for key, values in raw_dimensions.items()},
        tuple(key_by_position.get(position, f"Token {position + 1}") for position in range(max_parts)),
    )


@dataclass(frozen=True, slots=True)
class HeatmapCell:
    y_value: str
    case: str
    split_value: str | None
    eligible_count: int
    actual_count: int
    margin_count: int

    @property
    def actual_percent(self) -> float:
        return 100.0 * self.actual_count / self.eligible_count if self.eligible_count else 0.0

    @property
    def margin_percent(self) -> float:
        return 100.0 * self.margin_count / self.eligible_count if self.eligible_count else 0.0

    @property
    def margin_only_count(self) -> int:
        return max(0, self.margin_count - self.actual_count)

    @property
    def margin_only_percent(self) -> float:
        return 100.0 * self.margin_only_count / self.eligible_count if self.eligible_count else 0.0

    @property
    def has_eligible_data(self) -> bool:
        return self.eligible_count > 0


@dataclass(frozen=True, slots=True)
class HeatmapLayout:
    settings: HeatmapSettings
    metadata: HeatmapMetadata
    y_values: tuple[str, ...]
    cases: tuple[str, ...]
    split_values: tuple[str | None, ...]
    cells: dict[tuple[str, str, str | None], HeatmapCell]
    x_groups: dict[str, str]
    governing_keys: frozenset[tuple[str, str, str | None]]
    actual_scale_max: float = 0.0
    margin_scale_max: float = 0.0
    column_members: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def cell(self, y_value: str, case: str, split_value: str | None) -> HeatmapCell:
        return self.cells[(y_value, case, split_value)]


def _token_values(
    case: str,
    token_keys_by_position: Sequence[str] = (),
) -> dict[str, str]:
    return {
        token_keys_by_position[position] if position < len(token_keys_by_position) else token.key: token.value
        for position, token in enumerate(case_name_tokens(case))
    }


def _result_token_values(
    result: HeatmapItem | None,
    token_keys_by_position: Sequence[str] = (),
) -> dict[str, str]:
    if result is None:
        return {}
    return _token_values(result.case, token_keys_by_position)


def _case_token_values(
    case: str,
    token_keys_by_position: Sequence[str] = (),
) -> dict[str, str]:
    return _token_values(case, token_keys_by_position)


def _case_identity_without_token(
    case: str,
    token_key: str,
    token_keys_by_position: Sequence[str] = (),
) -> str:
    parts = _split_case_name(case)
    tokens = case_name_tokens(case)
    remaining = [
        part
        for position, (part, token) in enumerate(zip(parts, tokens))
        if (token_keys_by_position[position] if position < len(token_keys_by_position) else token.key)
        != token_key
    ]
    return "_".join(remaining) or case


def _case_columns(
    case_names: Sequence[str],
    y_grouping: str,
    token_keys_by_position: Sequence[str] = (),
) -> tuple[
    tuple[str, ...],
    dict[str, str],
    dict[str, str],
    dict[str, tuple[str, ...]],
]:
    """Build compact X columns for a non-fault Y token.

    A case-name Y token is represented by the row, so cases that differ only
    by that token share one column.  If removing the token would merge two
    cases with the same Y value, keep those cases separate.
    """
    unique_cases = list(dict.fromkeys(case_names))
    if y_grouping in {"", "All", NONE_GROUPING, FAULT_GROUPING, MM_GROUPING}:
        return (
            tuple(unique_cases),
            {case: case for case in unique_cases},
            {case: case for case in unique_cases},
            {case: (case,) for case in unique_cases},
        )

    grouped: dict[str, list[str]] = {}
    for case in unique_cases:
        grouped.setdefault(
            _case_identity_without_token(case, y_grouping, token_keys_by_position),
            [],
        ).append(case)

    columns: list[str] = []
    column_by_case: dict[str, str] = {}
    representative_by_column: dict[str, str] = {}
    members_by_column: dict[str, tuple[str, ...]] = {}
    for base, members in grouped.items():
        y_values = {
            _case_token_values(member, token_keys_by_position).get(y_grouping, UNKNOWN_GROUP).casefold()
            for member in members
        }
        if len(members) == 1 or len(y_values) == len(members):
            columns.append(base)
            representative_by_column[base] = members[0]
            members_by_column[base] = tuple(members)
            for member in members:
                column_by_case[member] = base
            continue

        # Keep ambiguous identities separate instead of silently merging
        # different cases after the Y token is removed.
        for member in members:
            column = member
            if column in representative_by_column:
                suffix = 2
                while f"{member} [{suffix}]" in representative_by_column:
                    suffix += 1
                column = f"{member} [{suffix}]"
            columns.append(column)
            column_by_case[member] = column
            representative_by_column[column] = member
            members_by_column[column] = (member,)
    return tuple(columns), column_by_case, representative_by_column, members_by_column


def _group_display_value(
    key: str,
    value: str,
    raw_values: Sequence[str] = (),
) -> str:
    prefix = key.split("#", 1)[0]
    normalized = _clean_group(value)
    if normalized.casefold() == UNKNOWN_GROUP.casefold():
        return UNKNOWN_GROUP
    for raw in raw_values:
        raw_text = _clean_group(raw)
        if raw_text.casefold() == normalized.casefold():
            return raw_text
        if (
            not prefix.casefold().startswith("token ")
            and raw_text.casefold() == f"{prefix}{normalized}".casefold()
        ):
            return raw_text
    if prefix.casefold().startswith("token ") or normalized.casefold().startswith(prefix.casefold()):
        return normalized
    return f"{prefix}{normalized}"


def display_group_value(
    key: str,
    value: str,
    raw_values: Sequence[str] = (),
) -> str:
    """Return the compact, unambiguous label used for a case-token value."""
    return _group_display_value(key, value, raw_values)


def _result_fault(result: HeatmapItem) -> str:
    value = _clean_group(result.fault_type)
    return UNKNOWN_GROUP if not value or value.casefold() in {"nan", "none"} else value


def _phase_flags(result: HeatmapItem) -> tuple[bool, bool]:
    if isinstance(result, HeatmapObservation):
        return result.actual, result.margin or result.actual
    phases = result.phases or (result.governing,)
    # The classifier owns the only qualification rule.  Do not recover a
    # finding from duration, a raw peak ratio, or a legacy classification:
    # those diagnostics can describe a short event that belongs to SFO/AFO.
    categories = [
        sustained_sdpf.candidate_category(phase)
        for phase in phases
    ]
    actual = any(category >= 2 for category in categories)
    margin = any(category >= 1 for category in categories)
    return actual, margin or actual


def compact_observations(
    results: Iterable[sustained_sdpf.SustainedSDPFResult],
) -> list[HeatmapObservation]:
    """Merge LGp/LLp result rows into one compact Run × MM observation."""
    merged: dict[tuple[str, int, str], HeatmapObservation] = {}
    for result in results:
        if not isinstance(result, sustained_sdpf.SustainedSDPFResult):
            continue
        observation = HeatmapObservation.from_result(result)
        key = (observation.case, observation.run, observation.mm_name)
        previous = merged.get(key)
        if previous is None:
            merged[key] = observation
            continue
        merged[key] = HeatmapObservation(
            case=previous.case,
            run=previous.run,
            mm_name=previous.mm_name,
            fault_type=previous.fault_type or observation.fault_type,
            actual=previous.actual or observation.actual,
            margin=previous.margin or observation.margin or previous.actual or observation.actual,
        )
    return list(merged.values())


def _ordered(values: Iterable[str], preferred: Sequence[str] = ()) -> tuple[str, ...]:
    preferred_keys = {value.casefold(): index for index, value in enumerate(preferred)}
    return tuple(sorted(set(values), key=lambda value: (preferred_keys.get(value.casefold(), 10**6), _natural_key(value))))


def build_heatmap_layout(
    results: Iterable[HeatmapItem],
    settings: HeatmapSettings | Mapping[str, Any] | None = None,
    metadata: HeatmapMetadata | None = None,
) -> HeatmapLayout:
    """Aggregate one persisted result per Run × MM into a display layout."""
    result_list = [
        result
        for result in results
        if isinstance(result, (sustained_sdpf.SustainedSDPFResult, HeatmapObservation))
    ]
    case_names = [result.case for result in result_list]
    metadata = metadata or metadata_from_cases(
        case_names,
        {
            (result.case, result.run): result.fault_type
            for result in result_list
            if result.fault_type
        },
    )
    parsed = settings if isinstance(settings, HeatmapSettings) else HeatmapSettings.from_mapping(settings)
    parsed = parsed.normalized(metadata)
    available_cases = list(metadata.case_names) or case_names
    cases_seen: list[str] = []
    for result in result_list:
        if result.case not in cases_seen:
            cases_seen.append(result.case)
    # Metadata can contain cases that have no eligible result rows after the
    # same exclusions/missing-data handling as Sustained SDPF.  Keep those
    # identities so their cells are visibly neutral rather than disappearing.
    full_case_order = list(available_cases)
    full_case_order.extend(case for case in cases_seen if case not in full_case_order)
    case_token_values = {
        case: _case_token_values(case, metadata.token_keys_by_position)
        for case in full_case_order
    }
    case_order, column_by_case, representative_by_column, column_members = _case_columns(
        full_case_order,
        parsed.y_grouping,
        metadata.token_keys_by_position,
    )
    if parsed.x_grouping:
        source_order = {case: index for index, case in enumerate(case_order)}
        group_values = {
            case: case_token_values.get(representative_by_column[case], {}).get(
                parsed.x_grouping,
                UNKNOWN_GROUP,
            )
            for case in case_order
        }
        case_order = sorted(case_order, key=lambda case: (_natural_key(group_values[case]), source_order[case]))
    x_groups = {
        case: (
            _group_display_value(
                parsed.x_grouping,
                case_token_values.get(representative_by_column[case], {}).get(
                    parsed.x_grouping,
                    UNKNOWN_GROUP,
                ),
                metadata.token_raw_values.get(parsed.x_grouping, ()),
            )
            if parsed.x_grouping else ""
        )
        for case in case_order
    }
    split_values: list[str | None]
    if parsed.split_by:
        values = list(metadata.token_values.get(parsed.split_by, ()))
        values.extend(
            case_token_values.get(result.case, {}).get(
                parsed.split_by,
                UNKNOWN_GROUP,
            )
            for result in result_list
        )
        split_values = list(_ordered(value for value in values if value))
        if not split_values:
            split_values = [UNKNOWN_GROUP]
    else:
        split_values = [None]

    if parsed.y_grouping in {"All", NONE_GROUPING}:
        y_values_source: list[str] = ["All"]
    elif parsed.y_grouping == FAULT_GROUPING:
        y_values_source = list(metadata.fault_types)
    elif parsed.y_grouping == MM_GROUPING:
        y_values_source = [result.mm_name for result in result_list if _clean_group(result.mm_name)]
    else:
        y_values_source = list(metadata.token_values.get(parsed.y_grouping, ()))
    for result in result_list:
        if parsed.y_grouping == FAULT_GROUPING:
            value = _result_fault(result)
        elif parsed.y_grouping == MM_GROUPING:
            value = _clean_group(result.mm_name) or UNKNOWN_GROUP
        elif parsed.y_grouping in {"All", NONE_GROUPING}:
            value = "All"
        else:
            value = case_token_values.get(result.case, {}).get(
                parsed.y_grouping,
                UNKNOWN_GROUP,
            )
        if value not in y_values_source:
            y_values_source.append(value)
    if not y_values_source:
        y_values_source = [UNKNOWN_GROUP]
    y_values = _ordered(y_values_source, metadata.token_values.get(parsed.y_grouping, ()))

    cells: dict[tuple[str, str, str | None], HeatmapCell] = {}
    observation_flags: dict[tuple[str, int, str, str | None], tuple[bool, bool, tuple[str, str, str | None]]] = {}
    counts: dict[tuple[str, str, str | None], list[int]] = {}
    for result in result_list:
        token_values = case_token_values.get(result.case, {})
        y_value = (
            _result_fault(result)
            if parsed.y_grouping == FAULT_GROUPING
            else _clean_group(result.mm_name) or UNKNOWN_GROUP
            if parsed.y_grouping == MM_GROUPING
            else "All" if parsed.y_grouping in {"All", NONE_GROUPING}
            else token_values.get(parsed.y_grouping, UNKNOWN_GROUP)
        )
        split_value = token_values.get(parsed.split_by, UNKNOWN_GROUP) if parsed.split_by else None
        observation_key = (result.case, int(result.run), result.mm_name, split_value)
        column = column_by_case.get(result.case, result.case)
        key = (y_value, column, split_value)
        actual, margin = _phase_flags(result)
        previous = observation_flags.get(observation_key)
        if previous is None:
            observation_flags[observation_key] = (actual, margin, key)
            values = counts.setdefault(key, [0, 0, 0])
            values[0] += 1
            values[1] += int(actual)
            values[2] += int(margin)
            continue
        previous_actual, previous_margin, previous_key = previous
        merged_actual = previous_actual or actual
        merged_margin = previous_margin or margin or merged_actual
        observation_flags[observation_key] = (merged_actual, merged_margin, previous_key)
        values = counts[previous_key]
        values[1] += int(merged_actual and not previous_actual)
        values[2] += int(merged_margin and not previous_margin)
    for y_value in y_values:
        for case in case_order:
            for split_value in split_values:
                eligible, actual, margin = counts.get((y_value, case, split_value), [0, 0, 0])
                cells[(y_value, case, split_value)] = HeatmapCell(
                    y_value, case, split_value, eligible, actual, margin
                )
    actual_max = max((cell.actual_count for cell in cells.values()), default=0)
    use_actual = actual_max > 0
    target = actual_max if use_actual else max((cell.margin_count for cell in cells.values()), default=0)
    governing = frozenset(
        key for key, cell in cells.items()
        if target > 0 and (cell.actual_count if use_actual else cell.margin_count) == target
    )
    actual_scale_max = max(
        (cell.actual_percent for cell in cells.values() if cell.actual_count > 0),
        default=0.0,
    )
    margin_scale_max = max(
        (cell.margin_only_percent for cell in cells.values() if cell.margin_only_count > 0),
        default=0.0,
    )
    return HeatmapLayout(
        parsed,
        metadata,
        tuple(y_values),
        tuple(case_order),
        tuple(split_values),
        cells,
        x_groups,
        governing,
        actual_scale_max,
        margin_scale_max,
        column_members,
    )


def aggregate_observations(
    results: Iterable[HeatmapItem],
    settings: HeatmapSettings | Mapping[str, Any] | None = None,
    metadata: HeatmapMetadata | None = None,
) -> HeatmapLayout:
    """Named aggregation entry point used by tests and report callers."""
    return build_heatmap_layout(results, settings, metadata)


def _layout_for_cases(layout: HeatmapLayout, cases: Sequence[str]) -> HeatmapLayout:
    selected = tuple(cases)
    selected_keys = tuple(
        (y_value, case, split_value)
        for y_value in layout.y_values
        for case in selected
        for split_value in layout.split_values
    )
    return HeatmapLayout(
        layout.settings,
        layout.metadata,
        layout.y_values,
        selected,
        layout.split_values,
        {key: layout.cells[key] for key in selected_keys},
        {case: layout.x_groups.get(case, "") for case in selected},
        frozenset(key for key in layout.governing_keys if key in selected_keys),
        layout.actual_scale_max,
        layout.margin_scale_max,
        {case: layout.column_members.get(case, (case,)) for case in selected},
    )


def format_incidence(count: int, eligible_count: int) -> str:
    if count <= 0 or eligible_count <= 0:
        return "0%"
    percentage = 100.0 * count / eligible_count
    if percentage < 1.0:
        return "<1%"
    if percentage < 10.0:
        return f"{percentage:.1f}%"
    return f"{percentage:.0f}%"


def cell_severity(cell: HeatmapCell) -> str:
    if not cell.has_eligible_data:
        return "none"
    if cell.actual_count > 0:
        return "actual"
    if cell.margin_count > 0:
        return "margin"
    return "clear"


@lru_cache(maxsize=1)
def _heatmap_colormaps():
    from matplotlib import colors

    return (
        colors.LinearSegmentedColormap.from_list(
            "sustained_sdpf_actual",
            HEATMAP_ACTUAL_COLORS,
        ),
        colors.LinearSegmentedColormap.from_list(
            "sustained_sdpf_margin",
            HEATMAP_MARGIN_COLORS,
        ),
    )


def _text_color_for_background(rgba) -> str:
    from matplotlib import colors

    red, green, blue = colors.to_rgb(rgba)
    channels = []
    for channel in (red, green, blue):
        channels.append(
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def contrast(reference: float) -> float:
        lighter, darker = sorted((reference, luminance), reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    return HEATMAP_TEXT_LIGHT if contrast(1.0) >= contrast(0.0) else HEATMAP_TEXT_DARK


def _severity_rgba(
    cell: HeatmapCell,
    actual_scale_max: float = 0.0,
    margin_scale_max: float = 0.0,
):
    from matplotlib import colors

    severity = cell_severity(cell)
    if severity == "none":
        return colors.to_rgba(HEATMAP_INELIGIBLE_COLOR)
    if severity == "clear":
        return colors.to_rgba(HEATMAP_CLEAR_COLOR)
    actual_cmap, margin_cmap = _heatmap_colormaps()
    if severity == "actual":
        scale = actual_scale_max if actual_scale_max > 0 else cell.actual_percent
        intensity = min(1.0, max(0.0, cell.actual_percent / scale)) if scale > 0 else 0.0
        return actual_cmap(intensity)
    scale = margin_scale_max if margin_scale_max > 0 else cell.margin_only_percent
    intensity = min(1.0, max(0.0, cell.margin_only_percent / scale)) if scale > 0 else 0.0
    return margin_cmap(intensity)


def heatmap_output_dir(project_root: str | Path, scope_folder: str) -> Path:
    return Path(project_root) / "Plots" / "Generated" / scope_folder / HEATMAP_EVENT


def _safe_filename(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    return text.strip("._") or "All"


def heatmap_set_folder_name(index: int, name: str) -> str:
    """Return the stable, readable folder name for one ordered heatmap set."""
    return f"{int(index) + 1:02d}_{_safe_filename(name)}"


def heatmap_set_output_dir(
    project_root: str | Path,
    scope_folder: str,
    index: int,
    name: str,
) -> Path:
    return heatmap_output_dir(project_root, scope_folder) / heatmap_set_folder_name(index, name)


def _clear_heatmap_images(output_dir: Path, voltage: str) -> None:
    if not output_dir.is_dir():
        return
    for image in output_dir.glob(f"MM_{_safe_filename(voltage)}_*_heatmap.png"):
        image.unlink(missing_ok=True)
    try:
        output_dir.rmdir()
    except OSError:
        pass


def clear_obsolete_heatmap_voltages(
    project_root: str | Path,
    scope_folder: str,
    active_voltages: Iterable[str],
) -> None:
    """Remove generated images for voltage levels absent from current results."""
    root = heatmap_output_dir(project_root, scope_folder)
    if not root.is_dir():
        return
    active = {_safe_filename(voltage) for voltage in active_voltages}
    directories = [root, *[child for child in root.iterdir() if child.is_dir()]]
    for directory in directories:
        for image in directory.glob("MM_*_heatmap.png"):
            name = image.name
            voltage_token = name[len("MM_") :].split("_", 1)[0]
            if voltage_token not in active:
                image.unlink(missing_ok=True)
        try:
            if directory != root:
                directory.rmdir()
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class _HeatmapPanelSpec:
    split_value: str | None
    cases: tuple[str, ...]
    part_index: int = 1
    part_count: int = 1


def _heatmap_panel_specs(layout: HeatmapLayout) -> tuple[_HeatmapPanelSpec, ...]:
    """Return the actual panels without inventing case identities.

    Splitting is applied only to the columns that belong to a real split value.
    The same specification drives both the legacy separate-file layout and the
    optional faceted layout, so the two presentation modes cannot disagree on
    which cases are represented.
    """
    specs: list[_HeatmapPanelSpec] = []
    chunk_size = max(1, int(layout.settings.max_cases_per_heatmap))
    for split_value in layout.split_values or (None,):
        split_cases = _columns_for_split(layout, split_value)
        chunks = [
            tuple(split_cases[index:index + chunk_size])
            for index in range(0, len(split_cases), chunk_size)
        ] or [()]
        part_count = len(chunks)
        specs.extend(
            _HeatmapPanelSpec(split_value, cases, index, part_count)
            for index, cases in enumerate(chunks, start=1)
        )
    return tuple(specs)


def _should_combine_panels(settings: HeatmapSettings, panel_count: int) -> bool:
    if panel_count <= 1:
        return False
    if settings.layout == HEATMAP_LAYOUT_COMBINED:
        return True
    if settings.layout == HEATMAP_LAYOUT_AUTO:
        # Automatic mode is deliberately conservative: a small number of
        # panels benefits from direct comparison, while a larger number is
        # easier to inspect as the existing one-panel-per-file output.
        return panel_count <= settings.max_panels_per_heatmap
    return False


def _panel_title(
    layout: HeatmapLayout,
    spec: _HeatmapPanelSpec,
    *,
    include_split: bool = True,
) -> str:
    if include_split and spec.split_value is not None:
        split_display = _group_display_value(
            layout.settings.split_by or "",
            spec.split_value,
            layout.metadata.token_raw_values.get(layout.settings.split_by or "", ()),
        )
        return f"Split: {split_display}"
    return ""


def _heatmap_cell_label(cell: HeatmapCell) -> str:
    """Return top/bottom SDPF and safety-margin incidence lines."""
    if not cell.has_eligible_data:
        return "—"
    actual = format_incidence(cell.actual_count, cell.eligible_count)
    margin = format_incidence(cell.margin_count, cell.eligible_count)
    return f"{actual}\n{margin}"


def _case_tick_label(case: str) -> str:
    """Keep the full case identity while wrapping it at predictable widths."""
    text = str(case)
    if len(text) <= 16:
        return text
    parts = [part for part in text.split("_") if part]
    if not parts:
        return text
    lines: list[str] = []
    current = ""
    for part in parts:
        # A long single token still needs a deterministic break; silently
        # truncating a case identity would make the plot ambiguous.
        if len(part) > 16:
            if current:
                lines.append(current)
                current = ""
            lines.extend(part[index:index + 16] for index in range(0, len(part), 16))
            continue
        candidate = part if not current else f"{current}_{part}"
        if current and len(candidate) > 16:
            lines.append(current)
            current = part
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines) or text


def _axis_tick_label(value: Any, *, max_chars: int = 18) -> str:
    """Wrap long Y-axis values without changing their displayed identity."""
    text = str(value)
    if len(text) <= max_chars:
        return text
    if "_" in text:
        return _case_tick_label(text)
    lines = textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(lines) <= 1:
        lines = [text[index:index + max_chars] for index in range(0, len(text), max_chars)]
    return "\n".join(lines)


def _case_token_parts(
    case: str,
    token_keys_by_position: Sequence[str] = (),
) -> tuple[tuple[str, str], ...]:
    parts = _split_case_name(case)
    tokens = case_name_tokens(case)
    return tuple(
        (
            token_keys_by_position[position]
            if position < len(token_keys_by_position)
            else token.key,
            part,
        )
        for position, (part, token) in enumerate(zip(parts, tokens))
    )


def _case_display_labels(
    layout: HeatmapLayout,
    cases: Sequence[str],
) -> tuple[str, ...]:
    """Return compact case labels using the visible grouping context.

    A token is removed only when it is represented by the selected Y/X/Split
    dimension or is constant across the rendered columns.  The full case
    identity remains in the persisted data and is used as a collision
    fallback when shortening would make two columns indistinguishable.  A
    collision is checked only within the same visible X-group and split
    context: equal labels in different X-groups are already unambiguous from
    the group band and must not cause the X-group token to reappear.
    """
    members_by_case = {
        case: layout.column_members.get(case, (case,))
        for case in cases
    }
    omitted: set[str] = set()
    for key in (
        layout.settings.y_grouping,
        layout.settings.x_grouping,
        layout.settings.split_by,
    ):
        if key and key not in {"All", NONE_GROUPING, FAULT_GROUPING, MM_GROUPING}:
            omitted.add(key)

    values_by_key: dict[str, set[str]] = {}
    for members in members_by_case.values():
        for member in members:
            for key, raw in _case_token_parts(
                member,
                layout.metadata.token_keys_by_position,
            ):
                values_by_key.setdefault(key, set()).add(raw.casefold())
    for key, values in values_by_key.items():
        if len(values) == 1:
            omitted.add(key)

    token_parts_by_case: list[tuple[tuple[str, str], ...]] = []
    representatives: list[str] = []
    for case in cases:
        representative = members_by_case[case][0]
        representatives.append(representative)
        token_parts_by_case.append(
            _case_token_parts(representative, layout.metadata.token_keys_by_position)
        )

    def render_label(index: int, extra_keys: set[str] = frozenset()) -> str:
        kept = [
            raw
            for key, raw in token_parts_by_case[index]
            if key not in omitted or key in extra_keys
        ]
        return _case_tick_label("_".join(kept) or representatives[index])

    labels = [render_label(index) for index in range(len(cases))]
    # X grouping and Split by are already shown in the group band/title.  Do
    # not use them as the first collision remedy: doing so made a label such
    # as ``<group-a>_...`` reappear merely because the same compact label
    # existed in the neighbouring ``<group-b>`` group.  The visible context scopes the
    # collision check below.
    visible_context = {
        key
        for key in (
            layout.settings.y_grouping,
            layout.settings.x_grouping,
            layout.settings.split_by,
        )
        if key and key not in {"All", NONE_GROUPING, FAULT_GROUPING, MM_GROUPING}
    }
    ordered_omitted = sorted(omitted.difference(visible_context))
    collisions: dict[tuple[tuple[str, ...], str], list[int]] = {}
    for index, label in enumerate(labels):
        context: list[str] = []
        if layout.settings.x_grouping:
            context.append(layout.x_groups.get(cases[index], UNKNOWN_GROUP).casefold())
        if layout.settings.split_by:
            context.append(
                _case_token_values(
                    representatives[index],
                    layout.metadata.token_keys_by_position,
                ).get(layout.settings.split_by, UNKNOWN_GROUP).casefold()
            )
        collisions.setdefault((tuple(context), label.casefold()), []).append(index)
    for indexes in collisions.values():
        if len(indexes) <= 1:
            continue
        extra_keys: set[str] = set()
        for key in ordered_omitted:
            values = {
                dict(token_parts_by_case[index]).get(key, "").casefold()
                for index in indexes
            }
            if len(values) <= 1:
                continue
            extra_keys.add(key)
            candidate = [render_label(index, extra_keys) for index in indexes]
            if len({label.casefold() for label in candidate}) == len(candidate):
                break
        candidate = [render_label(index, extra_keys) for index in indexes]
        if len({label.casefold() for label in candidate}) != len(candidate):
            candidate = [_case_tick_label(representatives[index]) for index in indexes]
        for index, label in zip(indexes, candidate):
            labels[index] = label
    return tuple(labels)


def _case_label_metrics(labels: Sequence[str]) -> tuple[int, int]:
    return (
        max((len(line) for label in labels for line in label.splitlines()), default=1),
        max((label.count("\n") + 1 for label in labels), default=1),
    )


def _case_label_rotation(labels: Sequence[str]) -> int:
    max_label_chars, max_label_lines = _case_label_metrics(labels)
    return 0 if len(labels) <= 8 and max_label_chars <= 14 and max_label_lines <= 2 else 35


def _draw_case_labels(label_ax, labels: Sequence[str]) -> None:
    """Draw case labels in a dedicated band below one heatmap panel."""
    n_cols = max(1, len(labels))
    max_label_chars, _ = _case_label_metrics(labels)
    rotation = _case_label_rotation(labels)
    label_ax.set_xlim(0, n_cols)
    label_ax.set_ylim(0, 1)
    label_ax.axis("off")
    for index, label in enumerate(labels):
        label_ax.text(
            index + 0.5,
            0.98,
            label,
            ha="center" if rotation == 0 else "right",
            va="top",
            rotation=rotation,
            rotation_mode="anchor",
            fontsize=7 if n_cols > 12 or max_label_chars > 16 else 8,
            linespacing=0.9,
            clip_on=False,
        )


def _case_label_band_height(labels: Sequence[str]) -> float:
    _, max_label_lines = _case_label_metrics(labels)
    rotation = _case_label_rotation(labels)
    # This is a physical figure height, not a GridSpec ratio.  Rotated labels
    # need a little more room, while short horizontal labels stay compact.
    if rotation:
        return 0.88 + 0.16 * max(0, max_label_lines - 1)
    return 0.52 + 0.16 * max(0, max_label_lines - 1)


def _case_cell_width(labels: Sequence[str]) -> float:
    """Return a readable fixed width for one case column in inches."""
    max_label_chars, _ = _case_label_metrics(labels)
    if max_label_chars <= 12:
        return 0.72
    if max_label_chars <= 16:
        return 0.86
    return 1.00


def _heatmap_matrix_height(row_count: int) -> float:
    """Return the physical matrix height used by every heatmap panel."""
    return max(
        HEATMAP_MATRIX_MIN_HEIGHT_IN,
        HEATMAP_ROW_HEIGHT_IN * max(1, row_count),
    )


def _stacked_band_axes(
    figure,
    bands: Sequence[tuple[str, float]],
    *,
    figure_width: float,
    figure_height: float,
    gap: float = HEATMAP_BAND_GAP_IN,
) -> dict[str, Any]:
    """Create named full-width axes at explicit inch positions.

    Entries whose name starts with ``__gap`` reserve whitespace but do not
    create an axes.  All visible content therefore has a dedicated band and
    cannot collide with another band's text.
    """
    left = HEATMAP_LEFT_MARGIN_IN / figure_width
    width = (
        figure_width - HEATMAP_LEFT_MARGIN_IN - HEATMAP_RIGHT_MARGIN_IN
    ) / figure_width
    top = figure_height - HEATMAP_TOP_MARGIN_IN
    axes: dict[str, Any] = {}
    for index, (name, height) in enumerate(bands):
        top -= height
        if not name.startswith("__gap") and height > 0:
            axes[name] = figure.add_axes(
                [
                    left,
                    top / figure_height,
                    width,
                    height / figure_height,
                ]
            )
        if index < len(bands) - 1:
            next_name = bands[index + 1][0]
            if not name.startswith("__gap") and not next_name.startswith("__gap"):
                top -= gap
    return axes


def _draw_figure_title(title_ax, title: str, *, fontsize: float) -> None:
    title_ax.set_axis_off()
    title_ax.text(
        0.5,
        0.48,
        title,
        transform=title_ax.transAxes,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight="bold",
        color=HEATMAP_TEXT_DARK,
    )


def _title_lines(title: str, figure_width: float) -> tuple[str, ...]:
    """Wrap long headers before they can run outside the fixed canvas."""
    content_width = max(
        1.0,
        figure_width - HEATMAP_LEFT_MARGIN_IN - HEATMAP_RIGHT_MARGIN_IN,
    )
    max_chars = max(42, int(content_width * 8.0))
    lines = list(
        textwrap.wrap(
            title,
            width=max_chars,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )
    if len(lines) > 1:
        lines[1:] = [line.lstrip("· ").strip() for line in lines[1:]]
    return tuple(lines) or (title,)


def _title_band_height(lines: Sequence[str]) -> float:
    """Reserve one fixed physical line height for every wrapped title line."""
    return max(
        HEATMAP_TITLE_BAND_IN,
        HEATMAP_TITLE_PADDING_IN + HEATMAP_TITLE_LINE_HEIGHT_IN * len(lines),
    )


def _draw_panel_header(header_ax, title: str) -> None:
    header_ax.set_axis_off()
    if title:
        header_ax.text(
            0.5,
            0.45,
            title,
            transform=header_ax.transAxes,
            ha="center",
            va="center",
            fontsize=10.5,
            fontweight="bold",
            color="#374151",
        )


def _x_group_ranges(layout: HeatmapLayout) -> tuple[tuple[str, int, int], ...]:
    """Return contiguous X-group ranges in the displayed column order."""
    if not layout.settings.x_grouping or not layout.cases:
        return ()
    ranges: list[tuple[str, int, int]] = []
    start = 0
    current = layout.x_groups.get(layout.cases[0], UNKNOWN_GROUP)
    for index, case in enumerate(layout.cases[1:], start=1):
        value = layout.x_groups.get(case, UNKNOWN_GROUP)
        if value != current:
            ranges.append((current, start, index))
            current, start = value, index
    ranges.append((current, start, len(layout.cases)))
    return tuple(ranges)


def _draw_x_group_band(group_ax, layout: HeatmapLayout) -> None:
    """Show only the selected X-group token above the matrix."""
    n_cols = max(1, len(layout.cases))
    group_ax.set_xlim(0, n_cols)
    group_ax.set_ylim(0, 1)
    group_ax.set_axis_off()
    ranges = _x_group_ranges(layout)
    if not ranges:
        return
    for value, start, end in ranges:
        group_display = _group_display_value(
            layout.settings.x_grouping or "",
            value,
            layout.metadata.token_raw_values.get(layout.settings.x_grouping or "", ()),
        )
        group_ax.text(
            (start + end) / 2,
            0.55,
            group_display,
            transform=group_ax.transData,
            ha="center",
            va="center",
            fontsize=10,
            fontweight="bold",
            color="#374151",
        )
        if start > 0:
            group_ax.plot(
                [start, start],
                [0.12, 0.88],
                color="#9ca3af",
                linewidth=0.8,
                clip_on=False,
            )
    group_ax.plot(
        [0, n_cols],
        [0.08, 0.08],
        color="#d1d5db",
        linewidth=0.8,
        clip_on=False,
    )


def _draw_heatmap_panel(
    ax,
    layout: HeatmapLayout,
    split_value: str | None,
    *,
    show_y_labels: bool = True,
    show_x_label: bool = True,
    show_x_labels: bool = True,
) -> None:
    """Draw the matrix only; surrounding text lives in dedicated bands."""
    from matplotlib.patches import Rectangle

    n_rows = max(1, len(layout.y_values))
    n_cols = max(1, len(layout.cases))
    case_labels = _case_display_labels(layout, layout.cases) if show_x_labels else ()
    max_label_chars = _case_label_metrics(case_labels)[0] if case_labels else 0
    ax.set_xlim(0, n_cols)
    ax.set_ylim(0, n_rows)
    ax.invert_yaxis()
    ax.set_xticks([index + 0.5 for index in range(n_cols)])
    if show_x_labels:
        rotation = _case_label_rotation(case_labels)
        ax.set_xticklabels(
            case_labels,
            rotation=rotation,
            ha="center" if rotation == 0 else "right",
            va="top",
            rotation_mode="anchor",
            fontsize=7 if n_cols > 12 or max_label_chars > 16 else 8,
        )
    else:
        ax.set_xticklabels([])
    ax.set_yticks([index + 0.5 for index in range(n_rows)])
    y_labels = [
        _axis_tick_label(
            _group_display_value(
                layout.settings.y_grouping,
                value,
                layout.metadata.token_raw_values.get(layout.settings.y_grouping, ()),
            )
            if layout.settings.y_grouping not in {"All", NONE_GROUPING, FAULT_GROUPING, MM_GROUPING}
            else value
        )
        for value in layout.y_values
    ]
    ax.set_yticklabels(
        y_labels if show_y_labels else [],
        fontsize=8,
        linespacing=0.9,
        rotation=0,
        ha="right",
        va="center",
    )
    ax.tick_params(length=0, axis="x", pad=5)
    ax.tick_params(length=0, axis="y", pad=5)
    for y_index, y_value in enumerate(layout.y_values):
        for x_index, case in enumerate(layout.cases):
            cell = layout.cell(y_value, case, split_value)
            cell_color = _severity_rgba(
                cell,
                layout.actual_scale_max,
                layout.margin_scale_max,
            )
            text_color = _text_color_for_background(cell_color)
            ax.add_patch(
                Rectangle(
                    (x_index, y_index), 1, 1,
                    facecolor=cell_color,
                    edgecolor="white",
                    linewidth=0.8,
                )
            )
            label = _heatmap_cell_label(cell)
            ax.text(
                x_index + 0.5,
                y_index + 0.5,
                label,
                ha="center",
                va="center",
                fontsize=7 if n_cols > 16 else 8,
                color=text_color,
                linespacing=0.9,
            )
            if (y_value, case, split_value) in layout.governing_keys:
                ax.add_patch(
                    Rectangle(
                        (x_index + 0.03, y_index + 0.03), 0.94, 0.94,
                        fill=False,
                        edgecolor=text_color,
                        linewidth=2.5,
                    )
                )
    if show_x_label:
        ax.set_xlabel("Cases", labelpad=4)
    ax.grid(False)


def _heatmap_legend_handles():
    from matplotlib.patches import Patch

    return [
        Patch(facecolor=HEATMAP_CLEAR_COLOR, edgecolor="none", label="No exceedance"),
        Patch(facecolor=HEATMAP_MARGIN_COLORS[2], edgecolor="none", label="Margin only"),
        Patch(facecolor=HEATMAP_ACTUAL_COLORS[2], edgecolor="none", label="SDPF exceedance"),
        Patch(facecolor=HEATMAP_INELIGIBLE_COLOR, edgecolor="none", label="No eligible data"),
    ]


def _add_heatmap_footer(footer_ax, *, columns: int = 2) -> None:
    footer_ax.set_axis_off()
    footer_ax.legend(
        handles=_heatmap_legend_handles(),
        loc="center",
        bbox_to_anchor=(0.5, 0.68),
        ncol=columns,
        fontsize=8.5,
        frameon=False,
        handlelength=1.25,
        handleheight=0.8,
        handletextpad=0.45,
        columnspacing=1.25,
        borderaxespad=0,
    )
    footer_ax.text(
        0.5,
        0.08,
        "Top: SDPF  ·  Bottom: SDPF/1.15 (including SDPF)  ·  —: no eligible data  ·  <1%: nonzero",
        transform=footer_ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=7.5,
        color="#4b5563",
    )


def _title_with_split(
    title: str,
    layout: HeatmapLayout,
    split_values: Sequence[str | None],
) -> str:
    values = [value for value in dict.fromkeys(split_values) if value is not None]
    if not layout.settings.split_by or not values:
        return title
    display_values = [
        _group_display_value(
            layout.settings.split_by,
            value,
            layout.metadata.token_raw_values.get(layout.settings.split_by, ()),
        )
        for value in values
    ]
    return f"{title} · Split: {', '.join(display_values)}"


def _heatmap_figure_width(labels: Sequence[str]) -> float:
    case_width = _case_cell_width(labels)
    n_cols = max(1, len(labels))
    return max(
        HEATMAP_MIN_FIG_WIDTH_IN,
        min(
            HEATMAP_MAX_FIG_WIDTH_IN,
            HEATMAP_LEFT_MARGIN_IN + HEATMAP_RIGHT_MARGIN_IN + case_width * n_cols,
        ),
    )


def _faceted_figure_width(panel_labels: Sequence[Sequence[str]]) -> float:
    """Use the widest real panel width for a vertical combined figure."""
    return max(
        (_heatmap_figure_width(labels) for labels in panel_labels),
        default=HEATMAP_MIN_FIG_WIDTH_IN,
    )


def _faceted_page_number_required(
    pages: Sequence[Sequence[_HeatmapPanelSpec]],
) -> bool:
    """Return whether pages are true continuations of the same split.

    A combined image for each distinct split value is self-identifying from
    its title.  A page number is useful only when one split (including an
    unsplit view) spans multiple files.
    """
    if len(pages) <= 1:
        return False
    pages_by_split: dict[str | None, set[int]] = {}
    for page_index, page in enumerate(pages):
        for split_value in {spec.split_value for spec in page}:
            pages_by_split.setdefault(split_value, set()).add(page_index)
    return any(len(page_indexes) > 1 for page_indexes in pages_by_split.values())


def _heatmap_figure_height(
    bands: Sequence[tuple[str, float]],
    *,
    gap: float,
) -> float:
    automatic_gaps = sum(
        1
        for index in range(len(bands) - 1)
        if not bands[index][0].startswith("__gap")
        and not bands[index + 1][0].startswith("__gap")
    )
    return (
        HEATMAP_TOP_MARGIN_IN
        + HEATMAP_BOTTOM_MARGIN_IN
        + sum(height for _, height in bands)
        + gap * automatic_gaps
    )


def _plot_layout(
    layout: HeatmapLayout,
    output_path: Path,
    title: str,
    split_value: str | None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    n_rows = max(1, len(layout.y_values))
    case_labels = _case_display_labels(layout, layout.cases)
    label_height = _case_label_band_height(case_labels)
    fig_width = _heatmap_figure_width(case_labels)
    title_lines = _title_lines(title, fig_width)
    title_band_height = _title_band_height(title_lines)
    bands: list[tuple[str, float]] = [("title", title_band_height)]
    if layout.settings.x_grouping:
        bands.append(("groups", HEATMAP_GROUP_BAND_IN))
    bands.extend(
        [
            ("matrix", _heatmap_matrix_height(n_rows)),
            ("labels", label_height),
            ("footer", HEATMAP_FOOTER_BAND_IN),
        ]
    )
    fig_height = _heatmap_figure_height(bands, gap=HEATMAP_BAND_GAP_IN)
    fig = plt.figure(figsize=(fig_width, fig_height), dpi=HEATMAP_RENDER_DPI, facecolor="white")
    axes = _stacked_band_axes(
        fig,
        bands,
        figure_width=fig_width,
        figure_height=fig_height,
    )
    _draw_figure_title(
        axes["title"],
        "\n".join(title_lines),
        fontsize=15 if len(title_lines) == 1 else 14,
    )
    if "groups" in axes:
        _draw_x_group_band(axes["groups"], layout)
    ax = axes["matrix"]
    label_ax = axes["labels"]
    footer_ax = axes["footer"]
    _draw_heatmap_panel(
        ax,
        layout,
        split_value,
        show_x_label=False,
        show_x_labels=False,
    )
    _draw_case_labels(label_ax, case_labels)
    _add_heatmap_footer(footer_ax, columns=4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=HEATMAP_RENDER_DPI, facecolor="white")
    plt.close(fig)
    return output_path


def _plot_faceted_layout(
    layout: HeatmapLayout,
    specs: Sequence[_HeatmapPanelSpec],
    output_path: Path,
    title: str,
    page_index: int,
    page_count: int,
    *,
    show_page_number: bool = True,
) -> Path:
    """Render several real split panels with one shared scale and legend."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    panel_count = max(1, len(specs))
    # Keep panels in one vertical column.  Each panel already contains a
    # potentially wide case axis; placing panels side by side makes the
    # combined figure unnecessarily wide and harder to read.
    panel_layouts = [
        _layout_for_cases(layout, spec.cases)
        for spec in specs
    ]
    panel_labels = [
        _case_display_labels(panel_layout, panel_layout.cases)
        for panel_layout in panel_layouts
    ]
    label_heights = [
        _case_label_band_height(labels)
        for labels in panel_labels
    ]
    panel_height = _heatmap_matrix_height(len(layout.y_values))
    fig_width = _faceted_figure_width(panel_labels)
    page_suffix = (
        f" · Page {page_index}/{page_count}"
        if show_page_number and page_count > 1
        else ""
    )
    figure_title = f"{title}{page_suffix}"
    page_split_values = {
        spec.split_value for spec in specs if spec.split_value is not None
    }
    include_panel_split = len(page_split_values) > 1
    title_lines = _title_lines(figure_title, fig_width)
    title_band_height = _title_band_height(title_lines)
    bands: list[tuple[str, float]] = [("title", title_band_height)]
    for panel_index in range(panel_count):
        if include_panel_split:
            bands.append((f"panel_header_{panel_index}", HEATMAP_PANEL_TITLE_BAND_IN))
        if layout.settings.x_grouping:
            bands.append((f"groups_{panel_index}", HEATMAP_GROUP_BAND_IN))
        bands.extend(
            [
                (f"matrix_{panel_index}", panel_height),
                (f"labels_{panel_index}", label_heights[panel_index]),
            ]
        )
        if panel_index < panel_count - 1:
            bands.append((f"__gap_{panel_index}", HEATMAP_PANEL_GAP_IN))
    bands.append(("footer", HEATMAP_FOOTER_BAND_IN))
    fig_height = _heatmap_figure_height(bands, gap=HEATMAP_BAND_GAP_IN)
    fig = plt.figure(figsize=(fig_width, fig_height), dpi=HEATMAP_RENDER_DPI, facecolor="white")
    band_axes = _stacked_band_axes(
        fig,
        bands,
        figure_width=fig_width,
        figure_height=fig_height,
    )
    _draw_figure_title(
        band_axes["title"],
        "\n".join(title_lines),
        fontsize=14 if len(title_lines) == 1 else 13,
    )
    for panel_index, spec in enumerate(specs):
        header_ax = band_axes.get(f"panel_header_{panel_index}")
        panel_title = _panel_title(
            layout,
            spec,
            include_split=include_panel_split,
        )
        if header_ax is not None:
            _draw_panel_header(header_ax, panel_title)
        group_ax = band_axes.get(f"groups_{panel_index}")
        if group_ax is not None:
            _draw_x_group_band(group_ax, panel_layouts[panel_index])
        ax = band_axes[f"matrix_{panel_index}"]
        _draw_heatmap_panel(
            ax,
            panel_layouts[panel_index],
            spec.split_value,
            show_y_labels=True,
            show_x_label=False,
            show_x_labels=False,
        )
        _draw_case_labels(band_axes[f"labels_{panel_index}"], panel_labels[panel_index])
    footer_ax = band_axes["footer"]
    _add_heatmap_footer(footer_ax, columns=4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=HEATMAP_RENDER_DPI, facecolor="white")
    plt.close(fig)
    return output_path


def clear_heatmaps(project_root: str | Path, scope_folder: str, voltage: str | None = None) -> None:
    path = heatmap_output_dir(project_root, scope_folder)
    if voltage is not None:
        _clear_heatmap_images(path, voltage)
        for child in list(path.iterdir()) if path.is_dir() else ():
            if child.is_dir():
                _clear_heatmap_images(child, voltage)
                try:
                    child.rmdir()
                except OSError:
                    pass
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def heatmap_paths_for_sets(
    project_root: str | Path,
    scope_folder: str,
    voltage: str,
    settings: Any,
) -> list[tuple[str, list[Path]]]:
    """Return rendered images grouped by the configured heatmap set."""
    root = heatmap_output_dir(project_root, scope_folder)
    sets = heatmap_sets_from_mapping(settings)
    output: list[tuple[str, list[Path]]] = []
    for index, heatmap_set in enumerate(sets):
        if not heatmap_set.settings.enabled:
            continue
        set_dir = heatmap_set_output_dir(project_root, scope_folder, index, heatmap_set.name)
        paths = sorted(set_dir.glob(f"MM_{_safe_filename(voltage)}_*_heatmap.png"))
        # Read legacy flat output while it is still present, so a report can be
        # rebuilt before the first multi-set render without losing the image.
        if not paths and index == 0:
            paths = sorted(root.glob(f"MM_{_safe_filename(voltage)}_*_heatmap.png"))
        if paths:
            output.append((heatmap_set.name, paths))
    return output


def _columns_for_split(layout: HeatmapLayout, split_value: str | None) -> list[str]:
    if split_value is None or not layout.settings.split_by:
        return list(layout.cases)
    split_key = layout.settings.split_by
    expected = split_value.casefold()
    return [
        column
        for column in layout.cases
        if any(
            _case_token_values(
                member,
                layout.metadata.token_keys_by_position,
            ).get(split_key, UNKNOWN_GROUP).casefold() == expected
            for member in layout.column_members.get(column, (column,))
        )
    ]


@dataclass(frozen=True, slots=True)
class _PreparedHeatmapData:
    """Validated, parsed heatmap source reused by all named views."""

    results: tuple[HeatmapItem, ...]
    metadata: HeatmapMetadata


def _heatmap_results_from_payload(
    payload: Mapping[str, Any],
    voltage_key: str,
) -> list[HeatmapItem]:
    observations_mapping = payload.get("observations")
    raw_results = (
        observations_mapping.get(voltage_key, [])
        if isinstance(observations_mapping, Mapping)
        else []
    )
    results: list[HeatmapItem] = []
    if isinstance(raw_results, list):
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                continue
            compact = HeatmapObservation.from_mapping(raw)
            if compact is not None:
                results.append(compact)
                continue
            try:
                results.append(sustained_sdpf.SustainedSDPFResult.from_dict(raw))
            except (TypeError, ValueError, KeyError):
                continue

    # Keep the governing result as a defensive fallback for a valid cache whose
    # compact observation list predates one selected run.  Avoid duplicating an
    # existing Run × MM cell.
    result_mapping = payload.get("results")
    governing_raw = result_mapping.get(voltage_key) if isinstance(result_mapping, Mapping) else None
    if isinstance(governing_raw, Mapping):
        try:
            governing_result = sustained_sdpf.SustainedSDPFResult.from_dict(governing_raw)
        except (TypeError, ValueError, KeyError):
            governing_result = None
        if governing_result is not None:
            governing_key = (
                governing_result.case,
                int(governing_result.run),
                governing_result.mm_name,
            )
            existing_keys = {
                (result.case, int(result.run), result.mm_name)
                for result in results
            }
            if governing_key not in existing_keys:
                results.append(governing_result)
    return results


def _prepare_heatmap_data(
    project_root: str | Path,
    scope_folder: str,
    voltage: str,
    sustained_settings: sustained_sdpf.SustainedSDPFSettings,
    *,
    metadata: HeatmapMetadata | None = None,
    payload: Mapping[str, Any] | None = None,
    shared_manifest_current: bool | None = None,
    log=None,
) -> _PreparedHeatmapData | None:
    saved_payload = (
        payload
        if isinstance(payload, Mapping)
        else sustained_sdpf.load_results(project_root, scope_folder)
    )
    voltage_key = sustained_sdpf.normalized_voltage_key(voltage)
    validation = sustained_sdpf.validate_result_cache(
        saved_payload,
        project_root,
        sustained_settings,
        shared_manifest_current=shared_manifest_current,
    )
    if not validation.valid:
        if log is not None:
            log(
                f"Sustained SDPF heatmap skipped for {scope_folder} / {voltage_key} kV: "
                f"{validation.reason}. Rebuild envelope data/checks first."
            )
        return None
    results = _heatmap_results_from_payload(saved_payload, voltage_key)
    if metadata is None:
        metadata = _metadata_from_payload(saved_payload, voltage_key)
    return _PreparedHeatmapData(tuple(results), metadata)


def generate_heatmaps(
    project_root: str | Path,
    scope_folder: str,
    voltage: str,
    settings: HeatmapSettings | Mapping[str, Any] | None,
    sustained_settings: sustained_sdpf.SustainedSDPFSettings,
    metadata: HeatmapMetadata | None = None,
    log=None,
    check_cancel=None,
    payload: Mapping[str, Any] | None = None,
    shared_manifest_current: bool | None = None,
    output_dir: str | Path | None = None,
    title_prefix: str | None = None,
    _prepared: _PreparedHeatmapData | None = None,
) -> list[Path]:
    """Render all split figures from one current, valid Sustained result payload."""
    parsed = settings if isinstance(settings, HeatmapSettings) else HeatmapSettings.from_mapping(settings)
    output_dir = Path(output_dir) if output_dir is not None else heatmap_output_dir(project_root, scope_folder)
    using_default_output = output_dir == heatmap_output_dir(project_root, scope_folder)

    def clear_current_output() -> None:
        if using_default_output:
            clear_heatmaps(project_root, scope_folder, voltage)
        else:
            _clear_heatmap_images(output_dir, voltage)

    if not sustained_settings.enabled or not parsed.enabled:
        if using_default_output:
            clear_heatmaps(project_root, scope_folder)
        else:
            shutil.rmtree(output_dir, ignore_errors=True)
        return []
    prepared = _prepared or _prepare_heatmap_data(
        project_root,
        scope_folder,
        voltage,
        sustained_settings,
        metadata=metadata,
        payload=payload,
        shared_manifest_current=shared_manifest_current,
        log=log,
    )
    if prepared is None:
        clear_current_output()
        return []
    results = list(prepared.results)
    metadata = prepared.metadata
    parsed = parsed.normalized(metadata)
    layout = build_heatmap_layout(results, parsed, metadata)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Keep the staging name short because PSCAD project roots can already be
    # deep, and Windows may reject an otherwise valid final PNG path.
    stage_dir = output_dir / f".h{uuid.uuid4().hex[:12]}"
    stage_dir.mkdir(parents=True, exist_ok=False)
    staged_paths: list[Path] = []
    panel_specs = _heatmap_panel_specs(layout)
    combine_panels = _should_combine_panels(layout.settings, len(panel_specs))
    # Project and scope are report context and belong in the figure caption,
    # not in the plot header.  Keep the voltage and optional named view so a
    # generated PNG remains useful when inspected on its own.
    title_parts = [f"{voltage} kV"]
    if title_prefix:
        title_parts.append(display_heatmap_set_name(title_prefix, parsed))
    title_parts.append("Sustained SDPF incidence")
    title = " · ".join(title_parts)
    try:
        if combine_panels:
            max_panels = max(1, layout.settings.max_panels_per_heatmap)
            pages = [
                panel_specs[index:index + max_panels]
                for index in range(0, len(panel_specs), max_panels)
            ] or [()]
            show_page_number = _faceted_page_number_required(pages)
            for page_index, page_specs in enumerate(pages, start=1):
                if check_cancel is not None:
                    check_cancel()
                filename = (
                    f"MM_{_safe_filename(voltage)}_faceted_{page_index:02d}_heatmap.png"
                )
                output_path = stage_dir / filename
                _plot_faceted_layout(
                    layout,
                    page_specs,
                    output_path,
                    _title_with_split(
                        title,
                        layout,
                        [spec.split_value for spec in page_specs],
                    ),
                    page_index,
                    len(pages),
                    show_page_number=show_page_number,
                )
                staged_paths.append(output_path)
        else:
            for spec in panel_specs:
                if check_cancel is not None:
                    check_cancel()
                part_layout = _layout_for_cases(layout, spec.cases)
                suffix = _safe_filename(spec.split_value or "All")
                part_suffix = f"_{spec.part_index:02d}" if spec.part_count > 1 else ""
                filename = f"MM_{_safe_filename(voltage)}_{suffix}{part_suffix}_heatmap.png"
                output_path = stage_dir / filename
                panel_title = _title_with_split(title, layout, [spec.split_value])
                _plot_layout(part_layout, output_path, panel_title, spec.split_value)
                staged_paths.append(output_path)

        if check_cancel is not None:
            check_cancel()
        old_images = list(output_dir.glob(f"MM_{_safe_filename(voltage)}_*_heatmap.png"))
        backup_dir = output_dir.parent / f".{output_dir.name}.backup-{uuid.uuid4().hex[:12]}"
        moved_old: list[Path] = []
        moved_new: list[Path] = []
        backup_dir.mkdir(parents=True, exist_ok=False)
        paths: list[Path] = []
        try:
            for old in old_images:
                backup_path = backup_dir / old.name
                old.replace(backup_path)
                moved_old.append(backup_path)
            for staged in staged_paths:
                final_path = output_dir / staged.name
                staged.replace(final_path)
                moved_new.append(final_path)
                paths.append(final_path)
                if log is not None:
                    log(f"Sustained SDPF heatmap saved: {final_path}")
        except Exception:
            for final_path in moved_new:
                final_path.unlink(missing_ok=True)
            for backup_path in moved_old:
                backup_path.replace(output_dir / backup_path.name)
            raise
        finally:
            shutil.rmtree(backup_dir, ignore_errors=True)
        stage_dir.rmdir()
        return paths
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def _metadata_from_payload(
    payload: Mapping[str, Any],
    voltage: str,
) -> HeatmapMetadata:
    """Build grouping metadata once from the compact saved observations."""
    voltage_key = sustained_sdpf.normalized_voltage_key(voltage)
    observations = payload.get("observations", {})
    raw_observations = (
        observations.get(voltage_key, [])
        if isinstance(observations, Mapping)
        else []
    )
    case_names: list[str] = []
    fault_types: dict[tuple[str, int], str] = {}
    if isinstance(raw_observations, list):
        for raw in raw_observations:
            if not isinstance(raw, Mapping):
                continue
            case = _clean_group(raw.get("case"))
            if not case:
                continue
            case_names.append(case)
            try:
                run = int(float(raw.get("run", 0)))
            except (TypeError, ValueError):
                run = 0
            fault = _clean_group(raw.get("fault_type"))
            if fault:
                fault_types[(case, run)] = fault
    signature_inputs = payload.get("signature_inputs", {})
    voltage_inputs = (
        signature_inputs.get(voltage_key, {})
        if isinstance(signature_inputs, Mapping)
        else {}
    )
    persisted_cases = (
        voltage_inputs.get("heatmap_case_names", [])
        if isinstance(voltage_inputs, Mapping)
        else []
    )
    names = (
        persisted_cases
        if isinstance(persisted_cases, list) and persisted_cases
        else case_names
    )
    return metadata_from_cases(names, fault_types)


def generate_heatmap_sets(
    project_root: str | Path,
    scope_folder: str,
    voltage: str,
    settings: Any,
    sustained_settings: sustained_sdpf.SustainedSDPFSettings,
    metadata: HeatmapMetadata | None = None,
    log=None,
    check_cancel=None,
    payload: Mapping[str, Any] | None = None,
    shared_manifest_current: bool | None = None,
) -> list[tuple[str, list[Path]]]:
    """Render every enabled named set into its own ordered output folder."""
    saved_payload = (
        payload
        if isinstance(payload, Mapping)
        else sustained_sdpf.load_results(project_root, scope_folder)
    )
    if metadata is None:
        metadata = _metadata_from_payload(saved_payload, str(voltage))
    heatmap_sets = tuple(
        heatmap_set.normalized(metadata)
        for heatmap_set in heatmap_sets_from_mapping(settings)
    )
    root = heatmap_output_dir(project_root, scope_folder)
    if not sustained_settings.enabled or not any(
        heatmap_set.settings.enabled for heatmap_set in heatmap_sets
    ):
        clear_heatmaps(project_root, scope_folder)
        return []

    root.mkdir(parents=True, exist_ok=True)
    prepared = _prepare_heatmap_data(
        project_root,
        scope_folder,
        voltage,
        sustained_settings,
        metadata=metadata,
        payload=saved_payload,
        shared_manifest_current=shared_manifest_current,
        log=log,
    )
    if prepared is None:
        clear_heatmaps(project_root, scope_folder, voltage)
        return []
    metadata = prepared.metadata
    active_sets = tuple(
        (index, heatmap_set)
        for index, heatmap_set in enumerate(heatmap_sets)
        if heatmap_set.settings.enabled
    )
    expected_dirs = {
        heatmap_set_folder_name(index, heatmap_set.name)
        for index, heatmap_set in active_sets
    }
    obsolete_children = [
        child
        for child in root.iterdir()
        if child.is_dir() and child.name not in expected_dirs
    ]
    legacy_flat_images = [
        child
        for child in root.iterdir()
        if child.is_file() and child.name.endswith("_heatmap.png")
    ]

    groups: list[tuple[str, list[Path]]] = []
    for index, heatmap_set in active_sets:
        if check_cancel is not None:
            check_cancel()
        set_dir = heatmap_set_output_dir(project_root, scope_folder, index, heatmap_set.name)
        paths = generate_heatmaps(
            project_root,
            scope_folder,
            voltage,
            heatmap_set.settings,
            sustained_settings,
            metadata=metadata,
            log=log,
            check_cancel=check_cancel,
            payload=saved_payload,
            shared_manifest_current=shared_manifest_current,
            output_dir=set_dir,
            title_prefix=display_heatmap_set_name(
                heatmap_set.name,
                heatmap_set.settings,
            ),
            _prepared=prepared,
        )
        if paths:
            groups.append((heatmap_set.name, paths))
    # Remove renamed/deleted/disabled set folders and legacy flat images only
    # after all current sets have rendered successfully. A cancelled or failed
    # rebuild therefore leaves the last complete output available.
    for child in obsolete_children:
        shutil.rmtree(child, ignore_errors=True)
    for image in legacy_flat_images:
        image.unlink(missing_ok=True)
    return groups


__all__ = [
    "DEFAULT_CASE_HEATMAP_SET_NAME",
    "DEFAULT_HEATMAP_MAX_PANELS",
    "DEFAULT_HEATMAP_SET_NAME",
    "FAULT_GROUPING",
    "HEATMAP_EVENT",
    "HEATMAP_LAYOUT_AUTO",
    "HEATMAP_LAYOUT_COMBINED",
    "HEATMAP_LAYOUT_SEPARATE",
    "MM_GROUPING",
    "HeatmapCell",
    "HeatmapLayout",
    "HeatmapMetadata",
    "HeatmapObservation",
    "HeatmapSet",
    "HeatmapSettings",
    "aggregate_observations",
    "build_heatmap_layout",
    "case_name_tokens",
    "cell_severity",
    "clear_heatmaps",
    "clear_obsolete_heatmap_voltages",
    "compact_observations",
    "default_heatmap_set_name",
    "display_heatmap_set_name",
    "display_group_value",
    "format_incidence",
    "generate_heatmap_sets",
    "generate_heatmaps",
    "heatmap_output_dir",
    "heatmap_paths_for_sets",
    "heatmap_set_folder_name",
    "heatmap_set_output_dir",
    "heatmap_sets_from_mapping",
    "heatmap_sets_to_mapping",
    "metadata_from_cases",
    "migrate_legacy_default_heatmap_set",
]
