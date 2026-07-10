"""View detection: spatial clustering of shapes + informal text-label matching."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .svgload import LoadedLayer, LoadedShape, TextLabel

VIEW_NAMES = ("top", "side", "front", "back")

_SYNONYMS = {
    "top": "top",
    "plan": "top",
    "roof": "top",
    "side": "side",
    "profile": "side",
    "left": "side",
    "right": "side",
    "front": "front",
    "back": "back",
    "rear": "back",
}


class ViewDetectionError(ValueError):
    pass


@dataclass
class ViewData:
    shapes: list[LoadedShape]
    bbox: tuple[float, float, float, float]
    label: str | None = None
    shared_with_back: bool = False  # a "front/back" drawing serving both


@dataclass
class ViewSet:
    views: dict[str, ViewData]
    warnings: list[str] = field(default_factory=list)
    unknown_labels: list[str] = field(default_factory=list)


def _normalize_label(text: str) -> list[str]:
    words = re.sub(r"[^a-z]+", " ", text.lower()).split()
    return [w for w in words if w != "view" and w != "views"]


def match_label(text: str, overrides: dict[str, str] | None = None) -> set[str] | None:
    """Map a text element to the view(s) it names, or None if it's not a label."""
    words = _normalize_label(text)
    if overrides:
        norm = " ".join(words)
        for key, view in overrides.items():
            if " ".join(_normalize_label(key)) == norm:
                return {view}
    if not words or len(words) > 3:
        return None
    mapped = [_SYNONYMS.get(w) for w in words]
    views = {m for m in mapped if m}
    if not views or None in mapped and len(views) == 0:
        return None
    # every word must be view-ish ("front portion" must not match)
    if any(m is None for m in mapped):
        return None
    return views


def _bbox_of(shape: LoadedShape) -> tuple[float, float, float, float] | None:
    bbox = shape.path.bbox()
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    if shape.stroke is not None and shape.stroke_width > 0:
        pad = shape.stroke_width / 2.0
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    return (x0, y0, x1, y1)


def _bboxes_intersect(a, b, gap: float) -> bool:
    return not (
        a[2] + gap < b[0]
        or b[2] + gap < a[0]
        or a[3] + gap < b[1]
        or b[3] + gap < a[1]
    )


