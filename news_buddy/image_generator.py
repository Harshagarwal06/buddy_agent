"""Generate and cache editorial explainer diagrams for enriched news articles."""

from __future__ import annotations

import base64
import hashlib
import io
import itertools
import os
import re
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


DEFAULT_STYLE = (
    "Warm cream paper; flat hand-drawn editorial diagram; thick charcoal "
    "outlines; obvious arrows; generous empty space; one muted brick-red or "
    "ochre accent. Front-facing 4:3 with three clear object groups. Every "
    "surface is blank and unmarked. No UI panels, documents, screens, forms, "
    "signage, written text, letters, numbers, captions, photos, people, logos, "
    "gradients, scenery, watermarks, or screenshots."
)

DEFAULT_NEGATIVE_PROMPT = (
    "photograph, photorealism, identifiable person, face, logo, watermark, "
    "screenshot, 3D render, glossy CGI, gradient, busy background, clutter, "
    "paragraph text, misspelled text, extra labels, low contrast, blurry"
)

DEFAULT_NVIDIA_API_URL = (
    "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.2-klein-4b"
)
MAX_IMAGE_PROMPT_CHARS = 800
_ROOT = Path(__file__).parent.parent
DEFAULT_STYLE_GUIDE = _ROOT / "prompts" / "image_style.md"
_STYLE_DIRECTIVE_MARKERS = (
    "<!-- image-model-directive:start -->",
    "<!-- image-model-directive:end -->",
)


class ImageContentFilteredError(RuntimeError):
    """Raised when the provider rejects a prompt but returns HTTP success."""


def _read_marked_section(path: Path, markers: tuple[str, str]) -> str:
    """Read one machine-consumable directive from a Markdown design contract."""
    text = path.read_text(encoding="utf-8")
    start_marker, end_marker = markers
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise ValueError(f"{path} is missing its directive markers")
    return " ".join(text[start + len(start_marker):end].split())


def _style_from_config(config: dict) -> str:
    configured = str(config.get("style_guide", "")).strip()
    guide_path = Path(configured).expanduser() if configured else DEFAULT_STYLE_GUIDE
    if not guide_path.is_absolute():
        guide_path = _ROOT / guide_path
    try:
        return _read_marked_section(guide_path, _STYLE_DIRECTIVE_MARKERS)
    except (OSError, ValueError) as exc:
        print(
            f"[warn] could not load image style guide {guide_path}: {exc}; "
            "using inline default",
            file=sys.stderr,
        )
        return str(config.get("style", DEFAULT_STYLE)).strip() or DEFAULT_STYLE


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
    require_article_brief: bool

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
            style=_style_from_config(config),
            style_version=str(config.get("style_version", "v1")),
            negative_prompt=(
                str(config.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT)).strip()
                or DEFAULT_NEGATIVE_PROMPT
            ),
            require_article_brief=bool(config.get("require_article_brief", False)),
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


_LAYOUT_DIRECTIONS = {
    "pipeline": "Arrange the three stages left to right with bold directional arrows.",
    "branching": "Start from one object, split into two or three paths, then converge on the outcome.",
    "comparison": "Use a clean two-column contrast divided by a single vertical rule.",
    "before_after": "Show a clear before state on the left and changed state on the right.",
    "bottleneck": "Show several inputs narrowing through one constrained gate into one output.",
    "layers": "Stack three protective or processing layers from outside to inside.",
}

_LABEL_CLEANER = re.compile(r"[^A-Za-z0-9 +/&-]+")


def _image_labels(item: dict) -> list[str]:
    """Return three short labels for the deterministic publisher-rendered legend."""
    supplied = item.get("image_labels") or []
    if isinstance(supplied, str):
        supplied = [part.strip() for part in supplied.split(",")]
    labels = []
    for value in supplied:
        cleaned = _LABEL_CLEANER.sub("", str(value)).strip()
        fitted_words = []
        for word in cleaned.split()[:3]:
            candidate = " ".join([*fitted_words, word])
            if len(candidate) > 18:
                break
            fitted_words.append(word)
        cleaned = " ".join(fitted_words).strip(" -")
        if cleaned and cleaned.lower() not in {label.lower() for label in labels}:
            labels.append(cleaned.upper())
        if len(labels) == 3:
            return labels
    return _fallback_labels(item)


