import pytest
from svgelements import Color

from svg2trains.colors import (
    ColorError,
    assign_slots,
    distance,
    merge_colors,
    normalize,
)


def test_normalize_hex_and_rgb():
    assert normalize("rgb(3, 255, 251)") == "#03fffb"
    assert normalize("#C2C3C7") == "#c2c3c7"
    assert normalize(Color("black")) == "#000000"


def test_normalize_none_and_transparent():
    assert normalize(None) is None
    assert normalize("none") is None
    assert normalize("rgba(0, 0, 0, 0)") is None


def test_normalize_partial_alpha_is_opaque():
    assert normalize("rgba(41, 173, 255, 0.7)") == "#29adff"


def test_distance():
    assert distance("#000000", "#000000") == 0
    assert distance("#000000", "#0a0514") == 20


def test_merge_colors():
    mapping = merge_colors(["#000000", "#050505", "#ff0000"], threshold=10)
    assert mapping == {"#000000": "#000000", "#050505": "#000000", "#ff0000": "#ff0000"}
    nomerge = merge_colors(["#000000", "#050505"], threshold=0)
    assert nomerge["#050505"] == "#050505"


def test_assign_slots_deterministic():
    slots = assign_slots(["#aa0000", "#00bb00", "#aa0000", "#0000cc"])
    assert slots == {"#aa0000": 1, "#00bb00": 2, "#0000cc": 3}


def test_assign_slots_cap():
    colors = [f"#{i:02x}0000" for i in range(17)]
    with pytest.raises(ColorError):
        assign_slots(colors)