def _merge_bbox(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def cluster_shapes(
    shapes: list[LoadedShape], gap: float
) -> list[tuple[list[LoadedShape], tuple[float, float, float, float]]]:
    """Group shapes whose (inflated) bounding boxes touch, via union-find."""
    boxed = [(s, _bbox_of(s)) for s in shapes]
    boxed = [(s, b) for s, b in boxed if b is not None]
    parent = list(range(len(boxed)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxed)):
        for j in range(i + 1, len(boxed)):
            if _bboxes_intersect(boxed[i][1], boxed[j][1], gap):
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(len(boxed)):
        groups.setdefault(find(i), []).append(i)

    clusters = []
    for members in groups.values():
        shapes_in = [boxed[i][0] for i in members]
        bbox = boxed[members[0]][1]
        for i in members[1:]:
            bbox = _merge_bbox(bbox, boxed[i][1])
        clusters.append((shapes_in, bbox))
    clusters.sort(key=lambda c: (c[1][1], c[1][0]))  # stable: top-to-bottom
    return clusters


def _point_bbox_distance(x: float, y: float, bbox) -> float:
    dx = max(bbox[0] - x, 0.0, x - bbox[2])
    dy = max(bbox[1] - y, 0.0, y - bbox[3])
    return (dx * dx + dy * dy) ** 0.5


def _in_box(bbox, rect) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    x, y, w, h = rect
    return x <= cx <= x + w and y <= cy <= y + h


def _dim_error(view_bboxes: dict[str, tuple[float, float, float, float]]) -> float:
    """Relative mismatch of dimensions that views must share.

    side is L x H, top is L x W, front/back are W x H (drawing bbox = w x h).
    """

    def dims(view):
        b = view_bboxes.get(view)
        return (b[2] - b[0], b[3] - b[1]) if b else None

    def rel(a, b):
        return abs(a - b) / max(a, b, 1e-9)

    side, top = dims("side"), dims("top")
    front, back = dims("front"), dims("back")
    err = 0.0
    if side and top:
        err += rel(side[0], top[0])  # length
    if top and front:
        err += rel(top[1], front[0])  # width
    if side and front:
        err += rel(side[1], front[1])  # height
    if back and back != front:
        if top:
            err += rel(top[1], back[0])
        if side:
            err += rel(side[1], back[1])
    return err


def _best_assignment(
    recognized: list[tuple[set[str], TextLabel]],
    clusters: list,
    needed: list[str],
    diag: float,
    dim_weight: float = 3.0,
):
    """Search injective label->cluster and missing-view->cluster assignments.

    Returns ({view: (cluster_idx, label_or_None)}, inferred_view_names) or None.
    """
    from itertools import permutations

    n = len(clusters)
    best_score = None
    best_result = None

    for label_perm in permutations(range(n), len(recognized)):
        view_map: dict[str, tuple[int, TextLabel | None]] = {}
        ok = True
        label_cost = 0.0
        for (label_views, label), cluster_idx in zip(recognized, label_perm):
            label_cost += _point_bbox_distance(
                label.x, label.y, clusters[cluster_idx][1]
            )
            for v in label_views:
                if v in view_map:
                    ok = False
                    break
                view_map[v] = (cluster_idx, label)
            if not ok:
                break
        if not ok:
            continue

        missing = [v for v in ("top", "side", "front") if v in needed and v not in view_map]
        leftover = [i for i in range(n) if i not in {c for c, _ in view_map.values()}]
        if len(leftover) < len(missing):
            continue

        for infer_perm in permutations(leftover, len(missing)):
            candidate = dict(view_map)
            for v, cluster_idx in zip(missing, infer_perm):
                candidate[v] = (cluster_idx, None)
            bboxes = {v: clusters[c][1] for v, (c, _) in candidate.items()}
            score = label_cost / diag + dim_weight * _dim_error(bboxes)
            # prefer assignments that use labels over pure inference slightly
            score += 0.01 * len(missing)
            if best_score is None or score < best_score:
                best_score = score
                best_result = (candidate, set(missing))

    return best_result


def detect_views(
    layer: LoadedLayer,
    cluster_gap: float | None = None,
    view_labels: dict[str, str] | None = None,
    view_boxes: dict[str, tuple[float, float, float, float]] | None = None,
) -> ViewSet:
    """Assign the layer's shapes to top/side/front/back views."""
    warnings: list[str] = []
    unknown: list[str] = []
    views: dict[str, ViewData] = {}

    remaining = list(layer.shapes)

    # 1. explicit rectangles win outright
    if view_boxes:
        for view, rect in view_boxes.items():
            selected = [s for s in remaining if (b := _bbox_of(s)) and _in_box(b, rect)]
            if not selected:
                raise ViewDetectionError(
                    f"--view-box for {view!r} selected no shapes (rect {rect})."
                )
            bbox = _bbox_of(selected[0])
            for s in selected[1:]:
                bbox = _merge_bbox(bbox, _bbox_of(s))
            views[view] = ViewData(shapes=selected, bbox=bbox, label=f"--view-box")
            remaining = [s for s in remaining if s not in selected]

    needed = [v for v in VIEW_NAMES if v not in views]
    if needed and remaining:
        if cluster_gap is None:
            boxes = [_bbox_of(s) for s in remaining]
            boxes = [b for b in boxes if b]
            gx0 = min(b[0] for b in boxes)
            gy0 = min(b[1] for b in boxes)
            gx1 = max(b[2] for b in boxes)
            gy1 = max(b[3] for b in boxes)
            cluster_gap = 0.02 * ((gx1 - gx0) ** 2 + (gy1 - gy0) ** 2) ** 0.5
        clusters = cluster_shapes(remaining, cluster_gap)

        # Collect recognized labels.
        recognized: list[tuple[set[str], TextLabel]] = []
        for label in layer.labels:
            matched = match_label(label.text, view_labels)
            if matched is None:
                if _normalize_label(label.text) and len(_normalize_label(label.text)) <= 3:
                    unknown.append(label.text)
                continue
            matched = {v for v in matched if v in needed}
            if not matched:
                continue
            recognized.append((matched, label))
        if len(recognized) > len(clusters):
            texts = ", ".join(repr(l.text) for _, l in recognized)
            raise ViewDetectionError(
                f"Found {len(recognized)} view labels ({texts}) but only "
                f"{len(clusters)} drawing group(s). Check --cluster-gap or "
                "use --view-box."
            )

        # Choose the best complete assignment of views to clusters. Candidates
        # map each label to a distinct cluster and each still-missing required
        # view to a distinct leftover cluster; score = normalized label
        # distances + cross-view dimensional consistency (side/top share
        # length, top/front share width, side/front share height). A label can
        # sit nearer a neighboring drawing than its own, and drawings can be
        # entirely unlabeled — geometry disambiguates both.
        diag = max(
            (
                (max(c[1][2] for c in clusters) - min(c[1][0] for c in clusters)) ** 2
                + (max(c[1][3] for c in clusters) - min(c[1][1] for c in clusters)) ** 2
            )
            ** 0.5,
            1e-9,
        )
        best = _best_assignment(recognized, clusters, needed, diag)
        if best is None:
            labels = ", ".join(repr(t.text) for t in layer.labels) or "none"
            raise ViewDetectionError(
                f"Could not assign views to the {len(clusters)} drawing group(s). "
                f"Text labels present: {labels}. "
                'Use --view-label "text=view" or --view-box "view=x,y,w,h".'
            )
        assignment, inferred = best
        for view, (cluster_idx, label) in assignment.items():
            if view in views:
                continue
            shapes_in, bbox = clusters[cluster_idx]
            shared = (
                label is not None
                and match_label(label.text, view_labels) == {"front", "back"}
            )
            views[view] = ViewData(
                shapes=shapes_in,
                bbox=bbox,
                label=label.text if label else None,
                shared_with_back=shared,
            )
        if inferred:
            warnings.append(
                "View(s) inferred from drawing dimensions (no matching label): "
                + ", ".join(sorted(inferred))
            )
        used = {idx for idx, _ in assignment.values()}
        unclaimed = [i for i in range(len(clusters)) if i not in used]
        if unclaimed:
            warnings.append(
                f"{len(unclaimed)} drawing group(s) were not used as views: "
                + "; ".join(f"bbox={clusters[i][1]}" for i in unclaimed)
            )

    if unknown:
        warnings.append(
            "Unrecognized label(s): "
            + ", ".join(repr(u) for u in unknown)
            + '. Map them with --view-label "text=view" if they name a view.'
        )

    missing = [v for v in ("top", "side", "front") if v not in views]
    if missing:
        found = ", ".join(f"{v}={d.label!r}" for v, d in views.items()) or "none"
        labels = ", ".join(repr(t.text) for t in layer.labels) or "none"
        raise ViewDetectionError(
            f"Could not find required view(s): {', '.join(missing)}. "
            f"Views detected: {found}. Text labels present: {labels}. "
            'Use --view-label "text=view" or --view-box "view=x,y,w,h".'
        )
    if "back" not in views:
        views["back"] = ViewData(
            shapes=views["front"].shapes,
            bbox=views["front"].bbox,
            label=views["front"].label,
            shared_with_back=True,
        )
        warnings.append("No back view found; mirroring the front view.")

    return ViewSet(views=views, warnings=warnings, unknown_labels=unknown)
