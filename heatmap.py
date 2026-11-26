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


def history_events(kind):
    """Episode/chapter updates from the recent history page: key -> (item, num, iso datetime)."""
    html = get(f"https://myanimelist.net/history/{USER}/{kind}")
    now = datetime.now()
    out = {}
    for m in re.finditer(
        r'href="/(?:anime|manga)\.php\?id=(\d+)">.*?<strong>(\d+)</strong>.*?align="right">&nbsp;([^<]+?)\s*</td>',
        html, re.S):
        item, num, stamp = m.group(1), int(m.group(2)), unescape(m.group(3)).strip()
        rel = re.match(r"(Today|Yesterday),?\s*(.*)", stamp)
        try:
            if rel:
                t = datetime.strptime(rel.group(2), "%I:%M %p").time() if rel.group(2) else datetime.min.time()
                day = now.date() - timedelta(days=0 if rel.group(1) == "Today" else 1)
                dt = datetime.combine(day, t)
            else:
                dt = datetime.strptime(f"{stamp} {now.year}", "%b %d, %I:%M %p %Y")
                if dt > now + timedelta(days=1):
                    dt = dt.replace(year=dt.year - 1)
        except ValueError:
            continue
        out[f"{kind}:{item}:{num}:{dt.isoformat()}"] = [kind, item, num, dt.isoformat()]
    return out


def episodes_per_day(store):
    """Turn progress updates into units watched per day (ep 2 -> ep 12 = 10 episodes)."""
    by_item = {}
    for kind, item, num, iso in store.values():
        by_item.setdefault((kind, item), []).append((iso, num))
    counts = Counter()
    for rows in by_item.values():
        prev = 0
        for iso, num in sorted(rows):
            counts[iso[:10]] += num - prev if num > prev else 1
            prev = num
    return counts


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

    cell, gap, left, top = 12, 3, 34, 38
    w = left + weeks * (cell + gap) + 12
    h = top + 7 * (cell + gap) + 36
    bg = (30, 33, 40, 255)
    img = Image.new("RGBA", (w, h), bg)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    palette = [(45, 51, 59), (38, 120, 70), (46, 160, 67), (57, 211, 83), (140, 255, 150)]

    def level(n):  # fixed thresholds so one busy day doesn't wash out the rest
        return 0 if n == 0 else 1 if n == 1 else 2 if n <= 3 else 3 if n <= 6 else 4

    d.text((left, 6), f"{USER} - episodes/chapters per day, last 12 months "
                      f"({sum(v for k, v in counts.items() if k >= start.isoformat())} episodes)",
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
                d.text((x, top - 13), day.strftime("%b"), fill=(140, 146, 158), font=font)
                last_month = day.month

    ly = h - 20
    d.text((w - 150, ly), "Less", fill=(140, 146, 158), font=font)
    for k, c in enumerate(palette):
        x = w - 118 + k * (cell + 3)
        d.rounded_rectangle([x, ly - 1, x + cell, ly - 1 + cell], 2, fill=c)
    d.text((w - 118 + 5 * (cell + 3) + 2, ly), "More", fill=(140, 146, 158), font=font)
    img.convert("RGB").save(path)


def main():
    store = {k: v for k, v in load_store().items() if isinstance(v, list)}  # drops old list-based data
    for kind in ("anime", "manga"):
        store.update(history_events(kind))
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=0, sort_keys=True)
    counts = episodes_per_day(store)
    render(counts, OUT)
    print(f"{len(store)} updates, {sum(counts.values())} episodes, wrote {OUT}")


if __name__ == "__main__":
    main()
