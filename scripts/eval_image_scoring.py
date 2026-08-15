"""Scoring and aggregation for the image directive evaluation. No network."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

# The cream paper token from prompts/image_style.md and tokens.css.
CREAM_RGB = (243, 236, 216)

# Measured separation on raw generations: white backgrounds land at 36.0-43.5,
# cream backgrounds at 6.4-23.0. 30 splits them with margin on both sides.
BACKGROUND_THRESHOLD = 30.0

_RING_PX = 8


def background_distance(image_bytes: bytes) -> float:
    """Euclidean RGB distance from the border-ring median colour to cream."""
    with Image.open(io.BytesIO(image_bytes)) as opened:
        pixels = np.asarray(opened.convert("RGB")).astype(float)
    ring = np.concatenate(
        [
            pixels[:_RING_PX].reshape(-1, 3),
            pixels[-_RING_PX:].reshape(-1, 3),
            pixels[:, :_RING_PX].reshape(-1, 3),
            pixels[:, -_RING_PX:].reshape(-1, 3),
        ]
    )
    median = np.median(ring, axis=0)
    return float(np.sqrt(((median - np.array(CREAM_RGB, dtype=float)) ** 2).sum()))


def background_is_cream(image_bytes: bytes) -> bool:
    return background_distance(image_bytes) <= BACKGROUND_THRESHOLD
