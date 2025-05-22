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
    if not UPBIT_MAP:
        UPBIT_MAP = get_upbit_symbol_map()
    return UPBIT_MAP.get(name)

# 바이낸스 글로벌 시세 (GET 방식)
def get_binance_price_and_change(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}USDT"
        r = requests.get(url, timeout=3)
        if r.status_code == 451:
            return None, None, "Binance API 국가 차단 (451)"
        if r.status_code != 200:
            return None, None, f"Binance API 접속 실패 (status:{r.status_code})"
        data = r.json()
        price = float(data["lastPrice"])
        change = float(data["priceChangePercent"])
        return price, change, None
    except Exception as e:
        return None, None, f"Binance API 에러: {e}"

def get_upbit_price_and_change(symbol):
    try:
        r = requests.get(f"https://api.upbit.com/v1/ticker?markets=KRW-{symbol.upper()}", timeout=3)
        if r.status_code != 200:
            return None, None, f"Upbit API 접속 실패 (status:{r.status_code})"
        data = r.json()[0]
        price = int(data["trade_price"])
        change = float(data.get("signed_change_rate", 0)) * 100
        return price, change, None
    except Exception as e:
        return None, None, f"Upbit 시세 에러: {e}"

def get_bithumb_price_and_change(symbol):
    try:
        r = requests.get(f"https://api.bithumb.com/public/ticker/{symbol.upper()}_KRW", timeout=3)
        if r.status_code != 200:
            return None, None, f"Bithumb API 접속 실패 (status:{r.status_code})"
        data = r.json()
        if data["status"] == "0000":
            price = int(float(data["data"]["closing_price"]))
            change = float(data["data"].get("fluctate_rate_24H", 0))
            return price, change, None
        else:
            return None, None, f"Bithumb 데이터 없음"
    except Exception as e:
        return None, None, f"Bithumb 시세 에러: {e}"

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
        query = query.strip()
        is_korean = not query.isascii()
        symbol = query.upper()
        kr_name = query
        error_msgs = []

        # 한글이면 업비트에서 심볼 변환
        if is_korean:
            symbol = get_symbol_by_korean_name(query)
            if not symbol:
                return f"[{query}] 코인없음 (국내 거래소에 존재하지 않음)"
        else:
            symbol = symbol.upper()

        # 바이낸스에서 시세 및 변동률 GET
        global_price, global_change, err1 = get_binance_price_and_change(symbol)
        upbit, upbit_change, err2 = get_upbit_price_and_change(symbol)
        bithumb, bithumb_change, err3 = get_bithumb_price_and_change(symbol)
        ex, err4 = get_exchange_rate()

        if err1: error_msgs.append(f"글로벌가격: {err1}")
        if err2: error_msgs.append(f"업비트: {err2}")
        if err3: error_msgs.append(f"빗썸: {err3}")
        if err4: error_msgs.append(f"환율: {err4}")

        if not global_price:
            global_str = "정보 없음"
            global_rate = ""
            kimchi_str = "계산불가"
        else:
            global_str = f"${global_price:,.2f}"
            global_rate = f" ({global_change:+.2f}%)"
            if upbit:
                kimchi = ((upbit - global_price * ex) / (global_price * ex)) * 100
                kimchi_str = f"{kimchi:+.2f}%"
            else:
                kimchi_str = "계산불가"

        result = f"""[{symbol}] {kr_name} 시세

💰 글로벌 가격 → {global_str}{global_rate}
🇰🇷 국내 거래소 가격
- 업비트 → {f'₩{upbit:,} ({upbit_change:+.2f}%)' if upbit else '정보 없음'}
- 빗썸 → {f'₩{bithumb:,} ({bithumb_change:+.2f}%)' if bithumb else '정보 없음'}

🧮 김치 프리미엄 → {kimchi_str}"""

        if error_msgs:
            result += "\n\n[접근 실패 정보]\n" + "\n".join(error_msgs)
        return result
    except Exception as e:
        return f"코인 시세 조회 중 오류 발생: {e}"

def get_korean_stock_price(query):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        # 다음금융 종목 검색 API
        search_url = f"https://finance.daum.net/api/search?q={query}"
        r = requests.get(search_url, headers=headers, timeout=3)
        js = r.json()
        # 첫 종목코드 추출
        items = js.get("searchCommon", [])
        if not items:
            return f"{query} : 종목코드를 찾을 수 없습니다."
        code = items[0]["code"]
        name = items[0]["name"]
        # 종목 상세 시세
        info_url = f"https://finance.daum.net/api/quotes/A{code}?summary=false"
        r2 = requests.get(info_url, headers=headers, timeout=3)
        data = r2.json()
        price = data.get("tradePrice")
        change = data.get("changeRate")
        volume = data.get("tradeVolume")
        sign = "+" if change and change >= 0 else ""
        if not price:
            return f"{name}: 시세 정보를 찾을 수 없습니다."
        return f"[{name}] 주식 시세\n💰 현재 가격 → ₩{price:,} ({sign}{change:.2f}%)\n📊 거래량 → {volume:,}주"
    except Exception as e:
        return f"한국 주식 정보를 가져올 수 없습니다. 원인: {e}"