def _fallback_labels(item: dict) -> list[str]:
    text = _article_context(item).lower()
    label_sets = [
        (("shared chat", "artifacts may", "ended up on"), ["PRIVATE CHAT", "PUBLIC LINK", "INDEXED"]),
        (("alignment and control", "breach has reignited"), ["ALIGNMENT", "CONTROL", "RISK"]),
        (("open-weight", "open weight"), ["OPEN WEIGHTS", "CONTROL", "RISK"]),
        (("chat with", "in their dms", "chatbot within"), ["MESSAGE", "ASSISTANT", "REPLY"]),
        (("localized pricing", "local hiring"), ["GLOBAL PRICE", "LOCAL PRICE", "ADOPTION"]),
        (("search is rapidly", "ai overviews"), ["QUERY", "AI ANSWER", "LINKS"]),
        (("ai gateway", "trust one ai"), ["PROMPT", "GATEWAY", "MODELS"]),
        (("cybersecurity model", "cyber model"), ["THREATS", "MODEL", "ACTIONS"]),
        (("backup", "database", "registry", "wipe"), ["PRIMARY", "BACKUP", "HALT"]),
        (("swarm", "planner", "worker"), ["PLANNER", "WORKERS", "RESULT"]),
        (("reasoning", "effort", "thinking"), ["TASK", "EFFORT", "RESULT"]),
        (("memory safe", "pointer", "compiler"), ["POINTER", "CHECK", "MEMORY"]),
        (("hallucination", "fabricat", "source"), ["MODEL", "SOURCE", "FALSE"]),
        (("retrieval", "search", "rag"), ["QUERY", "SEARCH", "ANSWER"]),
        (("security", "cyber", "breach", "shell"), ["INPUT", "GATE", "SYSTEM"]),
        (("cloud", "vendor", "sovereign"), ["LOCK-IN", "MIGRATE", "CONTROL"]),
        (("robot", "training", "policy"), ["DATA", "MODEL", "POLICY"]),
    ]
    return next(
        (labels for terms, labels in label_sets if any(term in text for term in terms)),
        ["INPUT", "SYSTEM", "RESULT"],
    )


def _article_context(item: dict) -> str:
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    return " — ".join(part for part in (title, summary) if part)[:700]


def _layout_direction(item: dict) -> str:
    layout = str(item.get("image_layout") or "").strip().lower()
    if layout in _LAYOUT_DIRECTIONS:
        return _LAYOUT_DIRECTIONS[layout]
    text = _article_context(item).lower()
    inferred = (
        "branching"
        if any(term in text for term in ("swarm", "reasoning effort", "ai gateway"))
        else "comparison"
        if any(
            term in text
            for term in ("alignment and control", "open-weight", "open weight", "trust one ai")
        )
        else "before_after"
        if any(term in text for term in ("wipes", "wiped", "localized pricing"))
        else "pipeline"
    )
    return _LAYOUT_DIRECTIONS[inferred]


def _visual_prompt(item: dict) -> str:
    """Build a self-contained diagram brief from the editorial plan."""
    planned = str(item.get("image_prompt") or "").strip()[:280]
    if not planned:
        planned = (
            "Use only this article context to choose the three concrete objects: "
            f"{_article_context(item)[:360]}"
        )
    return (
        "Create one wordless editorial spot illustration, not an infographic "
        f"or poster. Translate this mechanism into three unlabeled symbols: {planned} "
        f"{_layout_direction(item)} Keep all three object groups completely "
        "unlabeled; the publisher will add the legend."
    )


def _image_alt(item: dict) -> str:
    alt = str(item.get("image_alt") or "").strip()
    if alt:
        return alt
    return f"AI-generated editorial image for {item.get('title') or 'this news story'}"


