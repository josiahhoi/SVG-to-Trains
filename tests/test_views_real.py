"""View detection against the user's real drawing file."""

from svg2trains.svgload import load_layer
from svg2trains.views import detect_views


def test_layer8_all_views_labeled(real_svg):
    layer = load_layer(str(real_svg), layer="Layer 8")
    vs = detect_views(layer)
    assert vs.views["top"].label == "top view"
    assert vs.views["side"].label == "side view"
    assert vs.views["front"].label == "Front view"
    assert vs.views["back"].shared_with_back  # mirrored front


def test_metrolink_cab_roof_and_inference(real_svg):
    layer = load_layer(str(real_svg), layer="Metrolink Cab")
    vs = detect_views(layer)
    assert vs.views["top"].label == "roof"
    assert vs.views["front"].label == "Front/back"
    assert vs.views["front"].shared_with_back
    assert vs.views["side"].label is None  # inferred by dimensions
    # the side view is the detail-heavy drawing
    assert len(vs.views["side"].shapes) > len(vs.views["top"].shapes)


def test_metrolink_engine_fully_inferred(real_svg):
    layer = load_layer(str(real_svg), layer="Metrolink Engine")
    vs = detect_views(layer)
    assert {"top", "side", "front", "back"} <= set(vs.views)
    sb = vs.views["side"].bbox
    tb = vs.views["top"].bbox
    fb = vs.views["front"].bbox
    L_side, H_side = sb[2] - sb[0], sb[3] - sb[1]
    L_top, W_top = tb[2] - tb[0], tb[3] - tb[1]
    W_front, H_front = fb[2] - fb[0], fb[3] - fb[1]
    assert abs(L_side - L_top) / L_side < 0.2
    assert abs(W_top - W_front) / W_top < 0.2
