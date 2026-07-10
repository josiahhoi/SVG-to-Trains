"""Bambu Studio project 3MF writer.

The package layout, XML structure, UUID conventions, and config keys mirror
what BambuStudio itself reads and writes (verified against its importer in
src/libslic3r/Format/bbs_3mf.cpp and against a Bambu Studio-saved reference
project). The importer switches into "Bambu project" mode when the
Application metadata starts with "BambuStudio-"; per-part filament
assignment lives in Metadata/model_settings.config as an `extruder` key;
filament colors live in Metadata/project_settings.config, a JSON document
that tolerates partial content.
"""

from __future__ import annotations

import datetime
import io
import json
import zipfile
from importlib import resources
from xml.sax.saxutils import escape

from .mesher import MeshPart

PLATE_CENTER = (128.0, 128.0)  # 256mm bed

APPLICATION = "BambuStudio-02.00.00.00"

SUB_OBJECT_UUID_SUFFIX = "-81cb-4c03-9d28-80fed5dfa1dc"
OBJECT_UUID_SUFFIX = "-61cb-4c03-9d28-80fed5dfa1dc"
COMPONENT_UUID_SUFFIX = "-b206-40ff-9872-83e8017abed1"
BUILD_UUID = "2c7c17d8-22b5-4d84-8835-1976022ea369"
BUILD_UUID_SUFFIX = "-b1ec-4553-aec9-835e5b724bb4"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""

IDENTITY_4X4 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"
IDENTITY_3X4 = "1 0 0 0 1 0 0 0 1 0 0 0"


def _uuid(index: int, suffix: str) -> str:
    return f"{index:08x}{suffix}"


