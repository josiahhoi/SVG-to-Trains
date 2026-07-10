import pytest
from shapely.geometry import box

from svg2trains.hull import visual_hull
from svg2trains.partition import (
    directional_crust,
    dominant_color,
    partition_projection,
    partition_side,
)

L, W, H = 100.0, 30.0, 40.0
DIMS = (L, W, H)
BAND_H = 10.0  # red band at the bottom of the side view

SIDE_REGIONS = {
    "#ff0000": box(0, 0, L, BAND_H),
    "#0000ff": box(0, BAND_H, L, H),
}
TOP_REGIONS = {"#00ff00": box(0, -W / 2, L, W / 2)}
FRONT_REGIONS = {"#ffff00": box(-W / 2, 0, W / 2, H)}


@pytest.fixture
def hull():
    return visual_hull(
        {
            "side": box(0, 0, L, H),
            "top": box(0, -W / 2, L, W / 2),
            "front": box(-W / 2, 0, W / 2, H),
            "back": box(-W / 2, 0, W / 2, H),
        },
        DIMS,
    )


def test_side_mode_volumes(hull):
    parts = partition_side(hull, SIDE_REGIONS, DIMS)
    by_color = {p.color: p for p in parts}
    assert by_color["#ff0000"].volume == pytest.approx(L * W * BAND_H, rel=1e-9)
    assert by_color["#0000ff"].volume == pytest.approx(L * W * (H - BAND_H), rel=1e-9)
    total = sum(p.volume for p in parts)
    assert total == pytest.approx(hull.volume(), rel=1e-9)


def test_directional_crust_volumes(hull):
    d = 1.2
    assert directional_crust(hull, "top", d).volume() == pytest.approx(L * W * d, rel=1e-9)
    assert directional_crust(hull, "side", d).volume() == pytest.approx(
        2 * L * H * d, rel=1e-9
    )
    assert directional_crust(hull, "front", d).volume() == pytest.approx(
        W * H * d, rel=1e-9
    )


def test_projection_mode_exact_coverage(hull):
    d = 1.2
    view_regions = {
        "side": SIDE_REGIONS,
        "top": TOP_REGIONS,
        "front": FRONT_REGIONS,
        "back": FRONT_REGIONS,
    }
    parts = partition_projection(
        hull, view_regions, DIMS, shell_depth=d, core_color="#999999"
    )
    total = sum(p.volume for p in parts)
    assert total == pytest.approx(hull.volume(), rel=1e-9)

    by_color = {p.color: p for p in parts}
    # side crusts (both faces, highest priority): full L x H x d per face
    assert by_color["#ff0000"].volume == pytest.approx(2 * L * BAND_H * d, rel=1e-9)
    assert by_color["#0000ff"].volume == pytest.approx(
        2 * L * (H - BAND_H) * d, rel=1e-9
    )
    # top crust minus the side crusts' outer strips
    assert by_color["#00ff00"].volume == pytest.approx(L * (W - 2 * d) * d, rel=1e-9)
    # front + back crusts minus side strips and top layer
    assert by_color["#ffff00"].volume == pytest.approx(
        2 * (W - 2 * d) * (H - d) * d, rel=1e-9
    )
    # core: inset by d on sides and ends, d on top, open to the bottom
    assert by_color["#999999"].volume == pytest.approx(
        (L - 2 * d) * (W - 2 * d) * (H - d), rel=1e-9
    )
    assert by_color["#999999"].provenance == "core"


def test_projection_core_color_override(hull):
    view_regions = {"side": SIDE_REGIONS, "top": TOP_REGIONS, "front": FRONT_REGIONS}
    parts = partition_projection(
        hull, view_regions, DIMS, shell_depth=1.2, core_color="#123456"
    )
    colors = {p.color for p in parts}
    assert "#123456" in colors
    total = sum(p.volume for p in parts)
    assert total == pytest.approx(hull.volume(), rel=1e-9)


def test_dominant_color():
    view_regions = {"side": SIDE_REGIONS, "top": TOP_REGIONS}
    # blue: 100x30=3000, red: 100x10=1000, green: 100x30=3000 -> blue/green tie
    # resolved deterministically (first of the sorted max-area colors)
    assert dominant_color(view_regions) == "#0000ff"
    assert dominant_color({"side": {"#ff0000": box(0, 0, 10, 10)}}) == "#ff0000"


def test_slivers_absorbed(hull):
    regions = dict(SIDE_REGIONS)
    regions["#abcdef"] = box(0, H - 0.0001, L, H)  # ~0.3 mm^3 sliver
    parts = partition_side(hull, regions, DIMS)
    colors = {p.color for p in parts}
    assert "#abcdef" not in colors
    assert sum(p.volume for p in parts) == pytest.approx(hull.volume(), rel=1e-6)
