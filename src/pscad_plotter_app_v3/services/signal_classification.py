from __future__ import annotations

import re


def is_any_rms_signal(group_name: str, signal_name: str) -> bool:
    """Return True for Any-channel RMS signals that support min/max annotation."""
    group = (group_name or "").upper()
    base_signal = _strip_phase_suffix(signal_name).lower()
    if "MM_" in group:
        return base_signal in {"lgr", "llr"} or base_signal.endswith(("_lgr", "_llr"))
    if "CB_" in group:
        return base_signal in {"iir", "llr"} or base_signal.endswith(("_iir", "_llr"))
    return False


def _strip_phase_suffix(signal_name: str) -> str:
    signal = (signal_name or "").strip()
    match = re.match(r"^(?P<base>.+?)(?::[123]|_[abcABC])$", signal)
    if match:
        return match.group("base")
    return signal
