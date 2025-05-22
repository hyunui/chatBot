from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json

app = Flask(__name__)

def get_upbit_symbol_map():
    try:
        url = "https://api.upbit.com/v1/market/all"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return {}
        markets = r.json()
        name2symbol = {}
        for m in markets:
            if m["market"].startswith("KRW-"):
                symbol = m["market"].replace("KRW-", "")
                name2symbol[m["korean_name"]] = symbol
                name2symbol[symbol] = m["korean_name"]
        return name2symbol
    except Exception as e:
        print(f"Upbit Symbol Map Error: {e}")
        return {}

UPBIT_MAP = get_upbit_symbol_map()

def get_symbol_by_korean_name(name):
    global UPBIT_MAP
    # 맵이 비어있으면 재로딩
    if not UPBIT_MAP:
        UPBIT_MAP = get_upbit_symbol_map()
    return UPBIT_MAP.get(name)

def get_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return None, f"Binance API 접속 실패 (status:{r.status_code})"
        data = r.json()
        return float(data["price"]), None
    except Exception as e:
        return None, f"Binance API 에러: {e}"

def get_upbit_price(symbol):
    try:
        r = requests.get(f"https://api.upbit.com/v1/ticker?markets=KRW-{symbol.upper()}", timeout=3)
        if r.status_code != 200:
            return None, f"Upbit API 접속 실패 (status:{r.status_code})"
        data = r.json()
        return int(data[0]["trade_price"]), None
    except Exception as e:
        return None, f"Upbit 시세 에러: {e}"

def get_bithumb_price(symbol):
    try:
        r = requests.get(f"https://api.bithumb.com/public/ticker/{symbol.upper()}_KRW", timeout=3)
        if r.status_code != 200:
            return None, f"Bithumb API 접속 실패 (status:{r.status_code})"
        data = r.json()
        if data["status"] == "0000":
            return int(float(data["data"]["closing_price"])), None
        else:
            return None, f"Bithumb 데이터 없음"
    except Exception as e:
        return None, f"Bithumb 시세 에러: {e}"

def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return 1400.0, f"환율 API 접속 실패 (status:{r.status_code})"
        data = r.json()
        return float(data["country"][1]["value"].replace(",", "")), None
    except Exception as e:
        return 1400.0, f"환율 API 에러: {e}"

def get_coin_price(query):
    try:
        is_korean = not query.isascii()
        symbol = query.upper()
        kr_name = query
        error_msgs = []

        if is_korean:
            symbol = get_symbol_by_korean_name(query)
            if not symbol:
                return f"[{query}] 코인없음 (국내 거래소에 존재하지 않음)"

        global_price, err1 = get_binance_price(symbol)
        upbit, err2 = get_upbit_price(symbol)
        bithumb, err3 = get_bithumb_price(symbol)
        ex, err4 = get_exchange_rate()

        if err1: error_msgs.append(f"글로벌가격: {err1}")
        if err2: error_msgs.append(f"업비트: {err2}")
        if err3: error_msgs.append(f"빗썸: {err3}")
        if err4: error_msgs.append(f"환율: {err4}")

        if not global_price:
            global_str = "정보 없음"
            kimchi_str = "계산불가"
        else:
            global_str = f"${global_price:,.2f}"
            if upbit:
                kimchi = ((upbit - global_price * ex) / (global_price * ex)) * 100
                kimchi_str = f"{kimchi:+.2f}%"
            else:
                kimchi_str = "계산불가"

        result = f"""[{symbol}] {kr_name} 시세

💰 글로벌 가격 → {global_str}
🇰🇷 국내 거래소 가격
- 업비트 → {f'₩{upbit:,}' if upbit else '정보 없음'}
- 빗썸 → {f'₩{bithumb:,}' if bithumb else '정보 없음'}

🧮 김치 프리미엄 → {kimchi_str}"""

        if error_msgs:
            result += "\n\n[접근 실패 정보]\n" + "\n".join(error_msgs)
        return result
    except Exception as e:
        return f"코인 시세 조회 중 오류 발생: {e}"

# 한국 주식 (다음금융)
def get_korean_stock_price(query):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "referer": "https://finance.daum.net/",
        }
        search_url = f"https://search.daum.net/search?w=tot&q={query}+주식"
        r = requests.get(search_url, headers=headers, timeout=3)
        soup = BeautifulSoup(r.text, "html.parser")
        link = soup.select_one('a[href*="finance.daum.net/quotes/A"]')
        if not link:
            return f"{query} : 종목 코드를 찾을 수 없습니다."
        href = link["href"]
        code = href.split("/A")[-1].split("?")[0]

        info_url = f"https://finance.daum.net/api/quotes/A{code}?summary=false"
        resp = requests.get(info_url, headers=headers, timeout=3)
        if resp.status_code != 200:
            return f"다음금융 API 접속 실패 (status:{resp.status_code})"
        data = resp.json()
        price = data.get("tradePrice")
        volume = data.get("tradeVolume")  # 거래량(주식 수)
        name = data.get("name", query)
        if not price:
            return f"{query}: 가격 정보를 찾을 수 없습니다."
        return f"[{name}] 주식 시세\n💰 현재 가격 → ₩{price:,}\n📊 거래량 → {volume:,}주"
    except Exception as e:
        return f"한국 주식 정보를 가져올 수 없습니다. 원인: {e}"

