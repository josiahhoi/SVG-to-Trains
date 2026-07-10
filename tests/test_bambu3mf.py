import json
import re
import zipfile
import xml.etree.ElementTree as ET

import pytest
from shapely.geometry import box

from svg2trains.bambu3mf import project_settings, write_3mf
from svg2trains.hull import visual_hull
from svg2trains.mesher import to_mesh_parts, validate_watertight
from svg2trains.partition import partition_side

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"

L, W, H = 100.0, 30.0, 40.0


@pytest.fixture
def parts():
    hull = visual_hull(
        {
            "side": box(0, 0, L, H),
            "top": box(0, -W / 2, L, W / 2),
            "front": box(-W / 2, 0, W / 2, H),
            "back": box(-W / 2, 0, W / 2, H),
        },
        (L, W, H),
    )
    color_parts = partition_side(
        hull, {"#ff0000": box(0, 0, L, 10), "#0000ff": box(0, 10, L, H)}, (L, W, H)
    )
    slots = {"#ff0000": 1, "#0000ff": 2}
    return to_mesh_parts(color_parts, slots)


def test_mesh_parts_placed_and_watertight(parts):
    for part in parts:
        validate_watertight(part)
    lo_z = min(p.bbox[2] for p in parts)
    assert lo_z == pytest.approx(0)
    cx = (min(p.bbox[0] for p in parts) + max(p.bbox[3] for p in parts)) / 2
    cy = (min(p.bbox[1] for p in parts) + max(p.bbox[4] for p in parts)) / 2
    assert cx == pytest.approx(0)
    assert cy == pytest.approx(0)
    assert [p.extruder for p in parts] == [1, 2]


def test_write_3mf_structure(parts, tmp_path):
    out = tmp_path / "train.3mf"
    write_3mf(str(out), parts, title="box train")
    z = zipfile.ZipFile(out)
    names = set(z.namelist())
    assert {
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
    } <= names

    model = ET.fromstring(z.read("3D/3dmodel.model"))
    assert model.get("unit") == "millimeter"
    assert model.get("requiredextensions") == "p"
    metas = {
        m.get("name"): (m.text or "")
        for m in model.findall(f"{{{CORE_NS}}}metadata")
    }
    assert metas["Application"].startswith("BambuStudio-")
    assert metas["BambuStudio:3mfVersion"] == "1"

    objects = model.findall(f".//{{{CORE_NS}}}object")
    assert len(objects) == 3  # 2 meshes + 1 parent
    for obj in objects:
        uuid = obj.get(f"{{{PROD_NS}}}UUID")
        assert re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", uuid)
    parent = objects[-1]
    comps = parent.findall(f".//{{{CORE_NS}}}component")
    assert [c.get("objectid") for c in comps] == ["1", "2"]

    item = model.find(f".//{{{CORE_NS}}}item")
    assert item.get("objectid") == "3"
    assert item.get("printable") == "1"
    assert item.get("transform").split()[-3:] == ["128", "128", "0"]


def test_model_settings_extruders(parts, tmp_path):
    out = tmp_path / "train.3mf"
    write_3mf(str(out), parts, title="box train")
    z = zipfile.ZipFile(out)
    cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    obj = cfg.find("object")
    assert obj.get("id") == "3"
    part_els = obj.findall("part")
    assert [p.get("id") for p in part_els] == ["1", "2"]
    for i, p in enumerate(part_els, start=1):
        metas = {m.get("key"): m.get("value") for m in p.findall("metadata")}
        assert metas["extruder"] == str(i)
        assert p.get("subtype") == "normal_part"
        assert p.find("mesh_stat").get("face_count") not in (None, "0")
    inst = cfg.find("plate/model_instance")
    assert {m.get("key"): m.get("value") for m in inst.findall("metadata")}[
        "object_id"
    ] == "3"
    assert cfg.find("assemble/assemble_item").get("object_id") == "3"


def test_project_settings_colors_and_arrays(parts):
    cfg = project_settings(parts)
    assert cfg["filament_colour"][0] == "#FF0000"
    assert cfg["filament_colour"][1] == "#0000FF"
    n = len(cfg["filament_colour"])
    assert n >= 2
    # every per-filament array stays parallel
    assert len(cfg["filament_type"]) == n
    assert len(cfg["filament_settings_id"]) == n
    assert len(cfg["flush_volumes_matrix"]) == n * n
    assert len(cfg["flush_volumes_vector"]) == 2 * n
    assert cfg["name"] == "project_settings"
    # user's real printer profile is the default template
    assert "P2S" in cfg["printer_settings_id"]


def test_project_settings_extends_past_four():
    from svg2trains.mesher import MeshPart
    import numpy as np

    def fake(i, color):
        return MeshPart(
            name=f"p{i}", color=color, extruder=i,
            vertices=np.zeros((3, 3)), faces=np.array([[0, 1, 2]], dtype=np.uint32),
            volume=1.0, provenance="side",
        )

    parts = [fake(i + 1, f"#0000{i:02x}") for i in range(6)]
    cfg = project_settings(parts)
    n = len(cfg["filament_colour"])
    assert n == 6
    assert len(cfg["filament_type"]) == 6
    assert len(cfg["filament_extruder_variant"]) == 12  # paired key
    assert len(cfg["nozzle_temperature"]) == 12
    assert len(cfg["flush_volumes_matrix"]) == 36
    assert cfg["filament_self_index"] == [str(i // 2 + 1) for i in range(12)]


def test_reference_structure_matches_users_file(parts, tmp_path):
    """Our output mirrors the structure of the user's Bambu-saved project."""
    ref = zipfile.ZipFile("examples/Metrolink_Cab_HR.3mf")
    ref_model = ET.fromstring(ref.read("3D/3dmodel.model"))

    out = tmp_path / "train.3mf"
    write_3mf(str(out), parts)
    ours = ET.fromstring(zipfile.ZipFile(out).read("3D/3dmodel.model"))

    assert ours.get("requiredextensions") == ref_model.get("requiredextensions")
    ref_uuid_suffix = ref_model.find(f".//{{{CORE_NS}}}object").get(
        f"{{{PROD_NS}}}UUID"
    )[8:]
    our_parent = ours.findall(f".//{{{CORE_NS}}}object")[-1]
    assert our_parent.get(f"{{{PROD_NS}}}UUID")[8:] == ref_uuid_suffix

    ref_cfg = ET.fromstring(ref.read("Metadata/model_settings.config"))
    ref_part_keys = {
        m.get("key") for m in ref_cfg.find("object/part").findall("metadata")
    }
    our_cfg = ET.fromstring(
        zipfile.ZipFile(out).read("Metadata/model_settings.config")
    )
    our_part_keys = {
        m.get("key") for m in our_cfg.find("object/part").findall("metadata")
    }
    assert {"name", "matrix", "extruder"} <= our_part_keys
    assert our_part_keys <= ref_part_keys | {"extruder"}
