"""Generate an archive index.html listing all past digest pages.

Called by the GitHub Actions workflow after writing today's dated HTML file.
Scans the output directory for YYYY-MM-DD.html files and builds a landing page
with date, article count, and top tags extracted from each file's metadata.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import date as _date


def _extract_meta(html_path: Path) -> dict:
    """Pull count and tags out of a rendered digest HTML (best-effort)."""
    try:
        text = html_path.read_text(encoding="utf-8")
        count_m = re.search(r"(\d+) article", text)
        count = int(count_m.group(1)) if count_m else 0
        tag_m = re.findall(r'data-tag="([^"]+)"', text)
        tags = sorted(set(tag_m))[:4]
        return {"count": count, "tags": tags}
    except Exception:
        return {"count": 0, "tags": []}


_TAG_COLOURS = {
    "ai": ("#e8f0fe", "#1a73e8", "#1e3a5f", "#7ab3f5"),
    "technology": ("#e6f4ea", "#137333", "#1a3d2b", "#6fcf97"),
    "science": ("#fce8b2", "#b06000", "#3d2800", "#f6c84b"),
    "business": ("#fce8e6", "#c5221f", "#3d0a09", "#f28b82"),
    "world": ("#f3e8fd", "#7b1fa2", "#2d0b40", "#ce93d8"),
    "politics": ("#feefc3", "#b06000", "#3d2800", "#f6c84b"),
    "health": ("#e6f4ea", "#137333", "#1a3d2b", "#6fcf97"),
    "climate": ("#e8f5e9", "#2e7d32", "#1a3d1c", "#81c784"),
    "security": ("#fce8e6", "#c62828", "#3d0a09", "#ef9a9a"),
    "culture": ("#f8f0fb", "#6a1b9a", "#2a0a3d", "#ce93d8"),
    "other": ("#f1f3f4", "#5f6368", "#2d2d2d", "#9aa0a6"),
}


def _tag_pill(tag: str) -> str:
    c = _TAG_COLOURS.get(tag.lower(), _TAG_COLOURS["other"])
    return (
        f'<span class="tag-pill" style="--lbg:{c[0]};--lfg:{c[1]};--dbg:{c[2]};--dfg:{c[3]}">'
        f'{tag}</span>'
    )


def _day_row(date_str: str, meta: dict, is_today: bool) -> str:
    tags_html = "".join(_tag_pill(t) for t in meta["tags"])
    count = meta["count"]
    today_badge = '<span class="today-badge">Today</span>' if is_today else ""
    return f"""
<a href="{date_str}.html" class="day-row">
  <div class="day-left">
    <span class="day-date">{date_str}</span>
    {today_badge}
    <span class="day-tags">{tags_html}</span>
  </div>
  <span class="day-count">{count} article{"s" if count != 1 else ""} &rsaquo;</span>
</a>"""


def write_archive(output_dir: Path) -> Path:
    """Scan output_dir for YYYY-MM-DD.html files and write index.html."""
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")
    dated_files = sorted(
        [p for p in output_dir.glob("*.html") if pattern.match(p.name)],
        reverse=True,
    )

    today_str = _date.today().isoformat()
    rows_html = ""
    for p in dated_files:
        date_str = p.stem
        meta = _extract_meta(p)
        rows_html += _day_row(date_str, meta, date_str == today_str)

    total_days = len(dated_files)
    empty_msg = '<p class="empty-msg">No digests yet — run the pipeline to generate your first one.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Buddy — Archive</title>
<style>
:root {{
  --bg: #f8f9fa; --surface: #fff; --border: #e0e0e0;
  --text: #1a1a1a; --text-muted: #666; --text-faint: #999;
  --accent: #1a73e8;
  --header-bg: linear-gradient(135deg, #1a73e8, #0d47a1);
  --shadow: 0 1px 4px rgba(0,0,0,.07);
  --row-hover: #f0f6ff;
}}
[data-theme="dark"] {{
  --bg: #111318; --surface: #1e2128; --border: #2e3240;
  --text: #e8eaed; --text-muted: #9aa0a6; --text-faint: #5f6368;
  --accent: #7ab3f5;
  --header-bg: linear-gradient(135deg, #1e3a5f, #0d2647);
  --shadow: 0 1px 4px rgba(0,0,0,.3);
  --row-hover: #1e2d44;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); transition: background .2s, color .2s; }}
.wrap {{ max-width: 680px; margin: 0 auto; padding: 20px 16px 60px; }}
.site-header {{
  background: var(--header-bg); color: #fff;
  border-radius: 14px; padding: 22px 24px 18px; margin-bottom: 24px;
  display: flex; justify-content: space-between; align-items: center;
}}
.header-title {{ font-size: 1.5rem; font-weight: 800; }}
.header-sub {{ font-size: 0.8rem; opacity: .75; margin-top: 3px; }}
.dark-toggle {{
  background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.3);
  color: #fff; border-radius: 20px; padding: 5px 12px;
  font-size: 0.78rem; cursor: pointer; white-space: nowrap;
}}
.dark-toggle:hover {{ background: rgba(255,255,255,.28); }}
.day-list {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; overflow: hidden; box-shadow: var(--shadow);
}}
.day-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
  text-decoration: none; color: var(--text);
  transition: background .12s;
}}
.day-row:last-child {{ border-bottom: none; }}
.day-row:hover {{ background: var(--row-hover); }}
.day-left {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
.day-date {{ font-weight: 700; font-size: 0.9rem; }}
.today-badge {{
  background: #1a73e8; color: #fff;
  font-size: 0.65rem; font-weight: 700; padding: 1px 7px;
  border-radius: 10px; letter-spacing: .04em; text-transform: uppercase;
}}
.day-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.tag-pill {{
  background: var(--lbg); color: var(--lfg);
  padding: 1px 7px; border-radius: 10px; font-size: 0.68rem; font-weight: 600;
}}
[data-theme="dark"] .tag-pill {{ background: var(--dbg); color: var(--dfg); }}
.day-count {{ font-size: 0.78rem; color: var(--text-faint); white-space: nowrap; }}
.empty-msg {{ color: var(--text-faint); text-align: center; padding: 48px 0; }}
.site-footer {{
  text-align: center; font-size: 0.72rem; color: var(--text-faint);
  margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border);
}}
.site-footer a {{ color: var(--text-faint); }}
.site-footer a:hover {{ color: var(--accent); }}
@media (max-width: 600px) {{
  .wrap {{ padding: 12px 10px 40px; }}
  .site-header {{ border-radius: 10px; padding: 16px; }}
  .header-title {{ font-size: 1.25rem; }}
  .day-row {{ padding: 12px 14px; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="site-header">
    <div>
      <div class="header-title">&#128240; News Buddy</div>
      <div class="header-sub">{total_days} digest{"s" if total_days != 1 else ""} in archive</div>
    </div>
    <button class="dark-toggle" onclick="toggleDark()" id="dark-btn">🌙 Dark</button>
  </div>

  {'<div class="day-list">' + rows_html + '</div>' if dated_files else empty_msg}

  <div class="site-footer">
    News Buddy &nbsp;·&nbsp;
    <a href="https://github.com/Harshagarwal06/buddy_agent" target="_blank">source</a>
  </div>
</div>
<script>
function applyTheme(dark) {{
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('dark-btn').textContent = dark ? '☀ Light' : '🌙 Dark';
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
</script>
</body>
</html>"""

    target = output_dir / "index.html"
    tmp = target.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(target)
    return target
