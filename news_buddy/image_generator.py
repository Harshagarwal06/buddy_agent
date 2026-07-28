"""Generate and cache editorial photographs for enriched news articles."""

from __future__ import annotations

import base64
import hashlib
import io
import itertools
import os
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


DEFAULT_STYLE = (
    "Photorealistic conceptual editorial news photograph with one clear "
    "subject and a concrete visual metaphor. Natural light, realistic "
    "materials, restrained color, strong documentary composition, landscape "
    "orientation. Do not depict an invented event as documentary evidence. "
    "No words, letters, numbers, logos, watermarks, or screenshots."
)

DEFAULT_NEGATIVE_PROMPT = (
    "text, typography, letters, numbers, logo, watermark, screenshot, "
    "illustration, cartoon, painting, CGI, identifiable real person, clutter, "
    "low contrast, blurry"
)

DEFAULT_NVIDIA_API_URL = (
    "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b"
)


class ImageContentFilteredError(RuntimeError):
    """Raised when the provider rejects a prompt but returns HTTP success."""


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
    retries: int
    retry_delay: float
    steps: int
    api_url: str
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
            retries=max(0, min(5, int(config.get("retries", 2)))),
            retry_delay=max(0.0, min(30.0, float(config.get("retry_delay", 2)))),
            steps=max(1, min(50, int(config.get("steps", 4)))),
            api_url=str(config.get("api_url", DEFAULT_NVIDIA_API_URL)).strip()
            or DEFAULT_NVIDIA_API_URL,
            style=str(config.get("style", DEFAULT_STYLE)).strip() or DEFAULT_STYLE,
            style_version=str(config.get("style_version", "v1")),
            negative_prompt=(
                str(config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)).strip()
                or DEFAULT_NEGATIVE_PROMPT
            ),
        )


class _NvidiaImageClient:
    """Small adapter for NVIDIA's hosted Visual GenAI endpoint."""

    def __init__(self, settings: ImageSettings, token: str):
        self.settings = settings
        self.token = token
        self._request_numbers = itertools.count()

    def text_to_image(
        self,
        prompt: str,
        *,
        model: str,
        width: int,
        height: int,
        negative_prompt: str,
    ) -> bytes:
        del model, negative_prompt  # The hosted endpoint is model-specific.
        import httpx

        request_number = next(self._request_numbers)
        seed_material = f"{prompt}\nrequest:{request_number}"
        seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:8], 16)
        seed %= 2_147_483_647
        response = httpx.post(
            self.settings.api_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "width": width,
                "height": height,
                "seed": seed,
                "steps": self.settings.steps,
            },
            timeout=self.settings.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            artifact = payload["artifacts"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("NVIDIA returned no image artifact") from exc
        if artifact.get("finishReason") == "CONTENT_FILTERED":
            raise ImageContentFilteredError("NVIDIA content-filtered the image prompt")
        encoded = artifact.get("base64", "")
        if not encoded:
            raise RuntimeError("NVIDIA returned an empty image artifact")
        return base64.b64decode(encoded)


def _make_client(settings: ImageSettings, token: str):
    if settings.provider.lower() == "nvidia":
        return _NvidiaImageClient(settings, token)

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
    return _safe_photo_prompt(item)


def _image_alt(item: dict) -> str:
    alt = str(item.get("image_alt") or "").strip()
    if alt:
        return alt
    return f"AI-generated editorial image for {item.get('title') or 'this news story'}"


def _safe_photo_concept(item: dict) -> str:
    """Choose a name-free subject that still reflects the article's broad theme."""
    text = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            " ".join(str(tag) for tag in (item.get("tags") or [])),
        ]
    ).lower()
    concepts = [
        (
            ("security", "cyber", "breach", "privacy", "hack"),
            "a locked server rack beside glowing fiber-optic cables in a secure data center",
        ),
        (
            ("price", "pricing", "market", "business", "acquisition", "enterprise"),
            "two modern office buildings connected by a clean architectural bridge",
        ),
        (
            ("search", "discovery", "answer"),
            "a magnifying lens resting above an orderly network of illuminated data nodes",
        ),
        (
            ("chat", "message", "social", "assistant"),
            "two unbranded smartphones connected by a subtle beam of light on a studio table",
        ),
        (
            ("alignment", "control", "open-weight", "policy", "governance"),
            "a balanced scale between an open glass server cabinet and a sealed metal vault",
        ),
    ]
    return next(
        (description for terms, description in concepts if any(term in text for term in terms)),
        "a compact AI server module connected to a larger cloud data center",
    )


