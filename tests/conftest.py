from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def real_svg() -> Path:
    path = REPO_ROOT / "Trains 2.svg"
    if not path.exists():  # pragma: no cover
        pytest.skip("real example SVG not present")
    return path


def write_svg(tmp_path: Path, body: str, viewbox: str = "0 0 1000 1000") -> Path:
    doc = (
        f'<?xml version="1.0"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">{body}</svg>'
    )
    p = tmp_path / "test.svg"
    p.write_text(doc)
    return p
