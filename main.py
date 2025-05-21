from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)

# 1. 코인게코 한글/영문/심볼/id 매핑
def get_coingecko_kor_map():
    url = "https://api.coingecko.com/api/v3/coins/list?include_platform=false"
    try:
        data = requests.get(url).json()
    except Exception:
        data = []
    kor_map = {}
    for c in data:
        if isinstance(c, dict):
            name = c.get('name', '').strip()
            symbol = c.get('symbol', '').upper()
            id = c.get('id', '').lower()
            kor_map[name] = symbol
            kor_map[symbol] = name
            kor_map[id] = symbol
    return kor_map

COINGECKO_KR_MAP = get_coingecko_kor_map()

def kr_to_symbol(name):
    if not name.isascii():
        return COINGECKO_KR_MAP.get(name, name.upper())
    return name.upper()

def symbol_to_kr(symbol):
    return COINGECKO_KR_MAP.get(symbol.upper(), symbol.upper())

# 환율
def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        data = requests.get(url).json()
        return float(data["country"][1]["value"].replace(",", ""))
    except Exception:
        return 1400.0

# Binance 시세 조회 (글로벌)
def get_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
        data = requests.get(url).json()
        return float(data["price"])
    except Exception:
        return None

# CoinGecko 시세 조회 (fallback)
def get_coingecko_price(symbol):
    try:
        # 코인게코 symbol -> id 찾기
        for k, v in COINGECKO_KR_MAP.items():
            if v.lower() == symbol.lower():
                id = k if k.isascii() is False else None
                if id is None: continue
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=usd"
                data = requests.get(url).json()
                usd = data.get(id, {}).get('usd')
                if usd:
                    return float(usd)
        return None
    except Exception:
        return None

# 국내 거래소 시세
def get_upbit_price(symbol):
    try:
        symbol = symbol.upper()
        resp = requests.get("https://api.upbit.com/v1/ticker?markets=KRW-" + symbol)
        if resp.status_code == 200 and resp.json():
            return int(resp.json()[0]["trade_price"])
    except:
        return None

def get_bithumb_price(symbol):
    try:
        symbol = symbol.upper()
        resp = requests.get(f"https://api.bithumb.com/public/ticker/{symbol}_KRW")
        data = resp.json()
        if data["status"] == "0000":
            return int(float(data["data"]["closing_price"]))
    except:
        return None

def get_coinone_price(symbol):
    try:
        symbol = symbol.lower()
        resp = requests.get(f"https://api.coinone.co.kr/ticker?currency={symbol}")
        data = resp.json()
        if data.get("last"):
            return int(float(data["last"]))
    except:
        return None

def get_korea_prices(symbol):
    return {
        "upbit": get_upbit_price(symbol) or 0,
        "bithumb": get_bithumb_price(symbol) or 0,
        "coinone": get_coinone_price(symbol) or 0
    }

# 글로벌 + 국내 코인 시세, 김프계산, 한글/영문 자동 매핑
def get_coin_price(symbol):
    # 한글 자동 매핑
    if not symbol.isascii():
        symbol = kr_to_symbol(symbol)
    krname = symbol_to_kr(symbol)
    # 글로벌 가격 (1순위 Binance, 실패시 CoinGecko)
    global_price = get_binance_price(symbol)
    if not global_price:
        global_price = get_coingecko_price(symbol)
    ex = get_exchange_rate()
    kr_prices = get_korea_prices(symbol)
    if not global_price:
        global_str = "정보 없음"
        kimchi_str = "계산불가"
    else:
        global_str = f"${global_price:,.2f}"
        if kr_prices["upbit"]:
            kimchi = ((kr_prices["upbit"] - global_price * ex) / (global_price * ex)) * 100
            kimchi_str = f"{kimchi:+.2f}%"
        else:
            kimchi_str = "계산불가"

    result = (
        f"[{symbol.upper()}] {krname} 시세\n\n"
        f"💰 글로벌 가격 → {global_str}\n\n"
        f"🇰🇷 국내 거래소 가격\n"
        f"- 업비트 → ₩{kr_prices['upbit']:,}\n"
        f"- 빗썸 → ₩{kr_prices['bithumb']:,}\n"
        f"- 코인원 → ₩{kr_prices['coinone']:,}\n\n"
        f"🧮 김치 프리미엄 → {kimchi_str}"
    )
    return result

# 한국주식, 미국주식, TOP30, 일정, 도움말 등 기존 기능 유지
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
        "✔️ 코인 시세: !BTC / !비트코인 / !ETH / !이더리움 등 (한글/영문 모두)\n"
        "✔️ 한국 주식: @삼성전자\n"
        "✔️ 미국 주식: #TSLA\n"
        "✔️ 한국 주식 TOP30: /한국주식 TOP30\n"
        "✔️ 미국 주식 TOP30: /미국주식 TOP30\n"
        "✔️ 일정(경제캘린더): /일정\n"
        "✔️ 명령어 안내: /명령어"
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()

    if utter == "/명령어":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_help()}}]}})
    if utter == "/일정":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_economic_calendar()}}]}})
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
