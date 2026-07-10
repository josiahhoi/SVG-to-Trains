"""Registration: consistency-check views and map them to the canonical frame.

World frame (mm): X = length, Y = width, Z = height, right-handed, Z up.
The model rests on Z=0, spans X in [0, L], and is centered on Y.

Drawing conventions (SVG y is screen-down):
- side view: screen-x -> X (front of train at screen-left), screen-y -> -Z
- top view:  screen-x -> X, screen-y -> +Y
- front view (viewer ahead of the train looking along +X): screen-right -> -Y
- back view (viewer behind, looking along -X): screen-right -> +Y, i.e. the
  drawing is the mirror of the front. --no-back-mirror treats the back drawing
  as "see-through" (same orientation as the front).

Each view's transform maps its SVG coordinates to 2D view-plane mm coords:
side -> (X, Z), top -> (X, Y), front/back -> (Y, Z).
"""

from __future__ import annotations

from dataclasses import dataclass, field

BBox = tuple[float, float, float, float]

WARN_TOLERANCE = 0.02
ERROR_TOLERANCE = 0.25
DEFAULT_LENGTH_MM = 150.0


class RegistrationError(ValueError):
    pass


@dataclass
class Registration:
    length: float  # mm
    width: float
    height: float
    # shapely affine_transform coefficients [a, b, d, e, xoff, yoff] per view
    transforms: dict[str, list[float]]
    warnings: list[str] = field(default_factory=list)
    # views whose drawing is shorter than the train: below this Z (mm) the
    # view provides no information and must not constrain the hull
    fill_below: dict[str, float] = field(default_factory=dict)


def _dims(bbox: BBox) -> tuple[float, float]:
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(a, b, 1e-9)


def register(
    bboxes: dict[str, BBox],
    length: float | None = None,
    width: float | None = None,
    height: float | None = None,
    tolerance: float = WARN_TOLERANCE,
    no_back_mirror: bool = False,
    front_right: bool = False,
) -> Registration:
    """Compute mm dimensions and per-view SVG->view-plane transforms.

    `bboxes` must contain side/top/front (back optional; defaults to front's).
    Exactly one of length/width/height sets the physical scale.
    """
    warnings: list[str] = []
    for required in ("side", "top", "front"):
        if required not in bboxes:
            raise RegistrationError(f"Missing {required} view bounding box.")
    back_bbox = bboxes.get("back", bboxes["front"])

    L_side, H_side = _dims(bboxes["side"])
    L_top, W_top = _dims(bboxes["top"])
    W_front, H_front = _dims(bboxes["front"])
    W_back, H_back = _dims(back_bbox)

    # length and width must agree between views; height may legitimately be
    # short on front/back drawings (wheels/underframe often omitted) and is
    # handled by anchoring those views at the roofline instead
    checks = [
        ("length", "side vs top", L_side, L_top),
        ("width", "top vs front", W_top, W_front),
        ("width", "top vs back", W_top, W_back),
    ]
    for dim, pair, a, b in checks:
        mismatch = _rel(a, b)
        if mismatch > ERROR_TOLERANCE:
            raise RegistrationError(
                f"Views disagree on {dim} ({pair}: {a:.1f} vs {b:.1f} user units, "
                f"{mismatch:.0%} apart) — check the view assignment "
                "(--list-views, --view-box)."
            )
        if mismatch > tolerance:
            warnings.append(
                f"Views disagree on {dim} by {mismatch:.1%} ({pair}); "
                "rescaling to the side/top views."
            )

    sizes = [s for s in (length, width, height) if s is not None]
    if len(sizes) > 1:
        raise RegistrationError("Give only one of length/width/height.")
    if not sizes:
        length = DEFAULT_LENGTH_MM
        warnings.append(f"No physical size given; defaulting to --length {length:g} mm.")

    # canonical dims: trust side for L and H, top (scaled to side's L) for W
    if length is not None:
        L = float(length)
    elif height is not None:
        L = float(height) * L_side / H_side
    else:
        L = float(width) * L_top / W_top
    H = L * H_side / L_side
    W = W_top * L / L_top

    transforms: dict[str, list[float]] = {}

    def fit(bbox: BBox, u_span: tuple[float, float], v_span: tuple[float, float],
            flip_u: bool, flip_v: bool) -> list[float]:
        x0, y0, x1, y1 = bbox
        su = (u_span[1] - u_span[0]) / max(x1 - x0, 1e-9)
        sv = (v_span[1] - v_span[0]) / max(y1 - y0, 1e-9)
        if flip_u:
            a, xoff = -su, u_span[1] + su * x0
        else:
            a, xoff = su, u_span[0] - su * x0
        if flip_v:
            e, yoff = -sv, v_span[1] + sv * y0
        else:
            e, yoff = sv, v_span[0] - sv * y0
        return [a, 0.0, 0.0, e, xoff, yoff]

    # front of the train at screen-left by default
    side_flip_u = front_right
    transforms["side"] = fit(bboxes["side"], (0, L), (0, H), side_flip_u, True)
    transforms["top"] = fit(bboxes["top"], (0, L), (-W / 2, W / 2), side_flip_u, False)

    fill_below: dict[str, float] = {}

    def fit_end_view(view: str, bbox: BBox, flip_u: bool) -> list[float]:
        """Front/back: fit width exactly; anchor at the roofline with true
        proportions when the drawing is shorter than the train."""
        w_units, h_units = _dims(bbox)
        su = W / max(w_units, 1e-9)
        h_mm = h_units * su
        if _rel(h_mm, H) <= tolerance:
            return fit(bbox, (-W / 2, W / 2), (0, H), flip_u, True)
        if h_mm > H:
            if _rel(h_mm, H) > ERROR_TOLERANCE:
                raise RegistrationError(
                    f"The {view} view is taller than the side view "
                    f"({h_mm:.1f} vs {H:.1f} mm at matching width) — check the "
                    "view assignment (--list-views, --view-box)."
                )
            warnings.append(
                f"The {view} view is {_rel(h_mm, H):.1%} taller than the "
                "train; stretching it to fit."
            )
            return fit(bbox, (-W / 2, W / 2), (0, H), flip_u, True)
        v_min = H - h_mm
        fill_below[view] = v_min
        warnings.append(
            f"The {view} view is {_rel(h_mm, H):.0%} shorter than the train; "
            f"anchoring it at the roof and leaving Z below {v_min:.1f} mm to "
            "the side/top views."
        )
        return fit(bbox, (-W / 2, W / 2), (v_min, H), flip_u, True)

    transforms["front"] = fit_end_view("front", bboxes["front"], True)
    back_flip_u = no_back_mirror
    transforms["back"] = fit_end_view("back", back_bbox, back_flip_u)

    return Registration(
        length=L,
        width=W,
        height=H,
        transforms=transforms,
        warnings=warnings,
        fill_below=fill_below,
    )
