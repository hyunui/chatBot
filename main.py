from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time

app = Flask(__name__)

# ---- 1. 코인게코 ID/심볼/이름 한글-영문 매핑 ----
def fetch_coingecko_coinlist():
    url = "https://api.coingecko.com/api/v3/coins/list?include_platform=false"
    r = requests.get(url)
    try:
        data = r.json()
    except Exception:
        data = []
    id_map = {}   # key: id, symbol, name → value: id
    name_map = {} # key: id → value: name
    symbol_map = {} # key: id → value: symbol
    for c in data:
        id = c.get('id', '').lower()
        symbol = c.get('symbol', '').upper()
        name = c.get('name', '').strip()
        # 입력이 name/symbol/id 어떤 형태든 id로 변환할 수 있도록
        id_map[name] = id
        id_map[symbol] = id
        id_map[id] = id
        name_map[id] = name
        symbol_map[id] = symbol
    return id_map, name_map, symbol_map

COINGECKO_ID_MAP, COINGECKO_NAME_MAP, COINGECKO_SYMBOL_MAP = fetch_coingecko_coinlist()

# ---- 2. 한글/영문/심볼 입력 → 코인게코 id로 변환 ----
def get_cg_id_from_query(query):
    q = query.strip()
    # 우선 정확히 일치(한글, 영문, 심볼, id)
    cg_id = COINGECKO_ID_MAP.get(q)
    if cg_id:
        return cg_id
    # 대소문자 보정
    cg_id = COINGECKO_ID_MAP.get(q.upper())
    if cg_id:
        return cg_id
    cg_id = COINGECKO_ID_MAP.get(q.lower())
    if cg_id:
        return cg_id
    # 공백 등 제거 후 재검색
    cg_id = COINGECKO_ID_MAP.get(q.replace(' ', '').lower())
    return cg_id or q

def get_cg_name_from_id(cg_id):
    return COINGECKO_NAME_MAP.get(cg_id, cg_id)

def get_cg_symbol_from_id(cg_id):
    return COINGECKO_SYMBOL_MAP.get(cg_id, cg_id.upper())

# ---- 3. 환율 실시간 조회 ----
def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        data = requests.get(url).json()
        return float(data["country"][1]["value"].replace(",", ""))
    except Exception:
        return 1400.0

# ---- 4. 코인게코에서 실시간 가격 정보 조회 ----
def get_coingecko_market_data(cg_id):
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=true&market_data=true"
    try:
        r = requests.get(url)
        if r.status_code != 200:
            return None
        data = r.json()
        market_data = data.get("market_data", {})
        tickers = data.get("tickers", [])
        # 글로벌(달러) 가격
        price_usd = market_data.get("current_price", {}).get("usd", 0)
        # 업비트, 빗썸, 코인원 가격
        upbit = bithumb = coinone = 0
        for t in tickers:
            market = t.get("market", {}).get("name", "").lower()
            pair = t.get("target", "").upper()
            last = t.get("last")
            if not last or pair != "KRW":
                continue
            if "upbit" in market:
                upbit = int(float(last))
            elif "bithumb" in market:
                bithumb = int(float(last))
            elif "coinone" in market:
                coinone = int(float(last))
        return {
            "usd": price_usd,
            "upbit": upbit,
            "bithumb": bithumb,
            "coinone": coinone
        }
    except Exception:
        return None

# ---- 5. 코인 시세 출력 ----
def get_coin_price(query):
    cg_id = get_cg_id_from_query(query)
    cg_name = get_cg_name_from_id(cg_id)
    cg_symbol = get_cg_symbol_from_id(cg_id)
    price_info = get_coingecko_market_data(cg_id)
    ex = get_exchange_rate()
    if not price_info:
        return f"[{cg_symbol}] {cg_name} 시세\n\n가격 정보를 가져올 수 없습니다."

    # 글로벌(달러) 가격
    global_price = price_info.get("usd", 0)
    upbit = price_info.get("upbit", 0)
    bithumb = price_info.get("bithumb", 0)
    coinone = price_info.get("coinone", 0)

    if global_price:
        global_str = f"${global_price:,.2f}"
    else:
        global_str = "정보 없음"

    # 김치프리미엄
    if upbit and global_price:
        kimchi = ((upbit - global_price * ex) / (global_price * ex)) * 100
        kimchi_str = f"{kimchi:+.2f}%"
    else:
        kimchi_str = "계산불가"

    return f"""[{cg_symbol}] {cg_name} 시세

💰 글로벌 가격 → {global_str}

🇰🇷 국내 거래소 가격
- 업비트 → ₩{upbit:,}
- 빗썸 → ₩{bithumb:,}
- 코인원 → ₩{coinone:,}

🧮 김치 프리미엄 → {kimchi_str}
"""

