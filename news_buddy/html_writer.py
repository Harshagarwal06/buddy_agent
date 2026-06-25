"""Generate a self-contained HTML digest page from enriched article items."""

from __future__ import annotations

from pathlib import Path

_TAG_COLOURS = {
    "ai":         ("#e8f0fe", "#1a73e8", "#1e3a5f", "#7ab3f5"),
    "technology": ("#e6f4ea", "#137333", "#1a3d2b", "#6fcf97"),
    "science":    ("#fce8b2", "#b06000", "#3d2800", "#f6c84b"),
    "business":   ("#fce8e6", "#c5221f", "#3d0a09", "#f28b82"),
    "world":      ("#f3e8fd", "#7b1fa2", "#2d0b40", "#ce93d8"),
    "politics":   ("#feefc3", "#b06000", "#3d2800", "#f6c84b"),
    "health":     ("#e6f4ea", "#137333", "#1a3d2b", "#6fcf97"),
    "climate":    ("#e8f5e9", "#2e7d32", "#1a3d1c", "#81c784"),
    "security":   ("#fce8e6", "#c62828", "#3d0a09", "#ef9a9a"),
    "culture":    ("#f8f0fb", "#6a1b9a", "#2a0a3d", "#ce93d8"),
    "other":      ("#f1f3f4", "#5f6368", "#2d2d2d", "#9aa0a6"),
}


def _tag_badge(tag: str) -> str:
    colours = _TAG_COLOURS.get(tag.lower(), _TAG_COLOURS["other"])
    bg, fg = colours[0], colours[1]
    return (
        f'<span class="tag-badge" data-tag="{tag.lower()}" '
        f'style="--tag-bg:{bg};--tag-fg:{fg};--tag-bg-dark:{colours[2]};--tag-fg-dark:{colours[3]}">'
        f'{tag}</span>'
    )


def _stars(importance: int) -> str:
    n = max(1, min(5, int(importance)))
    return "★" * n + "☆" * (5 - n)


def _article_card(item: dict, large: bool = False) -> str:
    title   = item.get("title", "Untitled")
    url     = item.get("url", "#")
    source  = item.get("source", "")
    pub     = (item.get("published_at") or "")[:10]
    summary = item.get("summary", "")
    tags    = item.get("tags") or []
    imp     = item.get("importance", 3)

    badges  = "".join(_tag_badge(t) for t in tags)
    stars   = _stars(imp)
    tag_classes = " ".join(f"has-tag-{t.lower()}" for t in tags) or "has-tag-other"
    size_class = "card-large" if large else "card-normal"

    return f"""
<div class="article-card {size_class} {tag_classes}" data-tags="{','.join(t.lower() for t in tags)}">
  <div class="card-header">
    <a href="{url}" target="_blank" rel="noopener" class="card-title">{title}</a>
    <span class="card-stars" title="Importance {imp}/5">{stars}</span>
  </div>
  <div class="card-meta">{source}{' &nbsp;·&nbsp; ' + pub if pub else ''}</div>
  {"<p class='card-summary'>" + summary + "</p>" if summary else ""}
  <div class="card-tags">{badges}</div>
</div>"""


