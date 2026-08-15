import io
from pathlib import Path

from PIL import Image

from scripts.eval_image_scoring import (
    BACKGROUND_THRESHOLD,
    background_distance,
    background_is_cream,
)

FIXTURES = Path(__file__).parent / "fixtures" / "images"


def _solid_png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_cream_square_is_compliant():
    assert background_is_cream(_solid_png((243, 236, 216))) is True


def test_white_square_is_a_violation():
    assert background_is_cream(_solid_png((255, 255, 255))) is False


def test_white_background_fixture_exceeds_threshold():
    distance = background_distance((FIXTURES / "raw-white-bg.png").read_bytes())
    assert distance > BACKGROUND_THRESHOLD


def test_cream_background_fixture_is_within_threshold():
    distance = background_distance((FIXTURES / "raw-cream-bg.png").read_bytes())
    assert distance < BACKGROUND_THRESHOLD


def test_near_threshold_cream_fixture_still_passes():
    """Guards the 23.0-vs-30 margin: tightening the threshold must break a test."""
    distance = background_distance((FIXTURES / "raw-cream-edge.png").read_bytes())
    assert 15.0 < distance < BACKGROUND_THRESHOLD