def _safe_photo_prompt(item: dict) -> str:
    """Build a name-free photo brief for missing or content-filtered prompts."""
    concept = _safe_photo_concept(item)
    return (
        f"Create a photorealistic conceptual editorial photograph of {concept}. "
        "Use an unbranded, non-documentary studio scene with no people, flags, "
        "symbols, text, or logos."
    )


def _safe_image_alt(item: dict) -> str:
    return f"AI-generated editorial photograph of {_safe_photo_concept(item)}."


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


def _validate_image(image) -> None:
    """Reject empty or malformed provider payloads while retries are available."""
    from PIL import Image

    if isinstance(image, Image.Image):
        return
    try:
        with Image.open(io.BytesIO(image)) as candidate:
            candidate.verify()
    except Exception as exc:
        raise RuntimeError("image provider returned invalid image bytes") from exc


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


def _with_image_metadata(item: dict, image_url: str, image_alt: str | None = None) -> dict:
    return {
        **item,
        "image_url": image_url,
        "image_alt": image_alt or _image_alt(item),
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
    token_env = "NVIDIA_API_KEY" if settings.provider.lower() == "nvidia" else "HF_TOKEN"
    token = os.getenv(token_env, "").strip()
    client = _make_client(settings, token) if token else None
    if client is None:
        print(
            f"[warn] images are enabled but {token_env} is not set; using placeholders",
            file=sys.stderr,
        )

    def _process(item: dict) -> tuple[dict, bool]:
        planned_prompt = str(item.get("image_prompt") or "").strip()
        used_safe_prompt = not planned_prompt
        safe_prompt = _safe_photo_prompt(item)
        prompt = planned_prompt or safe_prompt
        stem = _cache_stem(item, prompt, settings)
        webp_target = image_dir / f"{stem}.webp"
        relative_webp = webp_target.relative_to(output_dir).as_posix()
        if webp_target.exists():
            image_alt = _safe_image_alt(item) if used_safe_prompt else None
            return _with_image_metadata(item, relative_webp, image_alt), False
        if planned_prompt:
            safe_stem = _cache_stem(item, safe_prompt, settings)
            safe_webp_target = image_dir / f"{safe_stem}.webp"
            if safe_webp_target.exists():
                relative_safe = safe_webp_target.relative_to(output_dir).as_posix()
                return _with_image_metadata(
                    item,
                    relative_safe,
                    _safe_image_alt(item),
                ), False

        try:
            if client is None:
                raise RuntimeError(f"{token_env} is not configured")
            full_prompt = f"{prompt}\n\nVisual direction: {settings.style}"
            request_prompt = full_prompt[:1800]
            image = None
            for attempt in range(settings.retries + 1):
                try:
                    image = client.text_to_image(
                        request_prompt,
                        model=settings.model,
                        width=settings.width,
                        height=settings.height,
                        negative_prompt=settings.negative_prompt,
                    )
                    _validate_image(image)
                    break
                except Exception as request_exc:
                    if attempt >= settings.retries:
                        raise
                    if isinstance(request_exc, ImageContentFilteredError):
                        used_safe_prompt = True
                        stem = _cache_stem(item, safe_prompt, settings)
                        webp_target = image_dir / f"{stem}.webp"
                        relative_webp = webp_target.relative_to(output_dir).as_posix()
                        if webp_target.exists():
                            return _with_image_metadata(
                                item,
                                relative_webp,
                                _safe_image_alt(item),
                            ), False
                        request_prompt = (
                            f"{safe_prompt}\n\n"
                            f"Visual direction: {settings.style}"
                        )[:1800]
                        reason = "content-filtered prompt; retrying with neutral brief"
                    else:
                        reason = "image request failed; retrying"
                    print(
                        f"[warn] {reason} ({attempt + 1}/{settings.retries})",
                        file=sys.stderr,
                    )
                    time.sleep(settings.retry_delay)
            if image is None:
                raise RuntimeError("image provider returned no image")
            _save_webp(image, webp_target, settings)
            image_alt = _safe_image_alt(item) if used_safe_prompt else None
            return _with_image_metadata(item, relative_webp, image_alt), False
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
