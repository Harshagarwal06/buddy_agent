"""Generate an archive index.html listing all past digest pages.

Called by the GitHub Actions workflow after writing today's dated HTML file.
Scans the output directory for YYYY-MM-DD.html files and builds a landing page
with date, article count, and top tags extracted from each file's metadata.
"""
from __future__ import annotations

import os
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
        tags = sorted(set(t for t in tag_m if t != "__all__"))[:4]
        return {"count": count, "tags": tags}
    except Exception:
        return {"count": 0, "tags": []}


_TAG_COLOURS = {
    "ai": ("#e8f0fe", "#1a56c4", "#1e3a5f", "#8bb8f5"),
    "technology": ("#e6f4ea", "#0f6b32", "#173a28", "#79cf9a"),
    "science": ("#fbecc7", "#8a5200", "#3a2900", "#f0c65a"),
    "business": ("#fce8e6", "#b31c1a", "#3d0a09", "#f28b82"),
    "world": ("#f2e8fc", "#6f1b9a", "#2d0b40", "#d09cdb"),
    "politics": ("#fdefc5", "#8a5200", "#3a2900", "#f0c65a"),
    "health": ("#e6f4ea", "#0f6b32", "#173a28", "#79cf9a"),
    "climate": ("#e6f5ea", "#256b2b", "#173a1c", "#84c988"),
    "security": ("#fce8e6", "#b31c1a", "#3d0a09", "#ef9a9a"),
    "culture": ("#f6effb", "#5f1a92", "#2a0a3d", "#d09cdb"),
    "other": ("#eeeeee", "#55565b", "#2a2a2a", "#a0a0a6"),
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
    search_key = f'{date_str} {" ".join(meta["tags"])}'.lower()
    return f"""
<a href="{date_str}.html" class="day-row" data-search="{search_key}">
  <div class="day-left">
    <span class="day-date">{date_str}</span>
    {today_badge}
    <span class="day-tags">{tags_html}</span>
  </div>
  <span class="day-count">{count} article{"s" if count != 1 else ""} &rsaquo;</span>
</a>"""


def _signup_form() -> str:
    """Buttondown signup embed; empty string when BUTTONDOWN_USERNAME is unset.

    The form's CSS is emitted here (not in the page's main style block) so the
    page carries zero signup artifacts when the feature is unconfigured.
    """
    username = os.getenv("BUTTONDOWN_USERNAME", "").strip()
    if not username:
        return ""
    return f"""
  <style>
  .signup-box {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; box-shadow: var(--shadow);
    padding: 24px 20px; margin-top: 26px; text-align: center;
  }}
  .signup-title {{ font-family: var(--serif); font-weight: 600; font-size: 1.15rem; margin-bottom: 4px; }}
  .signup-sub {{ font-size: 0.8rem; color: var(--text-muted); margin-bottom: 14px; }}
  .signup-form {{ display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }}
  .signup-form input[type=email] {{
    flex: 1 1 200px; max-width: 300px; padding: 9px 13px;
    border: 1px solid var(--border-strong); border-radius: 999px;
    background: var(--bg); color: var(--text); font-size: 0.88rem;
  }}
  .signup-form input[type=email]:focus {{ outline: none; border-color: var(--accent); }}
  .signup-form button {{
    background: var(--accent); color: #fff; border: none; border-radius: 999px;
    padding: 9px 20px; font-weight: 600; font-size: 0.88rem; cursor: pointer; transition: opacity .15s;
  }}
  .signup-form button:hover {{ opacity: .9; }}
  </style>
  <div class="signup-box">
    <div class="signup-title">Get this digest by email</div>
    <div class="signup-sub">One email every morning at 6am IST. Unsubscribe anytime.</div>
    <form class="signup-form"
          action="https://buttondown.com/api/emails/embed-subscribe/{username}"
          method="post" target="_blank">
      <input type="email" name="email" aria-label="Email address"
             placeholder="you@example.com" required>
      <button type="submit">Subscribe</button>
    </form>
  </div>"""


def write_archive(output_dir: Path) -> Path:
    """Scan output_dir for YYYY-MM-DD.html files and write index.html."""
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")
    dated_files = sorted(
        [p for p in output_dir.glob("*.html") if pattern.match(p.name)],
        reverse=True,
    )

    today_str = _date.today().isoformat()
    rows_html = ""
    total_articles = 0
    for p in dated_files:
        date_str = p.stem
        meta = _extract_meta(p)
        total_articles += meta["count"]
        rows_html += _day_row(date_str, meta, date_str == today_str)

    total_days = len(dated_files)
    empty_msg = '<p class="empty-msg">No digests yet — run the pipeline to generate your first one.</p>'

    search_html = (
        '<div class="search-box">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
        '<input type="search" id="archive-search" placeholder="Filter by date or topic…" aria-label="Filter digests">'
        '</div>'
        if dated_files else ""
    )
    stats_line = (
        f'<div class="header-sub">{total_days} digest{"s" if total_days != 1 else ""} '
        f'<span class="dot">·</span> {total_articles} articles archived</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>News Buddy — Archive</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;0,6..72,700;1,6..72,500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #faf9f7; --surface: #fff; --surface-2: #f4f2ee;
  --border: #e8e5df; --border-strong: #d9d5cc;
  --text: #1a1a1a; --text-muted: #5f6067; --text-faint: #97969c;
  --accent: #1a56c4; --accent-hover: #123f96;
  --shadow: 0 1px 2px rgba(20,20,20,.04), 0 4px 14px rgba(20,20,20,.04);
  --row-hover: #f4f2ee;
  --serif: "Newsreader", Georgia, "Times New Roman", serif;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}}
