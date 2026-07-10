# SVG-to-Trains

Convert multi-view train drawings (SVG) into **multi-color 3MF models** ready to
slice in **Bambu Studio** for Bambu Lab printers with an AMS.

Draw a train as labeled orthographic views (top, side, front/back) in one SVG.
`svg2trains` finds the views, builds the 3D body as the **visual hull**
(the intersection of each view's silhouette extruded along its axis), splits it
into one solid part per color, and writes a **Bambu Studio project 3MF** with
each part pre-assigned to a filament slot and the filament colors pre-filled.

## Install

```bash
pip install -e .          # from the repo root
pip install -e .[dev]     # with test dependencies
```

Requires Python 3.10+. Geometry is built with
[svgelements](https://pypi.org/project/svgelements/),
[shapely](https://pypi.org/project/shapely/), and
[manifold3d](https://pypi.org/project/manifold3d/) (robust, watertight 3D
booleans).

## Quick start

```bash
# see what layers and views the tool detects
svg2trains list-views "Trains 2.svg"

# convert the visible layer, train length 63.5 mm
svg2trains convert "Trains 2.svg" --layer "Metrolink Cab" --length 63.5 -o cab.3mf

# interactive: pick layer, convert, inspect in 3D, download
svg2trains gui
```

The GUI (`svg2trains gui`) opens a local web page: upload the SVG, choose a
layer and parameters, press Convert, then orbit the model. **Click a face** to
see which part it belongs to, its filament slot, volume, and which side of the
train it faces; **click an edge** to measure its length in mm. The Download
button saves the Bambu Studio project 3MF.

## Drawing conventions

- **One train per layer.** Each `<g data-layer="...">` group is a layer (the
  format the user's drawing app exports); by default the currently *visible*
  layer converts, `--layer NAME` selects any other.
- **Views are found by text labels** near each drawing: "top view" / "roof" /
  "plan", "side view", "front view", "back"/"rear", and "Front/back" for one
  drawing that serves as both ends. Long annotations are ignored. If a view has
  no label, it is inferred from the drawing dimensions (side and top share the
  train's length, top and front share its width, side and front share its
  height). Overrides: `--view-label "text=view"` and
  `--view-box "view=x,y,w,h"`.
- **Orientation**: side and top views point the same way, with the front of
  the train at screen-left (`--front=right` to flip). The back view is drawn
  as seen from behind (mirror of the front); `--no-back-mirror` for
  see-through style.
- **Front/back views may omit the underframe.** If they are shorter than the
  side view, they are anchored at the roofline and everything below their
  drawing is shaped by the side/top views alone.
- **Fills, strokes, and paint order all matter.** Stroke width and
  linecap/linejoin are honored (strokes become solid geometry); shapes painted
  later cover earlier ones; `fill-rule` (evenodd/nonzero) is respected;
  `fill="none"` / fully transparent paint is skipped.

## Color modes

- `--color-mode side` (default) — the side view's color regions are extruded
  through the full width of the train, producing stacked full-width slabs.
  This matches the layout of hand-built reference models and prints reliably.
- `--color-mode projection` — every exterior face takes the color of the view
  that faces it (roof from the top view, nose from the front view, ...).
  Color runs `--shell-depth` mm deep (default 1.2); the interior core gets
  `--core-color` (default: the dominant drawing color).

## Filament assignment

Each distinct color becomes one mesh part, assigned to filament slots in the
side view's paint order. More than 4 colors warns (one AMS unit), more than 16
is an error; merge near-identical colors with `--merge-colors <0-255>`.

The generated `project_settings.config` is based on a real Bambu Studio
project (Bambu Lab P2S, 0.2 mm nozzle, 0.10 mm Standard profile). Use
`--settings-template your_settings.json` to substitute the
`Metadata/project_settings.config` from any project exported by your own
Bambu Studio.

## CLI reference

```
svg2trains convert INPUT.svg [-o OUT.3mf]
    --layer NAME             layer to convert (default: the visible layer)
    --length/--width/--height MM   physical size (give exactly one)
    --color-mode side|projection   see above
    --shell-depth MM         projection color depth (1.2)
    --core-color #rrggbb     projection interior color
    --view-priority LIST     projection precedence (side,top,front,back)
    --front left|right       which end of the side view is the front
    --no-back-mirror         back view drawn see-through
    --view-label TEXT=VIEW   map a custom label (repeatable)
    --view-box VIEW=X,Y,W,H  assign a view by rectangle (repeatable)
    --tolerance MM           curve flattening (0.1)
    --min-area MM2           drop tiny color regions (0.05)
    --min-part-volume MM3    absorb tiny parts (1.0)
    --merge-colors N         merge colors within channel distance N
    --settings-template F    custom project_settings.config JSON
    --check                  verify meshes are watertight
svg2trains list-views INPUT.svg      show layers, views, labels
svg2trains list-colors INPUT.svg     show the filament assignment
svg2trains gui [--port N]            local web app
```

## Verifying a result

Open the produced `.3mf` in Bambu Studio: it should load as one object with
one part per color, parts pre-assigned to filaments 1..N, and the filament
colors filled in from the SVG. `examples/` contains the reference hand-built
`Metrolink_Cab_HR.3mf` this tool's output format was validated against, and a
copy of the real multi-layer input `Trains 2.svg`.

## Known limitations

- Gradients, patterns, `<text>` as geometry, clip-paths, and masks are
  skipped with a warning (convert text to paths in your editor).
- `stroke-dasharray` is ignored (strokes are solid).
- The bottom of the train (no bottom view) is shaped by the side/top views
  and, in projection mode, colored as core except near the side walls.
- Stroke width under a non-uniform scale transform is approximated.

## Development

```bash
python -m pytest          # full suite, includes end-to-end 3MF validation
```

The Bambu 3MF structure (package layout, per-part `extruder` config, UUID
conventions, `filament_colour` arrays) follows BambuStudio's own reader
(`src/libslic3r/Format/bbs_3mf.cpp`) and was cross-checked against a project
saved by Bambu Studio 2.6.
