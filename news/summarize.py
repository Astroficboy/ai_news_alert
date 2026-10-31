"""Summarize an article with a local Ollama model, returning structured JSON."""
import json
import urllib.error
import urllib.request

CATEGORIES = [
    "Model release", "Product", "Research", "Open source", "Funding & business",
    "Policy & safety", "Hardware", "Tools & tutorials", "Other",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
        "category": {"type": "string", "enum": CATEGORIES},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["summary", "importance", "category", "tags"],
}

SYSTEM = (
    "You are an AI-industry analyst writing a concise personal news briefing. "
    "Be factual, only use information in the provided text, and skip marketing fluff."
)

PROMPT = """Source: {source}
Title: {title}

Article text:
{text}

Respond with JSON:
- "summary": 2-3 plain-English sentences: what is new, and why it matters. Never use double-quote characters inside it; use single quotes instead.
- "importance": 1-5. 5 = major model/product launch or industry-shifting news; 4 = significant release or result; 3 = notable; 2 = minor update; 1 = opinion, promo, or trivia.
- "category": one of {categories}.
- "tags": up to 4 short tags (companies, models, topics)."""


class Summarizer:
    def __init__(self, base_url, model):
        self.url = base_url.rstrip("/") + "/api/chat"
        self.model = model
        self.think_supported = True

    def _post(self, body):
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())

    def _chat(self, body):
        try:
            return self._post(body)
        except urllib.error.HTTPError as e:
            if body.get("think") is False and e.code == 400:
                self.think_supported = False
                body.pop("think")
                return self._post(body)
            raise

    def summarize(self, source, title, text):
        body = {
            "model": self.model,
            "stream": False,
            "format": SCHEMA,
            "options": {"temperature": 0.2, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": PROMPT.format(
                    source=source, title=title, text=text or "(no text available; use the title)",
                    categories=", ".join(CATEGORIES))},
            ],
        }
        if self.think_supported:
            body["think"] = False  # gemma4 can reason; skip it for faster summaries
        for attempt in range(2):
            result = json.loads(self._chat(body)["message"]["content"])
            summary = result.get("summary", "").strip()
            # A stray inner quote can end the JSON string early; retry once if it looks cut off.
            if len(summary) >= 60 and summary[-1] in ".!?)'":
                break
            body["options"]["temperature"] = 0.5
        result["importance"] = max(1, min(5, int(result.get("importance", 2))))
        if result.get("category") not in CATEGORIES:
            result["category"] = "Other"
        return result


def check_ollama(base_url, model):
    """Return None if the model is available, else an error message."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=5) as r:
            names = [m["name"] for m in json.loads(r.read())["models"]]
    except Exception as e:
        return f"Can't reach Ollama at {base_url} ({e}). Is `ollama serve` running?"
    if model not in names:
        return f"Model {model} not found in Ollama. Run: ollama pull {model}"
    return None