def _safe_infographic_concept(item: dict) -> str:
    """Choose an article-shaped mechanism without named people or brands."""
    text = _article_context(item).lower()
    concepts = [
        (
            ("shared chat", "artifacts may", "ended up on"),
            "a sealed speech bubble passing through an open chain-link gate into a magnifying glass over public nodes",
        ),
        (
            ("alignment and control", "breach has reignited"),
            "an open model box on one side and a containment shield on the other, connected by a risk gauge",
        ),
        (
            ("open-weight", "open weight"),
            "an open model-weight vault contrasted with a controlled sealed vault, both pointing toward a risk meter",
        ),
        (
            ("chat with", "in their dms", "chatbot within"),
            "a message bubble entering a small assistant node and returning as a reply bubble inside one conversation",
        ),
        (
            ("localized pricing", "local hiring"),
            "a large global price tag becoming a smaller regional price tag before reaching a growing group of users",
        ),
        (
            ("search is rapidly", "ai overviews"),
            "a magnifying glass flowing into one large abstract synthesis orb while a stack of small link nodes becomes smaller",
        ),
        (
            ("ai gateway", "trust one ai"),
            "one plain input cube entering a router junction that fans out to three blank model cubes, beside a broken single path",
        ),
        (
            ("cybersecurity model", "cyber model"),
            "several threat symbols entering a security model that directs three shielded agent actions",
        ),
        (
            ("backup", "database", "registry", "wipe"),
            "a main database and its backup both crossed out, followed by a falling activity line",
        ),
        (
            ("swarm", "planner", "worker"),
            "one planner node branching to three worker nodes that converge on a completed task",
        ),
        (
            ("reasoning", "effort", "thinking"),
            "one task splitting into low, medium, and high effort paths that end in progressively stronger results",
        ),
        (
            ("memory safe", "pointer", "compiler"),
            "a pointer passing through a runtime safety gate before reaching a protected memory block",
        ),
        (
            ("hallucination", "fabricat", "source"),
            "a language model producing a document that passes under a magnifying glass and ends as a crossed-out claim",
        ),
        (
            ("cloud", "vendor", "sovereign"),
            "a tangled locked cloud feeding applications through a narrow migration arrow into a smaller controlled cloud",
        ),
        (
            ("robot", "training", "policy"),
            "two data sources flowing into one base model that points to a robotic arm policy",
        ),
        (
            ("search", "retrieval", "answer", "rag"),
            "a query moving through a magnifying-glass retrieval gate into one verified answer",
        ),
        (
            ("security", "cyber", "breach", "privacy", "hack", "shell"),
            "model output moving through a cracked unsafe pipe toward a protected computer system",
        ),
    ]
    return next(
        (description for terms, description in concepts if any(term in text for term in terms)),
        "three simple stages showing an input entering a system and producing a clear result",
    )


def _safe_infographic_prompt(item: dict) -> str:
    """Build a name-free but article-specific brief for filtered prompts."""
    concept = _safe_infographic_concept(item)
    return (
        "Create one wordless editorial spot illustration, not an infographic "
        f"or poster, showing {concept}. "
        f"{_layout_direction(item)} Keep all three object groups completely "
        "unlabeled; the publisher will add the legend. Keep every object generic "
        "and unbranded."
    )


def _safe_image_alt(item: dict) -> str:
    return f"AI-generated explainer diagram showing {_safe_infographic_concept(item)}."


def _request_prompt(prompt: str, settings: ImageSettings) -> str:
    return (
        f"{prompt}\n\nVisual direction: {settings.style}"
    )[:MAX_IMAGE_PROMPT_CHARS]


# Plain-English rendering of each code _article_brief_errors can emit. The
# repair prompt sends these to the model, which already has the rules and broke
# them anyway — naming the specific objection is what makes a retry worth doing.
_BRIEF_ERROR_HELP = {
    "image_prompt": "image_prompt was empty.",
    "image_layout": (
        'image_layout must be exactly one of "pipeline", "branching", '
        '"comparison", "before_after", "bottleneck", or "layers".'
    ),
    "image_labels": (
        "image_labels must be a list of exactly three short, non-empty strings."
    ),
    "article-specific image_labels": (
        "image_labels used the generic INPUT / SYSTEM / RESULT triad. Use "
        "concrete nouns taken from this specific story instead."
    ),
    "image_alt": "image_alt was empty.",
}


def describe_brief_errors(errors: list[str]) -> list[str]:
    """Explain validator error codes for the image-plan repair prompt."""
    return [_BRIEF_ERROR_HELP.get(code, code) for code in errors]


