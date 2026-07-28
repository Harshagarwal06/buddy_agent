"""Generate the dated editorial HTML digest from enriched article items."""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

_WPM = 220
_TOKENS_PATH = Path(__file__).resolve().parents[1] / "tokens.css"


def _copy_tokens(output_dir: Path) -> None:
    """Publish the shared design tokens beside generated pages."""
    shutil.copyfile(_TOKENS_PATH, output_dir / "tokens.css")


def _tag_badge(tag: str) -> str:
    tag_value = str(tag)
    return (
        f'<span class="tag-badge" data-tag="{escape(tag_value.lower(), quote=True)}">'
        f"{escape(tag_value)}</span>"
    )


def _importance_label(importance: int) -> str:
    n = max(1, min(5, int(importance)))
    if n >= 5:
        return "Lead story"
    if n >= 4:
        return "Must read"
    if n >= 3:
        return "Recommended"
    return "Briefing"


def _read_minutes(items: list[dict]) -> int:
    words = sum(len((it.get("summary") or "").split()) for it in items)
    return max(1, round(words / _WPM)) if words else 0


def _article_card(item: dict, large: bool = False, hero: bool = False) -> str:
    """Render one story while preserving markup consumed by the backfill parser."""
    title = str(item.get("title", "Untitled"))
    url = str(item.get("url", "#"))
    source = str(item.get("source", ""))
    pub = str(item.get("published_at") or "")[:10]
    summary = str(item.get("summary", ""))
    tags = item.get("tags") or []
    imp = int(item.get("importance", 3))
    icymi = bool(item.get("is_icymi"))
    image_url = str(item.get("image_url") or "").strip()
    image_alt = str(item.get("image_alt") or f"Editorial illustration for {title}")

    badges = '<span class="tag-separator" aria-hidden="true">/</span>'.join(
        _tag_badge(t) for t in tags
    )
    icymi_badge = '<span class="icymi-badge">From the archive</span>' if icymi else ""
    size_class = "card-hero" if hero else ("card-large" if large else "card-normal")
    image_class = "has-image" if image_url else "no-image"
    safe_url = escape(url, quote=True)
    safe_title = escape(title)
    safe_tags = escape(",".join(str(t).lower() for t in tags), quote=True)
    loading = "eager" if hero else "lazy"
    priority = ' fetchpriority="high"' if hero else ""
    image_html = (
        f'<a href="{safe_url}" target="_blank" rel="noopener" class="card-image" '
        f'aria-label="Read {escape(title, quote=True)}">'
        f'<img src="{escape(image_url, quote=True)}" alt="{escape(image_alt, quote=True)}" '
        f'width="960" height="720" loading="{loading}" decoding="async"{priority}>'
        f"</a>"
        if image_url
        else ""
    )

    return f"""
<article class="article-card {size_class} {image_class}" data-tags="{safe_tags}">
  {image_html}
  <div class="card-body">
    <div class="card-meta">{escape(source)}{' <span class="dot">·</span> ' + escape(pub) if pub else ''}{icymi_badge}</div>
    <div class="card-header">
      <a href="{safe_url}" target="_blank" rel="noopener" class="card-title">{safe_title}</a>
      <span class="card-stars" title="Importance {imp}/5" aria-label="Importance {imp} of 5">{_importance_label(imp)}</span>
    </div>
    {"<p class='card-summary'>" + escape(summary) + "</p>" if summary else ""}
    <div class="card-tail">
      <div class="card-tags">{badges}</div>
      <a class="read-link" href="{safe_url}" target="_blank" rel="noopener">Read at {escape(source or "source")} <span aria-hidden="true">↗</span></a>
    </div>
  </div>
</article>"""


def _source_stats(items: list[dict]) -> str:
    counts: dict[str, int] = {}
    for item in items:
        source = str(item.get("source", "Unknown"))
        counts[source] = counts.get(source, 0) + 1
    return "".join(
        f"<span class='stat-item'>{escape(source)} <b>{count}</b></span>"
        for source, count in sorted(counts.items(), key=lambda pair: -pair[1])
    )


