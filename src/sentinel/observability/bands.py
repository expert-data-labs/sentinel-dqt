"""The expected range a threshold strategy applied, read back from its stored details.

Used to draw the "acceptable band" behind a metric trend. Pure: no I/O.
"""

from __future__ import annotations

import json
from typing import Any

Bound = float | None


def _number(value: Any) -> Bound:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def expected_range(threshold_details: str | None) -> tuple[Bound, Bound]:
    """(lower, upper) the value had to stay within; either side may be None (unbounded).

    - statistical, median_mad, seasonal: their stored ``lower``/``upper``
    - static: ``min``/``max``
    - percentage_deviation: ``baseline +/- |baseline| * max_deviation``

    Returns (None, None) when there are no details or the shape is unknown.
    """
    if not threshold_details:
        return None, None
    details: dict[str, Any] = json.loads(threshold_details)

    if "lower" in details or "upper" in details:
        return _number(details.get("lower")), _number(details.get("upper"))
    if details.get("method") == "static" or "min" in details or "max" in details:
        return _number(details.get("min")), _number(details.get("max"))
    baseline, tolerance = _number(details.get("baseline")), _number(details.get("max_deviation"))
    if baseline is not None and tolerance is not None:
        margin = abs(baseline) * tolerance
        return baseline - margin, baseline + margin
    return None, None
