"""macOS notifications. Uses terminal-notifier (clickable) if installed, else osascript."""
import hashlib
import shutil
import subprocess
from urllib.parse import urlparse


def _osa_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, message, subtitle="", open_url=None):
    message = message[:220]
    if open_url and open_url.startswith("http"):
        message += "\n🔗 " + urlparse(open_url).netloc.removeprefix("www.")
    tn = shutil.which("terminal-notifier")
    if tn:
        # One group per link so alerts don't replace each other.
        group = "ai-news-" + hashlib.sha1((open_url or title).encode()).hexdigest()[:12]
        cmd = [tn, "-title", title, "-message", message, "-group", group]
        if subtitle:
            cmd += ["-subtitle", subtitle]
        if open_url:
            cmd += ["-open", open_url]
        if subprocess.run(cmd, check=False, capture_output=True).returncode == 0:
            return
        # Not permitted in System Settings (or broken): fall back to a plain, non-clickable alert.
    script = f"display notification {_osa_quote(message)} with title {_osa_quote(title)}"
    if subtitle:
        script += f" subtitle {_osa_quote(subtitle)}"
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
