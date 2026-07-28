"""Generate and cache editorial illustrations for enriched news articles."""

from __future__ import annotations

import hashlib
import io
import os
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


DEFAULT_STYLE = (
    "Editorial technology illustration with one clear visual metaphor. "
    "Warm paper background, cobalt blue and coral accents, clean geometric "
    "composition, subtle texture, landscape 4:3. No words, letters, numbers, "
    "logos, watermarks, screenshots, or photorealistic people."
)

DEFAULT_NEGATIVE_PROMPT = (
    "text, typography, letters, numbers, logo, watermark, screenshot, "
    "photorealistic face, clutter, low contrast, blurry"
)


@dataclass(frozen=True)
class ImageSettings:
    enabled: bool
    provider: str
    model: str
    width: int
    height: int
    quality: int
    max_workers: int
    timeout: float
    style: str
    style_version: str
    negative_prompt: str

    @classmethod
    def from_config(cls, config: dict) -> "ImageSettings":
        return cls(
            enabled=bool(config.get("enabled", False)),
            provider=str(config.get("provider", "auto")),
            model=str(config.get("model", "Qwen/Qwen-Image")),
            width=max(320, int(config.get("width", 960))),
            height=max(240, int(config.get("height", 720))),
            quality=max(1, min(100, int(config.get("quality", 82)))),
            max_workers=max(1, min(4, int(config.get("max_workers", 2)))),
            timeout=max(10.0, float(config.get("timeout", 180))),
            style=str(config.get("style", DEFAULT_STYLE)).strip() or DEFAULT_STYLE,
            style_version=str(config.get("style_version", "v1")),
            negative_prompt=(
                str(config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)).strip()
                or DEFAULT_NEGATIVE_PROMPT
            ),
        )


def _make_client(settings: ImageSettings, token: str):
    from huggingface_hub import InferenceClient

    return InferenceClient(
        provider=settings.provider,
        token=token,
        timeout=settings.timeout,
    )


def _visual_prompt(item: dict) -> str:
    prompt = str(item.get("image_prompt") or "").strip()
    if prompt:
        return prompt
    title = str(item.get("title") or "AI news story").strip()
    summary = str(item.get("summary") or "").strip()
    return f"Create a conceptual illustration for: {title}. {summary}".strip()


def _image_alt(item: dict) -> str:
    alt = str(item.get("image_alt") or "").strip()
    if alt:
        return alt
    return f"Editorial illustration for {item.get('title') or 'this news story'}"


def _cache_stem(item: dict, prompt: str, settings: ImageSettings) -> str:
    cache_material = "\n".join(
        [
            str(item.get("url") or item.get("title") or ""),
            prompt,
            settings.model,
            settings.provider,
            settings.style_version,
            settings.style,
        ]
    )
    return hashlib.sha256(cache_material.encode("utf-8")).hexdigest()[:20]


def _save_webp(image, target: Path, settings: ImageSettings) -> None:
    from PIL import Image, ImageOps

    if not isinstance(image, Image.Image):
        image = Image.open(io.BytesIO(image))
    image = ImageOps.fit(
        image.convert("RGB"),
        (settings.width, settings.height),
        method=Image.Resampling.LANCZOS,
    )
    tmp = target.with_suffix(".webp.tmp")
    image.save(tmp, format="WEBP", quality=settings.quality, method=6)
    tmp.replace(target)


