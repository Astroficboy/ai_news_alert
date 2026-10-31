# AI News Alert

A personal AI news feed. It pulls AI-related posts from 16 sources (OpenAI, DeepMind, Google AI, Hugging Face,
NVIDIA, Microsoft Research, TechCrunch, The Verge, MIT Tech Review, Ars Technica, Simon Willison,
Hacker News, r/LocalLLaMA, r/MachineLearning, and arXiv), summarizes each new item with **local Ollama `gemma4:12b`**,
rates it 1–5 for importance, then:

- sends a **macOS notification** for each important item (importance ≥ 4) plus a roll-up count,
- rebuilds **`digest.html`**, a searchable page of the last 3 days that you can filter by category and importance.

Uses only the Python standard library, so there's nothing to install apart from Ollama.

## Use

```bash
./run.sh              # fetch → summarize → notify → rebuild digest
./run.sh list         # print the last 24h (importance 3+) in the terminal
./run.sh list --hours 72 --min 4
./run.sh ui           # open the reader app at http://localhost:8790
./run.sh open         # open the static digest.html
./schedule.sh install 360  # run in the background every 6 hours (launchd)
./schedule.sh uninstall
./schedule.sh ui-install     # keep the reader app always running (starts at login)
./schedule.sh ui-uninstall
```

Ollama has to be running (`ollama serve`, or the Ollama app).

## Reader app (`./run.sh ui`)

A local web app, served by Python's built-in server on 127.0.0.1 only:
- **Inbox** shows unread stories; opening a story marks it read. There are also **Top stories** (importance 4+),
  **All stories** and **Saved**.
- Filter by category or source from the sidebar, search everything, and pick a 24h, 3d or 7d range.
- **Refresh** runs an update right away and shows live progress ("Summarizing 3 of 12…"). The page also picks up the
  scheduled runs on its own.
- Keyboard: `j`/`k` move, `o` open, `s` save, `m` read/unread, `/` search, `r` refresh.
- Read and saved state is stored in the same SQLite database.

## How it works

| File | Role |
|---|---|
| `news/feeds.py` | Parallel RSS/Atom fetch and parse, keyword filter for mixed-topic feeds, article text extraction |
| `news/store.py` | SQLite (`data/news.db`): dedupes by URL and by normalized title, tracks summaries and notifications |
| `news/summarize.py` | Ollama `/api/chat` with a JSON schema → `summary`, `importance`, `category`, `tags` |
| `news/notify.py` | macOS notifications (`terminal-notifier` if installed, else `osascript`) |
| `news/digest.py` | Renders `digest.html` |
| `news/server.py` + `news/static/index.html` | Reader app: JSON API and single-page UI |

New items go into SQLite unsummarized. Each run summarizes up to `max_summaries_per_run` of them, newest first,
so a backlog drains over a few runs. Posts older than `max_age_hours` are ignored.

## Customize (`config.json`)

- `feeds`: add or remove `{"name", "url"}`. Optional settings: `"filter": true` keeps only posts that match
  `filter_keywords`, `"max_items": N`, and `"skip_article_fetch": true` (summarize from the feed text only).
- `notify_min_importance`: lower it to 3 for more alerts.
- `model`: any Ollama model.

Notifications show the source site and open the article when clicked (via `terminal-notifier`, installed with `brew install terminal-notifier`). Without it they fall back to plain `osascript` alerts that show the site but are not clickable.
