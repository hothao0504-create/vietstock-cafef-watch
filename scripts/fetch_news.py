#!/usr/bin/env python3
"""Fetch latest news from Vietstock, CafeF and VietnamFinance RSS feeds, grouped
by category, and notify new items via ntfy.sh — one notification thread per
source. Also checks the VN-Index snapshot and notifies when it changes."""
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "seen_links.json")
INDEX_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "last_index.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "Tong-hop-VIETSTOCK-CAFEF")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
VNINDEX_URL = (
    "https://cafef.vn/du-lieu/Ajax/PageNew/DataHistory/PriceHistory.ashx"
    "?Symbol=VNINDEX&StartDate=&EndDate=&PageIndex=1&PageSize=1"
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Ordered category -> RSS feed. Order defines the grouping order in notifications.
SOURCES = {
    "Vietstock": {
        "Chung khoan": "https://vietstock.vn/144/chung-khoan.rss",
        "Doanh nghiep": "https://vietstock.vn/733/doanh-nghiep.rss",
        "Bat dong san": "https://vietstock.vn/763/bat-dong-san.rss",
        "Tai chinh": "https://vietstock.vn/734/tai-chinh.rss",
        "Hang hoa": "https://vietstock.vn/2/hang-hoa.rss",
        "Kinh te": "https://vietstock.vn/5307/kinh-te.rss",
        "The gioi": "https://vietstock.vn/736/the-gioi.rss",
        "Dong Duong": "https://vietstock.vn/1317/dong-duong.rss",
        "Tai chinh ca nhan": "https://vietstock.vn/4259/tai-chinh-ca-nhan.rss",
        "Phan tich": "https://vietstock.vn/579/nhan-dinh-phan-tich.rss",
    },
    "CafeF": {
        "Xa hoi": "https://cafef.vn/xa-hoi.rss",
        "Thi truong chung khoan": "https://cafef.vn/thi-truong-chung-khoan.rss",
        "Bat dong san": "https://cafef.vn/bat-dong-san.rss",
        "Doanh nghiep": "https://cafef.vn/doanh-nghiep.rss",
        "Tai chinh - ngan hang": "https://cafef.vn/tai-chinh-ngan-hang.rss",
        "Tai chinh quoc te": "https://cafef.vn/tai-chinh-quoc-te.rss",
        "Smart Money": "https://cafef.vn/smart-money.rss",
        "Kinh te vi mo - Dau tu": "https://cafef.vn/vi-mo-dau-tu.rss",
        "Kinh te so": "https://cafef.vn/kinh-te-so.rss",
        "Thi truong": "https://cafef.vn/thi-truong.rss",
        "Song": "https://cafef.vn/song.rss",
        "Lifestyle": "https://cafef.vn/lifestyle.rss",
    },
    "VietnamFinance": {
        "Chung khoan": "https://vietnamfinance.vn/chung-khoan.rss",
        "Tai chinh": "https://vietnamfinance.vn/tai-chinh.rss",
        "Ngan hang": "https://vietnamfinance.vn/ngan-hang.rss",
        "Bat dong san": "https://vietnamfinance.vn/bat-dong-san.rss",
        "Tai chinh quoc te": "https://vietnamfinance.vn/tai-chinh-quoc-te.rss",
    },
}

MAX_ITEMS_PER_FEED = 50
MAX_MESSAGE_BYTES = 3800  # stay under ntfy's ~4096 byte message limit


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
        json.dump(sorted(seen)[-8000:], f, ensure_ascii=False, indent=2)


def send_message(title: str, body: str) -> None:
    req = urllib.request.Request(
        NTFY_URL,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Failed to send notification: {e}", file=sys.stderr)


def chunk_blocks(blocks: list[str]) -> list[str]:
    """Pack category blocks into message bodies under the byte budget."""
    chunks = []
    current = ""
    for block in blocks:
        candidate = block if not current else current + "\n\n" + block
        if len(candidate.encode("utf-8")) > MAX_MESSAGE_BYTES and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def notify_source(source: str, items_by_category: dict) -> int:
    blocks = []
    total = 0
    for category, items in items_by_category.items():
        if not items:
            continue
        lines = [f"== {category} =="]
        for item in items:
            lines.append(f"- {item['title']}\n  {item['link']}")
            total += 1
        blocks.append("\n".join(lines))

    if not blocks:
        return 0

    chunks = chunk_blocks(blocks)
    n = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        title = f"{source} - Tin moi ({total})"
        if n > 1:
            title += f" - phan {i}/{n}"
        send_message(title, chunk)
    return total


def fetch_vnindex() -> dict | None:
    req = urllib.request.Request(VNINDEX_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read())
    data = payload.get("Data") or {}
    date_index = data.get("DateIndex")
    close = data.get("ClosePriceIndex")
    chg = data.get("ChgIndex")
    pct = data.get("PctIndex")
    if date_index is None or close is None:
        return None
    return {"date": date_index, "close": close, "chg": chg, "pct": pct}


def load_last_index() -> dict | None:
    if os.path.exists(INDEX_STATE_FILE):
        with open(INDEX_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_last_index(snapshot: dict) -> None:
    os.makedirs(os.path.dirname(INDEX_STATE_FILE), exist_ok=True)
    with open(INDEX_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


def check_vnindex(is_first_run: bool) -> None:
    try:
        snapshot = fetch_vnindex()
    except Exception as e:
        print(f"Error fetching VN-Index: {e}", file=sys.stderr)
        return
    if snapshot is None:
        return

    last = load_last_index()
    if last is not None and last.get("date") == snapshot["date"]:
        return  # already notified for this trading date

    save_last_index(snapshot)
    if is_first_run:
        return

    sign = "+" if (snapshot["chg"] or 0) >= 0 else ""
    body = (
        f"Ngay: {snapshot['date']}\n"
        f"Diem: {snapshot['close']}\n"
        f"Thay doi: {sign}{snapshot['chg']:.2f} ({sign}{snapshot['pct']:.2f}%)"
    )
    send_message("VN-Index - Cap nhat", body)
    print(f"VN-Index: notified update for {snapshot['date']}.")


def main() -> None:
    seen = load_seen()
    is_first_run = len(seen) == 0
    new_seen = set(seen)
    total_new = 0

    for source, categories in SOURCES.items():
        items_by_category = {}
        for category, url in categories.items():
            try:
                items = fetch_feed(url)
            except Exception as e:
                print(f"Error fetching {url}: {e}", file=sys.stderr)
                continue
            new_items = []
            for item in items:
                link = item["link"]
                if link in seen or link in new_seen:
                    continue
                new_seen.add(link)
                new_items.append(item)
            items_by_category[category] = new_items

        if not is_first_run:
            sent = notify_source(source, items_by_category)
            total_new += sent
            print(f"{source}: sent {sent} new items.")

    save_seen(new_seen)
    check_vnindex(is_first_run)
    if is_first_run:
        print(f"First run: seeded {len(new_seen)} links, no notifications sent.")
    else:
        print(f"Total new items sent: {total_new}.")


if __name__ == "__main__":
    main()
