"""End-to-end conversion pipeline: SVG layer -> colored mesh parts."""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.affinity import affine_transform

from . import colors as colors_mod
from .bambu3mf import write_3mf
from .mesher import MeshPart, to_mesh_parts, validate_watertight
from .partition import (
    DEFAULT_PRIORITY,
    DEFAULT_SHELL_DEPTH,
    MIN_PART_VOLUME,
    partition_projection,
    partition_side,
)
from .register import register
from .silhouette import color_regions, painted_regions, silhouette
from .svgload import load_layer
from .views import detect_views
from .hull import visual_hull


@dataclass
class Options:
    layer: str | None = None
    length: float | None = None
    width: float | None = None
    height: float | None = None
    color_mode: str = "side"           # side | projection
    shell_depth: float = DEFAULT_SHELL_DEPTH
    core_color: str | None = None
    view_priority: tuple[str, ...] = DEFAULT_PRIORITY
    front_right: bool = False
    no_back_mirror: bool = False
    tolerance: float = 0.1             # curve flattening, mm
    min_area: float = 0.05             # mm^2, per-color region cleanup
    min_part_volume: float = MIN_PART_VOLUME
    merge_colors: int = 0              # max channel distance, 0 = off
    view_labels: dict[str, str] = field(default_factory=dict)
    view_boxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    cluster_gap: float | None = None
    settings_template: str | None = None
    title: str | None = None
    check: bool = False


@dataclass
class ViewReport:
    label: str | None
    bbox: tuple[float, float, float, float]
    shape_count: int
    colors: list[str]


@dataclass
class Result:
    layer: str
    parts: list[MeshPart]
    length: float
    width: float
    height: float
    slots: dict[str, int]
    views: dict[str, ViewReport]
    warnings: list[str]


def convert(svg_path: str, options: Options | None = None) -> Result:
    opts = options or Options()
    warnings: list[str] = []

    layer = load_layer(svg_path, opts.layer)
    warnings.extend(layer.warnings)

    viewset = detect_views(
        layer,
        cluster_gap=opts.cluster_gap,
        view_labels=opts.view_labels or None,
        view_boxes=opts.view_boxes or None,
    )
    warnings.extend(viewset.warnings)

    # preliminary registration on drawing bboxes fixes the mm-per-unit scale
    # so curve flattening and area thresholds can work in real millimeters
    prelim = register(
        {v: d.bbox for v, d in viewset.views.items()},
        length=opts.length,
        width=opts.width,
        height=opts.height,
        front_right=opts.front_right,
        no_back_mirror=opts.no_back_mirror,
    )

    merge_map: dict[str, str] = {}
    view_regions_svg: dict[str, dict[str, object]] = {}
    view_sil_svg: dict[str, object] = {}
    per_view_paint_order: dict[str, list[str]] = {}
    for view, data in viewset.views.items():
        if (
            view == "back"
            and data.shapes is viewset.views["front"].shapes
            and "front" in view_regions_svg
        ):
            view_regions_svg["back"] = view_regions_svg["front"]
            view_sil_svg["back"] = view_sil_svg["front"]
            per_view_paint_order["back"] = per_view_paint_order["front"]
            continue
        scale = abs(prelim.transforms[view][0])
        tol_units = max(opts.tolerance / max(scale, 1e-12), 1e-9)
        regions = painted_regions(data.shapes, tol_units)
        if opts.merge_colors > 0:
            mapping = colors_mod.merge_colors(
                [r.color for r in regions], opts.merge_colors
            )
            merge_map.update(mapping)
            for r in regions:
                r.color = mapping[r.color]
        min_area_units = opts.min_area / max(scale, 1e-12) ** 2
        view_regions_svg[view] = color_regions(regions, min_area=min_area_units)
        view_sil_svg[view] = silhouette(regions)
        order: list[str] = []
        for r in regions:
            if r.color not in order:
                order.append(r.color)
        per_view_paint_order[view] = order

    merged = {k: v for k, v in merge_map.items() if k != v}
    if merged:
        warnings.append(
            "Merged similar colors: "
            + ", ".join(f"{k} -> {v}" for k, v in sorted(merged.items()))
        )

    # final registration on the exact painted silhouettes
    sil_bboxes = {}
    for view, sil in view_sil_svg.items():
        if sil.is_empty:
            raise ValueError(f"The {view} view has no painted area.")
        sil_bboxes[view] = sil.bounds
    reg = register(
        sil_bboxes,
        length=opts.length,
        width=opts.width,
        height=opts.height,
        front_right=opts.front_right,
        no_back_mirror=opts.no_back_mirror,
    )
    warnings.extend(reg.warnings)

    dims = (reg.length, reg.width, reg.height)
    view_sil = {
        v: affine_transform(sil, reg.transforms[v]) for v, sil in view_sil_svg.items()
    }
    # a short front/back drawing says nothing about the train below its
    # bottom edge — fill that zone so its prism doesn't clip wheels etc.
    for view, v_min in reg.fill_below.items():
        from shapely.geometry import box as shapely_box
        from shapely import unary_union

        filler = shapely_box(
            -reg.width / 2 - 1.0, -1.0, reg.width / 2 + 1.0, v_min + 0.01
        )
        view_sil[view] = unary_union([view_sil[view], filler])
    view_regions = {
        v: {
            c: affine_transform(g, reg.transforms[v])
            for c, g in regions.items()
        }
        for v, regions in view_regions_svg.items()
    }

    hull = visual_hull(view_sil, dims)

    if opts.color_mode == "side":
        color_parts = partition_side(
            hull,
            view_regions["side"],
            dims,
            min_part_volume=opts.min_part_volume,
        )
    elif opts.color_mode == "projection":
        color_parts = partition_projection(
            hull,
            view_regions,
            dims,
            shell_depth=opts.shell_depth,
            core_color=opts.core_color,
            priority=opts.view_priority,
            min_part_volume=opts.min_part_volume,
        )
    else:
        raise ValueError(f"Unknown color mode {opts.color_mode!r}.")

    # deterministic filament slots: side-view paint order first, then the rest
    ordered: list[str] = []
    for view in ("side", "top", "front", "back"):
        for color in per_view_paint_order.get(view, []):
            if color not in ordered:
                ordered.append(color)
    part_colors = [p.color for p in color_parts]
    for color in sorted(part_colors):
        if color not in ordered:
            ordered.append(color)
    slots = colors_mod.assign_slots([c for c in ordered if c in part_colors])
    if len(slots) > colors_mod.AMS_SLOTS:
        warnings.append(
            f"{len(slots)} filament colors — more than one AMS unit "
            f"({colors_mod.AMS_SLOTS} slots) will be needed."
        )

    parts = to_mesh_parts(color_parts, slots)
    if opts.check:
        for part in parts:
            validate_watertight(part)

    reports = {
        v: ViewReport(
            label=d.label,
            bbox=d.bbox,
            shape_count=len(d.shapes),
            colors=list(view_regions_svg.get(v, {})),
        )
        for v, d in viewset.views.items()
    }
    return Result(
        layer=layer.name,
        parts=parts,
        length=reg.length,
        width=reg.width,
        height=reg.height,
        slots=slots,
        views=reports,
        warnings=warnings,
    )


def convert_to_file(svg_path: str, out_path: str, options: Options | None = None) -> Result:
    opts = options or Options()
    result = convert(svg_path, opts)
    title = opts.title or result.layer
    write_3mf(out_path, result.parts, title=title, settings_template=opts.settings_template)
    return result
