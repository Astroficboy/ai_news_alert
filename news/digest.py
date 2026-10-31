"""Render a self-contained HTML digest of recent summarized items."""
import html
import json
from datetime import datetime

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e4e4e0;--accent:#3b5bdb;
--hi:#d9480f;--hi-bg:#fff4e6;--chip:#f0f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--card:#1c1c1f;--text:#ececef;--muted:#9a9aa2;
--line:#2c2c31;--accent:#7c95ff;--hi:#ff8c4b;--hi-bg:#2e1f14;--chip:#26262b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Inter",sans-serif}
main{max-width:860px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px;position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:1}
.bar input,.bar select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text)}
.bar input{flex:1;min-width:160px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:28px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.card.hot{border-color:var(--hi);background:linear-gradient(var(--hi-bg),var(--card) 60%)}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:12px;color:var(--muted);margin-bottom:4px}
.imp{font-weight:600;color:var(--hi);letter-spacing:1px}
.cat{background:var(--chip);border-radius:999px;padding:1px 8px;color:var(--text)}
.card a.t{color:var(--text);font-weight:600;font-size:16px;text-decoration:none}
.card a.t:hover{color:var(--accent);text-decoration:underline}
.card p{margin:6px 0 6px}
.tags{font-size:12px;color:var(--accent)}
.empty{color:var(--muted);text-align:center;padding:40px 0}
"""

JS = """
const q=document.getElementById('q'),cat=document.getElementById('cat'),imp=document.getElementById('imp');
function apply(){const s=q.value.toLowerCase(),c=cat.value,m=+imp.value;
document.querySelectorAll('.card').forEach(el=>{const ok=(!c||el.dataset.cat===c)&&(+el.dataset.imp>=m)&&
(!s||el.textContent.toLowerCase().includes(s));el.style.display=ok?'':'none'});
document.querySelectorAll('section').forEach(sec=>{sec.style.display=[...sec.querySelectorAll('.card')].some(c=>c.style.display!=='none')?'':'none'});}
[q,cat,imp].forEach(e=>e.addEventListener('input',apply));apply();
"""


def render(rows, path, days):
    e = html.escape
    by_day = {}
    for r in rows:
        local = datetime.fromisoformat(r["published"]).astimezone()
        by_day.setdefault(local.strftime("%A, %d %b"), []).append((local, r))

    sections = []
    for day, items in by_day.items():
        items.sort(key=lambda x: (-x[1]["importance"], -x[0].timestamp()))
        cards = []
        for local, r in items:
            tags = " ".join("#" + e(t) for t in json.loads(r["tags"] or "[]"))
            cards.append(
                f'<article class="card{" hot" if r["importance"] >= 4 else ""}" data-cat="{e(r["category"])}" data-imp="{r["importance"]}">'
                f'<div class="meta"><span class="imp" title="importance {r["importance"]}/5">{"●" * r["importance"]}{"○" * (5 - r["importance"])}</span>'
                f'<span class="cat">{e(r["category"])}</span><span>{e(r["source"])}</span><span>{local.strftime("%H:%M")}</span></div>'
                f'<a class="t" href="{e(r["link"])}" target="_blank" rel="noopener">{e(r["title"])}</a>'
                f'<p>{e(r["summary"])}</p><div class="tags">{tags}</div></article>'
            )
        sections.append(f"<section><h2>{e(day)}</h2>{''.join(cards)}</section>")

    cats = sorted({r["category"] for r in rows})
    options = "".join(f'<option value="{e(c)}">{e(c)}</option>' for c in cats)
    body = "".join(sections) or '<div class="empty">No summarized items yet. Run <code>./run.sh</code>.</div>'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI News Digest</title><style>{CSS}</style></head>
<body><main><h1>AI News Digest</h1>
<div class="sub">{len(rows)} items from the last {days} days · updated {datetime.now().strftime("%d %b %Y, %H:%M")} · summaries by local Ollama</div>
<div class="bar"><input id="q" type="search" placeholder="Search…">
<select id="cat"><option value="">All categories</option>{options}</select>
<select id="imp"><option value="1">All importance</option><option value="3" selected>Importance 3+</option><option value="4">Importance 4+</option><option value="5">Only 5</option></select></div>
{body}</main><script>{JS}</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