# ---- 6. 한국/미국 주식, TOP30, 일정, 명령어 안내 ----

def get_korean_stock_price(query):
    try:
        url = f"https://finance.naver.com/search/searchList.naver?query={query}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        href = soup.select_one(".section_search .tbl_search td a")["href"]
        code = href.split('=')[-1]
        stock_url = f"https://finance.naver.com/item/main.nhn?code={code}"
        r2 = requests.get(stock_url, headers={"User-Agent": "Mozilla/5.0"})
        soup2 = BeautifulSoup(r2.text, "html.parser")
        price = soup2.select_one("p.no_today span.blind").text
        return f"[{query}] 주식 시세\n💰 현재 가격 → ₩{price}\n📊 거래대금 → 지원예정"
    except Exception:
        return "한국 주식 정보를 가져올 수 없습니다."

def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        volume = stock.info.get("volume", 0)
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,}\n📊 거래대금 → {volume:,}"
    except Exception:
        return "미국 주식 정보를 가져올 수 없습니다."

def get_korea_top30():
    try:
        url = "https://finance.naver.com/sise/sise_rise.naver"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        trs = soup.select("table.type_2 tr")
        top = []
        for tr in trs[2:32]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            name = tds[1].get_text(strip=True)
            rate = tds[2].get_text(strip=True)
            top.append(f"{len(top)+1}. {name} ({rate})")
        return "📈 한국주식 상승률 TOP30\n" + "\n".join(top)
    except Exception:
        return "한국주식 TOP30 정보를 불러오지 못했습니다."

def get_us_top30():
    try:
        url = "https://finance.yahoo.com/screener/predefined/day_gainers"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        trs = soup.select('table tr[data-row]')
        top = []
        for tr in trs[:30]:
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            name = tds[1].get_text(strip=True)
            symbol = tds[0].get_text(strip=True)
            rate = tds[4].get_text(strip=True)
            top.append(f"{len(top)+1}. {name} ({symbol}) ({rate})")
        return "📈 미국주식 상승률 TOP30\n" + "\n".join(top)
    except Exception:
        return "미국주식 TOP30 정보를 불러오지 못했습니다."

def get_economic_calendar():
    try:
        url = "https://www.investing.com/economic-calendar/"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("tr.js-event-item")
        events = []
        now = datetime.now()
        one_month_later = now + timedelta(days=30)
        for row in rows:
            date_str = row.get("data-event-datetime", "")
            if not date_str:
                continue
            event_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            if event_dt < now or event_dt > one_month_later:
                continue
            country = row.get("data-country", "")
            event = row.select_one(".event").get_text(strip=True)
            impact = row.select_one(".sentiment")["title"] if row.select_one(".sentiment") else ""
            events.append(f"{event_dt.strftime('%Y-%m-%d')} [{country}] {event} ({impact})")
            if len(events) >= 10:
                break
        if not events:
            return "일정 정보를 찾을 수 없습니다."
        return "📅 주요 경제 일정 (1개월)\n" + "\n".join(events)
    except Exception:
        return "일정 정보를 불러오지 못했습니다."

def get_help():
    return (
        "📌 사용 가능한 명령어 목록\n\n"
        "✔️ 코인 시세: !BTC / !비트코인 / !ETH / !이더리움 등 (한글/영문/심볼 모두)\n"
        "✔️ 한국 주식: @삼성전자\n"
        "✔️ 미국 주식: #TSLA\n"
        "✔️ 한국 주식 TOP30: /한국주식 TOP30\n"
        "✔️ 미국 주식 TOP30: /미국주식 TOP30\n"
        "✔️ 일정(경제캘린더): /일정\n"
        "✔️ 차트 분석: !차트 BTC / @차트 삼성전자 / #차트 TSLA\n"
        "✔️ 명령어 안내: /명령어"
    )

# ---- 7. Flask Webhook 엔드포인트 ----

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()

    if utter == "/명령어":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_help()}}]}})
    if utter == "/일정":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_economic_calendar()}}]}})
    if utter.startswith("!차트") or utter.startswith("@차트") or utter.startswith("#차트"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "[차트 분석 기능 구조만 제공] (실서비스 연동시 별도 분석 API 필요)"}}]}})
    if utter.startswith("!"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_coin_price(utter[1:])}}]}})
    if utter.startswith("@"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korean_stock_price(utter[1:])}}]}})
    if utter.startswith("#"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_stock_price(utter[1:])}}]}})
    if utter == "/한국주식 TOP30":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korea_top30()}}]}})
    if utter == "/미국주식 TOP30":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_top30()}}]}})
    return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "[알림] 지원하지 않는 명령어입니다."}}]}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
