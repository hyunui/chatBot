from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json

app = Flask(__name__)

# 업비트 심볼 맵
def get_upbit_symbol_map():
    try:
        url = "https://api.upbit.com/v1/market/all"
        markets = requests.get(url).json()
        name2symbol = {}
        for m in markets:
            if m["market"].startswith("KRW-"):
                symbol = m["market"].replace("KRW-", "")
                name2symbol[m["korean_name"]] = symbol
                name2symbol[symbol] = m["korean_name"]
        return name2symbol
    except:
        return {}

UPBIT_MAP = get_upbit_symbol_map()

# 바이낸스 글로벌 시세
def get_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
        data = requests.get(url).json()
        return float(data["price"])
    except:
        return None

# 업비트 가격
def get_upbit_price(symbol):
    try:
        resp = requests.get(f"https://api.upbit.com/v1/ticker?markets=KRW-{symbol.upper()}")
        data = resp.json()
        return int(data[0]["trade_price"])
    except:
        return None

# 빗썸 가격
def get_bithumb_price(symbol):
    try:
        resp = requests.get(f"https://api.bithumb.com/public/ticker/{symbol.upper()}_KRW")
        data = resp.json()
        if data["status"] == "0000":
            return int(float(data["data"]["closing_price"]))
    except:
        return None

# 환율 (네이버)
def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        data = requests.get(url).json()
        return float(data["country"][1]["value"].replace(",", ""))
    except:
        return 1400.0

# 코인 시세 통합
def get_coin_price(query):
    try:
        is_korean = not query.isascii()
        symbol = query.upper()
        kr_name = query

        if is_korean:
            symbol = UPBIT_MAP.get(query)
            if not symbol:
                return f"[{query}] 코인없음"

        global_price = get_binance_price(symbol)
        upbit = get_upbit_price(symbol)
        bithumb = get_bithumb_price(symbol)
        coinone = 0  # 생략됨

        if not global_price:
            global_str = "정보 없음"
            kimchi_str = "계산불가"
        else:
            global_str = f"${global_price:,.2f}"
            ex = get_exchange_rate()
            if upbit:
                kimchi = ((upbit - global_price * ex) / (global_price * ex)) * 100
                kimchi_str = f"{kimchi:+.2f}%"
            else:
                kimchi_str = "계산불가"

        return f"""[{symbol}] {kr_name} 시세

💰 글로벌 가격 → {global_str}
🇰🇷 국내 거래소 가격
- 업비트 → ₩{upbit:,}""" + (f"\n- 빗썸 → ₩{bithumb:,}" if bithumb else "") + f"""

🧮 김치 프리미엄 → {kimchi_str}"""
    except Exception as e:
        return f"오류: {e}"

# 한국 주식
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
    except:
        return "한국 주식 정보를 가져올 수 없습니다."

# 미국 주식
def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        volume = stock.info.get("volume", 0)
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,}\n📊 거래대금 → {volume:,}"
    except:
        return "미국 주식 정보를 가져올 수 없습니다."

# 한국주식 TOP30
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
    except:
        return "한국주식 TOP30 정보를 불러오지 못했습니다."

# 미국주식 TOP30
def get_us_top30():
    try:
        url = "https://finance.yahoo.com/screener/predefined/day_gainers"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")
        # 실제로는 테이블이 자바스크립트로 동적으로 만들어지기 때문에
        # 표 파싱이 실패할 경우 fallback으로 json 데이터 요청을 시도
        rows = []
        table = soup.find("table")
        if table:
            rows = table.find("tbody").find_all("tr")
        top = []
        for idx, tr in enumerate(rows[:30]):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            symbol = tds[0].get_text(strip=True)
            name = tds[1].get_text(strip=True)
            rate = tds[4].get_text(strip=True)
            top.append(f"{idx+1}. {name} ({symbol}) ({rate})")
        # fallback (실패시)
        if not top:
            # Yahoo 파이낸스 API의 json url (비공식)
            screener_url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?count=30&scrIds=day_gainers"
            resp = requests.get(screener_url, headers=headers)
            js = resp.json()
            items = js["finance"]["result"][0]["quotes"]
            for idx, item in enumerate(items):
                symbol = item.get("symbol", "")
                name = item.get("shortName", "") or item.get("longName", "")
                rate = f'{item.get("regularMarketChangePercent", 0):+.2f}%'
                top.append(f"{idx+1}. {name} ({symbol}) ({rate})")
        if not top:
            return "미국주식 TOP30 정보를 불러오지 못했습니다."
        return "📈 미국주식 상승률 TOP30\n" + "\n".join(top)
    except Exception as e:
        return f"미국주식 TOP30 정보를 불러오지 못했습니다.\n오류: {e}"

# 경제일정
def get_economic_calendar():
    try:
        url = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest"
        }
        now = datetime.now()
        end = now + timedelta(days=30)
        data = {
            "dateFrom": now.strftime("%Y-%m-%d"),
            "dateTo": end.strftime("%Y-%m-%d"),
            "timezone": "Asia/Seoul",
            "limit_from": 0
        }
        resp = requests.post(url, headers=headers, data=data)
        resp_json = resp.json()

        # 안전하게 data 파싱
        events = []
        data_list = resp_json.get('data', [])
        if isinstance(data_list, list):
            for item in data_list[:10]:
                date_str = item.get("date", "")
                time_str = item.get("time", "")
                event = item.get("event", "")
                country = item.get("country", "")
                impact = item.get("importance", "")
                events.append(f"{date_str} [{country}] {event} ({impact})")
        else:
            return "일정 데이터를 파싱할 수 없습니다. 잠시 후 다시 시도해 주세요."

        if not events:
            return "일정 정보를 찾을 수 없습니다."
        return "📅 주요 경제 일정 (1개월)\n" + "\n".join(events)
    except Exception as e:
        return f"일정 정보를 불러오지 못했습니다.\n오류: {e}"

# 명령어 안내
def get_help():
    return (
        "📌 사용 가능한 명령어 목록\n\n"
        "✔️ 코인 시세: !비트코인 / !BTC / !이더리움 등\n"
        "✔️ 한국 주식: @삼성전자\n"
        "✔️ 미국 주식: #TSLA\n"
        "✔️ 한국 주식 TOP30: /한국주식 TOP30\n"
        "✔️ 미국 주식 TOP30: /미국주식 TOP30\n"
        "✔️ 일정: /일정\n"
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
    if utter == "/한국주식 TOP30":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korea_top30()}}]}})
    if utter == "/미국주식 TOP30":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_top30()}}]}})
    if utter.startswith("!"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_coin_price(utter[1:])}}]}})
    if utter.startswith("@"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korean_stock_price(utter[1:])}}]}})
    if utter.startswith("#"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_stock_price(utter[1:])}}]}})
    return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "지원하지 않는 명령어입니다."}}]}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
