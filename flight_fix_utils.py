from __future__ import annotations

from typing import Any


def fix_timestamp(fix: Any) -> float | None:
    value = getattr(fix, "timestamp", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        timestamp_fn = getattr(value, "timestamp", None)
        if callable(timestamp_fn):
            try:
                return float(timestamp_fn())
            except Exception:
                return None
        return None


def build_time_offsets(fixes: list[Any]) -> list[float]:
    if not fixes:
        return []

    first_timestamp = fix_timestamp(fixes[0])
    if first_timestamp is None:
        return [float(i) for i in range(len(fixes))]

    offsets: list[float] = []
    previous = 0.0
    for idx, fix in enumerate(fixes):
        timestamp = fix_timestamp(fix)
        if timestamp is None:
            offsets.append(float(idx))
            previous = offsets[-1]
            continue

        try:
            delta = float(timestamp - first_timestamp)
        except Exception:
            delta = float(idx)

        if delta < previous:
            delta = previous
        offsets.append(float(delta))
        previous = float(delta)

    if offsets and offsets[-1] <= 0.0:
        return [float(i) for i in range(len(fixes))]
    return offsets


def fix_altitude(fix: Any) -> float | None:
    for attr in ("alt", "gnss_alt", "press_alt"):
        value = getattr(fix, attr, None)
        if _value_present(value):
            return float(value)
    if isinstance(fix, dict):
        for key in ("alt", "gnss_alt", "press_alt"):
            value = fix.get(key)
            if _value_present(value):
                return float(value)
    return None


def has_any_altitude(fixes: list[Any]) -> bool:
    for fix in fixes:
        if fix_altitude(fix) is not None:
            return True
    return False


def _value_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
