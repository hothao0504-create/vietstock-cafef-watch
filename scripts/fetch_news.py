#!/usr/bin/env python3
"""Fetch latest news from Vietstock and CafeF RSS feeds and notify new items via ntfy.sh."""
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "seen_links.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "Tong-hop-VIETSTOCK-CAFEF")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

FEEDS = {
    "Vietstock": [
        "https://vietstock.vn/830/chung-khoan/co-phieu.rss",
        "https://vietstock.vn/737/chung-khoan/thi-truong.rss",
        "https://vietstock.vn/143/kinh-te.rss",
    ],
    "CafeF": [
        "https://cafef.vn/thi-truong-chung-khoan.rss",
        "https://cafef.vn/tai-chinh-ngan-hang.rss",
        "https://cafef.vn/vi-mo-dau-tu.rss",
    ],
}

MAX_ITEMS_PER_FEED = 30
MAX_NOTIFY_ITEMS = 20


def fetch_feed(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    items = []
    for item in root.findall("./channel/item")[:MAX_ITEMS_PER_FEED]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            items.append({"title": title, "link": link})
    return items


def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen)[-5000:], f, ensure_ascii=False, indent=2)


def notify_batch(items: list[dict]) -> None:
    lines = []
    for item in items:
        lines.append(f"[{item['source']}] {item['title']}\n{item['link']}")
    body = "\n\n".join(lines)
    req = urllib.request.Request(
        NTFY_URL,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Title": f"Tin moi ({len(items)})",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Failed to send notification batch: {e}", file=sys.stderr)


def main() -> None:
    seen = load_seen()
    is_first_run = len(seen) == 0
    new_seen = set(seen)
    new_items = []

    for source, urls in FEEDS.items():
        for url in urls:
            try:
                items = fetch_feed(url)
            except Exception as e:
                print(f"Error fetching {url}: {e}", file=sys.stderr)
                continue
            for item in items:
                link = item["link"]
                if link in seen:
                    continue
                new_seen.add(link)
                new_items.append({"source": source, "title": item["title"], "link": link})

    save_seen(new_seen)
    if is_first_run:
        print(f"First run: seeded {len(new_seen)} links, no notifications sent.")
        return

    if not new_items:
        print("Sent 0 notifications.")
        return

    for i in range(0, len(new_items), MAX_NOTIFY_ITEMS):
        batch = new_items[i:i + MAX_NOTIFY_ITEMS]
        notify_batch(batch)

    print(f"Sent {len(new_items)} new items in {(len(new_items) - 1) // MAX_NOTIFY_ITEMS + 1} notification(s).")


if __name__ == "__main__":
    main()
