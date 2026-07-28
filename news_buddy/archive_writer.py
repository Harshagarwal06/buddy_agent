"""Generate the editorial archive index for all dated digest pages."""

from __future__ import annotations

import os
import re
import shutil
from datetime import date as _date
from html import escape
from pathlib import Path

_TOKENS_PATH = Path(__file__).resolve().parents[1] / "tokens.css"
_FAVICON_PATH = Path(__file__).resolve().parents[1] / "favicon.svg"


def _copy_tokens(output_dir: Path) -> None:
    shutil.copyfile(_TOKENS_PATH, output_dir / "tokens.css")
    shutil.copyfile(_FAVICON_PATH, output_dir / "favicon.svg")


def _extract_meta(html_path: Path) -> dict:
    """Pull count and tags out of a rendered digest HTML (best-effort)."""
    try:
        text = html_path.read_text(encoding="utf-8")
        count_match = re.search(r"(\d+) article", text)
        count = int(count_match.group(1)) if count_match else 0
        tags = sorted(
            set(tag for tag in re.findall(r'data-tag="([^"]+)"', text) if tag != "__all__")
        )[:4]
        return {"count": count, "tags": tags}
    except Exception:
        return {"count": 0, "tags": []}


def _tag_label(tag: str) -> str:
    return f'<span class="tag-label">{escape(tag)}</span>'


def _display_date(value: str) -> str:
    """Return a concise publication date while tolerating malformed input."""
    try:
        parsed = _date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return value[:10]
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def _day_row(date_str: str, meta: dict, is_today: bool) -> str:
    tags_html = '<span class="tag-separator" aria-hidden="true">/</span>'.join(
        _tag_label(tag) for tag in meta["tags"]
    )
    count = int(meta["count"])
    today_label = '<span class="today-label">Latest issue</span>' if is_today else ""
    search_key = escape(f'{date_str} {" ".join(meta["tags"])}'.lower(), quote=True)
    return f"""
<a href="{date_str}.html" class="day-row" data-search="{search_key}">
  <time class="day-date" datetime="{date_str}">{_display_date(date_str)}</time>
  <span class="day-details">{today_label}<span class="day-tags">{tags_html}</span></span>
  <span class="day-count">{count} article{"s" if count != 1 else ""} <span aria-hidden="true">→</span></span>
</a>"""


def _signup_form() -> str:
    username = os.getenv("BUTTONDOWN_USERNAME", "").strip()
    if not username:
        return ""
    return f"""
  <style>
  .signup-box {{
    display: grid; gap: var(--space-lg); margin-block: var(--space-3xl) 0;
    padding-block: var(--space-xl); border-block: var(--rule-heavy) solid var(--color-ink);
  }}
  .signup-box h2 {{
    margin: 0; font-family: var(--font-display); font-size: var(--text-xl);
    font-style: normal; font-weight: 600; line-height: 1;
  }}
  .signup-box p {{ margin: var(--space-xs) 0 0; color: var(--color-muted); }}
  .signup-form {{ display: grid; gap: var(--space-xs); }}
  .signup-label {{
    color: var(--color-ink); font-family: var(--font-ui); font-size: var(--text-xs);
    font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  }}
  .signup-control {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; }}
  .signup-form input {{
    min-height: 3rem; padding-inline: var(--space-sm);
    border: var(--rule-hair) solid var(--color-rule-strong); border-inline-end: 0;
    border-radius: 0; background: transparent; color: var(--color-ink); font-family: var(--font-ui);
  }}
  .signup-form input:user-invalid {{ border-color: var(--color-error); }}
  .signup-help {{ color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs); }}
  .signup-help.error {{ color: var(--color-error); }}
  .signup-form button {{
    min-height: 3rem; padding-inline: var(--space-lg); border: var(--rule-hair) solid var(--color-ink);
    border-radius: 0; background: var(--color-ink); color: var(--color-paper);
    cursor: pointer; font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
    letter-spacing: .04em; text-transform: uppercase; white-space: nowrap;
  }}
  .signup-form button:active {{ background: var(--color-accent-hover); border-color: var(--color-accent-hover); color: var(--color-accent-ink); }}
  .signup-form button:disabled, .signup-form input:disabled {{ opacity: .55; cursor: not-allowed; }}
  @media (min-width: 60rem) {{
    .signup-box {{ grid-template-columns: minmax(0, 1fr) minmax(22rem, .85fr); align-items: end; }}
  }}
  @media (max-width: 39.999rem) {{
    .signup-control {{ grid-template-columns: minmax(0, 1fr); gap: var(--space-sm); }}
    .signup-form input {{ border-inline-end: var(--rule-hair) solid var(--color-rule-strong); }}
    .signup-form button {{ width: 100%; }}
  }}
  </style>
  <section class="signup-box" aria-labelledby="signup-title">
    <div>
      <h2 id="signup-title">The briefing, by email.</h2>
      <p>One concise issue each morning. Leave whenever you like.</p>
    </div>
    <form class="signup-form"
          action="https://buttondown.com/api/emails/embed-subscribe/{escape(username, quote=True)}"
          method="post" target="_blank">
      <label class="signup-label" for="signup-email">Email address</label>
      <div class="signup-control">
        <input id="signup-email" type="email" name="email" aria-required="true"
               aria-describedby="signup-help" placeholder="name@example.com" autocomplete="email" required>
        <button type="submit">Subscribe</button>
      </div>
      <small class="signup-help" id="signup-help">No spam. Unsubscribe from any email.</small>
    </form>
  </section>"""


