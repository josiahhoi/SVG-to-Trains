"""2D geometry: path flattening, fills, strokes, paint-order color regions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import svgelements as se
from shapely import make_valid, unary_union
from shapely.geometry import (
    LineString,
    MultiPolygon,
    Polygon,
)
from shapely.ops import polygonize

from .svgload import LoadedShape

_CAP_STYLE = {"butt": "flat", "round": "round", "square": "square"}
_JOIN_STYLE = {"miter": "mitre", "round": "round", "bevel": "bevel"}


@dataclass
class Subpath:
    points: np.ndarray  # (n, 2), no duplicate closing point
    closed: bool


@dataclass
class PaintedRegion:
    """A single paint operation (one shape's fill or stroke), in paint order."""

    color: str
    geom: object  # shapely geometry
    source: str   # e.g. "fill:rect-3" / "stroke:path-7"


def _samples_for(seg, tolerance: float) -> int:
    try:
        length = seg.length(error=1e-4)
    except (AttributeError, TypeError):
        length = abs(seg.end - seg.start)
    length = float(length)
    if length <= 0:
        return 2
    # chord deviation ~ c^2/(8R); with R~length this keeps deviation < tolerance
    chord = max(np.sqrt(8.0 * tolerance * length), tolerance, 1e-9)
    return int(np.clip(np.ceil(length / chord) * 2, 4, 512))


def flatten_path(path: se.Path, tolerance: float) -> list[Subpath]:
    """Flatten an svgelements Path into polyline subpaths."""
    subpaths: list[Subpath] = []
    points: list[tuple[float, float]] = []
    closed = False

    def flush():
        nonlocal points, closed
        if len(points) >= 2:
            pts = np.array(points, dtype=float)
            keep = np.ones(len(pts), dtype=bool)
            keep[1:] = np.any(np.abs(np.diff(pts, axis=0)) > 1e-12, axis=1)
            pts = pts[keep]
            is_closed = closed
            if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
                pts = pts[:-1]
                is_closed = True
            if len(pts) >= 2:
                subpaths.append(Subpath(points=pts, closed=is_closed))
        points = []
        closed = False

    for seg in path.segments():
        if isinstance(seg, se.Move):
            flush()
            if seg.end is not None:
                points = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, se.Close):
            closed = True
            flush()
        elif isinstance(seg, se.Line):
            if not points and seg.start is not None:
                points.append((seg.start.x, seg.start.y))
            points.append((seg.end.x, seg.end.y))
        elif isinstance(seg, (se.CubicBezier, se.QuadraticBezier, se.Arc)):
            if not points and seg.start is not None:
                points.append((seg.start.x, seg.start.y))
            n = _samples_for(seg, tolerance)
            ts = np.linspace(0.0, 1.0, n + 1)[1:]
            try:
                pts = seg.npoint(ts)
                points.extend((float(p[0]), float(p[1])) for p in pts)
            except (AttributeError, TypeError):
                for t in ts:
                    p = seg.point(t)
                    points.append((float(p.x), float(p.y)))
    flush()
    return subpaths


