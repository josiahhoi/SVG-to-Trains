import pytest

from svg2trains.svgload import load_layer
from svg2trains.views import ViewDetectionError, detect_views, match_label

from conftest import write_svg


def test_match_label_basics():
    assert match_label("top view") == {"top"}
    assert match_label("TOP") == {"top"}
    assert match_label("Side View") == {"side"}
    assert match_label("Rear view") == {"back"}
    assert match_label("plan") == {"top"}


def test_match_label_front_back_combo():
    assert match_label("Front/back") == {"front", "back"}
    assert match_label("front & back") == {"front", "back"}


def test_match_label_rejects_annotations():
    assert match_label("Front portion slopes back here") is None
    assert match_label("ceiling") is None
    assert match_label("") is None


def test_match_label_roof_synonym():
    assert match_label("roof") == {"top"}


def test_match_label_override():
    assert match_label("ceiling", {"ceiling": "top"}) == {"top"}


FOUR_VIEWS = """
<g data-layer="train">
  <rect x="0" y="0" width="300" height="100" style="fill: rgb(0,0,0);"/>
  <text x="100" y="130">top view</text>

  <rect x="0" y="300" width="300" height="80" style="fill: rgb(255,0,0);"/>
  <text x="100" y="420">side view</text>

  <rect x="0" y="600" width="100" height="80" style="fill: rgb(0,0,255);"/>
  <text x="10" y="720">Front view</text>

  <rect x="200" y="600" width="100" height="80" style="fill: rgb(0,255,0);"/>
  <text x="210" y="720">back</text>
</g>
"""


def test_detect_four_views(tmp_path):
    layer = load_layer(str(write_svg(tmp_path, FOUR_VIEWS)))
    vs = detect_views(layer)
    assert set(vs.views) == {"top", "side", "front", "back"}
    assert vs.views["top"].shapes[0].fill == "#000000"
    assert vs.views["side"].shapes[0].fill == "#ff0000"
    assert vs.views["front"].shapes[0].fill == "#0000ff"
    assert vs.views["back"].shapes[0].fill == "#00ff00"
    assert not vs.views["front"].shared_with_back


SHARED_FRONT_BACK = """
<g data-layer="train">
  <rect x="0" y="0" width="300" height="100" style="fill: rgb(0,0,0);"/>
  <text x="100" y="130">top view</text>
  <rect x="0" y="300" width="300" height="80" style="fill: rgb(255,0,0);"/>
  <text x="100" y="420">side view</text>
  <rect x="0" y="600" width="100" height="80" style="fill: rgb(0,0,255);"/>
  <text x="10" y="720">Front/back</text>
  <text x="10" y="760">Front portion slopes back here</text>
</g>
"""


def test_detect_shared_front_back(tmp_path):
    layer = load_layer(str(write_svg(tmp_path, SHARED_FRONT_BACK)))
    vs = detect_views(layer)
    assert vs.views["front"].shared_with_back
    assert vs.views["back"].shapes is vs.views["front"].shapes


MISSING_FRONT = """
<g data-layer="train">
  <rect x="0" y="0" width="300" height="100" style="fill: rgb(0,0,0);"/>
  <text x="100" y="130">top view</text>
  <rect x="0" y="300" width="300" height="80" style="fill: rgb(255,0,0);"/>
  <text x="100" y="420">side view</text>
</g>
"""


def test_missing_front_view_error(tmp_path):
    layer = load_layer(str(write_svg(tmp_path, MISSING_FRONT)))
    with pytest.raises(ViewDetectionError) as err:
        detect_views(layer)
    msg = str(err.value)
    assert "top view" in msg and "--view-box" in msg


def test_back_mirrors_front_when_absent(tmp_path):
    body = MISSING_FRONT.replace(
        '<text x="100" y="420">side view</text>',
        '<text x="100" y="420">side view</text>'
        '<rect x="0" y="600" width="100" height="80" style="fill: rgb(0,0,255);"/>'
        '<text x="10" y="720">front</text>',
    )
    layer = load_layer(str(write_svg(tmp_path, body)))
    vs = detect_views(layer)
    assert vs.views["back"].shared_with_back
    assert any("mirroring" in w for w in vs.warnings)


def test_view_label_override(tmp_path):
    body = FOUR_VIEWS.replace(">top view<", ">ceiling<")
    layer = load_layer(str(write_svg(tmp_path, body)))
    vs = detect_views(layer, view_labels={"ceiling": "top"})
    assert vs.views["top"].shapes[0].fill == "#000000"
    assert vs.views["top"].label == "ceiling"


def test_unlabeled_views_inferred_by_dimensions(tmp_path):
    body = """
    <g data-layer="train">
      <rect x="0" y="0" width="300" height="60" style="fill: rgb(0,0,0);"/>
      <rect x="0" y="300" width="300" height="100" style="fill: rgb(255,0,0);"/>
      <rect x="0" y="600" width="60" height="100" style="fill: rgb(0,0,255);"/>
    </g>
    """
    layer = load_layer(str(write_svg(tmp_path, body)))
    vs = detect_views(layer)
    # side is L x H (300x100), top is L x W (300x60), front is W x H (60x100)
    assert vs.views["top"].shapes[0].fill == "#000000"
    assert vs.views["side"].shapes[0].fill == "#ff0000"
    assert vs.views["front"].shapes[0].fill == "#0000ff"
    assert any("inferred" in w for w in vs.warnings)


def test_view_box_override(tmp_path):
    body = """
    <g data-layer="train">
      <rect x="0" y="0" width="300" height="100" style="fill: rgb(0,0,0);"/>
      <rect x="0" y="300" width="300" height="80" style="fill: rgb(255,0,0);"/>
      <rect x="0" y="600" width="100" height="80" style="fill: rgb(0,0,255);"/>
    </g>
    """
    layer = load_layer(str(write_svg(tmp_path, body)))
    vs = detect_views(
        layer,
        view_boxes={
            "top": (0, 0, 300, 200),
            "side": (0, 250, 300, 200),
            "front": (0, 550, 300, 200),
        },
    )
    assert vs.views["top"].shapes[0].fill == "#000000"
    assert vs.views["side"].shapes[0].fill == "#ff0000"
    assert vs.views["front"].shapes[0].fill == "#0000ff"
    assert vs.views["back"].shared_with_back


def test_real_svg_layer8_views(real_svg):
    layer = load_layer(str(real_svg), layer="Layer 8")
    vs = detect_views(layer)
    assert {"top", "side", "front", "back"} <= set(vs.views)
    assert vs.views["front"].shared_with_back or vs.views["back"] is not None
    # side view should be the widest drawing (train profile)
    sb = vs.views["side"].bbox
    fb = vs.views["front"].bbox
    assert (sb[2] - sb[0]) > (fb[2] - fb[0])