def write_html(
    output_dir: Path,
    date_str: str,
    enriched_items: list[dict],
    prev_date: str | None = None,
    next_date: str | None = None,
) -> Path:
    """Write a polished dated digest and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_tokens(output_dir)

    items = sorted(enriched_items, key=lambda item: item.get("importance", 3), reverse=True)
    top = items[:5]
    rest = items[5:]

    by_tag: dict[str, list[dict]] = {}
    for item in rest:
        tag = str((item.get("tags") or ["other"])[0]).lower()
        by_tag.setdefault(tag, []).append(item)

    top_html = ""
    if top:
        cards = _article_card(top[0], hero=True)
        cards += "\n".join(_article_card(item, large=True) for item in top[1:])
        top_html = (
            '<section class="story-section lead-section">'
            '<div class="section-heading"><h2>The briefing</h2>'
            '<p>The stories shaping AI today, selected and condensed.</p></div>'
            f'<div class="story-list">{cards}</div>'
            "</section>"
        )

    more_html = ""
    for tag, tag_items in sorted(by_tag.items()):
        cards = "\n".join(_article_card(item) for item in tag_items)
        more_html += (
            '<section class="story-section">'
            f'<div class="section-heading"><h2>{escape(tag.title())}</h2>'
            f'<p>{len(tag_items)} item{"s" if len(tag_items) != 1 else ""} in this desk.</p></div>'
            f'<div class="story-list">{cards}</div>'
            "</section>"
        )

    count = len(items)
    read_min = _read_minutes(items)
    read_html = f" · {read_min} min read" if read_min else ""
    stats_html = _source_stats(items)
    all_tags = sorted({str(tag).lower() for item in items for tag in (item.get("tags") or [])})
    tag_filter_html = "".join(
        f'<button class="filter-btn" type="button" data-tag="{escape(tag, quote=True)}">{escape(tag)}</button>'
        for tag in all_tags
    )
    filter_all = '<button class="filter-btn active" type="button" data-tag="__all__">All desks</button>'

    prev_btn = (
        f'<a href="{prev_date}.html" class="nav-btn"><span aria-hidden="true">←</span> {prev_date}</a>'
        if prev_date
        else '<span class="nav-btn nav-disabled"><span aria-hidden="true">←</span> Earlier</span>'
    )
    next_btn = (
        f'<a href="{next_date}.html" class="nav-btn">{next_date} <span aria-hidden="true">→</span></a>'
        if next_date
        else '<span class="nav-btn nav-disabled">Later <span aria-hidden="true">→</span></span>'
    )
    empty_msg = '<p class="empty-msg">No new articles today.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="News Buddy’s curated AI news briefing for {date_str}.">
<title>News Buddy — {date_str}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="tokens.css">
<style>
/* Hallmark · macrostructure: Long Document · tone: editorial · theme: studied-DNA */
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ overflow-x: clip; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  background: var(--color-paper);
  color: var(--color-ink);
  font-family: var(--font-body);
  font-size: var(--text-body);
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}}
::selection {{ background: var(--color-selection); color: var(--color-ink); }}
a {{ color: inherit; }}
button, input {{ font: inherit; }}
button, a {{ -webkit-tap-highlight-color: transparent; }}
:focus-visible {{ outline: var(--rule-heavy) solid var(--color-focus); outline-offset: var(--space-2xs); }}
button:disabled, [aria-disabled="true"] {{ color: var(--color-faint); cursor: not-allowed; opacity: .55; }}
.progress-track {{
  position: fixed; inset: 0 0 auto; height: var(--space-3xs);
  z-index: var(--z-sticky); pointer-events: none;
}}
.progress-fill {{ width: 0; height: 100%; background: var(--color-accent); }}
.site-shell {{ width: min(100%, var(--page-width)); margin-inline: auto; padding-inline: var(--page-gutter); }}
.masthead {{ padding-block: var(--space-lg) var(--space-xl); text-align: center; }}
.issue-line {{
  display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center; gap: var(--space-md);
  min-height: 2.75rem;
  border-block: var(--rule-hair) solid var(--color-rule);
  color: var(--color-muted); font-family: var(--font-ui);
  font-size: var(--text-xs); letter-spacing: .06em; text-transform: uppercase;
}}
.issue-line > :first-child {{ justify-self: start; }}
.issue-line > :last-child {{ justify-self: end; }}
.issue-link {{ min-height: 2.75rem; display: inline-flex; align-items: center; text-decoration: none; white-space: nowrap; }}
.issue-link:hover {{ color: var(--color-accent); }}
.issue-link:active {{ color: var(--color-accent-hover); }}
.issue-meta {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.theme-toggle {{
  min-width: 2.75rem; min-height: 2.75rem; display: inline-flex; align-items: center; justify-content: center;
  padding-inline: var(--space-sm); border: 0; border-inline: var(--rule-hair) solid var(--color-rule);
  border-radius: 0; background: transparent; color: var(--color-ink);
  cursor: pointer; font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  letter-spacing: .04em; text-transform: uppercase; white-space: nowrap;
}}
.theme-toggle:hover {{ color: var(--color-accent); }}
.theme-toggle:active {{ color: var(--color-accent-hover); }}
.theme-toggle .theme-dark-label {{ display: inline; }}
.theme-toggle .theme-light-label {{ display: none; }}
[data-theme="dark"] .theme-toggle .theme-dark-label {{ display: none; }}
[data-theme="dark"] .theme-toggle .theme-light-label {{ display: inline; }}
.mast-name {{
  margin: var(--space-lg) 0 var(--space-xs);
  color: var(--color-ink); font-family: var(--font-display); font-size: var(--text-display);
  font-style: normal; font-weight: 700; letter-spacing: -.055em; line-height: .78;
  overflow-wrap: anywhere; min-width: 0;
}}
.mast-deck {{
  margin: var(--space-lg) auto var(--space-md); max-width: 44ch;
  color: var(--color-ink-soft); font-size: var(--text-md); line-height: 1.45;
}}
.mast-rule {{ height: var(--space-xs); margin: 0; border: 0; border-block: var(--rule-hair) solid var(--color-rule-strong); }}
.source-line {{
  display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-xs) var(--space-md);
  margin-block: var(--space-sm) 0; color: var(--color-muted);
  font-family: var(--font-ui); font-size: var(--text-2xs); text-transform: uppercase; letter-spacing: .045em;
}}
.stat-item b {{ color: var(--color-ink); font-weight: 600; }}
.filter-bar {{
  display: flex; gap: 0; overflow-x: auto; scrollbar-width: none;
  margin-block: var(--space-lg) var(--space-2xl);
  border-block: var(--rule-hair) solid var(--color-rule);
}}
.filter-bar::-webkit-scrollbar {{ display: none; }}
.filter-btn {{
  flex: 0 0 auto; min-height: 2.75rem; padding-inline: var(--space-md);
  border: 0; border-inline-end: var(--rule-hair) solid var(--color-rule);
  border-radius: 0; background: transparent; color: var(--color-muted);
  cursor: pointer; font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  letter-spacing: .035em; text-transform: uppercase; white-space: nowrap;
}}
.filter-btn:hover {{ color: var(--color-accent); }}
.filter-btn:active {{ color: var(--color-accent-hover); }}
.filter-btn.active {{ color: var(--color-paper); background: var(--color-ink); }}
.story-section {{ margin-block: 0 var(--space-3xl); }}
.story-section.hidden, .article-card.hidden {{ display: none; }}
.section-heading {{
  display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-lg);
  padding-block-end: var(--space-sm); border-block-end: var(--rule-heavy) solid var(--color-ink);
}}
.section-heading h2 {{
  margin: 0; font-family: var(--font-display); font-size: var(--text-xl);
  font-style: normal; font-weight: 600; line-height: 1; overflow-wrap: anywhere; min-width: 0;
}}
.section-heading p {{
  margin: 0; color: var(--color-muted); font-family: var(--font-ui);
  font-size: var(--text-xs); line-height: 1.35; text-align: end;
}}
.story-list {{ display: grid; }}
.article-card {{
  display: grid; grid-template-columns: minmax(0, 1fr);
  min-width: 0; padding-block: var(--space-xl);
  border-block-end: var(--rule-hair) solid var(--color-rule);
}}
.article-card.has-image {{ gap: var(--space-lg); }}
.card-image {{
  display: block; min-width: 0; aspect-ratio: 4 / 3; overflow: hidden;
  align-self: start; border: var(--rule-hair) solid var(--color-rule-strong);
  border-radius: var(--radius-xs); background: var(--color-paper-muted);
}}
.card-image img {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
.card-image:hover {{ border-color: var(--color-accent); }}
.card-image:active {{ border-color: var(--color-accent-hover); }}
.card-body {{ display: flex; min-width: 0; flex-direction: column; justify-content: center; }}
.card-meta {{
  display: flex; flex-wrap: wrap; gap: var(--space-xs);
  margin-block-end: var(--space-sm); color: var(--color-muted);
  font-family: var(--font-ui); font-size: var(--text-xs); letter-spacing: .035em; text-transform: uppercase;
}}
.dot {{ color: var(--color-faint); }}
.icymi-badge {{ color: var(--color-accent); white-space: nowrap; }}
.card-header {{ display: flex; flex-direction: column; gap: var(--space-sm); min-width: 0; }}
.card-title {{
  color: var(--color-ink); font-family: var(--font-display);
  font-size: clamp(1.55rem, 3.2vw, 2.25rem); font-style: normal; font-weight: 600;
  letter-spacing: -.018em; line-height: 1.08; text-decoration-thickness: var(--rule-hair);
  text-decoration-color: transparent; text-underline-offset: var(--space-3xs);
  overflow-wrap: anywhere; min-width: 0;
}}
.card-title:hover {{ color: var(--color-accent); text-decoration-color: currentColor; }}
.card-title:active {{ color: var(--color-accent-hover); }}
.card-stars {{
  align-self: flex-start; color: var(--color-accent); font-family: var(--font-ui);
  font-size: var(--text-2xs); font-weight: 600; letter-spacing: .08em;
  line-height: 1; text-transform: uppercase; white-space: nowrap;
}}
.card-summary {{
  max-width: var(--prose-width); margin: var(--space-md) 0 0;
  color: var(--color-ink-soft); font-size: var(--text-md); line-height: 1.65;
}}
.card-tail {{
  display: flex; align-items: end; justify-content: space-between; gap: var(--space-lg);
  margin-block-start: var(--space-lg);
}}
.card-tags {{
  display: flex; flex-wrap: wrap; gap: var(--space-xs);
  color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-2xs);
  font-weight: 500; letter-spacing: .06em; text-transform: uppercase;
}}
.tag-separator {{ color: var(--color-rule-strong); }}
.read-link {{
  flex: 0 0 auto; color: var(--color-ink); font-family: var(--font-ui);
  font-size: var(--text-xs); font-weight: 600; text-decoration: underline;
  text-decoration-color: var(--color-rule-strong); text-underline-offset: var(--space-3xs); white-space: nowrap;
}}
.read-link:hover {{ color: var(--color-accent); text-decoration-color: currentColor; }}
.read-link:active {{ color: var(--color-accent-hover); }}
.day-nav {{
  display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center; gap: var(--space-sm);
  padding-block: var(--space-lg); border-block: var(--rule-hair) solid var(--color-rule);
}}
.nav-btn, .nav-archive a {{
  min-height: 2.75rem; display: inline-flex; align-items: center;
  color: var(--color-ink); font-family: var(--font-ui); font-size: var(--text-xs);
  font-weight: 600; letter-spacing: .025em; text-decoration: none; white-space: nowrap;
}}
.day-nav > :last-child {{ justify-self: end; }}
.nav-btn:hover, .nav-archive a:hover {{ color: var(--color-accent); }}
.nav-btn:active, .nav-archive a:active {{ color: var(--color-accent-hover); }}
.nav-disabled {{ color: var(--color-faint); }}
.empty-msg {{ padding-block: var(--space-3xl); color: var(--color-muted); font-size: var(--text-lg); text-align: center; }}
.site-footer {{
  margin-block-start: var(--space-2xl); padding-block: var(--space-xl) var(--space-2xl);
  border-block-start: var(--rule-heavy) solid var(--color-ink);
  color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs); line-height: 1.65;
}}
.footer-name {{ color: var(--color-ink); font-family: var(--font-display); font-size: var(--text-xl); font-weight: 600; }}
.site-footer p {{ margin: var(--space-xs) 0 0; max-width: 78ch; }}
.site-footer a {{ text-decoration-color: var(--color-rule-strong); text-underline-offset: .18em; }}
.site-footer a:hover {{ color: var(--color-accent); }}
.site-footer a:active {{ color: var(--color-accent-hover); }}
.to-top {{
  position: fixed; inset: auto var(--space-md) var(--space-md) auto; z-index: var(--z-raised);
  min-width: 2.75rem; min-height: 2.75rem; padding-inline: var(--space-sm);
  border: var(--rule-hair) solid var(--color-rule-strong); border-radius: var(--radius-xs);
  background: var(--color-paper-raised); color: var(--color-ink);
  cursor: pointer; font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  opacity: 0; pointer-events: none;
}}
.to-top.show {{ opacity: 1; pointer-events: auto; }}
.to-top:hover {{ color: var(--color-accent); border-color: var(--color-accent); }}
.to-top:active {{ color: var(--color-accent-hover); border-color: var(--color-accent-hover); }}
@media (min-width: 40rem) {{
  .article-card.has-image {{ grid-template-columns: minmax(16rem, .78fr) minmax(0, 1.22fr); }}
  .card-hero.has-image {{ grid-template-columns: minmax(20rem, 1.08fr) minmax(0, .92fr); }}
  .card-hero .card-title {{ font-size: clamp(2rem, 4.8vw, 3.65rem); }}
  .card-large .card-title {{ font-size: clamp(1.7rem, 3.4vw, 2.55rem); }}
}}
@media (min-width: 60rem) {{
  .masthead {{ padding-block: var(--space-xl) var(--space-2xl); }}
  .article-card {{ padding-block: var(--space-2xl); }}
  .card-body {{ padding-inline: var(--space-lg); }}
  .card-hero .card-body {{ padding-inline-end: var(--space-xl); }}
}}
@media (max-width: 39.999rem) {{
  .issue-line {{ grid-template-columns: minmax(0, 1fr) auto; }}
  .issue-meta {{ grid-column: 1 / -1; grid-row: 1; justify-self: center; padding-block: var(--space-xs); }}
  .issue-line > :first-child {{ grid-column: 1; grid-row: 2; }}
  .issue-line > :last-child {{ grid-column: 2; grid-row: 2; }}
  .mast-name {{ line-height: .86; }}
  .section-heading {{ display: grid; gap: var(--space-xs); }}
  .section-heading p {{ text-align: start; }}
  .article-card {{ padding-block: var(--space-lg); }}
  .card-tail {{ align-items: flex-start; flex-direction: column; gap: var(--space-md); }}
  .read-link {{ min-height: 2.75rem; display: inline-flex; align-items: center; }}
  .day-nav {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }}
  .nav-archive {{ grid-column: 1 / -1; grid-row: 1; justify-self: center; }}
  .nav-btn {{ grid-row: 2; }}
}}
@media (pointer: coarse) {{
  .filter-btn, .theme-toggle, .issue-link, .nav-btn, .nav-archive a, .read-link, .to-top {{ min-height: 3rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
}}
</style>
</head>
<body>
<div class="progress-track" aria-hidden="true"><div class="progress-fill" id="progress"></div></div>
<div class="site-shell">
  <header class="masthead">
    <div class="issue-line">
      <a class="issue-link" href="index.html">Archive</a>
      <span class="issue-meta">{date_str} · {count} article{"s" if count != 1 else ""}{read_html}</span>
      <button class="theme-toggle" type="button" onclick="toggleDark()" id="theme-btn" aria-label="Toggle color theme">
        <span class="theme-dark-label">Night</span><span class="theme-light-label">Day</span>
      </button>
    </div>
    <h1 class="mast-name">News Buddy</h1>
    <p class="mast-deck">A daily briefing on artificial intelligence—selected for signal, written for clarity.</p>
    <hr class="mast-rule" aria-hidden="true">
    {f'<div class="source-line" aria-label="Sources in this issue">{stats_html}</div>' if items else ''}
  </header>

  {'<nav class="filter-bar" aria-label="Filter articles by desk">' + filter_all + tag_filter_html + '</nav>' if tag_filter_html else ''}

  <main>
    {top_html + more_html if enriched_items else empty_msg}
  </main>

  <nav class="day-nav" aria-label="Browse daily issues">
    {prev_btn}
    <div class="nav-archive"><a href="index.html">All issues</a></div>
    {next_btn}
  </nav>

  <footer class="site-footer">
    <div class="footer-name">News Buddy</div>
    <p>{date_str}. {count} article{"s" if count != 1 else ""} selected from public feeds, summarized by the News Buddy pipeline, and linked to the original publishers. <a href="https://github.com/Harshagarwal06/buddy_agent" target="_blank" rel="noopener">View the source on GitHub ↗</a></p>
  </footer>
</div>

<button class="to-top" id="to-top" type="button" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" aria-label="Back to top">Top ↑</button>

<script>
function applyTheme(dark) {{
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
}}
function toggleDark() {{
  var now = document.documentElement.getAttribute('data-theme') === 'dark';
  localStorage.setItem('nb-theme', now ? 'light' : 'dark');
  applyTheme(!now);
}}
(function() {{
  var saved = localStorage.getItem('nb-theme');
  var sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved ? saved === 'dark' : sysDark);
}})();

document.querySelectorAll('.filter-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    var tag = this.getAttribute('data-tag');
    document.querySelectorAll('.filter-btn').forEach(function(other) {{
      other.classList.toggle('active', other.getAttribute('data-tag') === tag);
    }});
    document.querySelectorAll('.article-card').forEach(function(card) {{
      var tags = (card.getAttribute('data-tags') || '').split(',');
      card.classList.toggle('hidden', tag !== '__all__' && tags.indexOf(tag) === -1);
    }});
    document.querySelectorAll('.story-section').forEach(function(section) {{
      section.classList.toggle('hidden', !section.querySelector('.article-card:not(.hidden)'));
    }});
  }});
}});

var progress = document.getElementById('progress');
var toTop = document.getElementById('to-top');
function onScroll() {{
  var root = document.documentElement;
  var scrollTop = root.scrollTop || document.body.scrollTop;
  var max = root.scrollHeight - root.clientHeight;
  progress.style.width = (max > 0 ? scrollTop / max * 100 : 0) + '%';
  toTop.classList.toggle('show', scrollTop > 500);
}}
window.addEventListener('scroll', onScroll, {{passive: true}});
onScroll();
</script>
</body>
</html>"""

    target = output_dir / f"{date_str}.html"
    tmp = target.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(target)
    return target
