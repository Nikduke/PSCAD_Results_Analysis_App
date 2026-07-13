from __future__ import annotations

UNIT_LABELS = {
    "kv": ("Voltage", "kV"),
    "v": ("Voltage", "V"),
    "ka": ("Current", "kA"),
    "a": ("Current", "A"),
    "mj": ("Energy", "MJ"),
    "kj": ("Energy", "kJ"),
    "j": ("Energy", "J"),
    "mw": ("Active Power", "MW"),
    "kw": ("Active Power", "kW"),
    "w": ("Active Power", "W"),
    "mvar": ("Reactive Power", "MVAr"),
    "kvar": ("Reactive Power", "kVAr"),
    "var": ("Reactive Power", "VAr"),
    "mva": ("Apparent Power", "MVA"),
    "kva": ("Apparent Power", "kVA"),
    "va": ("Apparent Power", "VA"),
    "hz": ("Frequency", "Hz"),
    "deg": ("Angle", "deg"),
    "pu": ("Per Unit", "pu"),
    "s": ("Time", "s"),
    "ms": ("Time", "ms"),
}


def unit_suffix(unit: str) -> str:
    normalized = unit.strip()
    if not normalized:
        return ""
    return UNIT_LABELS.get(normalized.lower(), ("", normalized))[1]


def unit_axis_label(unit: str) -> str:
    normalized = unit.strip()
    if not normalized:
        return "Value"
    mapped = UNIT_LABELS.get(normalized.lower())
    if mapped is None:
        return f"[{normalized}]"
    quantity, suffix = mapped
    return f"{quantity} [{suffix}]"
