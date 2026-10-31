#!/usr/bin/env python3
"""AI news alert: fetch AI news feeds, summarize with local Ollama, alert + build a digest.

Usage:
  python3 ainews.py run [--no-notify] [--limit N]   fetch, summarize, notify, rebuild digest
  python3 ainews.py list [--hours 24] [--min 3]    print recent summaries in the terminal
  python3 ainews.py ui [--no-browser]              start the local web UI (http://localhost:8790)
  python3 ainews.py open                           open the static HTML digest
"""
import argparse
import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news import digest, feeds, server
from news.notify import notify
from news.store import Store
from news.summarize import Summarizer, check_ollama

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DIGEST = ROOT / "digest.html"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config():
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def cmd_run(cfg, store, args):
    # One run at a time (scheduled job vs. the UI's Refresh button).
    lock = open(DATA / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another update is already running; skipping.")
        return 0
    log(f"Fetching {len(cfg['feeds'])} feeds…")
    items, errors = feeds.fetch_all(cfg["feeds"], cfg["filter_keywords"], cfg["max_items_per_feed"])
    for err in errors:
        log(f"  ! {err}")
    # Only "what's new": ignore older posts still sitting in feeds.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["max_age_hours"])
    items = [i for i in items if i["published"] >= cutoff]
    added = store.add_new(items)
    log(f"{len(items)} items fetched, {added} new.")

    err = check_ollama(cfg["ollama_url"], cfg["model"])
    if err:
        log(err)
        if not args.no_notify:
            notify("AI News", err)
        return 1

    summarizer = Summarizer(cfg["ollama_url"], cfg["model"])
    pending = store.pending(args.limit or cfg["max_summaries_per_run"])
    for n, row in enumerate(pending, 1):
        t0 = time.time()
        text = row["feed_text"] or ""
        if not row["skip_article_fetch"]:
            article = feeds.fetch_article_text(row["link"])
            if len(article) > len(text):
                text = article
        try:
            result = summarizer.summarize(row["source"], row["title"], text[:6000])
        except Exception as e:
            log(f"  ! summarize failed for {row['title'][:60]}: {e}")
            continue
        store.save_summary(row["id"], result)
        log(f"  [{n}/{len(pending)}] {result['importance']}★ {row['title'][:70]} ({time.time() - t0:.1f}s)")

    fresh = store.unnotified()
    if fresh and not args.no_notify:
        important = [r for r in fresh if r["importance"] >= cfg["notify_min_importance"]]
        for r in important[: cfg["max_individual_alerts"]]:
            notify(f"AI News · {r['source']}", r["summary"], subtitle=r["title"], open_url=r["link"])
        ui_url = f"http://localhost:{cfg['ui_port']}/"
        notify("AI News", f"{len(fresh)} new AI updates, {len(important)} important.",
               open_url=ui_url if server.is_serving(cfg["ui_port"]) else DIGEST.as_uri())
    store.mark_notified([r["id"] for r in fresh])

    since = (datetime.now(timezone.utc) - timedelta(days=cfg["digest_days"])).isoformat()
    digest.render(store.recent(since), DIGEST, cfg["digest_days"])
    store.set_meta("last_run", datetime.now(timezone.utc).isoformat())
    store.set_meta("last_run_new", str(added))
    log(f"Digest updated: {DIGEST}")
    return 0


def cmd_list(cfg, store, args):
    since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()
    rows = sorted(store.recent(since, args.min), key=lambda r: (-r["importance"], r["published"]))
    if not rows:
        print("Nothing yet. Try: python3 ainews.py run")
    for r in rows:
        when = datetime.fromisoformat(r["published"]).astimezone().strftime("%d %b %H:%M")
        print(f"\n{'★' * r['importance']:<5} [{r['category']}] {r['title']}")
        print(f"      {r['source']} · {when} · {r['link']}")
        print(f"      {r['summary']}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Personal AI news alerts with local Ollama summaries")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--no-notify", action="store_true")
    r.add_argument("--limit", type=int, help="max items to summarize this run")
    l = sub.add_parser("list")
    l.add_argument("--hours", type=int, default=24)
    l.add_argument("--min", type=int, default=3, help="minimum importance (1-5)")
    u = sub.add_parser("ui")
    u.add_argument("--no-browser", action="store_true")
    sub.add_parser("open")
    args = p.parse_args()

    cfg = load_config()
    DATA.mkdir(exist_ok=True)
    store = Store(DATA / "news.db")
    if args.cmd == "list":
        return cmd_list(cfg, store, args)
    if args.cmd == "ui":
        store.close()
        return server.serve(ROOT, cfg, open_browser=not args.no_browser)
    if args.cmd == "open":
        if not DIGEST.exists():
            print("No digest yet. Run: python3 ainews.py run")
            return 1
        subprocess.run(["open", str(DIGEST)])
        return 0
    if args.cmd is None:
        args = p.parse_args(["run"])
    return cmd_run(cfg, store, args)


if __name__ == "__main__":
    sys.exit(main())
