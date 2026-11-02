"""
بناء الموقع: يقرأ ملفات Markdown من content/ ويحوّلها لصفحات HTML في _site/

  python build.py           بناء فقط
  python build.py --serve   بناء ثم معاينة على http://localhost:8000
"""

import datetime as dt
import http.server
import math
import re
import shutil
import socketserver
import sys
from functools import partial
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader
from pygments.formatters import HtmlFormatter
from pymdownx.slugs import slugify

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
THEME = ROOT / "theme"
OUT = ROOT / "_site"
SECTIONS = ["concepts", "research"]

MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
          "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

MD_EXTENSIONS = [
    "tables", "attr_list", "md_in_html", "footnotes", "admonition", "toc",
    "pymdownx.superfences", "pymdownx.highlight", "pymdownx.inlinehilite",
    "pymdownx.details", "pymdownx.tasklist", "pymdownx.mark",
    "pymdownx.betterem", "pymdownx.tilde",
]
MD_CONFIG = {
    "toc": {"slugify": slugify(case="lower"), "permalink": False},
    "pymdownx.highlight": {"css_class": "highlight", "guess_lang": False},
    "pymdownx.tasklist": {"custom_checkbox": True},
}


def arabic_date(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def count_label(n):
    if n == 0:
        return "لا توجد ملخصات بعد"
    if n == 1:
        return "ملخص واحد"
    if n == 2:
        return "ملخصان"
    return f"{n} ملخصات" if n <= 10 else f"{n} ملخصًا"


def minutes_label(n):
    if n == 1:
        return "قراءة في دقيقة"
    if n == 2:
        return "قراءة في دقيقتين"
    return f"قراءة في {n} دقائق" if n <= 10 else f"قراءة في {n} دقيقة"


def to_html(text):
    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_CONFIG)
    return md.convert(str(text or ""))


def to_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip()[:10])


def read_post(path, section):
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.S)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
    if meta.get("draft"):
        return None
    missing = [k for k in ("title", "date") if not meta.get(k)]
    if missing:
        print(f"  ⚠ تم تجاهل {path.relative_to(ROOT)}: ناقص {', '.join(missing)}")
        return None
    if not body.strip() and meta.get("body"):
        body = str(meta["body"])
    date = to_date(meta["date"])

    questions = []
    for q in meta.get("questions") or []:
        if isinstance(q, dict) and q.get("question"):
            questions.append({"question": q["question"], "answer": to_html(q.get("answer", ""))})

    paper = meta.get("paper") if isinstance(meta.get("paper"), dict) else None
    if paper and not any(paper.values()):
        paper = None

    text_for_count = " ".join([body, str(meta.get("summary") or "")] +
                              [f"{q.get('question','')} {q.get('answer','')}" for q in meta.get("questions") or [] if isinstance(q, dict)])
    words = len(re.findall(r"\w+", text_for_count))
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "slug": path.stem,
        "section": section,
        "title": meta["title"],
        "description": meta.get("description") or "",
        "date": date,
        "date_label": arabic_date(date),
        "tags": tags,
        "author": meta.get("author"),
        "summary": to_html(meta["summary"]) if meta.get("summary") else "",
        "paper": paper,
        "questions": questions,
        "minutes": max(1, math.ceil(words / 180)),
        "html": to_html(body),
    }


def build():
    site = yaml.safe_load((ROOT / "site.yml").read_text(encoding="utf-8"))
    env = Environment(loader=FileSystemLoader(THEME / "layouts"), autoescape=True)
    env.globals.update(site=site, year=dt.date.today().year)
    env.filters.update(count_label=count_label, minutes_label=minutes_label)

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(THEME / "assets", OUT / "assets")
    if (CONTENT / "media").exists():
        shutil.copytree(CONTENT / "media", OUT / "media")
    css = HtmlFormatter(style="github-dark").get_style_defs(".highlight")
    (OUT / "assets" / "code.css").write_text(css, encoding="utf-8")

    posts = {}
    for sec in SECTIONS:
        folder = CONTENT / sec
        items = [read_post(p, sec) for p in sorted(folder.glob("*.md"))
                 if not p.name.startswith("_")]
        posts[sec] = sorted([p for p in items if p], key=lambda p: p["date"], reverse=True)

    def write(rel, template, root=None, **ctx):
        target = OUT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if root is None:
            depth = len(Path(rel).parts) - 1
            root = "../" * depth if depth else "./"
        html = env.get_template(template).render(root=root, **ctx)
        target.write_text(html, encoding="utf-8")

    write("index.html", "home.html", posts=posts, page="home")
    # صفحة 404 تظهر على أي رابط، فتحتاج مسارًا ثابتًا
    write("404.html", "404.html", root=site.get("base", "/"), page="404")
    for sec in SECTIONS:
        write(f"{sec}/index.html", "section.html", section=sec, items=posts[sec], page=sec)
        for p in posts[sec]:
            write(f"{sec}/{p['slug']}/index.html", "article.html", post=p, page=sec)

    total = sum(len(v) for v in posts.values())
    print(f"✓ تم بناء الموقع في {OUT.name}/ ({count_label(total)})")


def serve(port=8000):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"المعاينة على http://localhost:{port}  (Ctrl+C للإيقاف)")
        httpd.serve_forever()


if __name__ == "__main__":
    build()
    if "--serve" in sys.argv:
        serve()
