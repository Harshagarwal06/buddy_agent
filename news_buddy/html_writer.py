"""Generate a self-contained HTML digest page from enriched article items."""

from __future__ import annotations

from html import escape
from pathlib import Path

_TAG_COLOURS = {
    "ai":         ("#e8f0fe", "#1a56c4", "#1e3a5f", "#8bb8f5"),
    "technology": ("#e6f4ea", "#0f6b32", "#173a28", "#79cf9a"),
    "science":    ("#fbecc7", "#8a5200", "#3a2900", "#f0c65a"),
    "business":   ("#fce8e6", "#b31c1a", "#3d0a09", "#f28b82"),
    "world":      ("#f2e8fc", "#6f1b9a", "#2d0b40", "#d09cdb"),
    "politics":   ("#fdefc5", "#8a5200", "#3a2900", "#f0c65a"),
    "health":     ("#e6f4ea", "#0f6b32", "#173a28", "#79cf9a"),
    "climate":    ("#e6f5ea", "#256b2b", "#173a1c", "#84c988"),
    "security":   ("#fce8e6", "#b31c1a", "#3d0a09", "#ef9a9a"),
    "culture":    ("#f6effb", "#5f1a92", "#2a0a3d", "#d09cdb"),
    "other":      ("#eeeeee", "#55565b", "#2a2a2a", "#a0a0a6"),
}

_WPM = 220  # words per minute, for read-time estimate


def _tag_badge(tag: str) -> str:
    tag_value = str(tag)
    tag_key = tag_value.lower()
    colours = _TAG_COLOURS.get(tag_key, _TAG_COLOURS["other"])
    bg, fg = colours[0], colours[1]
    return (
        f'<span class="tag-badge" data-tag="{escape(tag_key, quote=True)}" '
        f'style="--tag-bg:{bg};--tag-fg:{fg};--tag-bg-dark:{colours[2]};--tag-fg-dark:{colours[3]}">'
        f'{escape(tag_value)}</span>'
    )


def _stars(importance: int) -> str:
    n = max(1, min(5, int(importance)))
    return "★" * n + "☆" * (5 - n)


def _read_minutes(items: list[dict]) -> int:
    words = sum(len((it.get("summary") or "").split()) for it in items)
    return max(1, round(words / _WPM)) if words else 0


def _article_card(item: dict, large: bool = False, hero: bool = False) -> str:
    title   = str(item.get("title", "Untitled"))
    url     = str(item.get("url", "#"))
    source  = str(item.get("source", ""))
    pub     = str(item.get("published_at") or "")[:10]
    summary = str(item.get("summary", ""))
    tags    = item.get("tags") or []
    imp     = item.get("importance", 3)
    icymi   = bool(item.get("is_icymi"))
    image_url = str(item.get("image_url") or "").strip()
    image_alt = str(item.get("image_alt") or f"Editorial illustration for {title}")

    badges  = "".join(_tag_badge(t) for t in tags)
    icymi_badge = '<span class="icymi-badge">ICYMI</span>' if icymi else ""
    stars   = _stars(imp)
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
    <div class="card-header">
      <a href="{safe_url}" target="_blank" rel="noopener" class="card-title">{safe_title}</a>
      <span class="card-stars" title="Importance {imp}/5" aria-label="Importance {imp} of 5">{stars}</span>
    </div>
    <div class="card-meta">{escape(source)}{' <span class="dot">·</span> ' + escape(pub) if pub else ''}{icymi_badge}</div>
    {"<p class='card-summary'>" + escape(summary) + "</p>" if summary else ""}
    <div class="card-tags">{badges}</div>
  </div>