def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        volume = stock.info.get("volume", 0)
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,}\n📊 거래량 → {volume:,}주"
    except Exception as e:
        return f"미국 주식 정보를 가져올 수 없습니다. 원인: {e}"

def get_korea_ranking(rise=True):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "referer": "https://finance.daum.net/domestic/features/rise_stocks/kospi",
        }
        fieldName = "changeRate"
        order = "desc" if rise else "asc"
        change = "RISE" if rise else "FALL"
        kospi_url = f"https://finance.daum.net/api/quotes/stocks?exchange=KOSPI&change={change}&page=1&perPage=30&fieldName={fieldName}&order={order}"
        resp_kospi = requests.get(kospi_url, headers=headers, timeout=3)
        if resp_kospi.status_code != 200:
            return f"코스피 정보 접속 실패 (status:{resp_kospi.status_code})"
        items_kospi = resp_kospi.json().get("data", [])
        kospi_list = [
            f"{idx+1}. {item['name']} ({item['symbol']}) {item['changeRate']}%"
            for idx, item in enumerate(items_kospi)
        ]
        kosdaq_url = f"https://finance.daum.net/api/quotes/stocks?exchange=KOSDAQ&change={change}&page=1&perPage=30&fieldName={fieldName}&order={order}"
        resp_kosdaq = requests.get(kosdaq_url, headers=headers, timeout=3)
        if resp_kosdaq.status_code != 200:
            return f"코스닥 정보 접속 실패 (status:{resp_kosdaq.status_code})"
        items_kosdaq = resp_kosdaq.json().get("data", [])
        kosdaq_list = [
            f"{idx+1}. {item['name']} ({item['symbol']}) {item['changeRate']}%"
            for idx, item in enumerate(items_kosdaq)
        ]
        if not kospi_list and not kosdaq_list:
            return "한국주식 정보를 불러오지 못했습니다."
        res = "코스피 상승률\n" if rise else "코스피 하락률\n"
        res += "\n".join(kospi_list)
        res += "\n\n코스닥 상승률\n" if rise else "\n\n코스닥 하락률\n"
        res += "\n".join(kosdaq_list)
        return res
    except Exception as e:
        return f"한국주식 {'상승률' if rise else '하락률'} 정보를 불러오지 못했습니다. 원인: {e}"

def get_us_ranking(rise=True):
    try:
        suffix = "day_gainers" if rise else "day_losers"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
        screener_url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?count=30&scrIds={suffix}"
        resp = requests.get(screener_url, headers=headers, timeout=3)
        if resp.status_code != 200:
            return f"야후파이낸스 정보 접속 실패 (status:{resp.status_code})"
        js = resp.json()
        items = js["finance"]["result"][0]["quotes"]
        top = []
        for idx, item in enumerate(items):
            symbol = item.get("symbol", "")
            name = item.get("shortName", "") or item.get("longName", "")
            rate = item.get("regularMarketChangePercent", 0)
            sign = "+" if rate >= 0 else ""
            top.append(f"{idx+1}. {name} ({symbol}) {sign}{rate:.2f}%")
        if not top:
            return "미국주식 정보를 불러오지 못했습니다."
        return ("미국주식 상승률\n" if rise else "미국주식 하락률\n") + "\n".join(top)
    except Exception as e:
        return f"미국주식 정보를 불러오지 못했습니다. 원인: {e}"

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
        resp = requests.post(url, headers=headers, data=data, timeout=5)
        if resp.status_code != 200:
            return f"경제일정 사이트 접속 실패 (status:{resp.status_code})"
        resp_json = resp.json()
        events = []
        data_list = resp_json.get('data', [])
        if isinstance(data_list, list):
            for item in data_list[:10]:
                date_str = item.get("date", "")
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
        return f"일정 정보를 불러오지 못했습니다. 원인: {e}"

def get_help():
    return (
        "📌 사용 가능한 명령어 목록\n\n"
        "✔️ 코인 시세: !비트코인 / !BTC / !이더리움 등\n"
        "✔️ 한국 주식: @삼성전자\n"
        "✔️ 미국 주식: #TSLA\n"
        "✔️ 한국 주식 상승률: /한국주식 상승률\n"
        "✔️ 한국 주식 하락률: /한국주식 하락률\n"
        "✔️ 미국 주식 상승률: /미국주식 상승률\n"
        "✔️ 미국 주식 하락률: /미국주식 하락률\n"
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
    if utter == "/한국주식 상승률":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korea_ranking(rise=True)}}]}})
    if utter == "/한국주식 하락률":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korea_ranking(rise=False)}}]}})
    if utter == "/미국주식 상승률":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_ranking(rise=True)}}]}})
    if utter == "/미국주식 하락률":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_ranking(rise=False)}}]}})
    if utter.startswith("!"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_coin_price(utter[1:])}}]}})
    if utter.startswith("@"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korean_stock_price(utter[1:])}}]}})
    if utter.startswith("#"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_stock_price(utter[1:])}}]}})
    return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "지원하지 않는 명령어입니다."}}]}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
