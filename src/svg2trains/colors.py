"""Color normalization, merging, and filament-slot assignment."""

from __future__ import annotations

MAX_FILAMENTS = 16
AMS_SLOTS = 4


class ColorError(ValueError):
    pass


def normalize(color) -> str | None:
    """Normalize an svgelements Color (or CSS string) to '#rrggbb'.

    Returns None for absent/none/fully-transparent colors. Partial alpha is
    treated as opaque (we print solid plastic).
    """
    if color is None:
        return None
    from svgelements import Color

    if not isinstance(color, Color):
        try:
            color = Color(color)
        except ValueError:
            return None
    if color.value is None:
        return None
    if color.alpha == 0:
        return None
    return f"#{color.red:02x}{color.green:02x}{color.blue:02x}"


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    return int(hexcolor[1:3], 16), int(hexcolor[3:5], 16), int(hexcolor[5:7], 16)


def distance(a: str, b: str) -> int:
    """Max channel distance between two '#rrggbb' colors."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return max(abs(ra - rb), abs(ga - gb), abs(ba - bb))


def merge_colors(colors: list[str], threshold: int) -> dict[str, str]:
    """Map each color to a canonical representative.

    Colors within `threshold` max-channel distance of an earlier color are
    merged into it (first occurrence wins, deterministic).
    """
    mapping: dict[str, str] = {}
    canonical: list[str] = []
    for c in colors:
        if c in mapping:
            continue
        target = c
        if threshold > 0:
            for rep in canonical:
                if distance(c, rep) <= threshold:
                    target = rep
                    break
        mapping[c] = target
        if target == c:
            canonical.append(c)
    return mapping


def assign_slots(colors: list[str]) -> dict[str, int]:
    """Deterministic color -> 1-based filament slot, by first appearance.

    Raises ColorError above MAX_FILAMENTS. Returns the mapping; the caller is
    responsible for warning when more than one AMS unit (4 slots) is needed.
    """
    slots: dict[str, int] = {}
    for c in colors:
        if c not in slots:
            slots[c] = len(slots) + 1
    if len(slots) > MAX_FILAMENTS:
        raise ColorError(
            f"{len(slots)} distinct colors found, but Bambu Studio supports at "
            f"most {MAX_FILAMENTS} filaments. Use --merge-colors to reduce them."
        )
    return slots
