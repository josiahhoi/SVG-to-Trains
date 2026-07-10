import io
import json
import threading
import zipfile

import pytest

from svg2trains.gui import create_app

from conftest import write_svg
from test_e2e import BOX_TRAIN


@pytest.fixture
def client(tmp_path):
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _upload(client, tmp_path):
    svg = write_svg(tmp_path, BOX_TRAIN)
    with open(svg, "rb") as f:
        return client.post(
            "/api/svg",
            data={"svg": (io.BytesIO(f.read()), "box.svg")},
            content_type="multipart/form-data",
        )


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"svg2trains" in res.data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/vendor/three.module.js").status_code == 200


def test_upload_lists_layers(client, tmp_path):
    res = _upload(client, tmp_path)
    assert res.status_code == 200
    data = res.get_json()
    assert data["layers"] == [{"name": "box train", "visible": True}]


def test_convert_and_download(client, tmp_path):
    _upload(client, tmp_path)
    res = client.post(
        "/api/convert",
        data=json.dumps({"layer": "box train", "length": 150, "color_mode": "side"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["length"] == pytest.approx(150)
    assert len(data["parts"]) == 2
    part = data["parts"][0]
    assert part["extruder"] == 1
    assert len(part["vertices"]) % 3 == 0
    assert len(part["faces"]) % 3 == 0
    assert max(part["faces"]) < len(part["vertices"]) // 3

    dl = client.get("/api/download")
    assert dl.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(dl.data))
    assert "3D/3dmodel.model" in z.namelist()


def test_convert_before_upload_fails(client):
    res = client.post("/api/convert", data="{}", content_type="application/json")
    assert res.status_code == 400


def test_convert_error_reported(client, tmp_path):
    svg = write_svg(tmp_path, '<g data-layer="only"><rect x="0" y="0" width="10" height="10" style="fill: rgb(0,0,0)"/></g>')
    with open(svg, "rb") as f:
        client.post(
            "/api/svg",
            data={"svg": (io.BytesIO(f.read()), "bad.svg")},
            content_type="multipart/form-data",
        )
    res = client.post("/api/convert", data="{}", content_type="application/json")
    assert res.status_code == 422
    assert "view" in res.get_json()["error"].lower()
