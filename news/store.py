"""SQLite store: dedupes items and remembers summaries/notification state."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT, title TEXT, title_key TEXT, link TEXT,
    published TEXT, fetched TEXT,
    feed_text TEXT, skip_article_fetch INTEGER DEFAULT 0,
    summary TEXT, importance INTEGER, category TEXT, tags TEXT,
    notified INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_title_key ON items(title_key);
CREATE INDEX IF NOT EXISTS idx_published ON items(published);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Columns added after the first release; created on open if missing.
MIGRATIONS = {"is_read": "INTEGER DEFAULT 0", "is_saved": "INTEGER DEFAULT 0"}
UI_FIELDS = ("id", "source", "title", "link", "published", "summary", "importance", "category", "tags",
             "is_read", "is_saved")


def _title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _link_id(link):
    link = re.sub(r"[?#].*$", "", link.strip()).rstrip("/")
    return hashlib.sha1(link.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(items)")}
        for col, decl in MIGRATIONS.items():
            if col not in cols:
                self.db.execute(f"ALTER TABLE items ADD COLUMN {col} {decl}")
        self.db.commit()

    def close(self):
        self.db.close()

    def get_meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def ui_items(self, since_iso):
        """Summarized items in range, plus saved items of any age, as plain dicts."""
        rows = self.db.execute(
            f"SELECT {', '.join(UI_FIELDS)} FROM items WHERE summary IS NOT NULL AND (published >= ? OR is_saved=1)"
            " ORDER BY published DESC",
            (since_iso,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["is_read"], d["is_saved"] = bool(d["is_read"]), bool(d["is_saved"])
            out.append(d)
        return out

    def set_flag(self, ids, field, value):
        if field not in ("is_read", "is_saved"):
            raise ValueError(field)
        self.db.executemany(f"UPDATE items SET {field}=? WHERE id=?", [(int(value), i) for i in ids])
        self.db.commit()

    def pending_count(self):
        return self.db.execute("SELECT COUNT(*) FROM items WHERE summary IS NULL").fetchone()[0]

    def add_new(self, items):
        """Insert unseen items (by URL and by normalized title). Returns count added."""
        now = datetime.now(timezone.utc).isoformat()
        added = 0
        for i in items:
            iid, tkey = _link_id(i["link"]), _title_key(i["title"])
            if self.db.execute("SELECT 1 FROM items WHERE id=? OR title_key=?", (iid, tkey)).fetchone():
                continue
            self.db.execute(
                "INSERT INTO items (id, source, title, title_key, link, published, fetched, feed_text, skip_article_fetch)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (iid, i["source"], i["title"], tkey, i["link"], i["published"].isoformat(), now,
                 i["feed_text"], int(i.get("skip_article_fetch", False))),
            )
            added += 1
        self.db.commit()
        return added

    def pending(self, limit):
        return self.db.execute(
            "SELECT * FROM items WHERE summary IS NULL ORDER BY published DESC LIMIT ?", (limit,)
        ).fetchall()

    def save_summary(self, iid, result):
        self.db.execute(
            "UPDATE items SET summary=?, importance=?, category=?, tags=? WHERE id=?",
            (result["summary"], int(result["importance"]), result["category"],
             json.dumps(result.get("tags", [])), iid),
        )
        self.db.commit()

    def unnotified(self):
        return self.db.execute(
            "SELECT * FROM items WHERE summary IS NOT NULL AND notified=0 ORDER BY importance DESC, published DESC"
        ).fetchall()

    def mark_notified(self, ids):
        self.db.executemany("UPDATE items SET notified=1 WHERE id=?", [(i,) for i in ids])
        self.db.commit()

    def recent(self, since_iso, min_importance=1):
        return self.db.execute(
            "SELECT * FROM items WHERE summary IS NOT NULL AND published >= ? AND importance >= ?"
            " ORDER BY published DESC",
            (since_iso, min_importance),
        ).fetchall()
