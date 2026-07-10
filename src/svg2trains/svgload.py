"""SVG loading: layer enumeration/selection, shape and label extraction.

The user's drawing app exports one train per layer (``<g data-layer="...">``)
and hides all but the active layer with ``display: none`` in the inline style.
svgelements prunes hidden elements at parse time, so layer handling happens on
the raw XML first; the selected layer is re-serialized (visible) and only then
parsed with svgelements for style/transform resolution.
"""

from __future__ import annotations

import copy
import io
import re
from dataclasses import dataclass, field

import svgelements as se
import xml.etree.ElementTree as ET

from .colors import normalize

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"


class SVGLoadError(ValueError):
    pass


@dataclass
class LoadedShape:
    """One drawable element with resolved geometry and paint."""

    path: se.Path                 # reified: transforms baked in
    fill: str | None              # '#rrggbb' or None
    stroke: str | None
    stroke_width: float           # user units, transform-scaled
    linecap: str                  # butt|round|square
    linejoin: str                 # miter|round|bevel
    miterlimit: float
    fill_rule: str                # nonzero|evenodd
    element_id: str | None


@dataclass
class TextLabel:
    text: str
    x: float
    y: float


@dataclass
class LayerInfo:
    name: str
    visible: bool
    index: int


@dataclass
class LoadedLayer:
    name: str
    shapes: list[LoadedShape] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _layer_name(g: ET.Element, index: int) -> str:
    return (
        g.get("data-layer")
        or g.get(f"{{{INKSCAPE_NS}}}label")
        or g.get("id")
        or f"layer-{index}"
    )


def _is_background(g: ET.Element) -> bool:
    return "bg" in (g.get("class") or "").split()

def _is_hidden(el: ET.Element) -> bool:
    style = el.get("style") or ""
    if re.search(r"display\s*:\s*none", style):
        return True
    return el.get("display") == "none"


def _layer_groups(root: ET.Element) -> list[ET.Element]:
    return [
        g
        for g in root
        if _local(g.tag) == "g" and not _is_background(g)
    ]


def list_layers(svg_path: str) -> list[LayerInfo]:
    root = ET.parse(svg_path).getroot()
    return [
        LayerInfo(name=_layer_name(g, i), visible=not _is_hidden(g), index=i)
        for i, g in enumerate(_layer_groups(root))
    ]


def _select_layer(root: ET.Element, layer: str | None) -> tuple[ET.Element, str]:
    groups = _layer_groups(root)
    if not groups:
        raise SVGLoadError("No layer groups found in the SVG.")
    named = [(i, g, _layer_name(g, i)) for i, g in enumerate(groups)]

    if layer is not None:
        want = layer.strip().lower()
        exact = [t for t in named if t[2].lower() == want]
        fuzzy = [t for t in named if want in t[2].lower()]
        matches = exact or fuzzy
        if not matches:
            names = ", ".join(repr(n) for _, _, n in named)
            raise SVGLoadError(f"No layer matching {layer!r}. Layers: {names}")
        if len(matches) > 1:
            names = ", ".join(repr(n) for _, _, n in matches)
            raise SVGLoadError(f"Layer {layer!r} is ambiguous: {names}")
        return matches[0][1], matches[0][2]

    visible = [t for t in named if not _is_hidden(t[1])]
    if not visible:
        names = ", ".join(repr(n) for _, _, n in named)
        raise SVGLoadError(
            f"No visible layer found; select one with --layer. Layers: {names}"
        )
    if len(visible) > 1:
        names = ", ".join(repr(n) for _, _, n in visible)
        raise SVGLoadError(
            f"Multiple visible layers ({names}); select one with --layer."
        )
    return visible[0][1], visible[0][2]


def _isolated_svg(root: ET.Element, layer_group: ET.Element) -> str:
    """Rebuild an SVG document containing only defs/style + the chosen layer."""
    new_root = ET.Element(root.tag, dict(root.attrib))
    for child in root:
        tag = _local(child.tag)
        if tag in ("defs", "style"):
            new_root.append(copy.deepcopy(child))
    g = copy.deepcopy(layer_group)
    style = g.get("style") or ""
    style = re.sub(r"display\s*:\s*[^;]+;?", "", style)
    style = re.sub(r"visibility\s*:\s*[^;]+;?", "", style)
    g.set("style", style)
    g.attrib.pop("display", None)
    g.attrib.pop("opacity", None)  # editor artifact, not paint
    new_root.append(g)
    return ET.tostring(new_root, encoding="unicode")


_CAPS = {0: "butt", 1: "round", 2: "square"}
_JOINS = {0: "miter", 2: "round", 4: "bevel"}  # svgelements Linejoin enum values


def _cap_name(shape: se.Shape) -> str:
    v = shape.values.get("stroke-linecap", "butt")
    return v if v in ("butt", "round", "square") else "butt"


def _join_name(shape: se.Shape) -> str:
    v = shape.values.get("stroke-linejoin", "miter")
    return v if v in ("miter", "round", "bevel") else "miter"


def _scaled_stroke_width(shape: se.Shape) -> float:
    width = shape.stroke_width
    if width is None:
        return 0.0
    try:
        iw = shape.implied_stroke_width
        if iw is not None:
            return float(iw)
    except (AttributeError, TypeError):
        pass
    return float(width)


def load_layer(svg_path: str, layer: str | None = None) -> LoadedLayer:
    """Load one layer of the SVG into resolved shapes and text labels."""
    root = ET.parse(svg_path).getroot()
    group, name = _select_layer(root, layer)
    doc = _isolated_svg(root, group)
    svg = se.SVG.parse(io.StringIO(doc), reify=True, ppi=96)

    out = LoadedLayer(name=name)
    seen_warn: set[str] = set()

    def warn(msg: str) -> None:
        if msg not in seen_warn:
            seen_warn.add(msg)
            out.warnings.append(msg)

    for el in svg.elements():
        if isinstance(el, se.Text):
            if el.text:
                out.labels.append(TextLabel(text=el.text.strip(), x=float(el.x), y=float(el.y)))
            continue
        if not isinstance(el, se.Shape):
            continue
        if isinstance(el, (se.Group, se.SVG)):
            continue

        raw_fill = el.values.get("fill", "")
        if isinstance(raw_fill, str) and raw_fill.startswith("url("):
            warn(f"Skipping paint server fill {raw_fill!r} (gradients/patterns unsupported).")
            fill = None
        else:
            fill = normalize(el.fill)
        stroke = normalize(el.stroke)
        width = _scaled_stroke_width(el) if stroke else 0.0
        if stroke and width <= 0:
            stroke = None
        if fill is None and stroke is None:
            continue

        try:
            path = abs(se.Path(el))
        except (ValueError, TypeError) as exc:
            warn(f"Skipping unconvertible element {el.id or type(el).__name__}: {exc}")
            continue
        if len(path) == 0:
            continue

        fill_alpha = getattr(el.fill, "alpha", None)
        if fill is not None and fill_alpha not in (None, 255):
            warn(
                f"Element {el.id or '?'} has partial fill opacity; printing it opaque."
            )

        out.shapes.append(
            LoadedShape(
                path=path,
                fill=fill,
                stroke=stroke,
                stroke_width=width,
                linecap=_cap_name(el),
                linejoin=_join_name(el),
                miterlimit=float(el.values.get("stroke-miterlimit", 4) or 4),
                fill_rule=str(el.values.get("fill-rule", "nonzero") or "nonzero"),
                element_id=el.id,
            )
        )

    if not out.shapes:
        raise SVGLoadError(f"Layer {name!r} contains no drawable shapes.")
    return out
