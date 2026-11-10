import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
from urllib.parse import urljoin
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path


BASE = "https://ticketjam.jp"
LIST = BASE + "/tickets/bj-league"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_soup(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def get_seat_info(text):
    # 表記ゆれを統一
    text = unicodedata.normalize("NFKC", text)

    # 範囲記号を統一
    text = text.replace("～", "〜")
    text = text.replace("~", "〜")


    # 座席階
    floor = re.search(
        r"上層|下層|\d+\s*(?:階|F)\s*席?|"
        r"アリーナ席?|スタンド席?",
        text, re.I
    )
    floor = floor.group() if floor else None

    if floor:
        floor = re.sub(r"(\d+)\s*F", r"\1階", floor, flags=re.I)
        floor = floor.replace("席", "")

    # 座席種別を3種類に分類
    if "当日引換券" in text:
      seat_type = "座席選択不可（当日引換券）"
    elif "自由席" in text:
      seat_type = "自由席"
    else:
      seat_type = "指定席"
    
    # エリアの抽出
    area = None

    # ブロック表記を優先
    block = re.search(
        r"([A-Z]+\d+)\s*ブロック",
        text,
        re.I
    )

    if block:
        area = block.group(1)
    else:
        match = re.search(
            r"[【\[]\s*"
            r"(?:上層|下層|\d+\s*(?:階|F))"
            r"\s*[|｜]\s*([^|｜\]】]+)",
            text,
            re.I
        )

        if match:
            candidate = match.group(1).strip()

            # 列や座席番号をエリアと誤認しない
            if not re.search(
                r"\d+\s*(?:[~〜\-]\s*\d+)?\s*(?:列|番)",
                candidate
            ):
                area = candidate


    # セクション
    section = re.search(
        r"セクション\s*([A-Z0-9]+)", text, re.I
    )

    # 列（範囲表記にも対応）
    row = re.search(
        r"(\d+)\s*(?:[~〜\-]\s*(\d+))?\s*列",
        text
    )
    row_value = None
    if row:
        row_value = (
            f"{row.group(1)}〜{row.group(2)}"
            if row.group(2) else row.group(1)
        )

    # 座席番号
    seat = re.search(
        r"(\d+)\s*(?:[~〜\-]\s*(\d+))?\s*番",
        text
    )
    seat_value = None
    if seat:
        seat_value = (
            f"{seat.group(1)}〜{seat.group(2)}"
            if seat.group(2) else seat.group(1)
        )

    seat_known = (
        "位置情報あり"
        if row_value is not None and seat_value is not None
        else "一部判明"
        if any(x is not None for x in [floor, area, row_value, seat_value])
        else "不明"
    )

    return (
        floor,
        area,
        section.group(1) if section else None,
        row_value,
        seat_value,
        seat_type,
    )


soup = get_soup(LIST)
urls = list(dict.fromkeys(
    urljoin(BASE, a["href"])
    for a in soup.find_all("a", href=True)
    if "/tickets/bj-league/event_groups/" in a["href"]
))

data = []
failed_urls = []
for i, url in enumerate(urls, 1):
    print(f"{i}/{len(urls)}: {url}")
    try:
        soup = get_soup(url)
        h1 = soup.find("h1")
        game = h1.get_text(" ", strip=True) if h1 else ""
        game = game.replace("リセールチケット一覧", "").strip()

        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if "円/枚" not in text:
                continue

            price = re.search(r"([\d,]+)\s*円/枚", text)
            qty = re.search(r"(\d+)\s*枚", text)
            dt = re.search(
                r"(\d{4}/\d{2}/\d{2})\([^)]+\)\s*(\d{1,2}:\d{2})",
                text
            )

            # リンク自身と親要素のテキストから座席情報を探す
            seat_text = text
            floor, area, section, row, seat_no, seat_type = get_seat_info(seat_text)

            data.append({
                "試合名": game,
                "開催日": dt.group(1) if dt else None,
                "開始時刻": dt.group(2) if dt else None,
                "価格": int(price.group(1).replace(",", "")) if price else None,
                "枚数": int(qty.group(1)) if qty else None,
                "座席種別": seat_type,
                "座席階": floor,
                "エリア": area,
                "列": row,
                "座席番号": seat_no,
                "セクション": section,
                "チケットURL": urljoin(BASE, a["href"]),
                "取得日時": datetime.now(
                    ZoneInfo("Asia/Tokyo")
                ).strftime("%Y-%m-%d %H:%M:%S"),
            })
        time.sleep(1)
    except requests.RequestException as e:
        print("取得失敗:", url, e)
        failed_urls.append(url)
    print("取得失敗ページ数:", len(failed_urls))

df = pd.DataFrame(data)

# 取得件数が0件の場合は処理を中止
if df.empty:
    raise RuntimeError(
        "取得件数が0件のため、CSVの保存を中止しました。"
    )

# データの重複削除と前処理
df = df.drop_duplicates(subset=["チケットURL"])

df["開催日"] = pd.to_datetime(df["開催日"], errors="coerce")

for col in ["価格", "枚数"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df["曜日"] = df["開催日"].dt.dayofweek
df["開催月"] = df["開催日"].dt.month

# 日本時間の取得日
today = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")

# 日付ごとにCSVを作成
output_dir = Path("data")
output_dir.mkdir(parents=True, exist_ok=True)

filename = output_dir / f"bj_league_ticket_data_{today}.csv"

df.to_csv(filename, index=False, encoding="utf-8-sig")

print("保存ファイル:", filename)
print("取得件数:", len(df))
print(df.head())