def _winding_numbers(pt: tuple[float, float], rings: list[np.ndarray]) -> int:
    x, y = pt
    total = 0
    for ring in rings:
        p0 = ring
        p1 = np.roll(ring, -1, axis=0)
        cross = (p1[:, 0] - p0[:, 0]) * (y - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (x - p0[:, 0])
        up = (p0[:, 1] <= y) & (p1[:, 1] > y) & (cross > 0)
        down = (p1[:, 1] <= y) & (p0[:, 1] > y) & (cross < 0)
        total += int(np.count_nonzero(up)) - int(np.count_nonzero(down))
    return total


def fill_geometry(subpaths: list[Subpath], fill_rule: str):
    """Build the filled area of a path honoring nonzero/evenodd winding."""
    rings = [sp.points for sp in subpaths if len(sp.points) >= 3]
    if not rings:
        return Polygon()
    if len(rings) == 1:
        poly = Polygon(rings[0])
        if poly.is_valid:
            return poly
    boundaries = unary_union(
        [LineString(np.vstack([r, r[:1]])) for r in rings]
    )
    kept = []
    for face in polygonize(boundaries):
        pt = face.representative_point()
        w = _winding_numbers((pt.x, pt.y), rings)
        inside = (w % 2 == 1) if fill_rule == "evenodd" else (w != 0)
        if inside:
            kept.append(face)
    if not kept:
        return Polygon()
    return make_valid(unary_union(kept))


def stroke_geometry(
    subpaths: list[Subpath],
    width: float,
    linecap: str = "butt",
    linejoin: str = "miter",
    miterlimit: float = 4.0,
):
    """Build the painted area of a stroke by buffering the centerline."""
    if width <= 0:
        return Polygon()
    pieces = []
    for sp in subpaths:
        pts = sp.points
        if len(pts) < 2:
            continue
        if sp.closed:
            pts = np.vstack([pts, pts[:1]])
        line = LineString(pts)
        pieces.append(
            line.buffer(
                width / 2.0,
                cap_style=_CAP_STYLE.get(linecap, "flat"),
                join_style=_JOIN_STYLE.get(linejoin, "mitre"),
                mitre_limit=max(miterlimit, 1.0),
            )
        )
    if not pieces:
        return Polygon()
    return make_valid(unary_union(pieces))


def painted_regions(shapes: list[LoadedShape], tolerance: float) -> list[PaintedRegion]:
    """Expand shapes into their paint operations, in document paint order.

    SVG paints each shape's fill first, then its stroke on top.
    """
    regions: list[PaintedRegion] = []
    for i, shape in enumerate(shapes):
        name = shape.element_id or f"shape-{i}"
        subpaths = flatten_path(shape.path, tolerance)
        if not subpaths:
            continue
        if shape.fill is not None:
            geom = fill_geometry(subpaths, shape.fill_rule)
            if not geom.is_empty:
                regions.append(PaintedRegion(shape.fill, geom, f"fill:{name}"))
        if shape.stroke is not None:
            geom = stroke_geometry(
                subpaths,
                shape.stroke_width,
                shape.linecap,
                shape.linejoin,
                shape.miterlimit,
            )
            if not geom.is_empty:
                regions.append(PaintedRegion(shape.stroke, geom, f"stroke:{name}"))
    return regions


def _polygonal(geom):
    """Reduce a geometry to its polygonal parts."""
    if geom.is_empty:
        return Polygon()
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    polys = [g for g in getattr(geom, "geoms", [geom]) if isinstance(g, Polygon)]
    return unary_union(polys) if polys else Polygon()


def silhouette(regions: list[PaintedRegion]):
    """Union of everything painted — the view's outline."""
    if not regions:
        return Polygon()
    return _polygonal(make_valid(unary_union([r.geom for r in regions])))


def fill_holes(geom):
    """Keep only exterior rings — unpainted enclosed areas become solid.

    A window or door drawn as an outline leaves its interior unpainted; for
    hull carving that must read as surface detail, not a hole through the
    train.
    """
    if geom.is_empty:
        return geom
    polys = [
        Polygon(p.exterior)
        for p in getattr(geom, "geoms", [geom])
        if isinstance(p, Polygon) and not p.is_empty
    ]
    if not polys:
        return Polygon()
    return _polygonal(make_valid(unary_union(polys)))


def color_regions(regions: list[PaintedRegion], min_area: float = 0.0) -> dict[str, object]:
    """Resolve paint order into non-overlapping per-color regions.

    Iterates topmost-first; each region only keeps what nothing above painted.
    The results exactly partition the silhouette.
    """
    covered = None
    by_color: dict[str, list] = defaultdict(list)
    for region in reversed(regions):
        geom = make_valid(region.geom)
        visible = geom if covered is None else geom.difference(covered)
        visible = _polygonal(visible)
        if not visible.is_empty:
            by_color[region.color].append(visible)
        covered = geom if covered is None else make_valid(covered.union(geom))

    out: dict[str, object] = {}
    for color, parts in by_color.items():
        merged = _polygonal(make_valid(unary_union(parts)))
        if min_area > 0:
            pieces = [p for p in getattr(merged, "geoms", [merged]) if p.area >= min_area]
            merged = unary_union(pieces) if pieces else Polygon()
        if not merged.is_empty:
            out[color] = merged
    return out