[data-theme="dark"] {{
  --bg: #0f1114; --surface: #16181d; --surface-2: #1c1f26;
  --border: #262a31; --border-strong: #333944;
  --text: #ececef; --text-muted: #9a9aa2; --text-faint: #67676f;
  --accent: #8bb8f5; --accent-hover: #aecbfa;
  --shadow: 0 1px 2px rgba(0,0,0,.3), 0 4px 14px rgba(0,0,0,.35);
  --row-hover: #1c1f26;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: var(--sans); background: var(--bg); color: var(--text);
  line-height: 1.6; -webkit-font-smoothing: antialiased;
  transition: background .25s, color .25s;
}}
.wrap {{ max-width: 680px; margin: 0 auto; padding: 0 20px 80px; }}

.masthead {{ padding: 34px 0 22px; border-bottom: 1px solid var(--border-strong); margin-bottom: 24px; }}
.mast-top {{ display: flex; justify-content: space-between; align-items: center; }}
.header-title {{ font-family: var(--serif); font-size: clamp(1.9rem, 6vw, 2.5rem); font-weight: 600; letter-spacing: -0.01em; display: inline-flex; align-items: center; gap: 10px; }}
.header-title .glyph {{ color: var(--accent); font-size: 0.7em; }}
.header-sub {{ font-size: 0.82rem; color: var(--text-muted); margin-top: 10px; }}
.header-sub .dot {{ color: var(--text-faint); margin: 0 3px; }}
.theme-toggle {{
  background: var(--surface); border: 1px solid var(--border-strong);
  color: var(--text-muted); border-radius: 999px;
  width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer; transition: border-color .15s, color .15s; flex-shrink: 0;
}}
.theme-toggle:hover {{ border-color: var(--accent); color: var(--accent); }}
.theme-toggle svg {{ width: 17px; height: 17px; }}
.theme-toggle .icon-moon {{ display: block; }}
.theme-toggle .icon-sun {{ display: none; }}
[data-theme="dark"] .theme-toggle .icon-moon {{ display: none; }}
[data-theme="dark"] .theme-toggle .icon-sun {{ display: block; }}

