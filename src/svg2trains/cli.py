"""Command-line interface: convert, list-views, list-colors, gui."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _parse_view_box(spec: str) -> tuple[str, tuple[float, float, float, float]]:
    try:
        name, rect = spec.split("=", 1)
        x, y, w, h = (float(t) for t in rect.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f'expected "view=x,y,w,h", got {spec!r}'
        ) from None
    name = name.strip().lower()
    if name not in ("top", "side", "front", "back"):
        raise argparse.ArgumentTypeError(f"unknown view {name!r}")
    return name, (x, y, w, h)


def _parse_view_label(spec: str) -> tuple[str, str]:
    try:
        text, view = spec.rsplit("=", 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected "text=view", got {spec!r}') from None
    view = view.strip().lower()
    if view not in ("top", "side", "front", "back"):
        raise argparse.ArgumentTypeError(f"unknown view {view!r}")
    return text.strip(), view


def _add_convert_args(p: argparse.ArgumentParser, with_output: bool = True) -> None:
    p.add_argument("input", help="SVG file with labeled train views")
    if with_output:
        p.add_argument("-o", "--output", help="output .3mf path (default: input name)")
    p.add_argument("--layer", help="layer name (default: the visible layer)")
    size = p.add_mutually_exclusive_group()
    size.add_argument("--length", type=float, help="train length in mm")
    size.add_argument("--width", type=float, help="train width in mm")
    size.add_argument("--height", type=float, help="train height in mm")
    p.add_argument(
        "--color-mode",
        choices=("side", "projection"),
        default="side",
        help="side: side-view colors through the full width (default); "
        "projection: each face colored by its facing view",
    )
    p.add_argument("--shell-depth", type=float, default=1.2,
                   help="projection mode color depth in mm (default 1.2)")
    p.add_argument("--core-color", help="projection mode interior color (hex)")
    p.add_argument("--view-priority", default="side,top,front,back",
                   help="projection mode view precedence (comma separated)")
    p.add_argument("--front", choices=("left", "right"), default="left",
                   help="which screen side of the side view is the train front")
    p.add_argument("--no-back-mirror", action="store_true",
                   help="back view drawn see-through (not mirrored)")
    p.add_argument("--carve-holes", action="store_true",
                   help="unpainted enclosed areas in a view carve real holes "
                   "through the model (default: treat them as surface detail)")
    p.add_argument("--tolerance", type=float, default=0.1,
                   help="curve flattening tolerance in mm (default 0.1)")
    p.add_argument("--min-area", type=float, default=0.05,
                   help="drop color regions smaller than this (mm^2)")
    p.add_argument("--min-part-volume", type=float, default=1.0,
                   help="absorb parts smaller than this (mm^3)")
    p.add_argument("--merge-colors", type=int, default=0,
                   help="merge colors within this channel distance (0-255)")
    p.add_argument("--view-label", action="append", default=[], metavar="TEXT=VIEW",
                   help='map a label to a view, e.g. "roof=top" (repeatable)')
    p.add_argument("--view-box", action="append", default=[], metavar="VIEW=X,Y,W,H",
                   help="assign a view by SVG-coordinate rectangle (repeatable)")
    p.add_argument("--cluster-gap", type=float,
                   help="drawing grouping distance in SVG units")
    p.add_argument("--settings-template",
                   help="project_settings.config JSON to use instead of the built-in")
    p.add_argument("--title", help="model name inside the 3MF")
    p.add_argument("--check", action="store_true",
                   help="validate meshes are watertight before writing")
    p.add_argument("-v", "--verbose", action="store_true")


def _options_from(args: argparse.Namespace):
    from .pipeline import Options

    return Options(
        layer=args.layer,
        length=args.length,
        width=args.width,
        height=args.height,
        color_mode=args.color_mode,
        shell_depth=args.shell_depth,
        core_color=args.core_color,
        view_priority=tuple(t.strip() for t in args.view_priority.split(",") if t.strip()),
        front_right=(args.front == "right"),
        no_back_mirror=args.no_back_mirror,
        carve_holes=args.carve_holes,
        tolerance=args.tolerance,
        min_area=args.min_area,
        min_part_volume=args.min_part_volume,
        merge_colors=args.merge_colors,
        view_labels=dict(_parse_view_label(s) for s in args.view_label),
        view_boxes=dict(_parse_view_box(s) for s in args.view_box),
        cluster_gap=args.cluster_gap,
        settings_template=args.settings_template,
        title=args.title,
        check=args.check,
    )


def _print_result(result, verbose: bool) -> None:
    print(
        f"Layer {result.layer!r}: {result.length:.1f} x {result.width:.1f} x "
        f"{result.height:.1f} mm, {len(result.parts)} color part(s)"
    )
    for part in result.parts:
        print(
            f"  filament {part.extruder}: {part.color}  "
            f"{part.volume / 1000:.2f} cm^3  ({part.name})"
        )
    for warning in result.warnings:
        print(f"  warning: {warning}", file=sys.stderr)
    if verbose:
        for view, report in result.views.items():
            print(
                f"  {view}: label={report.label!r} shapes={report.shape_count} "
                f"colors={report.colors}"
            )


def cmd_convert(args: argparse.Namespace) -> int:
    from .pipeline import convert_to_file

    output = args.output or str(Path(args.input).with_suffix(".3mf"))
    result = convert_to_file(args.input, output, _options_from(args))
    _print_result(result, args.verbose)
    print(f"Wrote {output}")
    return 0


def cmd_list_views(args: argparse.Namespace) -> int:
    from .svgload import list_layers, load_layer
    from .views import detect_views

    print("Layers:")
    for info in list_layers(args.input):
        marker = "*" if info.visible else " "
        print(f" {marker} {info.name}")
    layer = load_layer(args.input, args.layer)
    viewset = detect_views(
        layer,
        cluster_gap=args.cluster_gap,
        view_labels=dict(_parse_view_label(s) for s in args.view_label) or None,
        view_boxes=dict(_parse_view_box(s) for s in args.view_box) or None,
    )
    print(f"Views in layer {layer.name!r}:")
    for view, data in viewset.views.items():
        x0, y0, x1, y1 = data.bbox
        print(
            f"  {view:5s} label={data.label!r} shapes={len(data.shapes)} "
            f"bbox=({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f})"
        )
    for warning in viewset.warnings:
        print(f"  warning: {warning}", file=sys.stderr)
    return 0


def cmd_list_colors(args: argparse.Namespace) -> int:
    from .pipeline import convert

    result = convert(args.input, _options_from(args))
    print(f"Colors in layer {result.layer!r} ({args.color_mode} mode):")
    for part in result.parts:
        print(
            f"  filament {part.extruder}: {part.color}  "
            f"{part.volume / 1000:.2f} cm^3  ({part.name})"
        )
    for warning in result.warnings:
        print(f"  warning: {warning}", file=sys.stderr)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui import run_gui

    return run_gui(port=args.port, open_browser=not args.no_browser)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="svg2trains",
        description="Convert multi-view train SVGs into Bambu Lab multi-color 3MF files.",
    )
    parser.add_argument("--version", action="version", version=f"svg2trains {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser("convert", help="convert an SVG to a 3MF")
    _add_convert_args(p_convert)
    p_convert.set_defaults(func=cmd_convert)

    p_views = sub.add_parser("list-views", help="show layers and detected views")
    p_views.add_argument("input")
    p_views.add_argument("--layer")
    p_views.add_argument("--cluster-gap", type=float)
    p_views.add_argument("--view-label", action="append", default=[], metavar="TEXT=VIEW")
    p_views.add_argument("--view-box", action="append", default=[], metavar="VIEW=X,Y,W,H")
    p_views.set_defaults(func=cmd_list_views)

    p_colors = sub.add_parser("list-colors", help="show the filament assignment")
    _add_convert_args(p_colors, with_output=False)
    p_colors.set_defaults(func=cmd_list_colors)

    p_gui = sub.add_parser("gui", help="start the local web app")
    p_gui.add_argument("--port", type=int, default=8323)
    p_gui.add_argument("--no-browser", action="store_true")
    p_gui.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