def _placeholder_svg(item: dict, target: Path, settings: ImageSettings) -> None:
    """Write a deterministic branded fallback when remote generation fails."""
    title = str(item.get("title") or "News Buddy").strip()
    tags = item.get("tags") or ["ai"]
    tag = str(tags[0]).upper()
    title_lines = textwrap.wrap(title, width=34)[:3] or ["News Buddy"]
    line_height = max(34, round(settings.height * 0.065))
    start_y = round(settings.height * 0.43)
    title_svg = "".join(
        f'<text x="8%" y="{start_y + (i * line_height)}" class="title">'
        f"{xml_escape(line)}</text>"
        for i, line in enumerate(title_lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{settings.width}" height="{settings.height}" viewBox="0 0 {settings.width} {settings.height}">
  <rect width="100%" height="100%" fill="#eee8da"/>
  <circle cx="82%" cy="22%" r="18%" fill="#ef6a5b" opacity=".92"/>
  <rect x="69%" y="46%" width="25%" height="36%" rx="28" fill="#1a56c4" opacity=".94"/>
  <path d="M0 {round(settings.height * .78)} L{round(settings.width * .38)} {round(settings.height * .32)} L{round(settings.width * .62)} {settings.height} Z" fill="#d4a72c" opacity=".75"/>
  <text x="8%" y="17%" class="label">{xml_escape(tag)} · NEWS BUDDY</text>
  {title_svg}
  <style>
    .label {{ font: 700 {max(18, round(settings.height * .032))}px system-ui, sans-serif; letter-spacing: 3px; fill: #5d594f; }}
    .title {{ font: 700 {max(32, round(settings.height * .062))}px Georgia, serif; fill: #1b1a17; }}
  </style>
</svg>"""
    tmp = target.with_suffix(".svg.tmp")
    tmp.write_text(svg, encoding="utf-8")
    tmp.replace(target)


def _with_image_metadata(item: dict, image_url: str) -> dict:
    return {
        **item,
        "image_url": image_url,
        "image_alt": _image_alt(item),
    }


def generate_article_images(
    items: list[dict],
    output_dir: Path,
    config: dict,
) -> tuple[list[dict], int, int]:
    """
    Generate images for articles while preserving input order.

    Returns ``(enriched_items, images_ready, generation_failures)``. A remote
    failure produces a local SVG placeholder so publishing remains fail-open.
    """
    settings = ImageSettings.from_config(config)
    if not settings.enabled or not items:
        return items, 0, 0

    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    token = os.getenv("HF_TOKEN", "").strip()
    client = _make_client(settings, token) if token else None
    if client is None:
        print(
            "[warn] images are enabled but HF_TOKEN is not set; using placeholders",
            file=sys.stderr,
        )

    def _process(item: dict) -> tuple[dict, bool]:
        prompt = _visual_prompt(item)
        stem = _cache_stem(item, prompt, settings)
        webp_target = image_dir / f"{stem}.webp"
        relative_webp = webp_target.relative_to(output_dir).as_posix()
        if webp_target.exists():
            return _with_image_metadata(item, relative_webp), False

        try:
            if client is None:
                raise RuntimeError("HF_TOKEN is not configured")
            full_prompt = f"{prompt}\n\nVisual direction: {settings.style}"
            image = client.text_to_image(
                full_prompt[:1800],
                model=settings.model,
                width=settings.width,
                height=settings.height,
                negative_prompt=settings.negative_prompt,
            )
            _save_webp(image, webp_target, settings)
            return _with_image_metadata(item, relative_webp), False
        except Exception as exc:
            print(
                f"[warn] image generation failed for {item.get('url', 'article')}: {exc}",
                file=sys.stderr,
            )
            svg_target = image_dir / f"{stem}.svg"
            try:
                if not svg_target.exists():
                    _placeholder_svg(item, svg_target, settings)
                relative_svg = svg_target.relative_to(output_dir).as_posix()
                return _with_image_metadata(item, relative_svg), True
            except Exception as placeholder_exc:
                print(
                    f"[warn] image placeholder failed for "
                    f"{item.get('url', 'article')}: {placeholder_exc}",
                    file=sys.stderr,
                )
                return item, True

    with ThreadPoolExecutor(max_workers=settings.max_workers) as executor:
        results = list(executor.map(_process, items))

    enriched = [item for item, _failed in results]
    failures = sum(1 for _item, failed in results if failed)
    ready = sum(1 for item in enriched if item.get("image_url"))
    return enriched, ready, failures