def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        prev = stock.info.get("regularMarketPreviousClose", 0)
        volume = stock.info.get("volume", 0)
        if price is None or prev is None:
            return f"{ticker}: 시세/변동률 정보 없음"
        change = ((price - prev) / prev * 100) if prev else 0
        sign = "+" if change >= 0 else ""
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,} ({sign}{change:.2f}%)\n📊 거래량 → {volume:,}주"
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
        url = "https://kr.investing.com/economic-calendar/"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code != 200:
            return f"경제일정 사이트 접속 실패 (status:{r.status_code})"

        soup = BeautifulSoup(r.text, "html.parser")
        events = []

        rows = soup.select("tr.js-event-item")
        today = datetime.now()
        this_month = today.month

        for row in rows:
            # 날짜 정보
            date_text = row.get("data-event-datetime", "")
            if not date_text:
                continue

            event_dt = datetime.strptime(date_text, "%Y-%m-%d %H:%M:%S")
            if event_dt.month != this_month:
                continue  # 이번 달 이벤트만 추출

            # 중요도 확인 (불꽃 아이콘 개수)
            impact = len(row.select(".grayFullBullishIcon"))
            if impact < 3:
                continue  # 중요도 3 미만 이벤트는 제외

            country = row.select_one(".flagCur span").get_text(strip=True)
            event = row.select_one(".event").get_text(strip=True)
            time_str = event_dt.strftime("%m월 %d일")
            events.append(f"{time_str} [{country}] {event} (★★★)")

            if len(events) >= 10:
                break

        if not events:
            return "이번 달 중요 경제일정을 찾을 수 없습니다."

        return "📅 이번 달 중요 경제 일정 (★★★ 이상)\n\n" + "\n".join(events)

    except Exception as e:
        return f"경제일정 정보를 불러오지 못했습니다. 원인: {e}"

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
        "✔️ 주요 금융시장 지수: /지수\n"
        "✔️ 일정: /일정\n"
        "✔️ 명령어 안내: /명령어"
    )

def get_market_indices():
    try:
        results = []

        # 한국 코스피/코스닥 (네이버)
        try:
            url = "https://finance.naver.com/sise/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            r = requests.get(url, headers=headers, timeout=3)
            soup = BeautifulSoup(r.text, "html.parser")
            kospi = soup.select_one("#KOSPI_now").text.strip()
            kospi_diff = soup.select_one("#KOSPI_change").text.strip()
            kospi_rate = soup.select_one("#KOSPI_rate").text.strip()
            kosdaq = soup.select_one("#KOSDAQ_now").text.strip()
            kosdaq_diff = soup.select_one("#KOSDAQ_change").text.strip()
            kosdaq_rate = soup.select_one("#KOSDAQ_rate").text.strip()
            results.append(f"🇰🇷 한국\n- 코스피: {kospi} ({kospi_rate})\n- 코스닥: {kosdaq} ({kosdaq_rate})")
        except Exception as e:
            results.append("🇰🇷 한국\n- 코스피/코스닥 정보를 불러올 수 없습니다.")

        # 미국 (야후파이낸스)
        try:
            indices = {
                "다우존스": "^DJI",
                "나스닥": "^IXIC",
                "S&P500": "^GSPC"
            }
            us_lines = []
            for name, ticker in indices.items():
                stock = yf.Ticker(ticker)
                price = stock.info["regularMarketPrice"]
                change = stock.info["regularMarketChangePercent"]
                sign = "+" if change >= 0 else ""
                us_lines.append(f"- {name}: {price:,} ({sign}{change:.2f}%)")
            results.append("🇺🇸 미국\n" + "\n".join(us_lines))
        except Exception:
            results.append("🇺🇸 미국\n- 미국 지수 정보를 불러올 수 없습니다.")

        # 일본 니케이225 (야후파이낸스)
        try:
            stock = yf.Ticker("^N225")
            price = stock.info["regularMarketPrice"]
            change = stock.info["regularMarketChangePercent"]
            sign = "+" if change >= 0 else ""
            results.append(f"🇯🇵 일본\n- 니케이225: {price:,} ({sign}{change:.2f}%)")
        except Exception:
            results.append("🇯🇵 일본\n- 니케이225 정보를 불러올 수 없습니다.")

        # 중국 상해종합 (야후파이낸스)
        try:
            stock = yf.Ticker("000001.SS")
            price = stock.info["regularMarketPrice"]
            change = stock.info["regularMarketChangePercent"]
            sign = "+" if change >= 0 else ""
            results.append(f"🇨🇳 중국\n- 상해종합: {price:,} ({sign}{change:.2f}%)")
        except Exception:
            results.append("🇨🇳 중국\n- 상해종합 정보를 불러올 수 없습니다.")

        return "📈 주요 금융시장 지수\n\n" + "\n\n".join(results)
    except Exception as e:
        return f"지수 정보를 불러오지 못했습니다. 원인: {e}"


@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()
    if utter == "/지수":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_market_indices()}}]}})
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
