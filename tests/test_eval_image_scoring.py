import io
from pathlib import Path

from PIL import Image

from scripts.eval_image_scoring import (
    BACKGROUND_THRESHOLD,
    ImageResult,
    aggregate,
    background_distance,
    background_is_cream,
    is_clean,
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


def _result(**overrides):
    base = dict(
        article_url="https://example.test/a",
        stratum="mechanism",
        variant="positive-preserved",
        ok=True,
        error="",
        content_filtered=False,
        background_is_cream=True,
        background_distance=5.0,
        has_text=False,
        has_person=False,
        object_group_count=3,
        judge_error="",
    )
    base.update(overrides)
    return ImageResult(**base)


def test_is_clean_requires_no_text_no_person_and_cream():
    assert is_clean(_result()) is True
    assert is_clean(_result(has_text=True)) is False
    assert is_clean(_result(has_person=True)) is False
    assert is_clean(_result(background_is_cream=False)) is False


def test_is_clean_is_unknown_when_the_judge_failed():
    """A failed judge must never be scored as clean."""
    assert is_clean(_result(has_text=None, judge_error="boom")) is None


def test_rates_divide_by_judged_not_generated():
    results = [
        _result(),
        _result(has_text=True),
        _result(has_text=None, judge_error="boom"),
    ]
    agg = aggregate("positive-preserved", results)
    assert agg.generated == 3
    assert agg.judged == 2
    assert agg.clean_rate == 0.5


def test_generation_failures_are_excluded_and_counted():
    results = [
        _result(),
        _result(ok=False, error="content filtered", content_filtered=True,
                has_text=None, has_person=None),
    ]
    agg = aggregate("positive-preserved", results)
    assert agg.generated == 1
    assert agg.judged == 1
    assert agg.content_filtered == 1
    assert agg.clean_rate == 1.0


def test_aggregate_splits_by_stratum():
    results = [
        _result(stratum="mechanism"),
        _result(stratum="person", has_person=True),
    ]
    agg = aggregate("positive-preserved", results)
    assert agg.clean_rate == 0.5
    assert agg.by_stratum["mechanism"].clean_rate == 1.0
    assert agg.by_stratum["person"].clean_rate == 0.0


def test_empty_results_do_not_divide_by_zero():
    agg = aggregate("positive-preserved", [])
    assert agg.generated == 0
    assert agg.judged == 0
    assert agg.clean_rate == 0.0