def _article_brief_errors(item: dict) -> list[str]:
    """Return reasons an editorial image plan is unsafe to publish."""
    errors = []
    if not str(item.get("image_prompt") or "").strip():
        errors.append("image_prompt")
    if str(item.get("image_layout") or "").strip().lower() not in _LAYOUT_DIRECTIONS:
        errors.append("image_layout")
    labels = item.get("image_labels")
    # Over-long labels are not fatal: _image_labels() deterministically trims
    # each one to three words / 18 chars for the rendered legend.
    if not isinstance(labels, list) or len(labels) != 3 or any(
        not str(label).strip() for label in labels
    ):
        errors.append("image_labels")
    elif [str(label).strip().lower() for label in labels] == [
        "input",
        "system",
        "result",
    ]:
        errors.append("article-specific image_labels")
    if not str(item.get("image_alt") or "").strip():
        errors.append("image_alt")
    return errors


def _is_retryable_request_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", 0)
    return not (
        400 <= status_code < 500
        and status_code not in {408, 409, 425, 429}
    )


def _cache_stem(item: dict, prompt: str, settings: ImageSettings) -> str:
    cache_material = "\n".join(
        [
            str(item.get("url") or item.get("title") or ""),
            prompt,
            settings.model,
            settings.provider,
            settings.style_version,
            settings.style,
            ",".join(_image_labels(item)),
        ]
    )
    return hashlib.sha256(cache_material.encode("utf-8")).hexdigest()[:20]


