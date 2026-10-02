"""유니테스트 페로브스카이트 뉴스 수집기 -> docs/news.json (+ 텔레그램 알림)"""
import json, os, re, html, struct, zlib, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

QUERIES = [
    '"유니테스트" 페로브스카이트',
    '"유니테스트" 태양전지',
    '"유니테스트" 솔루엠 ESL',
    '"유니테스트" BIPV',
]
MAX_ITEMS = 300
OUT = "docs/news.json"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def clean(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()


def google_news(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:30d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    root = ET.fromstring(get(url))
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        src = clean(it.findtext("source"))
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        yield {
            "title": title,
            "link": it.findtext("link"),
            "source": src,
            "published": parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).isoformat(),
        }


def naver_news(q, cid, secret):
    url = "https://openapi.naver.com/v1/search/news.json?" + urllib.parse.urlencode(
        {"query": q.replace('"', ""), "display": 50, "sort": "date"})
    data = json.loads(get(url, {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}))
    for it in data.get("items", []):
        title, desc = clean(it["title"]), clean(it["description"])
        if "유니테스트" not in title + desc:
            continue
        yield {
            "title": title,
            "link": it.get("originallink") or it["link"],
            "source": urllib.parse.urlparse(it.get("originallink") or it["link"]).netloc.replace("www.", ""),
            "published": parsedate_to_datetime(it["pubDate"]).astimezone(timezone.utc).isoformat(),
        }


def key(title):
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())[:40]


def telegram(items):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for it in items[:10]:
        text = f"📰 {it['title']}\n{it['source']}\n{it['link']}"
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)
        except Exception as e:
            print("telegram 실패:", e)


def make_icon(path):
    """앱 아이콘(180x180 PNG)을 외부 라이브러리 없이 생성"""
    n = 180
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            cx, cy = x - n / 2, y - n / 2
            lit = abs(cx) + abs(cy) < 62  # 가운데 마름모(결정 모양)
            row += bytes((232, 161, 0) if lit else (18, 32, 46))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def main():
    os.makedirs("docs", exist_ok=True)
    if not os.path.exists("docs/icon.png"):
        make_icon("docs/icon.png")

    old = []
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding="utf-8")).get("items", [])
    seen = {key(i["title"]) for i in old} | {i["link"] for i in old}

    found = []
    cid, sec = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    for q in QUERIES:
        try:
            found += list(google_news(q))
        except Exception as e:
            print("구글 실패:", q, e)
        if cid and sec:
            try:
                found += list(naver_news(q, cid, sec))
            except Exception as e:
                print("네이버 실패:", q, e)

    now = datetime.now(timezone.utc).isoformat()
    new = []
    for it in sorted(found, key=lambda x: x["published"], reverse=True):
        k = key(it["title"])
        if k in seen or it["link"] in seen:
            continue
        seen |= {k, it["link"]}
        it["first_seen"] = now
        new.append(it)

    items = sorted(new + old, key=lambda x: x["published"], reverse=True)[:MAX_ITEMS]
    json.dump({"updated": now, "items": items}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"새 기사 {len(new)}건, 전체 {len(items)}건")

    if old:  # 첫 실행은 알림 폭탄 방지를 위해 건너뜀
        telegram(new)


if __name__ == "__main__":
    main()
