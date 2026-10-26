"""Monitor USHauls Redemption Mall -> powiadomienia na Discorda.

Uruchomienie:
    python monitor.py          # normalny przebieg
    python monitor.py --test   # wysyla tylko wiadomosc testowa na Discorda

Webhook podaj w zmiennej srodowiskowej DISCORD_WEBHOOK (nigdy w kodzie).
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://ushauls.com/api/mall/goods/list"
SITE = "https://ushauls.com/"
STATE_FILE = Path(__file__).with_name("seen.json")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
PAGE_SIZE = 20
MAX_PAGES = 50

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://ushauls.com",
    "Referer": SITE,
}


def fetch_all():
    """Pobiera wszystkie strony listy produktow."""
    items, seen_ids = [], set()
    for page in range(1, MAX_PAGES + 1):
        payload = {
            "pageNum": page,
            "pageSize": PAGE_SIZE,
            "keyword": "",
            "categoryParentCode": "",
            "meetMemberLevel": False,
            "exchangeable": False,
        }
        body = None
        for attempt in range(3):
            try:
                r = requests.post(API, json=payload, headers=HEADERS, timeout=20)
                r.raise_for_status()
                body = r.json()
                break
            except Exception as exc:  # siec / JSON
                if attempt == 2:
                    raise
                print(f"Blad ({exc}), ponawiam...")
                time.sleep(3)
        if body.get("code") != 200:
            raise RuntimeError(f"API zwrocilo blad: {body}")
        records = (body.get("data") or {}).get("records") or []
        for rec in records:
            gid = str(rec["goodsId"])
            if gid not in seen_ids:
                seen_ids.add(gid)
                items.append(rec)
        if len(records) < PAGE_SIZE:
            break
        time.sleep(0.5)
    return items


def is_available(it):
    return bool(it.get("onSale")) and not it.get("soldOut") and (it.get("stock") or 0) > 0


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None


def save_state(items):
    data = {str(it["goodsId"]): {"available": is_available(it)} for it in items}
    STATE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def post_discord(payload):
    if not WEBHOOK:
        print("[brak DISCORD_WEBHOOK] ->", json.dumps(payload, ensure_ascii=False)[:500])
        return
    for _ in range(5):
        r = requests.post(WEBHOOK, json=payload, timeout=20)
        if r.status_code == 429:  # rate limit
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord: za duzo prob (rate limit)")


def make_embed(it, label):
    return {
        "title": f"{label}: {it.get('goodsName', '?')}"[:250],
        "url": SITE,
        "description": f"💰 **{it.get('medalPrice')}** medali  •  📦 stan: **{it.get('stock')}**"
                       f"  •  {it.get('categoryParentCode') or '-'}",
        "thumbnail": {"url": it.get("mainImage") or ""},
        "color": 0xFF4800,
    }


def notify(new_items, restocked):
    embeds = [make_embed(i, "🆕 Nowe") for i in new_items]
    embeds += [make_embed(i, "🔁 Znowu dostepne") for i in restocked]
    for start in range(0, len(embeds), 10):  # max 10 embedow na wiadomosc
        post_discord({"content": "USHauls: zmiany w sklepie!" if start == 0 else "", "embeds": embeds[start:start + 10]})
        time.sleep(1)


def main():
    if "--test" in sys.argv:
        post_discord({"content": "Test z ushauls monitor ✅"})
        return

    items = fetch_all()
    print(f"Pobrano {len(items)} produktow.")
    old = load_state()

    if old is None:  # pierwszy przebieg: zapisz stan, nie spamuj
        save_state(items)
        post_discord({"content": f"Monitor USHauls dziala ✅ Widze {len(items)} produktow. "
                                 f"Od teraz dostaniesz powiadomienia o nowych."})
        return

    new_items = [i for i in items if str(i["goodsId"]) not in old and is_available(i)]
    restocked = [i for i in items
                 if str(i["goodsId"]) in old
                 and not old[str(i["goodsId"])]["available"]
                 and is_available(i)]

    if new_items or restocked:
        print(f"Nowe: {len(new_items)}, wrocily: {len(restocked)}")
        notify(new_items, restocked)  # jesli to sie wywali, stan sie nie zapisze -> proba przy nastepnym razie
    else:
        print("Bez zmian.")
    save_state(items)


if __name__ == "__main__":
    main()