def _fmt(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def _mesh_xml(part: MeshPart) -> str:
    verts = "\n".join(
        f'     <vertex x="{_fmt(v[0])}" y="{_fmt(v[1])}" z="{_fmt(v[2])}"/>'
        for v in part.vertices
    )
    tris = "\n".join(
        f'     <triangle v1="{f[0]}" v2="{f[1]}" v3="{f[2]}"/>'
        for f in part.faces
    )
    return (
        "   <mesh>\n    <vertices>\n" + verts + "\n    </vertices>\n"
        "    <triangles>\n" + tris + "\n    </triangles>\n   </mesh>"
    )


def _model_xml(parts: list[MeshPart], title: str, date: str) -> str:
    parent_id = len(parts) + 1
    objects = []
    for i, part in enumerate(parts, start=1):
        objects.append(
            f'  <object id="{i}" p:UUID="{_uuid(i, SUB_OBJECT_UUID_SUFFIX)}" type="model">\n'
            + _mesh_xml(part)
            + "\n  </object>"
        )
    components = "\n".join(
        f'    <component objectid="{i}" '
        f'p:UUID="{_uuid(i - 1 + (parent_id << 16), COMPONENT_UUID_SUFFIX)}" '
        f'transform="{IDENTITY_3X4}"/>'
        for i in range(1, len(parts) + 1)
    )
    objects.append(
        f'  <object id="{parent_id}" p:UUID="{_uuid(parent_id, OBJECT_UUID_SUFFIX)}" type="model">\n'
        f"   <components>\n{components}\n   </components>\n"
        f"  </object>"
    )
    build_transform = (
        f"1 0 0 0 1 0 0 0 1 {_fmt(PLATE_CENTER[0])} {_fmt(PLATE_CENTER[1])} 0"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
        'requiredextensions="p">\n'
        f' <metadata name="Application">{APPLICATION}</metadata>\n'
        f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <metadata name="CreationDate">{date}</metadata>\n'
        f' <metadata name="ModificationDate">{date}</metadata>\n'
        f' <metadata name="Title">{escape(title)}</metadata>\n'
        " <resources>\n" + "\n".join(objects) + "\n </resources>\n"
        f' <build p:UUID="{BUILD_UUID}">\n'
        f'  <item objectid="{parent_id}" '
        f'p:UUID="{_uuid(parent_id, BUILD_UUID_SUFFIX)}" '
        f'transform="{build_transform}" printable="1"/>\n'
        " </build>\n"
        "</model>\n"
    )


def _model_settings_xml(parts: list[MeshPart], title: str) -> str:
    parent_id = len(parts) + 1
    part_blocks = []
    for i, part in enumerate(parts, start=1):
        part_blocks.append(
            f'  <part id="{i}" subtype="normal_part">\n'
            f'   <metadata key="name" value="{escape(part.name)}"/>\n'
            f'   <metadata key="matrix" value="{IDENTITY_4X4}"/>\n'
            f'   <metadata key="extruder" value="{part.extruder}"/>\n'
            f'   <mesh_stat face_count="{len(part.faces)}" edges_fixed="0" '
            f'degenerate_facets="0" facets_removed="0" facets_reversed="0" '
            f'backwards_edges="0"/>\n'
            f"  </part>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<config>\n"
        f' <object id="{parent_id}">\n'
        f'  <metadata key="name" value="{escape(title)}"/>\n'
        f'  <metadata key="extruder" value="1"/>\n'
        + "\n".join(part_blocks)
        + "\n </object>\n"
        " <plate>\n"
        '  <metadata key="plater_id" value="1"/>\n'
        '  <metadata key="plater_name" value=""/>\n'
        '  <metadata key="locked" value="false"/>\n'
        "  <model_instance>\n"
        f'   <metadata key="object_id" value="{parent_id}"/>\n'
        '   <metadata key="instance_id" value="0"/>\n'
        '   <metadata key="identify_id" value="128"/>\n'
        "  </model_instance>\n"
        " </plate>\n"
        " <assemble>\n"
        f'  <assemble_item object_id="{parent_id}" instance_id="0" '
        f'transform="{IDENTITY_3X4}" offset="0 0 0"/>\n'
        " </assemble>\n"
        "</config>\n"
    )


def _load_template(settings_template: str | None) -> dict:
    if settings_template:
        with open(settings_template, encoding="utf-8") as f:
            return json.load(f)
    ref = resources.files("svg2trains.data").joinpath("project_settings_template.json")
    return json.loads(ref.read_text(encoding="utf-8"))


# per-filament list keys in the template hold one entry per filament;
# a few hold two entries per filament (dual extruder variants) or N^2.
_PAIRED_NON_FILAMENT_KEYS = {
    "nozzle_temperature",
    "nozzle_temperature_initial_layer",
    "slow_down_min_speed",
    "long_retractions_when_ec",
    "retraction_distances_when_ec",
    "override_process_overhang_speed",
    "volumetric_speed_coefficients",
}


def project_settings(parts: list[MeshPart], settings_template: str | None = None) -> dict:
    """Patch the settings template's per-filament arrays for these parts."""
    cfg = _load_template(settings_template)
    base = len(cfg.get("filament_colour", ["", "", "", ""]))
    count = max(base, max(p.extruder for p in parts))

    def resize(values: list, per: int) -> list:
        target = count * per
        if len(values) >= target:
            return values
        unit = values[:per] if len(values) >= per else values + values[:1] * (per - len(values))
        out = list(values)
        while len(out) < target:
            out.extend(unit)
        return out[:target]

    for key, value in list(cfg.items()):
        if not isinstance(value, list):
            continue
        if key.startswith("filament_dev_ams"):
            continue
        if key.startswith("filament_") and len(value) == base:
            cfg[key] = resize(value, 1)
        elif (key.startswith("filament_") or key in _PAIRED_NON_FILAMENT_KEYS) and len(
            value
        ) == 2 * base:
            cfg[key] = resize(value, 2)

    cfg["filament_self_index"] = [str(i // 2 + 1) for i in range(2 * count)]
    cfg["flush_volumes_vector"] = resize(cfg.get("flush_volumes_vector", ["140"]), 2)
    flush = []
    for i in range(count):
        for j in range(count):
            flush.append("0" if i == j else "280")
    cfg["flush_volumes_matrix"] = flush

    colours = list(cfg.get("filament_colour", []))
    while len(colours) < count:
        colours.append("#FFFFFF")
    for part in parts:
        colours[part.extruder - 1] = part.color.upper()
    cfg["filament_colour"] = colours
    cfg["name"] = "project_settings"
    cfg["from"] = "project"
    return cfg


def write_3mf(
    path: str,
    parts: list[MeshPart],
    title: str = "svg2trains model",
    settings_template: str | None = None,
) -> None:
    """Write a Bambu Studio project 3MF with one mesh part per color."""
    if not parts:
        raise ValueError("No parts to write.")
    date = datetime.date.today().isoformat()
    settings = project_settings(parts, settings_template)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", _model_xml(parts, title, date))
        z.writestr("Metadata/model_settings.config", _model_settings_xml(parts, title))
        z.writestr(
            "Metadata/project_settings.config", json.dumps(settings, indent=4)
        )
    with open(path, "wb") as f:
        f.write(buffer.getvalue())
