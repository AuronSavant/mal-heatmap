"""Generate a MAL activity heatmap PNG from a public MyAnimeList profile.

Sources (no API key needed, list must be public):
  * list entries' last-updated date (anime + manga load.json)
  * the recent-history page (episode/chapter level), accumulated over time in
    data/activity.json so history builds up with every run.
"""
import json, os, re, sys, time, urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import unescape

from PIL import Image, ImageDraw, ImageFont

USER = os.environ.get("MAL_USER", "Auron")
OUT = os.environ.get("OUT", "heatmap.png")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "activity.json")
UA = {"User-Agent": "Mozilla/5.0 (mal-heatmap personal script)"}


def get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception as e:
            print("retry", url, e, file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"failed to fetch {url}")


def list_events(kind):
    """One event per list entry, on the day it was last updated."""
    events, offset = {}, 0
    while True:
        rows = json.loads(get(f"https://myanimelist.net/{kind}list/{USER}/load.json?offset={offset}&status=7"))
        for row in rows:
            if not row.get("updated_at"):
                continue  # manga rows only expose created_at on some lists
            key = f"list:{kind}:{row.get('anime_id') or row.get('manga_id')}"
            day = datetime.fromtimestamp(row["updated_at"], timezone.utc).date().isoformat()
            events[key] = day
        if len(rows) < 300:
            return events
        offset += 300
        time.sleep(1)


def history_events(kind):
    """Episode/chapter level events from the recent history page."""
    html = get(f"https://myanimelist.net/history/{USER}?type={kind}")
    today = date.today()
    events = {}
    for m in re.finditer(
        r'href="/(?:anime|manga)\.php\?id=(\d+)">.*?<strong>(\d+)</strong>.*?align="right">&nbsp;([^<]+?)\s*</td>',
        html, re.S):
        item, num, stamp = m.group(1), m.group(2), unescape(m.group(3)).strip()
        try:
            d = datetime.strptime(f"{stamp} {today.year}", "%b %d, %I:%M %p %Y").date()
        except ValueError:
            continue  # "Today, 3:05 PM" / "Yesterday" style stamps
        if d > today:
            d = d.replace(year=d.year - 1)
        events[f"hist:{kind}:{item}:{num}:{stamp}"] = d.isoformat()
    # relative stamps ("Today", "Yesterday")
    for m in re.finditer(
        r'href="/(?:anime|manga)\.php\?id=(\d+)">.*?<strong>(\d+)</strong>.*?align="right">&nbsp;(Today|Yesterday)[^<]*?\s*</td>',
        html, re.S):
        d = today if m.group(3) == "Today" else today - timedelta(days=1)
        events[f"hist:{kind}:{m.group(1)}:{m.group(2)}:{m.group(3)}"] = d.isoformat()
    return events


def load_store():
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    return {}


def render(counts, path):
    end = date.today()
    start = end - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)  # align to Sunday
    weeks = (end - start).days // 7 + 1

    cell, gap, left, top = 12, 3, 34, 30
    w = left + weeks * (cell + gap) + 12
    h = top + 7 * (cell + gap) + 36
    bg = (30, 33, 40, 255)
    img = Image.new("RGBA", (w, h), bg)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    palette = [(45, 51, 59), (14, 68, 41), (0, 109, 50), (38, 166, 65), (57, 211, 83)]
    peak = max(counts.values(), default=1)

    def level(n):
        if n == 0:
            return 0
        q = n / peak
        return 1 if q <= .25 else 2 if q <= .5 else 3 if q <= .75 else 4

    d.text((left, 8), f"{USER} - MyAnimeList activity, last 12 months "
                      f"({sum(v for k, v in counts.items() if k >= start.isoformat())} updates)",
           fill=(200, 205, 215), font=font)
    for label, row in (("Mon", 1), ("Wed", 3), ("Fri", 5)):
        d.text((6, top + row * (cell + gap) + 1), label, fill=(140, 146, 158), font=font)

    last_month = None
    for i in range(weeks):
        for j in range(7):
            day = start + timedelta(days=i * 7 + j)
            if day > end:
                continue
            x, y = left + i * (cell + gap), top + j * (cell + gap)
            d.rounded_rectangle([x, y, x + cell, y + cell], 2,
                                fill=palette[level(counts.get(day.isoformat(), 0))])
            if j == 0 and day.month != last_month and day.day <= 7:
                d.text((x, top - 14), day.strftime("%b"), fill=(140, 146, 158), font=font)
                last_month = day.month

    ly = h - 20
    d.text((w - 150, ly), "Less", fill=(140, 146, 158), font=font)
    for k, c in enumerate(palette):
        x = w - 118 + k * (cell + 3)
        d.rounded_rectangle([x, ly - 1, x + cell, ly - 1 + cell], 2, fill=c)
    d.text((w - 118 + 5 * (cell + 3) + 2, ly), "More", fill=(140, 146, 158), font=font)
    img.convert("RGB").save(path)


def main():
    store = load_store()
    for kind in ("anime", "manga"):
        for k, v in list_events(kind).items():
            # a list entry whose date moved replaces its earlier list event only
            store[k] = v
        store.update(history_events(kind))
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=0, sort_keys=True)
    counts = Counter(store.values())
    render(counts, OUT)
    print(f"{len(store)} events, wrote {OUT}")


if __name__ == "__main__":
    main()
