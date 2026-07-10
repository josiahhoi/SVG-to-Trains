"""Visual hull: extrude per-view silhouettes into prisms and intersect them.

View-plane 2D mm coordinates (from register.py) map into the world frame as:
- top:   (u, v) = (X, Y), prism extruded through Z
- side:  (u, v) = (X, Z), prism extruded through Y
- front: (u, v) = (Y, Z), prism extruded through X (same for back)

Prisms are padded beyond the model extents so their caps never form hull
boundary faces.
"""

from __future__ import annotations

import manifold3d as m3
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

PAD = 2.0  # mm


class HullError(ValueError):
    pass


def cross_section(geom) -> m3.CrossSection | None:
    """Convert a shapely (Multi)Polygon to a manifold3d CrossSection."""
    if geom is None or geom.is_empty:
        return None
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    rings: list[np.ndarray] = []
    for poly in polys:
        if not isinstance(poly, Polygon) or poly.is_empty:
            continue
        poly = orient(poly, sign=1.0)  # exterior CCW, holes CW
        rings.append(np.asarray(poly.exterior.coords[:-1], dtype=np.float64))
        for hole in poly.interiors:
            rings.append(np.asarray(hole.coords[:-1], dtype=np.float64))
    if not rings:
        return None
    cs = m3.CrossSection(rings, m3.FillRule.Positive)
    return None if cs.is_empty() else cs


def view_prism(
    view: str,
    geom,
    dims: tuple[float, float, float],
    pad: float = PAD,
) -> m3.Manifold | None:
    """Extrude a view silhouette (view-plane mm coords) into its world prism."""
    length, width, height = dims
    cs = cross_section(geom)
    if cs is None:
        return None
    if view == "top":
        depth = height + 2 * pad
        solid = cs.extrude(depth).translate((0.0, 0.0, -pad))
    elif view == "side":
        depth = width + 2 * pad
        # rotate X+90: cs-y -> +Z, extrusion axis -> -Y
        solid = cs.extrude(depth).rotate((90.0, 0.0, 0.0)).translate(
            (0.0, width / 2.0 + pad, 0.0)
        )
    elif view in ("front", "back"):
        depth = length + 2 * pad
        # rotate X+90 then Z+90: cs-x -> +Y, cs-y -> +Z, extrusion -> +X
        solid = cs.extrude(depth).rotate((90.0, 0.0, 90.0)).translate(
            (-pad, 0.0, 0.0)
        )
    else:
        raise ValueError(f"unknown view {view!r}")
    return solid


def visual_hull(
    view_geoms: dict[str, object],
    dims: tuple[float, float, float],
    pad: float = PAD,
) -> m3.Manifold:
    """Intersect all view prisms. Raises HullError if the result is empty."""
    prisms = []
    for view, geom in view_geoms.items():
        prism = view_prism(view, geom, dims, pad)
        if prism is None:
            raise HullError(f"The {view} view silhouette is empty.")
        prisms.append(prism)
    if not prisms:
        raise HullError("No view silhouettes to intersect.")
    hull = m3.Manifold.batch_boolean(prisms, m3.OpType.Intersect)
    if hull.is_empty() or hull.volume() <= 0:
        raise HullError(
            "The view silhouettes do not intersect into a solid — the views "
            "are probably misassigned or drawn at incompatible positions. "
            "Check with list-views, or override with --view-box."
        )
    return hull