/* Search */
.search-box {{
  display: flex; align-items: center; gap: 9px;
  background: var(--surface); border: 1px solid var(--border-strong);
  border-radius: 999px; padding: 9px 15px; margin-bottom: 18px;
  transition: border-color .15s;
}}
.search-box:focus-within {{ border-color: var(--accent); }}
.search-box svg {{ width: 16px; height: 16px; color: var(--text-faint); flex-shrink: 0; }}
.search-box input {{
  border: none; outline: none; background: transparent; width: 100%;
  color: var(--text); font-size: 0.9rem; font-family: var(--sans);
}}
.search-box input::placeholder {{ color: var(--text-faint); }}

.day-list {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; overflow: hidden; box-shadow: var(--shadow);
}}
.day-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 15px 18px; border-bottom: 1px solid var(--border);
  text-decoration: none; color: var(--text); transition: background .12s;
}}
.day-row:last-child {{ border-bottom: none; }}
.day-row:hover {{ background: var(--row-hover); }}
.day-row.hidden {{ display: none; }}
.day-left {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
.day-date {{ font-family: var(--serif); font-weight: 600; font-size: 1.02rem; }}
.today-badge {{
  background: var(--accent); color: #fff;
  font-size: 0.62rem; font-weight: 700; padding: 2px 8px;
  border-radius: 999px; letter-spacing: .05em; text-transform: uppercase;
}}
.day-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.tag-pill {{
  background: var(--lbg); color: var(--lfg);
  padding: 2px 9px; border-radius: 999px; font-size: 0.66rem; font-weight: 600; text-transform: capitalize;
}}
[data-theme="dark"] .tag-pill {{ background: var(--dbg); color: var(--dfg); }}
.day-count {{ font-size: 0.78rem; color: var(--text-faint); white-space: nowrap; }}
.empty-msg, .no-results {{ color: var(--text-faint); text-align: center; padding: 48px 0; font-family: var(--serif); font-size: 1.05rem; }}
.no-results {{ display: none; }}
.site-footer {{
  text-align: center; font-size: 0.72rem; color: var(--text-faint);
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
}}
.site-footer a {{ color: var(--text-muted); text-decoration: none; }}
.site-footer a:hover {{ color: var(--accent); }}
@media (max-width: 600px) {{
  .wrap {{ padding: 0 14px 56px; }}
  .masthead {{ padding: 24px 0 18px; }}
  .day-row {{ padding: 13px 14px; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ transition: none !important; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div class="mast-top">
      <div class="header-title"><span class="glyph">&#9632;</span> News Buddy</div>
      <button class="theme-toggle" onclick="toggleDark()" id="theme-btn" aria-label="Toggle dark mode" title="Toggle theme">
        <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      </button>
    </div>
    {stats_line}
  </header>

  {search_html}
  {'<div class="day-list" id="day-list">' + rows_html + '</div><p class="no-results" id="no-results">No digests match that filter.</p>' if dated_files else empty_msg}
{_signup_form()}
  <footer class="site-footer">
    News Buddy &nbsp;·&nbsp;
    <a href="https://github.com/Harshagarwal06/buddy_agent" target="_blank" rel="noopener">source</a>
  </footer>
</div>
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

// -- Archive search --
var search = document.getElementById('archive-search');
if (search) {{
  search.addEventListener('input', function() {{
    var q = this.value.trim().toLowerCase();
    var shown = 0;
    document.querySelectorAll('.day-row').forEach(function(row) {{
      var match = !q || (row.getAttribute('data-search') || '').indexOf(q) !== -1;
      row.classList.toggle('hidden', !match);
      if (match) shown++;
    }});
    var nr = document.getElementById('no-results');
    if (nr) nr.style.display = shown === 0 ? 'block' : 'none';
  }});
}}
</script>
</body>
</html>"""

    target = output_dir / "index.html"
    tmp = target.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(target)
    return target


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) != 2:
        print("usage: python -m news_buddy.archive_writer <output-dir>", file=_sys.stderr)
        _sys.exit(1)
    result = write_archive(Path(_sys.argv[1]))
    print(f"archive written → {result}")
