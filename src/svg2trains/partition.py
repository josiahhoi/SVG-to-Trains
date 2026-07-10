"""Partition the hull into per-color solids.

Two modes:

- side (default): each side-view color region is extruded through the full
  width and intersected with the hull. The side view's regions tile its
  silhouette (paint-order resolution), so the parts exactly partition the
  hull. This matches the user's proven manual workflow of full-width slabs.

- projection: each exterior surface takes the color of the view that faces
  it. Every point of the hull lies inside every view's full prism (the hull
  is their intersection), so prisms alone cannot decide ownership; instead a
  "directional crust" — hull minus hull shifted by the shell depth along a
  face direction — isolates the material within that depth of each facing
  surface with a single boolean. Crusts are claimed in view-priority order
  and colored by that view's regions; whatever no crust claims becomes the
  core.
"""

from __future__ import annotations

from dataclasses import dataclass

import manifold3d as m3

from .hull import PAD, HullError, view_prism

DEFAULT_SHELL_DEPTH = 1.2  # mm
DEFAULT_PRIORITY = ("side", "top", "front", "back")
MIN_PART_VOLUME = 1.0  # mm^3


@dataclass
class ColorPart:
    color: str
    solid: m3.Manifold
    provenance: str  # e.g. "side", "projection:top", "core"

    @property
    def volume(self) -> float:
        return self.solid.volume()


def _merge_by_color(pieces: list[ColorPart]) -> list[ColorPart]:
    by_color: dict[str, list[ColorPart]] = {}
    for piece in pieces:
        by_color.setdefault(piece.color, []).append(piece)
    merged = []
    for color, group in by_color.items():
        solid = (
            group[0].solid
            if len(group) == 1
            else m3.Manifold.batch_boolean([g.solid for g in group], m3.OpType.Add)
        )
        provenance = "+".join(dict.fromkeys(g.provenance for g in group))
        merged.append(ColorPart(color=color, solid=solid, provenance=provenance))
    return merged


def _absorb_slivers(parts: list[ColorPart], min_volume: float) -> list[ColorPart]:
    """Union sub-threshold parts into the largest part (never drop material)."""
    if len(parts) <= 1:
        return parts
    keep = [p for p in parts if p.volume >= min_volume]
    slivers = [p for p in parts if p.volume < min_volume]
    if not slivers:
        return parts
    if not keep:
        return [_merge_by_color(slivers)[0]] if slivers else []
    host = max(range(len(keep)), key=lambda i: keep[i].volume)
    merged_solid = m3.Manifold.batch_boolean(
        [keep[host].solid] + [s.solid for s in slivers], m3.OpType.Add
    )
    keep[host] = ColorPart(
        color=keep[host].color, solid=merged_solid, provenance=keep[host].provenance
    )
    return keep


def partition_side(
    hull: m3.Manifold,
    side_regions: dict[str, object],
    dims: tuple[float, float, float],
    pad: float = PAD,
    min_part_volume: float = MIN_PART_VOLUME,
) -> list[ColorPart]:
    """Full-width color slabs from the side view's paint-order regions."""
    pieces: list[ColorPart] = []
    for color, geom in side_regions.items():
        prism = view_prism("side", geom, dims, pad)
        if prism is None:
            continue
        solid = prism ^ hull
        if not solid.is_empty() and solid.volume() > 0:
            pieces.append(ColorPart(color=color, solid=solid, provenance="side"))
    if not pieces:
        raise HullError("No side-view color region intersects the hull.")
    return _absorb_slivers(_merge_by_color(pieces), min_part_volume)


_CRUST_SHIFTS = {
    # view -> list of translation vectors whose difference isolates material
    # within `depth` of a surface facing that view
    "top": [(0.0, 0.0, -1.0)],
    "side": [(0.0, -1.0, 0.0), (0.0, 1.0, 0.0)],  # both left and right faces
    "front": [(1.0, 0.0, 0.0)],
    "back": [(-1.0, 0.0, 0.0)],
}


def directional_crust(hull: m3.Manifold, view: str, depth: float) -> m3.Manifold:
    """Material within `depth` (along the view axis) of a surface facing it."""
    crusts = []
    for direction in _CRUST_SHIFTS[view]:
        shift = tuple(c * depth for c in direction)
        crusts.append(hull - hull.translate(shift))
    return crusts[0] if len(crusts) == 1 else m3.Manifold.batch_boolean(crusts, m3.OpType.Add)


def dominant_color(view_regions: dict[str, dict[str, object]]) -> str:
    """Color with the largest total flat-region area across all views."""
    areas: dict[str, float] = {}
    for regions in view_regions.values():
        for color, geom in regions.items():
            areas[color] = areas.get(color, 0.0) + geom.area
    if not areas:
        raise HullError("No colored regions found in any view.")
    return max(sorted(areas), key=lambda c: areas[c])


def partition_projection(
    hull: m3.Manifold,
    view_regions: dict[str, dict[str, object]],
    dims: tuple[float, float, float],
    shell_depth: float = DEFAULT_SHELL_DEPTH,
    core_color: str | None = None,
    priority: tuple[str, ...] = DEFAULT_PRIORITY,
    pad: float = PAD,
    min_part_volume: float = MIN_PART_VOLUME,
) -> list[ColorPart]:
    """Directional-crust projection: each face shows its facing view's color."""
    if core_color is None:
        core_color = dominant_color(view_regions)

    pieces: list[ColorPart] = []
    claimed: m3.Manifold | None = None
    for view in priority:
        regions = view_regions.get(view)
        if not regions:
            continue
        crust = directional_crust(hull, view, shell_depth)
        band = crust if claimed is None else crust - claimed
        for color, geom in regions.items():
            prism = view_prism(view, geom, dims, pad)
            if prism is None:
                continue
            piece = band ^ prism
            if not piece.is_empty() and piece.volume() > 0:
                pieces.append(
                    ColorPart(color=color, solid=piece, provenance=f"projection:{view}")
                )
        claimed = crust if claimed is None else claimed + crust

    # the core is whatever no colored piece claimed (crust bands can be
    # partially uncolored where a view is shorter than the train)
    if pieces:
        core = hull - m3.Manifold.batch_boolean(
            [p.solid for p in pieces], m3.OpType.Add
        )
    else:
        core = hull
    if not core.is_empty() and core.volume() > 0:
        pieces.append(ColorPart(color=core_color, solid=core, provenance="core"))
    if not pieces:
        raise HullError("Color projection produced no parts.")
    return _absorb_slivers(_merge_by_color(pieces), min_part_volume)
