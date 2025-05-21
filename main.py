from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)

# 1. 업비트 한글-심볼 자동매핑
def get_upbit_map():
    try:
        r = requests.get("https://api.upbit.com/v1/market/all")
        coins = r.json()
        name2symbol = {}
        for c in coins:
            if c["market"].startswith("KRW-"):
                name2symbol[c["korean_name"]] = c["market"].replace("KRW-", "")
        return name2symbol
    except:
        return {}

# 2. 코인게코 전체 코인 리스트
def get_coingecko_list():
    try:
        url = "https://api.coingecko.com/api/v3/coins/list"
        coins = requests.get(url).json()
        return coins
    except:
        return []

COINGECKO_LIST = get_coingecko_list()
UPBIT_MAP = get_upbit_map()

def get_symbol_by_kor(kor):
    symbol = UPBIT_MAP.get(kor)
    if symbol:
        return symbol
    return None

def get_coingecko_id_by_symbol(symbol):
    symbol = symbol.lower()
    for c in COINGECKO_LIST:
        if c["symbol"].lower() == symbol:
            return c["id"]
    return None

def find_coingecko_id(query):
    q = query.strip().lower()
    # 심볼 일치
    for c in COINGECKO_LIST:
        if c['symbol'].lower() == q:
            return c['id'], c['name'], c['symbol'].upper()
    # 영문 이름 일치
    for c in COINGECKO_LIST:
        if c['name'].lower() == q:
            return c['id'], c['name'], c['symbol'].upper()
    return None, None, None

def get_coingecko_price(id):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=usd,krw"
        data = requests.get(url).json()
        price_usd = data[id]["usd"]
        price_krw = data[id]["krw"]
        return price_usd, price_krw
    except:
        return None, None

def get_coin_price(query):
    try:
        # Step1. 한글이면 업비트 심볼 → 코인게코 id → 가격
        if not query.isascii():
            symbol = get_symbol_by_kor(query)
            if symbol:
                cid = get_coingecko_id_by_symbol(symbol)
                if cid:
                    price_usd, price_krw = get_coingecko_price(cid)
                    if price_usd:
                        return f"[{symbol}] {query} 시세\n💰 글로벌 가격 → ${price_usd:,.2f}\n🇰🇷 원화 가격 → ₩{price_krw:,.0f}"
                    else:
                        return f"{query} 실시간 가격 정보를 찾을 수 없습니다."
            # 국내 거래소에 없으면 → 코인게코에서 영문이름/심볼 매칭 시도
            cid, name, symbol = find_coingecko_id(query)
            if cid:
                price_usd, price_krw = get_coingecko_price(cid)
                if price_usd:
                    return f"[{symbol}] {name} 시세\n💰 글로벌 가격 → ${price_usd:,.2f}\n🇰🇷 원화 가격 → ₩{price_krw:,.0f}"
                else:
                    return f"{query} 실시간 가격 정보를 찾을 수 없습니다."
            return f"{query} : 코인 정보를 찾을 수 없습니다."
        else:
            # 영문 심볼/이름 → 코인게코에서 id 매핑 후 실시간 조회
            cid, name, symbol = find_coingecko_id(query)
            if cid:
                price_usd, price_krw = get_coingecko_price(cid)
                if price_usd:
                    return f"[{symbol}] {name} 시세\n💰 글로벌 가격 → ${price_usd:,.2f}\n🇰🇷 원화 가격 → ₩{price_krw:,.0f}"
                else:
                    return f"{query} 실시간 가격 정보를 찾을 수 없습니다."
            return f"{query} : 코인 정보를 찾을 수 없습니다."
    except Exception as e:
        return f"오류 발생: {e}"

# 한국 주식 시세 (네이버)
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
        volume = soup2.select_one("table.no_info td em span.blind").text
        return f"[{query}] 주식 시세\n💰 현재 가격 → ₩{price}\n📊 거래대금 → ₩{volume}"
    except Exception:
        return "한국 주식 정보를 가져올 수 없습니다."

# 미국 주식 시세 (yfinance)
def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        volume = stock.info.get("volume", 0)
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,}\n📊 거래대금 → {volume:,}"
    except Exception:
        return "미국 주식 정보를 가져올 수 없습니다."

# 한국 주식 TOP30 (네이버)
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

# 미국 주식 TOP30 (야후 파이낸스)
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

# 경제일정 (Investing.com)
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