</article>"""


def _source_stats(items: list[dict]) -> str:
    counts: dict[str, int] = {}
    for it in items:
        s = it.get("source", "Unknown")
        counts[s] = counts.get(s, 0) + 1
    parts = [f"<span class='stat-pill'>{escape(str(s))} <b>{n}</b></span>"
             for s, n in sorted(counts.items(), key=lambda x: -x[1])]
    return "".join(parts)


def write_html(
    output_dir: Path,
    date_str: str,
    enriched_items: list[dict],
    prev_date: str | None = None,
    next_date: str | None = None,
) -> Path:
    """Write a styled HTML digest. Returns the path written."""
    output_dir.mkdir(parents=True, exist_ok=True)

    items = sorted(enriched_items, key=lambda x: x.get("importance", 3), reverse=True)
    max_top = 5
    top  = items[:max_top]
    rest = items[max_top:]

    by_tag: dict[str, list[dict]] = {}
    for it in rest:
        tag = (it.get("tags") or ["other"])[0].lower()
        by_tag.setdefault(tag, []).append(it)

    # The single most important story gets a hero treatment; the rest of the
    # top slice renders as prominent large cards.
    top_html = ""
    if top:
        cards = _article_card(top[0], hero=True)
        cards += "\n".join(_article_card(it, large=True) for it in top[1:])
        top_html = (
            '<section class="story-section">'
            '<h2 class="section-heading">Top Stories</h2>'
            f'<div class="story-grid">{cards}</div>'
            "</section>"
        )

    more_html = ""
    for tag, tag_items in sorted(by_tag.items()):
        cards = "\n".join(_article_card(it) for it in tag_items)
        more_html += (
            '<section class="story-section">'
            f'<h2 class="section-heading">{escape(tag.title())}</h2>'
            f'<div class="story-grid">{cards}</div>'
            "</section>"
        )

    count = len(enriched_items)
    read_min = _read_minutes(items)
    read_html = f' <span class="dot">·</span> ~{read_min} min read' if read_min else ""
    stats_html = _source_stats(items)

    all_tags = sorted({t.lower() for it in items for t in (it.get("tags") or [])})
    tag_filter_html = "".join(
        f'<button class="filter-btn" data-tag="{t}">{t}</button>'
        for t in all_tags
    )
    filter_all = '<button class="filter-btn active" data-tag="__all__">All</button>'

    prev_btn = (
        f'<a href="{prev_date}.html" class="nav-btn">&#8592; {prev_date}</a>'
        if prev_date else '<span class="nav-btn nav-disabled">&#8592; Earlier</span>'
    )
    next_btn = (
        f'<a href="{next_date}.html" class="nav-btn">{next_date} &#8594;</a>'
        if next_date else '<span class="nav-btn nav-disabled">Later &#8594;</span>'
    )

    empty_msg = '<p class="empty-msg">No new articles today.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Buddy — {date_str}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #faf9f7;
  --surface: #ffffff;
  --surface-2: #f4f2ee;
  --border: #e8e5df;
  --border-strong: #d9d5cc;
  --text: #1a1a1a;
  --text-muted: #5f6067;
  --text-faint: #97969c;
  --accent: #1a56c4;
  --accent-hover: #123f96;
  --shadow: 0 1px 2px rgba(20,20,20,.04), 0 4px 14px rgba(20,20,20,.04);
  --shadow-hover: 0 2px 6px rgba(20,20,20,.06), 0 10px 30px rgba(20,20,20,.08);
  --star-color: #d99400;
  --serif: "Newsreader", Georgia, "Times New Roman", serif;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}}
[data-theme="dark"] {{
  --bg: #0f1114;
  --surface: #16181d;
  --surface-2: #1c1f26;
  --border: #262a31;
  --border-strong: #333944;
  --text: #ececef;
  --text-muted: #9a9aa2;
  --text-faint: #67676f;
  --accent: #8bb8f5;
  --accent-hover: #aecbfa;
  --shadow: 0 1px 2px rgba(0,0,0,.3), 0 4px 14px rgba(0,0,0,.35);
  --shadow-hover: 0 2px 6px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.5);
  --star-color: #f0c65a;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  transition: background .25s, color .25s;
}}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 0 24px 80px; }}

/* Reading progress bar */
.progress-track {{
  position: fixed; top: 0; left: 0; right: 0; height: 3px;
  background: transparent; z-index: 100;
}}
.progress-fill {{
  height: 100%; width: 0%;
  background: var(--accent);
  transition: width .08s linear;
}}

/* Masthead */
.masthead {{ padding: 34px 0 22px; border-bottom: 1px solid var(--border-strong); margin-bottom: 22px; }}
.mast-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
.wordmark {{
  font-family: var(--serif); font-weight: 600; font-size: 1.02rem;
  letter-spacing: .01em; color: var(--text);
  display: inline-flex; align-items: center; gap: 8px; text-decoration: none;
}}
.wordmark .glyph {{ color: var(--accent); }}
.header-label {{ font-size: 0.7rem; color: var(--text-faint); letter-spacing: .14em; text-transform: uppercase; margin-bottom: 8px; }}
.header-date {{ font-family: var(--serif); font-size: clamp(2rem, 7vw, 2.9rem); font-weight: 600; line-height: 1.05; letter-spacing: -0.01em; margin-bottom: 10px; }}
.header-count {{ font-size: 0.82rem; color: var(--text-muted); }}
.header-count .dot {{ color: var(--text-faint); margin: 0 2px; }}

/* Theme toggle */
.theme-toggle {{
  background: var(--surface); border: 1px solid var(--border-strong);
  color: var(--text-muted); border-radius: 999px;
  width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer; transition: border-color .15s, color .15s, background .15s; flex-shrink: 0;
}}
.theme-toggle:hover {{ border-color: var(--accent); color: var(--accent); }}
.theme-toggle svg {{ width: 17px; height: 17px; }}
.theme-toggle .icon-moon {{ display: block; }}
.theme-toggle .icon-sun {{ display: none; }}
[data-theme="dark"] .theme-toggle .icon-moon {{ display: none; }}
[data-theme="dark"] .theme-toggle .icon-sun {{ display: block; }}

/* Source stats */
.stats-bar {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }}
.stat-pill {{
  font-size: 0.72rem; color: var(--text-muted);
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 999px; padding: 3px 10px;
}}
.stat-pill b {{ color: var(--text); font-weight: 600; }}

/* Sticky tag filter bar */
.filter-bar {{
  position: sticky; top: 0; z-index: 50;
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 12px 0; margin-bottom: 8px;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: saturate(140%) blur(8px);
  -webkit-backdrop-filter: saturate(140%) blur(8px);
  border-bottom: 1px solid var(--border);
}}
.filter-btn {{
  background: var(--surface); border: 1px solid var(--border-strong);
  color: var(--text-muted); border-radius: 999px;
  padding: 5px 13px; font-size: 0.75rem; font-weight: 600;
  cursor: pointer; transition: all .15s; text-transform: capitalize;
}}
.filter-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.filter-btn.active {{ background: var(--text); border-color: var(--text); color: var(--bg); }}

/* Section headings */
.section-heading {{
  font-size: 0.72rem; font-weight: 700; color: var(--text-faint);
  text-transform: uppercase; letter-spacing: .12em;
  padding-bottom: 8px; margin: 34px 0 16px;
  border-bottom: 1px solid var(--border);
}}
.story-section.hidden {{ display: none; }}
.story-grid {{
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px; align-items: start;
}}

/* Cards */
.article-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden; min-width: 0;
  box-shadow: var(--shadow); transition: opacity .2s, transform .18s, box-shadow .18s, border-color .18s;
}}
.article-card:hover {{ box-shadow: var(--shadow-hover); transform: translateY(-1px); }}
.article-card.card-hero {{ grid-column: 1 / -1; border-color: var(--border-strong); }}
.article-card.card-hero.has-image {{
  display: grid; grid-template-columns: minmax(0, 1.12fr) minmax(320px, .88fr);
  align-items: stretch;
}}
.article-card.hidden {{ display: none; }}
.card-body {{ padding: 18px 20px 20px; }}
.card-large .card-body {{ padding: 20px 22px 22px; }}
.card-hero .card-body {{ padding: 28px 28px 26px; align-self: center; }}
.card-image {{
  display: block; aspect-ratio: 4 / 3; overflow: hidden;
  background: var(--surface-2); border-bottom: 1px solid var(--border);
}}
.card-image img {{
  display: block; width: 100%; height: 100%; object-fit: cover;
  transition: transform .35s ease;
}}
.article-card:hover .card-image img {{ transform: scale(1.012); }}
.card-hero.has-image .card-image {{
  height: 100%; min-height: 360px; aspect-ratio: auto;
  border-bottom: 0; border-right: 1px solid var(--border);
}}
.card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 6px; }}
.card-title {{
  font-family: var(--serif); font-size: 1.12rem; font-weight: 600; color: var(--text);
  text-decoration: none; line-height: 1.32; letter-spacing: -0.003em; flex: 1;
  transition: color .12s;
}}
.card-large .card-title {{ font-size: 1.2rem; }}
.card-hero .card-title {{ font-size: clamp(1.4rem, 4.4vw, 1.75rem); line-height: 1.24; }}
.card-title:hover {{ color: var(--accent); }}
.card-stars {{ font-size: 0.8rem; color: var(--star-color); white-space: nowrap; letter-spacing: 1px; flex-shrink: 0; margin-top: 4px; }}
.card-meta {{ font-size: 0.75rem; color: var(--text-faint); margin-bottom: 9px; }}
.card-meta .dot {{ margin: 0 2px; }}
.icymi-badge {{
  display: inline-block; margin-left: 8px; padding: 1px 7px;
  border: 1px solid var(--border-strong); border-radius: 999px;
  color: var(--text-muted); font-size: 0.62rem; font-weight: 700; letter-spacing: .05em;
}}
.card-summary {{ font-size: 0.9rem; color: var(--text-muted); line-height: 1.65; margin-bottom: 12px; }}
.card-hero .card-summary {{ font-size: 0.98rem; }}
.card-tags {{ display: flex; flex-wrap: wrap; gap: 5px; }}

/* Tag badges */
.tag-badge {{
  background: var(--tag-bg); color: var(--tag-fg);
  padding: 2px 10px; border-radius: 999px;
  font-size: 0.68rem; font-weight: 600; text-transform: capitalize;
}}
[data-theme="dark"] .tag-badge {{ background: var(--tag-bg-dark, #1e3a5f); color: var(--tag-fg-dark, #8bb8f5); }}

/* Navigation */
.day-nav {{ display: flex; justify-content: space-between; align-items: center; margin: 40px 0 8px; gap: 10px; }}
.nav-btn {{
  background: var(--surface); border: 1px solid var(--border-strong);
  color: var(--text-muted); border-radius: 999px;
  padding: 8px 16px; font-size: 0.8rem; font-weight: 600;
  text-decoration: none; transition: all .15s;
}}
a.nav-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.nav-disabled {{ opacity: .4; cursor: default; }}
.nav-archive {{ font-size: 0.78rem; text-align: center; }}
.nav-archive a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
.nav-archive a:hover {{ text-decoration: underline; }}

/* Empty state */
.empty-msg {{ color: var(--text-faint); text-align: center; padding: 56px 0; font-family: var(--serif); font-size: 1.1rem; }}

/* Footer */
.site-footer {{
  text-align: center; font-size: 0.72rem; color: var(--text-faint);
  margin-top: 48px; padding-top: 22px; border-top: 1px solid var(--border);
}}
.site-footer a {{ color: var(--text-muted); text-decoration: none; }}
.site-footer a:hover {{ color: var(--accent); }}

/* Back to top */
.to-top {{
  position: fixed; right: 20px; bottom: 20px; z-index: 60;
  width: 42px; height: 42px; border-radius: 50%;
  background: var(--surface); border: 1px solid var(--border-strong);
  color: var(--text-muted); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow); opacity: 0; pointer-events: none;
  transform: translateY(8px); transition: opacity .2s, transform .2s, color .15s, border-color .15s;
}}
.to-top.show {{ opacity: 1; pointer-events: auto; transform: translateY(0); }}
.to-top:hover {{ color: var(--accent); border-color: var(--accent); }}
.to-top svg {{ width: 18px; height: 18px; }}

@media (max-width: 760px) {{
  .wrap {{ padding: 0 14px 56px; }}
  .masthead {{ padding: 24px 0 18px; }}
  .story-grid {{ grid-template-columns: 1fr; gap: 14px; }}
  .article-card.card-hero {{ grid-column: auto; }}
  .article-card.card-hero.has-image {{ display: block; }}
  .card-hero.has-image .card-image {{
    min-height: 0; aspect-ratio: 4 / 3;
    border-right: 0; border-bottom: 1px solid var(--border);
  }}
  .card-body, .card-large .card-body {{ padding: 16px; }}
  .card-hero .card-body {{ padding: 20px 18px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  *, *::before, *::after {{ transition: none !important; }}
}}
</style>
</head>
<body>
<div class="progress-track"><div class="progress-fill" id="progress"></div></div>
<div class="wrap">

  <header class="masthead">
    <div class="mast-top">
      <a class="wordmark" href="index.html"><span class="glyph">&#9632;</span> News Buddy</a>
      <button class="theme-toggle" onclick="toggleDark()" id="theme-btn" aria-label="Toggle dark mode" title="Toggle theme">
        <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      </button>
    </div>
    <div class="header-label">Daily News Digest</div>
    <h1 class="header-date">{date_str}</h1>
    <div class="header-count">{count} article{"s" if count != 1 else ""}{read_html}</div>
    {f'<div class="stats-bar">{stats_html}</div>' if items else ''}
  </header>

  {'<div class="filter-bar">' + filter_all + tag_filter_html + '</div>' if tag_filter_html else ''}

  {f'''
  {top_html}
  {more_html}
  ''' if enriched_items else empty_msg}

  <nav class="day-nav">
    {prev_btn}
    <div class="nav-archive"><a href="index.html">&#9776; Archive</a></div>
    {next_btn}
  </nav>

  <footer class="site-footer">
    News Buddy &nbsp;·&nbsp; {date_str} &nbsp;·&nbsp;
    <a href="https://github.com/Harshagarwal06/buddy_agent" target="_blank" rel="noopener">source</a>
  </footer>

</div>

<button class="to-top" id="to-top" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" aria-label="Back to top">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
</button>

<script>
// -- Dark mode --
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

// -- Tag filter --
var activeTag = '__all__';
document.querySelectorAll('.filter-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    var tag = this.getAttribute('data-tag');
    activeTag = tag;
    document.querySelectorAll('.filter-btn').forEach(function(b) {{
      b.classList.toggle('active', b.getAttribute('data-tag') === tag);
    }});
    document.querySelectorAll('.article-card').forEach(function(c) {{
      var tags = (c.getAttribute('data-tags') || '').split(',');
      c.classList.toggle('hidden', tag !== '__all__' && tags.indexOf(tag) === -1);
    }});
    document.querySelectorAll('.story-section').forEach(function(section) {{
      var visibleCard = section.querySelector('.article-card:not(.hidden)');
      section.classList.toggle('hidden', !visibleCard);
    }});
  }});
}});

// -- Reading progress + back to top --
var progress = document.getElementById('progress');
var toTop = document.getElementById('to-top');
function onScroll() {{
  var h = document.documentElement;
  var max = h.scrollHeight - h.clientHeight;
  var pct = max > 0 ? (h.scrollTop || document.body.scrollTop) / max * 100 : 0;
  progress.style.width = pct + '%';
  toTop.classList.toggle('show', (h.scrollTop || document.body.scrollTop) > 400);
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