def _source_stats(items: list[dict]) -> str:
    counts: dict[str, int] = {}
    for it in items:
        s = it.get("source", "Unknown")
        counts[s] = counts.get(s, 0) + 1
    parts = [f"<span class='stat-pill'>{s} <b>{n}</b></span>"
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

    top_html = "\n".join(_article_card(it, large=True) for it in top)

    more_html = ""
    for tag, tag_items in sorted(by_tag.items()):
        cards = "\n".join(_article_card(it) for it in tag_items)
        more_html += f'<h2 class="section-heading">{tag.title()}</h2>\n{cards}\n'

    count = len(enriched_items)
    stats_html = _source_stats(items)

    all_tags = sorted({t.lower() for it in items for t in (it.get("tags") or [])})
    tag_filter_html = "".join(
        f'<button class="filter-btn" data-tag="{t}">{t}</button>'
        for t in all_tags
    )

    prev_btn = (
        f'<a href="{prev_date}.html" class="nav-btn">&#8592; {prev_date}</a>'
        if prev_date else '<span class="nav-btn nav-disabled">&#8592; Earlier</span>'
    )
    next_btn = (
        f'<a href="{next_date}.html" class="nav-btn">&#8594; {next_date}</a>'
        if next_date else '<span class="nav-btn nav-disabled">Later &#8594;</span>'
    )

    empty_msg = '<p class="empty-msg">No new articles today.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Buddy — {date_str}</title>
<style>
:root {{
  --bg: #f8f9fa;
  --surface: #ffffff;
  --border: #e0e0e0;
  --text: #1a1a1a;
  --text-muted: #666;
  --text-faint: #999;
  --accent: #1a73e8;
  --accent-hover: #1557b0;
  --header-bg: linear-gradient(135deg, #1a73e8, #0d47a1);
  --shadow: 0 1px 4px rgba(0,0,0,.07);
  --star-color: #f9a825;
  --tag-bg: var(--tag-bg-light, #e8f0fe);
  --tag-fg: var(--tag-fg-light, #1a73e8);
}}
[data-theme="dark"] {{
  --bg: #111318;
  --surface: #1e2128;
  --border: #2e3240;
  --text: #e8eaed;
  --text-muted: #9aa0a6;
  --text-faint: #5f6368;
  --accent: #7ab3f5;
  --accent-hover: #aecbfa;
  --header-bg: linear-gradient(135deg, #1e3a5f, #0d2647);
  --shadow: 0 1px 4px rgba(0,0,0,.3);
  --star-color: #f6c84b;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  transition: background .2s, color .2s;
}}
.wrap {{ max-width: 780px; margin: 0 auto; padding: 20px 16px 60px; }}

/* Header */
.site-header {{
  background: var(--header-bg);
  color: #fff;
  border-radius: 14px;
  padding: 22px 24px 18px;
  margin-bottom: 20px;
  position: relative;
}}
.header-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.header-label {{ font-size: 0.72rem; opacity: .75; letter-spacing: .07em; text-transform: uppercase; margin-bottom: 4px; }}
.header-date {{ font-size: 1.55rem; font-weight: 800; margin-bottom: 4px; }}
.header-count {{ font-size: 0.82rem; opacity: .8; }}
.dark-toggle {{
  background: rgba(255,255,255,.18);
  border: 1px solid rgba(255,255,255,.3);
  color: #fff;
  border-radius: 20px;
  padding: 5px 12px;
  font-size: 0.78rem;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background .15s;
}}
.dark-toggle:hover {{ background: rgba(255,255,255,.28); }}

/* Source stats */
.stats-bar {{
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid rgba(255,255,255,.2);
}}
.stat-pill {{
  font-size: 0.72rem; color: rgba(255,255,255,.8);
  background: rgba(255,255,255,.12);
  border-radius: 10px; padding: 2px 8px;
}}
.stat-pill b {{ color: #fff; }}

/* Tag filter bar */
.filter-bar {{
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-bottom: 18px;
}}
.filter-btn {{
  background: var(--surface); border: 1.5px solid var(--border);
  color: var(--text-muted); border-radius: 20px;
  padding: 4px 12px; font-size: 0.75rem; font-weight: 600;
  cursor: pointer; transition: all .15s;
}}
.filter-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.filter-btn.active {{
  background: var(--accent); border-color: var(--accent);
  color: #fff;
}}

/* Section headings */
.section-heading {{
  font-size: 0.78rem; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .08em;
  border-bottom: 2px solid var(--border); padding-bottom: 6px;
  margin: 28px 0 14px;
}}

/* Cards */
.article-card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px; margin-bottom: 12px;
  box-shadow: var(--shadow); transition: opacity .2s, transform .15s;
}}
.article-card.card-large {{ padding: 20px 22px; }}
.article-card.hidden {{ display: none; }}
.card-header {{
  display: flex; justify-content: space-between;
  align-items: flex-start; gap: 10px; margin-bottom: 5px;
}}
.card-title {{
  font-size: 0.96rem; font-weight: 700; color: var(--text);
  text-decoration: none; line-height: 1.4; flex: 1;
  transition: color .12s;
}}
.card-large .card-title {{ font-size: 1.04rem; }}
.card-title:hover {{ color: var(--accent); }}
.card-stars {{ font-size: 0.85rem; color: var(--star-color); white-space: nowrap; letter-spacing: 1px; flex-shrink: 0; }}
.card-meta {{ font-size: 0.75rem; color: var(--text-faint); margin-bottom: 8px; }}
.card-summary {{ font-size: 0.86rem; color: var(--text-muted); line-height: 1.6; margin-bottom: 10px; }}
.card-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}

/* Tag badges */
.tag-badge {{
  background: var(--tag-bg); color: var(--tag-fg);
  padding: 2px 9px; border-radius: 12px;
  font-size: 0.7rem; font-weight: 600;
}}
[data-theme="dark"] .tag-badge {{
  background: var(--tag-bg-dark, #1e3a5f);
  color: var(--tag-fg-dark, #7ab3f5);
}}

/* Navigation */
.day-nav {{
  display: flex; justify-content: space-between; align-items: center;
  margin: 32px 0 20px; gap: 10px;
}}
.nav-btn {{
  background: var(--surface); border: 1.5px solid var(--border);
  color: var(--text-muted); border-radius: 8px;
  padding: 8px 16px; font-size: 0.82rem; font-weight: 600;
  text-decoration: none; transition: all .15s;
}}
a.nav-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.nav-disabled {{ opacity: .4; cursor: default; }}
.nav-archive {{
  font-size: 0.78rem; color: var(--text-faint); text-align: center;
}}
.nav-archive a {{ color: var(--accent); text-decoration: none; }}
.nav-archive a:hover {{ text-decoration: underline; }}

/* Empty state */
.empty-msg {{ color: var(--text-faint); text-align: center; padding: 48px 0; }}

/* Footer */
.site-footer {{
  text-align: center; font-size: 0.72rem; color: var(--text-faint);
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
}}
.site-footer a {{ color: var(--text-faint); }}
.site-footer a:hover {{ color: var(--accent); }}

@media (max-width: 600px) {{
  .wrap {{ padding: 12px 10px 40px; }}
  .site-header {{ border-radius: 10px; padding: 16px 16px 14px; }}
  .header-date {{ font-size: 1.3rem; }}
  .article-card {{ padding: 14px 14px; }}
  .article-card.card-large {{ padding: 16px 14px; }}
}}
</style>
</head>
<body>
<div class="wrap">

  <div class="site-header">
    <div class="header-top">
      <div>
        <div class="header-label">Daily News Digest</div>
        <div class="header-date">{date_str}</div>
        <div class="header-count">{count} article{"s" if count != 1 else ""}</div>
      </div>
      <button class="dark-toggle" onclick="toggleDark()" id="dark-btn">🌙 Dark</button>
    </div>
    {f'<div class="stats-bar">{stats_html}</div>' if items else ''}
  </div>

  {'<div class="filter-bar">' + tag_filter_html + '</div>' if tag_filter_html else ''}

  {f'''
  <h2 class="section-heading">Top Stories</h2>
  {top_html}
  {more_html}
  ''' if enriched_items else empty_msg}

  <div class="day-nav">
    {prev_btn}
    <div class="nav-archive"><a href="index.html">&#128197; Archive</a></div>
    {next_btn}
  </div>

  <div class="site-footer">
    News Buddy &nbsp;·&nbsp; {date_str} &nbsp;·&nbsp;
    <a href="https://github.com/Harshagarwal06/buddy_agent" target="_blank">source</a>
  </div>

</div>
<script>
// ── Dark mode ─────────────────────────────────────────────────────────────────
function applyTheme(dark) {{
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('dark-btn').textContent = dark ? '☀ Light' : '🌙 Dark';
}}
function toggleDark() {{
  const now = document.documentElement.getAttribute('data-theme') === 'dark';
  localStorage.setItem('nb-theme', now ? 'light' : 'dark');
  applyTheme(!now);
}}
(function() {{
  const saved = localStorage.getItem('nb-theme');
  const sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved ? saved === 'dark' : sysDark);
}})();

// ── Tag filter ────────────────────────────────────────────────────────────────
var activeTag = null;
document.querySelectorAll('.filter-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    var tag = this.getAttribute('data-tag');
    if (activeTag === tag) {{
      activeTag = null;
      document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
      document.querySelectorAll('.article-card').forEach(function(c) {{ c.classList.remove('hidden'); }});
    }} else {{
      activeTag = tag;
      document.querySelectorAll('.filter-btn').forEach(function(b) {{
        b.classList.toggle('active', b.getAttribute('data-tag') === tag);
      }});
      document.querySelectorAll('.article-card').forEach(function(c) {{
        var tags = (c.getAttribute('data-tags') || '').split(',');
        c.classList.toggle('hidden', tags.indexOf(tag) === -1);
      }});
    }}
  }});
}});
</script>
</body>
</html>"""

    target = output_dir / f"{date_str}.html"
    tmp = target.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(target)
    return target
