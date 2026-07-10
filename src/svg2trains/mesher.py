"""Convert partitioned Manifold solids into placed numpy meshes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .partition import ColorPart


class MeshError(ValueError):
    pass


@dataclass
class MeshPart:
    name: str
    color: str            # '#rrggbb'
    extruder: int         # 1-based filament slot
    vertices: np.ndarray  # (V, 3) float64, mm
    faces: np.ndarray     # (F, 3) uint32
    volume: float         # mm^3
    provenance: str

    @property
    def bbox(self) -> tuple[float, float, float, float, float, float]:
        lo = self.vertices.min(axis=0)
        hi = self.vertices.max(axis=0)
        return (*lo, *hi)


_COLOR_NAMES = {
    "#000000": "black",
    "#ffffff": "white",
    "#ff0000": "red",
    "#00ff00": "green",
    "#0000ff": "blue",
    "#ffff00": "yellow",
    "#c2c3c7": "grey",
    "#8e9089": "grey",
    "#03fffb": "cyan",
    "#00b1b7": "cyan",
    "#0086d6": "blue",
}


def part_name(color: str, provenance: str) -> str:
    base = _COLOR_NAMES.get(color, color.lstrip("#"))
    return f"{base} {color}" if base != color else base


def to_mesh_parts(
    parts: list[ColorPart],
    slots: dict[str, int],
) -> list[MeshPart]:
    """Mesh each color part, translating the assembly to rest at Z=0 centered on X/Y."""
    if not parts:
        raise MeshError("No parts to mesh.")
    boxes = [p.solid.bounding_box() for p in parts]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    z0 = min(b[2] for b in boxes)
    x1 = max(b[3] for b in boxes)
    y1 = max(b[4] for b in boxes)
    shift = (-(x0 + x1) / 2.0, -(y0 + y1) / 2.0, -z0)

    out: list[MeshPart] = []
    for part in sorted(parts, key=lambda p: slots[p.color]):
        solid = part.solid.translate(shift)
        mesh = solid.to_mesh()
        verts = np.asarray(mesh.vert_properties[:, :3], dtype=np.float64)
        faces = np.asarray(mesh.tri_verts, dtype=np.uint32)
        if len(verts) == 0 or len(faces) == 0:
            raise MeshError(f"Part {part.color} produced an empty mesh.")
        volume = solid.volume()
        if volume <= 0:
            raise MeshError(f"Part {part.color} has non-positive volume.")
        out.append(
            MeshPart(
                name=part_name(part.color, part.provenance),
                color=part.color,
                extruder=slots[part.color],
                vertices=verts,
                faces=faces,
                volume=volume,
                provenance=part.provenance,
            )
        )
    return out


def validate_watertight(part: MeshPart) -> None:
    """Every undirected edge must be shared by exactly two opposite half-edges."""
    faces = part.faces
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    directed = {}
    for a, b in edges:
        key = (int(a), int(b))
        directed[key] = directed.get(key, 0) + 1
    for (a, b), count in directed.items():
        if count != 1 or directed.get((b, a), 0) != 1:
            raise MeshError(
                f"Part {part.name} is not watertight (edge {a}-{b} count {count})."
            )