def write_archive(output_dir: Path) -> Path:
    """Scan output_dir for dated HTML pages and write index.html."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_tokens(output_dir)
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.html$")
    dated_files = sorted(
        [path for path in output_dir.glob("*.html") if pattern.match(path.name)],
        reverse=True,
    )

    today_str = _date.today().isoformat()
    rows_html = ""
    total_articles = 0
    for path in dated_files:
        meta = _extract_meta(path)
        total_articles += meta["count"]
        rows_html += _day_row(path.stem, meta, path.stem == today_str)

    total_days = len(dated_files)
    search_html = (
        '<div class="search-box">'
        '<label for="archive-search">Find an issue</label>'
        '<input type="search" id="archive-search" placeholder="Date or topic" autocomplete="off" '
        'aria-describedby="search-count">'
        f'<span class="search-count" id="search-count" aria-live="polite">{total_days} issues</span>'
        "</div>"
        if dated_files
        else ""
    )
    empty_msg = (
        '<section class="empty-state"><h2>The archive is taking shape.</h2>'
        '<p>The first published briefing will appear here.</p></section>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="description" content="The complete News Buddy AI news archive.">
<title>News Buddy — Archive</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<script>
(function() {{
  var saved = null;
  try {{ saved = localStorage.getItem('nb-theme'); }} catch (error) {{}}
  var dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
}})();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="tokens.css">
<style>
/* Hallmark · macrostructure: Long Document · tone: editorial · theme: studied-DNA */
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ overflow-x: clip; }}
html {{ scroll-behavior: smooth; scroll-padding-top: var(--space-lg); }}
body {{
  margin: 0; background: var(--color-paper); color: var(--color-ink);
  font-family: var(--font-body); font-size: var(--text-body); line-height: 1.7;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}}
::selection {{ background: var(--color-selection); color: var(--color-ink); }}
a {{ color: inherit; }}
button, input {{ font: inherit; }}
:focus-visible {{ outline: var(--rule-heavy) solid var(--color-focus); outline-offset: var(--space-2xs); }}
button:disabled, [aria-disabled="true"] {{ color: var(--color-faint); cursor: not-allowed; opacity: .55; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}
.skip-link {{
  position: fixed; inset: var(--space-sm) auto auto var(--space-sm); z-index: var(--z-toast);
  padding: var(--space-sm) var(--space-md); background: var(--color-ink);
  color: var(--color-paper); font-family: var(--font-ui); font-weight: 600;
  text-decoration: none; transform: translateY(-200%);
}}
.skip-link:focus {{ transform: translateY(0); }}
.site-shell {{ width: min(100%, var(--page-width)); margin-inline: auto; padding-inline: var(--page-gutter); }}
.masthead {{ padding-block: var(--space-md) var(--space-lg); text-align: center; }}
.issue-line {{
  display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center; gap: var(--space-md); min-height: 2.75rem;
  border-block: var(--rule-hair) solid var(--color-rule);
  color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs);
  letter-spacing: .06em; text-transform: uppercase;
}}
.issue-line > :first-child {{ justify-self: start; }}
.issue-line > :last-child {{ justify-self: end; }}
.archive-kicker {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.theme-toggle {{
  min-width: 2.75rem; min-height: 2.75rem; padding-inline: var(--space-sm);
  border: 0; border-inline: var(--rule-hair) solid var(--color-rule);
  border-radius: 0; background: transparent; color: var(--color-ink);
  cursor: pointer; font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  letter-spacing: .04em; text-transform: uppercase; white-space: nowrap;
}}
.theme-toggle:active {{ color: var(--color-accent-hover); }}
.theme-dark-label {{ display: inline; }}
.theme-light-label {{ display: none; }}
[data-theme="dark"] .theme-dark-label {{ display: none; }}
[data-theme="dark"] .theme-light-label {{ display: inline; }}
.mast-name {{
  margin: var(--space-md) 0 var(--space-xs); font-family: var(--font-display);
  font-size: var(--text-display); font-style: normal; font-weight: 700;
  letter-spacing: -.055em; line-height: .78; overflow-wrap: anywhere; min-width: 0;
}}
.mast-deck {{ max-width: 46ch; margin: var(--space-md) auto var(--space-md); color: var(--color-ink-soft); font-size: var(--text-md); line-height: 1.45; }}
.mast-rule {{ height: var(--space-xs); margin: 0; border: 0; border-block: var(--rule-hair) solid var(--color-rule-strong); }}
.archive-heading {{
  display: grid; gap: var(--space-sm); margin-block: var(--space-xl) var(--space-lg);
  padding-block-end: var(--space-sm); border-block-end: var(--rule-heavy) solid var(--color-ink);
}}
.archive-heading h2 {{
  margin: 0; font-family: var(--font-display); font-size: var(--text-xl);
  font-style: normal; font-weight: 600; line-height: 1; overflow-wrap: anywhere; min-width: 0;
}}
.archive-heading p {{ margin: 0; color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs); }}
.search-box {{
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center; gap: var(--space-md); margin-block-end: var(--space-xl);
  border-block: var(--rule-hair) solid var(--color-rule); min-height: 3.25rem;
}}
.search-box label, .search-count {{
  font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  letter-spacing: .04em; text-transform: uppercase; white-space: nowrap;
}}
.search-box input {{
  width: 100%; min-height: 3.25rem; border: 0; background: transparent; color: var(--color-ink);
  font-family: var(--font-ui); font-size: var(--text-sm);
}}
.search-box input:focus {{ outline: 0; }}
.search-box input:focus-visible {{ outline: var(--rule-heavy) solid var(--color-focus); outline-offset: calc(var(--space-2xs) * -1); }}
.search-box input:disabled {{ opacity: .55; cursor: not-allowed; }}
.search-box:focus-within {{ border-color: var(--color-focus); }}
.search-box input::placeholder, .search-count {{ color: var(--color-faint); }}
.day-list {{ border-block-start: var(--rule-hair) solid var(--color-rule); }}
.day-row {{
  display: grid; grid-template-columns: minmax(8.5rem, .7fr) minmax(0, 1.35fr) auto;
  align-items: center; gap: var(--space-lg); min-height: 6rem;
  padding-block: var(--space-lg); border-block-end: var(--rule-hair) solid var(--color-rule);
  color: var(--color-ink); text-decoration: none;
}}
.day-row:active .day-date, .day-row:active .day-count {{ color: var(--color-accent-hover); }}
.day-row.hidden {{ display: none; }}
.day-date {{
  font-family: var(--font-display); font-size: var(--text-lg); font-weight: 600;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}}
.day-details {{ display: flex; flex-direction: column; gap: var(--space-xs); min-width: 0; }}
.today-label {{
  color: var(--color-accent); font-family: var(--font-ui); font-size: var(--text-2xs);
  font-weight: 600; letter-spacing: .07em; text-transform: uppercase; white-space: nowrap;
}}
.day-tags {{
  display: flex; flex-wrap: wrap; gap: var(--space-xs);
  color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs);
  letter-spacing: .04em; text-transform: uppercase;
}}
.tag-separator {{ color: var(--color-rule-strong); }}
.day-count {{
  color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs);
  font-weight: 600; white-space: nowrap;
}}
.empty-state, .no-results {{
  padding-block: var(--space-2xl); color: var(--color-muted);
  font-size: var(--text-lg); text-align: center;
}}
.empty-state h2 {{ margin: 0; color: var(--color-ink); font-family: var(--font-display); font-size: var(--text-xl); }}
.empty-state p {{ margin: var(--space-xs) 0 0; }}
.no-results {{ display: none; }}
.clear-search {{
  display: inline-flex; align-items: center; min-height: 2.75rem; margin-block-start: var(--space-md);
  padding-inline: var(--space-md); border: var(--rule-hair) solid var(--color-ink);
  border-radius: 0; background: transparent; color: var(--color-ink); cursor: pointer;
  font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600; text-transform: uppercase;
}}
.site-footer {{
  margin-block-start: var(--space-2xl); padding-block: var(--space-xl) var(--space-2xl);
  border-block-start: var(--rule-heavy) solid var(--color-ink);
  color: var(--color-muted); font-family: var(--font-ui); font-size: var(--text-xs); line-height: 1.65;
}}
.footer-name {{ color: var(--color-ink); font-family: var(--font-display); font-size: var(--text-xl); font-weight: 600; }}
.site-footer p {{ max-width: 78ch; margin: var(--space-xs) 0 0; }}
.site-footer a {{
  display: inline-flex; align-items: center; min-height: 2.75rem;
  text-decoration-color: var(--color-rule-strong); text-underline-offset: var(--space-3xs);
}}
.site-footer a:active {{ color: var(--color-accent-hover); }}
@media (min-width: 60rem) {{
  .masthead {{ padding-block: var(--space-lg) var(--space-xl); }}
  .archive-heading {{ grid-template-columns: minmax(0, 1fr) auto; align-items: end; }}
  .archive-heading p {{ text-align: end; }}
}}
@media (max-width: 39.999rem) {{
  .issue-line {{ grid-template-columns: minmax(0, 1fr) auto; }}
  .archive-kicker {{ grid-column: 1 / -1; grid-row: 1; justify-self: center; padding-block: var(--space-xs); }}
  .issue-line > :first-child {{ grid-column: 1; grid-row: 2; }}
  .issue-line > :last-child {{ grid-column: 2; grid-row: 2; }}
  .mast-name {{ line-height: .86; }}
  .search-box {{ grid-template-columns: auto minmax(0, 1fr); }}
  .search-count {{ grid-column: 1 / -1; padding-block-end: var(--space-xs); }}
  .day-row {{ grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-xs) var(--space-md); }}
  .day-details {{ grid-column: 1 / -1; grid-row: 2; }}
  .day-count {{ grid-column: 2; grid-row: 1; }}
}}
@media (pointer: coarse) {{
  .theme-toggle, .day-row, .clear-search {{ min-height: 3rem; }}
}}
@media (hover: hover) and (pointer: fine) {{
  .theme-toggle:hover, .site-footer a:hover {{ color: var(--color-accent); }}
  .search-box:hover {{ border-color: var(--color-rule-strong); }}
  .day-row:hover .day-date, .day-row:hover .day-count {{ color: var(--color-accent); }}
  .clear-search:hover {{ border-color: var(--color-accent); color: var(--color-accent); }}
  .signup-form button:hover {{ background: var(--color-accent); border-color: var(--color-accent); color: var(--color-accent-ink); }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
}}
</style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to archive</a>
<div class="site-shell" id="top">
  <header class="masthead">
    <div class="issue-line">
      <span>Daily AI briefing</span>
      <span class="archive-kicker">{total_days} issue{"s" if total_days != 1 else ""} · {total_articles} articles</span>
      <button class="theme-toggle" type="button" onclick="toggleDark()" id="theme-btn" aria-label="Use dark theme" aria-pressed="false">
        <span class="theme-dark-label">Night</span><span class="theme-light-label">Day</span>
      </button>
    </div>
    <h1 class="mast-name">News Buddy</h1>
    <p class="mast-deck">A daily briefing on artificial intelligence—selected for signal, written for clarity.</p>
    <hr class="mast-rule" aria-hidden="true">
  </header>

  <main id="main-content" tabindex="-1">
    <div class="archive-heading">
      <h2>Issue archive</h2>
      <p>Browse every published briefing, newest first.</p>
    </div>
    {search_html}
    {'<div class="day-list" id="day-list">' + rows_html + '</div><div class="no-results" id="no-results"><p>No issues match that search.</p><button class="clear-search" id="clear-search" type="button">Clear search</button></div>' if dated_files else empty_msg}
    {_signup_form()}
  </main>

  <footer class="site-footer">
    <div class="footer-name">News Buddy</div>
    <p>An independent, automated reading list built from public feeds. Every summary links back to its original publisher. <a href="https://github.com/Harshagarwal06/buddy_agent" target="_blank" rel="noopener">View the source on GitHub ↗</a> <a class="footer-top" href="#top">Back to top ↑</a></p>
  </footer>
</div>

<script>
function applyTheme(dark) {{
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  var button = document.getElementById('theme-btn');
  if (button) {{
    button.setAttribute('aria-pressed', dark ? 'true' : 'false');
    button.setAttribute('aria-label', dark ? 'Use light theme' : 'Use dark theme');
  }}
}}
function toggleDark() {{
  var now = document.documentElement.getAttribute('data-theme') === 'dark';
  try {{ localStorage.setItem('nb-theme', now ? 'light' : 'dark'); }} catch (error) {{}}
  applyTheme(!now);
}}
(function() {{
  applyTheme(document.documentElement.getAttribute('data-theme') === 'dark');
}})();

var search = document.getElementById('archive-search');
if (search) {{
  function updateSearch() {{
    var query = search.value.trim().toLowerCase();
    var shown = 0;
    document.querySelectorAll('.day-row').forEach(function(row) {{
      var match = !query || (row.getAttribute('data-search') || '').indexOf(query) !== -1;
      row.classList.toggle('hidden', !match);
      if (match) shown++;
    }});
    var noResults = document.getElementById('no-results');
    var count = document.getElementById('search-count');
    if (noResults) noResults.style.display = shown === 0 ? 'block' : 'none';
    if (count) count.textContent = shown + ' issue' + (shown === 1 ? ' found' : 's found');
  }}
  search.addEventListener('input', updateSearch);
  var clearSearch = document.getElementById('clear-search');
  if (clearSearch) {{
    clearSearch.addEventListener('click', function() {{
      search.value = '';
      updateSearch();
      search.focus();
    }});
  }}
}}

var signupEmail = document.getElementById('signup-email');
if (signupEmail) {{
  var signupHelp = document.getElementById('signup-help');
  signupEmail.addEventListener('invalid', function() {{
    if (signupHelp) {{
      signupHelp.textContent = 'Enter a valid email address to subscribe.';
      signupHelp.classList.add('error');
    }}
  }});
  signupEmail.addEventListener('input', function() {{
    if (signupHelp && signupEmail.validity.valid) {{
      signupHelp.textContent = 'No spam. Unsubscribe from any email.';
      signupHelp.classList.remove('error');
    }}
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
