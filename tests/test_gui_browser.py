"""Headless-browser test of the GUI: render, convert, pick a face."""

import glob
import socket
import threading

import pytest

from svg2trains.gui import create_app

from conftest import write_svg
from test_e2e import BOX_TRAIN

playwright_api = pytest.importorskip("playwright.sync_api")


def _chromium_path() -> str | None:
    for pattern in (
        "/opt/pw-browsers/chromium",
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
    ):
        hits = [h for h in glob.glob(pattern) if not h.endswith(".zip")]
        for h in hits:
            import os

            if os.path.isfile(h) and os.access(h, os.X_OK):
                return h
    return None


@pytest.fixture(scope="module")
def server():
    app = create_app()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    import time

    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"


def test_gui_end_to_end(server, tmp_path):
    exe = _chromium_path()
    if exe is None:
        pytest.skip("no chromium available")
    svg = write_svg(tmp_path, BOX_TRAIN)

    with playwright_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(server)
        assert page.title() == "svg2trains"

        page.set_input_files("#file", str(svg))
        page.wait_for_selector("#layer:not([disabled])")
        assert "box train" in page.inner_text("#layer")

        page.fill("#size-mm", "150")
        page.click("#convert")
        page.wait_for_selector('body[data-converted="1"]', timeout=30000)

        # parts list rendered with both filaments
        parts_text = page.inner_text("#parts")
        assert "slot 1" in parts_text and "slot 2" in parts_text
        assert "L 150.0" in page.inner_text("#dims")

        # click the canvas center: should hit the model and show face info
        page.click("#canvas-holder canvas", position={"x": 640, "y": 400})
        info = page.inner_text("#info")
        assert "part:" in info
        assert "filament" in info

        # download works end-to-end
        with page.expect_download() as dl:
            page.click("#download")
        path = dl.value.path()
        import zipfile

        assert "3D/3dmodel.model" in zipfile.ZipFile(path).namelist()

        assert errors == [], f"JS errors: {errors}"
        browser.close()
