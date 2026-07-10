import pytest
from shapely.geometry import Polygon, box

from svg2trains.hull import HullError, view_prism, visual_hull

L, W, H = 100.0, 30.0, 40.0
DIMS = (L, W, H)

SIDE = box(0, 0, L, H)             # (X, Z)
TOP = box(0, -W / 2, L, W / 2)     # (X, Y)
FRONT = box(-W / 2, 0, W / 2, H)   # (Y, Z)


def test_prism_orientations():
    top = view_prism("top", TOP, DIMS)
    assert top.bounding_box() == pytest.approx((0, -W / 2, -2, L, W / 2, H + 2))
    side = view_prism("side", SIDE, DIMS)
    assert side.bounding_box() == pytest.approx((0, -W / 2 - 2, 0, L, W / 2 + 2, H))
    front = view_prism("front", FRONT, DIMS)
    assert front.bounding_box() == pytest.approx((-2, -W / 2, 0, L + 2, W / 2, H))


def test_box_train_hull_volume():
    hull = visual_hull({"side": SIDE, "top": TOP, "front": FRONT, "back": FRONT}, DIMS)
    assert hull.volume() == pytest.approx(L * W * H, rel=1e-9)
    assert hull.bounding_box() == pytest.approx((0, -W / 2, 0, L, W / 2, H))


def test_wedge_hull_volume():
    # side view is a triangle -> hull is a wedge of half the box volume
    tri = Polygon([(0, 0), (L, 0), (L, H)])
    hull = visual_hull({"side": tri, "top": TOP, "front": FRONT, "back": FRONT}, DIMS)
    assert hull.volume() == pytest.approx(L * W * H / 2, rel=1e-9)


def test_hole_survives_extrusion():
    donut = Polygon(
        [(0, 0), (L, 0), (L, H), (0, H)],
        holes=[[(30, 10), (30, 30), (60, 30), (60, 10)]],
    )
    hull = visual_hull({"side": donut, "top": TOP, "front": FRONT, "back": FRONT}, DIMS)
    assert hull.volume() == pytest.approx((L * H - 30 * 20) * W, rel=1e-9)
    assert hull.genus() == 1  # a through-hole


def test_disjoint_views_error():
    far_top = box(1000, -W / 2, 1100, W / 2)
    with pytest.raises(HullError):
        visual_hull({"side": SIDE, "top": far_top, "front": FRONT, "back": FRONT}, DIMS)


def test_empty_silhouette_error():
    with pytest.raises(HullError):
        visual_hull({"side": Polygon(), "top": TOP, "front": FRONT, "back": FRONT}, DIMS)
