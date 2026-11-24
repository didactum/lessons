# Vendored from github.com/didactum (source: app/utils/math_regex.py) by scripts/vendor_lesson_validator.py. Do not edit.
"""Canonical mathematical and numerical extraction regex utilities.

Single source of truth for sign-aware and decimal lookbehind extraction across Didactum.
Prevents split numbers in negative values, decimals, and fractional notation.
"""
from __future__ import annotations

import math as _math
import re
from typing import Any, List, Optional, Tuple

# Sign-aware lookbehind decimal regex (prevents splitting dotted decimals like 3.14.15 or negative numbers)
_NUMRE = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?")
_FRACTION = re.compile(r"(-?\d+)\s*/\s*(\d+)")
_TOKEN_RE = re.compile(r"-?\d+(?:,\d{3})+(?:\.\d+)?|-?\d*\.\d+|-?\d+\s*/\s*-?\d+|-?\d+")
_DIGITS = re.compile(r"^\d{1,12}$")
_BASETEN = re.compile(r"^\d{1,3}$")


def extract_numbers(text: str) -> List[float]:
    """Extract all valid finite float numbers from a text string with sign and decimal awareness."""
    results = []
    for m in _NUMRE.findall(text or ""):
        try:
            val = float(m)
            if _math.isfinite(val):
                results.append(val)
        except (ValueError, TypeError):
            continue
    return results


def extract_tokens(text: str) -> List[str]:
    """Extract canonical numeric and fractional tokens from text."""
    return _TOKEN_RE.findall(text or "")


def is_valid_number(v: Any, lo: float = -1e9, hi: float = 1e9) -> bool:
    """Check if value is a finite number within bounds [lo, hi]."""
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and _math.isfinite(v)
        and lo <= v <= hi
    )


def parse_fraction(val: str) -> Optional[float]:
    """Parse a fraction string (e.g. '3/4' or '-1/2' or '5') into a float."""
    if not val:
        return None
    val = str(val).strip()
    m = _FRACTION.match(val)
    if m:
        try:
            num = float(m.group(1))
            den = float(m.group(2))
            if den != 0:
                return num / den
        except (ValueError, ZeroDivisionError):
            return None
    try:
        f = float(val)
        return f if _math.isfinite(f) else None
    except ValueError:
        return None


def numbers_match(a: float, b: float, tol: float = 1e-5) -> bool:
    """Check if two floats match within a standard numerical tolerance."""
    try:
        return abs(float(a) - float(b)) <= tol
    except (ValueError, TypeError):
        return False

