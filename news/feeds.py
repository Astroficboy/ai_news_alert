"""Fetch and parse RSS/Atom feeds, plus best-effort article text extraction."""
import gzip
import html
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

FEED_UA = "ai-news-alert/1.0 (personal RSS reader)"  # Reddit rejects browser-like UAs on RSS
PAGE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/605.1.15"


def http_get(url, timeout=20, ua=FEED_UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    # Some servers (e.g. DeepMind's CDN) gzip responses even when not asked to.
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def clean_html(s):
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_feed(data, source):
    root = ET.fromstring(data)
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in el:
            n = _local(c.tag)
            if n == "link":
                href = c.get("href")
                if href:
                    if c.get("rel", "alternate") == "alternate":
                        f.setdefault("link", href)
                elif c.text:
                    f.setdefault("link", c.text.strip())
            elif n == "title":
                f["title"] = clean_html("".join(c.itertext()))
            elif n in ("description", "summary"):
                f.setdefault("desc", "".join(c.itertext()))
            elif n in ("encoded", "content"):
                f["content"] = "".join(c.itertext())
            elif n in ("pubDate", "published", "updated", "date"):
                f.setdefault("date", c.text)
        if not f.get("link") or not f.get("title"):
            continue
        items.append({
            "source": source,
            "title": f["title"],
            "link": f["link"],
            "published": _parse_date(f.get("date")) or datetime.now(timezone.utc),
            "feed_text": clean_html(f.get("content") or f.get("desc") or ""),
        })
    return items


def _matches(item, keywords):
    hay = f" {item['title']} {item['feed_text'][:2000]} ".lower()
    return any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", hay) for k in keywords)


def fetch_all(feeds, keywords, default_max):
    """Fetch every feed in parallel. Returns (items, errors)."""
    def one(feed):
        try:
            try:
                items = parse_feed(http_get(feed["url"]), feed["name"])
            except Exception:
                time.sleep(4)  # one retry for timeouts / 429s / garbled responses
                items = parse_feed(http_get(feed["url"], timeout=30), feed["name"])
        except Exception as e:  # network/parse errors shouldn't kill the run
            return [], f"{feed['name']}: {e}"
        if feed.get("filter"):
            items = [i for i in items if _matches(i, keywords)]
        items.sort(key=lambda i: i["published"], reverse=True)
        for i in items:
            i["skip_article_fetch"] = feed.get("skip_article_fetch", False)
        return items[: feed.get("max_items", default_max)], None

    out, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for items, err in pool.map(one, feeds):
            out.extend(items)
            if err:
                errors.append(err)
    return out, errors


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"}
    KEEP = {"p", "h1", "h2", "h3", "li", "blockquote"}

    def __init__(self):
        super().__init__()
        self.skip_depth = 0
        self.keep_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.KEEP:
            self.keep_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.KEEP and self.keep_depth:
            self.keep_depth -= 1
            self.parts.append("\n")

    def handle_data(self, data):
        if self.keep_depth and not self.skip_depth:
            self.parts.append(data)


def fetch_article_text(url, max_chars=6000):
    """Best-effort readable text from an article page; '' on failure."""
    try:
        raw = http_get(url, timeout=15, ua=PAGE_UA).decode("utf-8", errors="replace")
        p = _TextExtractor()
        p.feed(raw)
        text = re.sub(r"[ \t]+", " ", "".join(p.parts))
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        return text[:max_chars]
    except Exception:
        return ""
