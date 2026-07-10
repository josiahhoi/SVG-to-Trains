import json
import zipfile
import xml.etree.ElementTree as ET

import pytest

from svg2trains.cli import main
from svg2trains.pipeline import Options, convert, convert_to_file

from conftest import write_svg

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

# 300x100 side split into a red bottom band and blue body, 300x60 top (green),
# 60x100 front (yellow) -> a box train with analytic volumes
BOX_TRAIN = """
<g data-layer="box train">
  <rect x="0" y="0" width="300" height="60" style="fill: rgb(0,255,0);"/>
  <text x="100" y="90">top view</text>

  <rect x="0" y="300" width="300" height="100" style="fill: rgb(0,0,255);"/>
  <rect x="0" y="375" width="300" height="25" style="fill: rgb(255,0,0);"/>
  <text x="100" y="440">side view</text>

  <rect x="0" y="600" width="60" height="100" style="fill: rgb(255,255,0);"/>
  <text x="10" y="740">Front/back</text>
</g>
"""


def test_box_train_side_mode(tmp_path):
    svg = write_svg(tmp_path, BOX_TRAIN)
    result = convert(str(svg), Options(length=150, check=True))
    assert (result.length, result.width, result.height) == pytest.approx((150, 30, 50))
    by_color = {p.color: p for p in result.parts}
    # side mode: full-width slabs; red band is the bottom quarter
    assert by_color["#ff0000"].volume == pytest.approx(150 * 30 * 12.5, rel=1e-6)
    assert by_color["#0000ff"].volume == pytest.approx(150 * 30 * 37.5, rel=1e-6)
    assert set(by_color) == {"#ff0000", "#0000ff"}
    # slots follow side-view paint order (blue painted first)
    assert result.slots == {"#0000ff": 1, "#ff0000": 2}


def test_box_train_projection_mode(tmp_path):
    svg = write_svg(tmp_path, BOX_TRAIN)
    result = convert(
        str(svg),
        Options(length=150, color_mode="projection", core_color="#999999", check=True),
    )
    total = sum(p.volume for p in result.parts)
    assert total == pytest.approx(150 * 30 * 50, rel=1e-6)
    colors = {p.color for p in result.parts}
    assert {"#ff0000", "#0000ff", "#00ff00", "#ffff00", "#999999"} == colors


def test_box_train_3mf_file(tmp_path):
    svg = write_svg(tmp_path, BOX_TRAIN)
    out = tmp_path / "out.3mf"
    convert_to_file(str(svg), str(out), Options(length=150))
    z = zipfile.ZipFile(out)
    model = ET.fromstring(z.read("3D/3dmodel.model"))
    objects = model.findall(f".//{{{CORE_NS}}}object")
    assert len(objects) == 3  # blue, red, parent
    cfg = json.loads(z.read("Metadata/project_settings.config"))
    assert cfg["filament_colour"][:2] == ["#0000FF", "#FF0000"]


def test_cli_convert_and_list(tmp_path, capsys):
    svg = write_svg(tmp_path, BOX_TRAIN)
    out = tmp_path / "cli.3mf"
    rc = main(["convert", str(svg), "-o", str(out), "--length", "150", "--check"])
    assert rc == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "2 color part(s)" in captured.out

    rc = main(["list-views", str(svg)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "side  label='side view'" in captured.out

    rc = main(["list-colors", str(svg), "--length", "150"])
    assert rc == 0


def test_cli_error_handling(tmp_path, capsys):
    svg = write_svg(tmp_path, '<g data-layer="empty"><text x="0" y="0">hi</text></g>')
    rc = main(["convert", str(svg)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_real_metrolink_cab_both_modes(real_svg, tmp_path):
    out = tmp_path / "cab.3mf"
    result = convert_to_file(
        str(real_svg),
        str(out),
        Options(layer="Metrolink Cab", length=63.5, check=True),
    )
    assert result.length == pytest.approx(63.5)
    assert result.height == pytest.approx(25.5, abs=0.5)
    colors = {p.color for p in result.parts}
    assert {"#c2c3c7", "#000000", "#03fffb"} <= colors
    assert len(result.parts) == 4
    # matches the scale of the user's hand-built Metrolink_Cab_HR.3mf
    grey = next(p for p in result.parts if p.color == "#c2c3c7")
    assert grey.extruder == 1

    proj = convert(
        str(real_svg),
        Options(layer="Metrolink Cab", length=63.5, color_mode="projection", check=True),
    )
    assert sum(p.volume for p in proj.parts) == pytest.approx(
        sum(p.volume for p in result.parts), rel=1e-4
    )


def test_real_layer8_converts(real_svg):
    result = convert(str(real_svg), Options(length=100, check=True))
    assert result.layer == "Layer 8"
    assert len(result.parts) >= 2
    assert all(p.volume > 0 for p in result.parts)
