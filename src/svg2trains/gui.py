"""Local web app: upload an SVG, convert, inspect the 3D result, download 3MF."""

from __future__ import annotations

import io
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from .bambu3mf import write_3mf
from .pipeline import Options, convert
from .svgload import list_layers

WEB_DIR = Path(__file__).parent / "web"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
    state: dict = {"svg_path": None, "svg_name": None, "result": None, "title": None}

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.post("/api/svg")
    def upload_svg():
        file = request.files.get("svg")
        if file is None or not file.filename:
            return jsonify({"error": "No SVG file uploaded."}), 400
        tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
        file.save(tmp.name)
        state["svg_path"] = tmp.name
        state["svg_name"] = file.filename
        try:
            layers = list_layers(tmp.name)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(
            {
                "name": file.filename,
                "layers": [
                    {"name": l.name, "visible": l.visible} for l in layers
                ],
            }
        )

    @app.post("/api/convert")
    def api_convert():
        if state["svg_path"] is None:
            return jsonify({"error": "Upload an SVG first."}), 400
        params = request.get_json(force=True) or {}
        opts = Options(
            layer=params.get("layer") or None,
            length=params.get("length"),
            width=params.get("width"),
            height=params.get("height"),
            color_mode=params.get("color_mode", "side"),
            shell_depth=float(params.get("shell_depth", 1.2)),
            core_color=params.get("core_color") or None,
            merge_colors=int(params.get("merge_colors", 0)),
            tolerance=float(params.get("tolerance", 0.1)),
            check=True,
        )
        try:
            result = convert(state["svg_path"], opts)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 422
        state["result"] = result
        state["title"] = params.get("title") or result.layer
        return jsonify(
            {
                "layer": result.layer,
                "length": result.length,
                "width": result.width,
                "height": result.height,
                "warnings": result.warnings,
                "views": {
                    view: {
                        "label": rep.label,
                        "shapes": rep.shape_count,
                        "colors": rep.colors,
                    }
                    for view, rep in result.views.items()
                },
                "parts": [
                    {
                        "name": p.name,
                        "color": p.color,
                        "extruder": p.extruder,
                        "volume": p.volume,
                        "provenance": p.provenance,
                        "vertices": p.vertices.ravel().tolist(),
                        "faces": p.faces.ravel().tolist(),
                    }
                    for p in result.parts
                ],
            }
        )

    @app.get("/api/download")
    def api_download():
        result = state.get("result")
        if result is None:
            return jsonify({"error": "Nothing converted yet."}), 400
        buffer = io.BytesIO()
        tmp = tempfile.NamedTemporaryFile(suffix=".3mf", delete=False)
        write_3mf(tmp.name, result.parts, title=state["title"] or "svg2trains model")
        data = Path(tmp.name).read_bytes()
        buffer.write(data)
        buffer.seek(0)
        name = (state["title"] or "model").replace(" ", "_") + ".3mf"
        return send_file(
            buffer,
            mimetype="application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
            as_attachment=True,
            download_name=name,
        )

    return app


def run_gui(port: int = 8323, open_browser: bool = True) -> int:
    app = create_app()
    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"svg2trains GUI running at {url}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False)
    return 0
