"""Outline-drawn doors/windows are surface detail, not holes (real-file bugs)."""

import pytest

from svg2trains.pipeline import Options, convert

from conftest import write_svg

# Box train whose front view has a door drawn ONLY as outlines (transparent
# fill), with a thick door-frame stroke that overhangs the face fill at the
# bottom edge — the exact style of the user's drawing app. Without hole
# filling this carved a tunnel through the train plus a thin full-width slab
# gap where the stroke overhang shifted the drawing's bounding box.
OUTLINED_DOOR = """
<g data-layer="train">
  <rect x="0" y="0" width="300" height="60" style="fill: rgb(0,255,0);"/>
  <text x="100" y="90">top view</text>

  <rect x="0" y="300" width="300" height="100" style="fill: rgb(0,0,255);"/>
  <text x="100" y="440">side view</text>

  <path d="M 20 700 L 0 700 L 0 600 L 60 600 L 60 700 L 40 700 L 40 640 L 20 640 Z"
        style="fill: rgb(255,255,0); stroke: rgb(0,0,0); stroke-width: 1;"/>
  <path d="M 20 700 L 20 640 L 40 640 L 40 700 Z"
        style="fill: rgba(0,0,0,0); stroke: rgb(0,0,0); stroke-width: 6;"/>
  <text x="10" y="740">Front/back</text>
</g>
"""


def test_outlined_door_does_not_tunnel(tmp_path):
    svg = write_svg(tmp_path, OUTLINED_DOOR)
    result = convert(str(svg), Options(length=150, check=True))
    total = sum(p.volume for p in result.parts)
    # solid box: the door outline must neither tunnel through the length nor
    # cut a slab where the frame stroke overhangs the face fill
    assert total == pytest.approx(
        result.length * result.width * result.height, rel=0.01
    )


def test_outlined_door_projection_mode(tmp_path):
    svg = write_svg(tmp_path, OUTLINED_DOOR)
    result = convert(
        str(svg), Options(length=150, color_mode="projection", check=True)
    )
    total = sum(p.volume for p in result.parts)
    assert total == pytest.approx(
        result.length * result.width * result.height, rel=0.01
    )


def test_carve_holes_opt_in(tmp_path):
    svg = write_svg(tmp_path, OUTLINED_DOOR)
    solid = convert(str(svg), Options(length=150))
    carved = convert(str(svg), Options(length=150, carve_holes=True, check=True))
    solid_total = sum(p.volume for p in solid.parts)
    carved_total = sum(p.volume for p in carved.parts)
    assert carved_total < solid_total  # the door interior became a channel


def test_real_trains3_cab_is_solid():
    from pathlib import Path

    svg = Path(__file__).resolve().parent.parent / "examples" / "Trains 3.svg"
    if not svg.exists():  # pragma: no cover
        pytest.skip("example not present")
    result = convert(str(svg), Options(layer="Metrolink Cab", length=150, check=True))
    total = sum(p.volume for p in result.parts)
    # full-height cross-sections everywhere below the roofline slope: the
    # model must be substantially solid (no door tunnels, no slab gaps)
    assert total > 0.9 * result.length * result.width * result.height * 0.9
    assert len(result.parts) == 4
