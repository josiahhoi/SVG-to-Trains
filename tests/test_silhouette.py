import numpy as np
import pytest
import svgelements as se

from svg2trains.silhouette import (
    PaintedRegion,
    color_regions,
    fill_geometry,
    flatten_path,
    painted_regions,
    silhouette,
    stroke_geometry,
)
from svg2trains.svgload import load_layer

from conftest import write_svg


def path_of(d: str) -> se.Path:
    return se.Path(d)


def test_flatten_rect_like_path():
    subs = flatten_path(path_of("M 0 0 L 10 0 L 10 5 L 0 5 Z"), tolerance=0.1)
    assert len(subs) == 1
    assert subs[0].closed
    assert len(subs[0].points) == 4


def test_flatten_circle_accuracy():
    circle = se.Path(se.Circle(cx=0, cy=0, r=10))
    subs = flatten_path(circle, tolerance=0.05)
    geom = fill_geometry(subs, "nonzero")
    assert geom.area == pytest.approx(np.pi * 100, rel=0.01)


def test_fill_evenodd_donut():
    d = "M 0 0 L 100 0 L 100 100 L 0 100 Z M 25 25 L 75 25 L 75 75 L 25 75 Z"
    subs = flatten_path(path_of(d), tolerance=0.1)
    donut = fill_geometry(subs, "evenodd")
    assert donut.area == pytest.approx(100 * 100 - 50 * 50)
    # nonzero with both rings wound the same way fills the hole too
    solid = fill_geometry(subs, "nonzero")
    assert solid.area == pytest.approx(100 * 100)


def test_fill_nonzero_opposite_winding_has_hole():
    d = "M 0 0 L 100 0 L 100 100 L 0 100 Z M 25 25 L 25 75 L 75 75 L 75 25 Z"
    subs = flatten_path(path_of(d), tolerance=0.1)
    donut = fill_geometry(subs, "nonzero")
    assert donut.area == pytest.approx(100 * 100 - 50 * 50)


def test_stroke_width_open_line():
    subs = flatten_path(path_of("M 0 0 L 100 0"), tolerance=0.1)
    geom = stroke_geometry(subs, width=10, linecap="butt")
    assert geom.area == pytest.approx(100 * 10, rel=1e-6)
    square = stroke_geometry(subs, width=10, linecap="square")
    assert square.area == pytest.approx(110 * 10, rel=1e-6)


def test_stroke_closed_ring():
    subs = flatten_path(path_of("M 0 0 L 100 0 L 100 100 L 0 100 Z"), tolerance=0.1)
    geom = stroke_geometry(subs, width=10, linejoin="miter")
    assert geom.area == pytest.approx(110**2 - 90**2, rel=1e-6)


def test_painted_regions_fill_then_stroke(tmp_path):
    body = """
    <g data-layer="L1">
      <rect x="0" y="0" width="100" height="50"
            style="fill: rgb(255,0,0); stroke: rgb(0,0,0); stroke-width: 4;"/>
    </g>
    """
    layer = load_layer(str(write_svg(tmp_path, body)))
    regions = painted_regions(layer.shapes, tolerance=0.1)
    assert [r.color for r in regions] == ["#ff0000", "#000000"]
    assert regions[0].source.startswith("fill:")
    assert regions[1].source.startswith("stroke:")


def test_color_regions_paint_order():
    bottom = PaintedRegion("#ff0000", fill_geometry(
        flatten_path(path_of("M 0 0 L 100 0 L 100 100 L 0 100 Z"), 0.1), "nonzero"), "fill:a")
    top = PaintedRegion("#0000ff", fill_geometry(
        flatten_path(path_of("M 50 0 L 150 0 L 150 100 L 50 100 Z"), 0.1), "nonzero"), "fill:b")
    out = color_regions([bottom, top])
    assert out["#0000ff"].area == pytest.approx(100 * 100)
    assert out["#ff0000"].area == pytest.approx(50 * 100)  # covered part removed
    sil = silhouette([bottom, top])
    assert sil.area == pytest.approx(150 * 100)
    # regions partition the silhouette exactly
    assert sum(g.area for g in out.values()) == pytest.approx(sil.area)
    assert out["#ff0000"].intersection(out["#0000ff"]).area == pytest.approx(0)


def test_color_regions_same_color_merges():
    a = PaintedRegion("#000000", fill_geometry(
        flatten_path(path_of("M 0 0 L 10 0 L 10 10 L 0 10 Z"), 0.1), "nonzero"), "fill:a")
    b = PaintedRegion("#000000", fill_geometry(
        flatten_path(path_of("M 20 0 L 30 0 L 30 10 L 20 10 Z"), 0.1), "nonzero"), "fill:b")
    out = color_regions([a, b])
    assert list(out) == ["#000000"]
    assert out["#000000"].area == pytest.approx(200)


def test_min_area_filter():
    big = PaintedRegion("#000000", fill_geometry(
        flatten_path(path_of("M 0 0 L 10 0 L 10 10 L 0 10 Z"), 0.1), "nonzero"), "fill:a")
    tiny = PaintedRegion("#ff0000", fill_geometry(
        flatten_path(path_of("M 20 0 L 20.1 0 L 20.1 0.1 L 20 0.1 Z"), 0.1), "nonzero"), "fill:b")
    out = color_regions([big, tiny], min_area=1.0)
    assert "#ff0000" not in out