def _add_label_band(image, labels: list[str]):
    """Cover model-generated captions and render an exact three-step legend."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    source = image.convert("RGB")
    width, height = source.size
    paper = "#f3ecd8"
    band_height = max(160, round(height * 0.28))
    band_top = height - band_height
    crop_top = max(64, round(height * 0.18))
    crop_bottom = max(180, round(height * 0.34))
    art = source.crop((0, crop_top, width, height - crop_bottom))
    light_background = ImageOps.grayscale(art).point(
        lambda value: 255 if value >= 245 else 0
    )
    art = Image.composite(
        Image.new("RGB", art.size, paper),
        art,
        light_background,
    )
    rendered = Image.new("RGB", (width, height), paper)
    art_y = max(0, (band_top - art.height) // 2)
    rendered.paste(art, (0, art_y))
    draw = ImageDraw.Draw(rendered)
    ink = "#27251f"
    accent = "#9a3a2a"
    draw.rectangle((0, band_top, width, height), fill=paper)
    draw.line((0, band_top, width, band_top), fill="#8a806c", width=max(2, width // 500))

    font_size = max(24, round(height * 0.038))
    number_size = max(20, round(height * 0.03))
    try:
        label_font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        number_font = ImageFont.truetype("DejaVuSans-Bold.ttf", number_size)
    except OSError:
        label_font = ImageFont.load_default(size=font_size)
        number_font = ImageFont.load_default(size=number_size)

    centers = [round(width / 6), round(width / 2), round(width * 5 / 6)]
    circle_y = band_top + round(band_height * 0.29)
    label_y = band_top + round(band_height * 0.56)
    radius = max(17, round(height * 0.023))

    for index, (center_x, label) in enumerate(zip(centers, labels), 1):
        draw.ellipse(
            (
                center_x - radius,
                circle_y - radius,
                center_x + radius,
                circle_y + radius,
            ),
            fill=accent,
        )
        number = str(index)
        number_box = draw.textbbox((0, 0), number, font=number_font)
        draw.text(
            (
                center_x - (number_box[2] - number_box[0]) / 2,
                circle_y - (number_box[3] - number_box[1]) / 2 - number_box[1],
            ),
            number,
            fill="#fffaf0",
            font=number_font,
        )
        label_box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(
            (
                center_x - (label_box[2] - label_box[0]) / 2,
                label_y,
            ),
            label,
            fill=ink,
            font=label_font,
        )

    arrow_y = circle_y
    for left, right in zip(centers, centers[1:]):
        start = left + radius + round(width * 0.025)
        end = right - radius - round(width * 0.025)
        line_width = max(3, width // 330)
        draw.line((start, arrow_y, end, arrow_y), fill=accent, width=line_width)
        arrow = max(9, round(width * 0.012))
        draw.polygon(
            [
                (end, arrow_y),
                (end - arrow, arrow_y - arrow // 2),
                (end - arrow, arrow_y + arrow // 2),
            ],
            fill=accent,
        )
    return rendered


def _save_webp(
    image,
    target: Path,
    settings: ImageSettings,
    labels: list[str],
) -> None:
    from PIL import Image, ImageOps

    if not isinstance(image, Image.Image):
        image = Image.open(io.BytesIO(image))
    image = ImageOps.fit(
        image.convert("RGB"),
        (settings.width, settings.height),
        method=Image.Resampling.LANCZOS,
    )
    image = _add_label_band(image, labels)
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


def _with_image_metadata(
    item: dict,
    image_url: str,
    settings: ImageSettings,
    image_alt: str | None = None,
) -> dict:
    return {
        **item,
        "image_url": image_url,
        "image_alt": image_alt or _image_alt(item),
        "image_width": settings.width,
        "image_height": settings.height,
    }


def generate_article_images(
    items: list[dict],
    output_dir: Path,
    config: dict,
) -> tuple[list[dict], int, int]:
    """
    Generate images for articles while preserving input order.

    Returns ``(enriched_items, images_ready, generation_failures)``. Production
    can require a complete article-grounded brief before any provider calls.
    """
    settings = ImageSettings.from_config(config)
    if not settings.enabled or not items:
        return items, 0, 0
    if settings.require_article_brief:
        invalid = [
            (str(item.get("title") or "Untitled"), _article_brief_errors(item))
            for item in items
            if _article_brief_errors(item)
        ]
        if invalid:
            details = "; ".join(
                f"{title[:60]}: {', '.join(errors)}"
                for title, errors in invalid[:5]
            )
            # Every brief failing means the prompt or the model regressed, which
            # is worth stopping for. A few bad briefs only cost those articles
            # their image — the rest of the digest still publishes.
            if len(invalid) == len(items):
                raise RuntimeError(
                    "article image briefs are incomplete; refusing generic images — "
                    f"{details}"
                )
            print(
                f"[warn] publishing {len(invalid)} of {len(items)} article(s) "
                f"without an image; incomplete briefs — {details}",
                file=sys.stderr,
            )

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
        if settings.require_article_brief and _article_brief_errors(item):
            # Skipped, not failed: `require_all` counts genuine generation
            # failures, and a deliberate skip must not trip it.
            return item, False
        planned_prompt = str(item.get("image_prompt") or "").strip()
        used_safe_prompt = not planned_prompt
        safe_prompt = _safe_infographic_prompt(item)
        prompt = _visual_prompt(item)
        stem = _cache_stem(item, prompt, settings)
        webp_target = image_dir / f"{stem}.webp"
        relative_webp = webp_target.relative_to(output_dir).as_posix()
        if webp_target.exists():
            image_alt = _safe_image_alt(item) if used_safe_prompt else None
            return _with_image_metadata(item, relative_webp, settings, image_alt), False
        if planned_prompt:
            safe_stem = _cache_stem(item, safe_prompt, settings)
            safe_webp_target = image_dir / f"{safe_stem}.webp"
            if safe_webp_target.exists():
                relative_safe = safe_webp_target.relative_to(output_dir).as_posix()
                return _with_image_metadata(
                    item,
                    relative_safe,
                    settings,
                    _safe_image_alt(item),
                ), False

        try:
            if client is None:
                raise RuntimeError(f"{token_env} is not configured")
            request_prompt = _request_prompt(prompt, settings)
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
                        if settings.require_article_brief:
                            raise
                        used_safe_prompt = True
                        stem = _cache_stem(item, safe_prompt, settings)
                        webp_target = image_dir / f"{stem}.webp"
                        relative_webp = webp_target.relative_to(output_dir).as_posix()
                        if webp_target.exists():
                            return _with_image_metadata(
                                item,
                                relative_webp,
                                settings,
                                _safe_image_alt(item),
                            ), False
                        request_prompt = (
                            _request_prompt(safe_prompt, settings)
                        )
                        reason = "content-filtered prompt; retrying with neutral brief"
                    else:
                        if not _is_retryable_request_error(request_exc):
                            raise
                        reason = "image request failed; retrying"
                    print(
                        f"[warn] {reason} ({attempt + 1}/{settings.retries})",
                        file=sys.stderr,
                    )
                    time.sleep(settings.retry_delay)
            if image is None:
                raise RuntimeError("image provider returned no image")
            _save_webp(image, webp_target, settings, _image_labels(item))
            image_alt = _safe_image_alt(item) if used_safe_prompt else None
            return _with_image_metadata(item, relative_webp, settings, image_alt), False
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
                image_alt = _safe_image_alt(item) if used_safe_prompt else None
                return _with_image_metadata(
                    item,
                    relative_svg,
                    settings,
                    image_alt,
                ), True
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
