import pytest

from svg2trains.svgload import SVGLoadError, list_layers, load_layer

from conftest import write_svg


LAYERED = """
<g class="bg"><rect x="0" y="0" width="1000" height="1000" style="fill: url(#nope);"/></g>
<g class="u" data-layer="Alpha" style="visibility: visible; display: none;" opacity="0.6">
  <rect x="10" y="10" width="100" height="50" style="fill: rgb(255, 0, 0);"/>
</g>
<g class="u current" data-layer="Beta" style="visibility: visible;">
  <rect x="10" y="10" width="100" height="50" style="fill: rgb(0, 0, 255); stroke: rgb(0,0,0); stroke-width: 4;"/>
  <path d="M 0 0 L 100 0" style="fill: rgba(0,0,0,0); stroke: rgb(3, 255, 251); stroke-width: 10;"/>
  <text x="20" y="90" style="font-size: 18px;">side view</text>
</g>
"""


def test_list_layers(tmp_path):
    layers = list_layers(str(write_svg(tmp_path, LAYERED)))
    assert [(l.name, l.visible) for l in layers] == [("Alpha", False), ("Beta", True)]


def test_load_visible_layer_by_default(tmp_path):
    layer = load_layer(str(write_svg(tmp_path, LAYERED)))
    assert layer.name == "Beta"
    assert len(layer.shapes) == 2
    rect, path = layer.shapes
    assert rect.fill == "#0000ff"
    assert rect.stroke == "#000000"
    assert rect.stroke_width == 4
    assert path.fill is None  # rgba(0,0,0,0)
    assert path.stroke == "#03fffb"
    assert path.stroke_width == 10
    assert [t.text for t in layer.labels] == ["side view"]


def test_load_hidden_layer_by_name(tmp_path):
    layer = load_layer(str(write_svg(tmp_path, LAYERED)), layer="alpha")
    assert layer.name == "Alpha"
    assert layer.shapes[0].fill == "#ff0000"


def test_unknown_layer_lists_names(tmp_path):
    with pytest.raises(SVGLoadError) as err:
        load_layer(str(write_svg(tmp_path, LAYERED)), layer="Gamma")
    assert "Alpha" in str(err.value) and "Beta" in str(err.value)


def test_transform_baked_in(tmp_path):
    body = """
    <g data-layer="L1">
      <g transform="translate(100, 200)">
        <rect x="0" y="0" width="10" height="10" style="fill: rgb(0,0,0);"/>
      </g>
    </g>
    """
    layer = load_layer(str(write_svg(tmp_path, body)))
    bbox = layer.shapes[0].path.bbox()
    assert bbox == (100.0, 200.0, 110.0, 210.0)


def test_real_svg_layers(real_svg):
    layers = list_layers(str(real_svg))
    names = [l.name for l in layers]
    assert "Metrolink Cab" in names and "Layer 8" in names
    visible = [l.name for l in layers if l.visible]
    assert visible == ["Layer 8"]


def test_real_svg_load_metrolink_cab(real_svg):
    layer = load_layer(str(real_svg), layer="Metrolink Cab")
    assert len(layer.shapes) > 30
    fills = {s.fill for s in layer.shapes if s.fill}
    assert "#03fffb" in fills and "#c2c3c7" in fills and "#000000" in fills
    assert {s.stroke_width for s in layer.shapes if s.stroke} <= {4.0, 20.0}
    labels = [t.text for t in layer.labels]
    assert "Front/back" in labels and "roof" in labels
