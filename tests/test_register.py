import pytest
from shapely.affinity import affine_transform
from shapely.geometry import Point, box

from svg2trains.register import Registration, RegistrationError, register

# a 300x100 side, 300x60 top, 60x100 front (user units), i.e. L:W:H = 300:60:100
BOXES = {
    "side": (0.0, 300.0, 300.0, 400.0),
    "top": (0.0, 0.0, 300.0, 60.0),
    "front": (0.0, 600.0, 60.0, 700.0),
}


def test_dimensions_from_length():
    reg = register(BOXES, length=150)
    assert reg.length == pytest.approx(150)
    assert reg.width == pytest.approx(30)
    assert reg.height == pytest.approx(50)


def test_dimensions_from_height_and_width():
    assert register(BOXES, height=50).length == pytest.approx(150)
    assert register(BOXES, width=30).length == pytest.approx(150)


def test_default_length_warns():
    reg = register(BOXES)
    assert reg.length == pytest.approx(150)
    assert any("defaulting" in w for w in reg.warnings)


def test_two_sizes_rejected():
    with pytest.raises(RegistrationError):
        register(BOXES, length=100, width=30)


def test_side_transform_maps_and_flips():
    reg = register(BOXES, length=150)
    side = affine_transform(box(*BOXES["side"]), reg.transforms["side"])
    assert side.bounds == pytest.approx((0, 0, 150, 50))
    # SVG top edge of the drawing (y=300) is the TOP of the train (Z=H)
    pt = affine_transform(Point(0, 300), reg.transforms["side"])
    assert (pt.x, pt.y) == pytest.approx((0, 50))


def test_top_transform_centers_width():
    reg = register(BOXES, length=150)
    top = affine_transform(box(*BOXES["top"]), reg.transforms["top"])
    assert top.bounds == pytest.approx((0, -15, 150, 15))


def test_front_transform_mirrors_vs_back():
    reg = register(BOXES, length=150)
    front = affine_transform(box(*BOXES["front"]), reg.transforms["front"])
    assert front.bounds == pytest.approx((-15, 0, 15, 50))
    # a feature at the drawing's left edge lands at +Y for front, -Y for back
    p_front = affine_transform(Point(0, 700), reg.transforms["front"])
    p_back = affine_transform(Point(0, 700), reg.transforms["back"])
    assert p_front.x == pytest.approx(15)
    assert p_back.x == pytest.approx(-15)
    assert p_front.y == pytest.approx(0)  # bottom of drawing = Z 0


def test_no_back_mirror():
    # see-through convention: back drawing oriented exactly like the front
    reg = register(BOXES, length=150, no_back_mirror=True)
    p_front = affine_transform(Point(0, 700), reg.transforms["front"])
    p_back = affine_transform(Point(0, 700), reg.transforms["back"])
    assert p_back.x == pytest.approx(p_front.x)


def test_mismatch_warning_and_error():
    slightly_off = dict(BOXES, front=(0.0, 600.0, 62.0, 700.0))  # 3% width off
    reg = register(slightly_off, length=150)
    assert any("disagree" in w for w in reg.warnings)

    badly_off = dict(BOXES, front=(0.0, 600.0, 120.0, 700.0))  # 50% off
    with pytest.raises(RegistrationError):
        register(badly_off, length=150)


def test_missing_view():
    with pytest.raises(RegistrationError):
        register({"side": BOXES["side"], "top": BOXES["top"]}, length=150)


def test_anisotropic_rescale_exact():
    # top view drawn 5% short: still lands exactly on the canonical frame
    squished = dict(BOXES, top=(0.0, 0.0, 285.0, 60.0))
    reg = register(squished, length=150)
    top = affine_transform(box(*squished["top"]), reg.transforms["top"])
    assert top.bounds == pytest.approx((0, -reg.width / 2, 150, reg.width / 2))
