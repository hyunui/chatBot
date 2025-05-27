from flask import Flask, request, jsonify
import requests
import yfinance as yf
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import os
import json

def build_stock_code_map():
    """
    네이버 금융에서 전체 상장종목(코스피+코스닥) 코드를 긁어와서
    종목명/심볼/코드 모두를 key로 하여 빠른 검색을 지원하는 dict(code_map)와,
    종목코드 → 종목명 딕셔너리(code_to_korname)도 함께 만든다.
    """
    code_map = {}
    code_to_korname = {}
    urls = [
        "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13",  # 코스피
        "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=14",  # 코스닥
    ]
    for url in urls:
        try:
            df = None
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                import pandas as pd
                import io
                df = pd.read_html(io.BytesIO(r.content), header=0)[0]
                for _, row in df.iterrows():
                    code = str(row['종목코드']).zfill(6)
                    name = str(row['회사명']).strip()
                    code_map[name] = code
                    code_map[code] = code
                    code_to_korname[code] = name
        except Exception:
            pass
    return code_map, code_to_korname

# 실행 시
STOCK_CODE_MAP, CODE_TO_KORNAME = build_stock_code_map()

app = Flask(__name__)

load_dotenv()
CMC_API_KEY = os.environ.get("CMC_API_KEY")
    
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

def get_symbol_by_korean_name_krw_btc(name):
    # KRW마켓 → 없으면 BTC마켓도 추가 탐색
    try:
        url = "https://api.upbit.com/v1/market/all"
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return None, None  # 심볼, 마켓
        markets = r.json()
        krw_symbol = None
        btc_symbol = None
        for m in markets:
            if m["korean_name"] == name:
                if m["market"].startswith("KRW-"):
                    krw_symbol = m["market"].replace("KRW-", "")
                elif m["market"].startswith("BTC-"):
                    btc_symbol = m["market"].replace("BTC-", "")
        if krw_symbol:
            return krw_symbol, "KRW"
        if btc_symbol:
            return btc_symbol, "BTC"
        return None, None
    except Exception as e:
        return None, None

def get_cmc_price_and_change(symbol, convert="KRW"):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
    }
    params = {
        "symbol": symbol.upper(),
        "convert": convert
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        if r.status_code != 200:
            return None, None, f"CMC API 접속 실패 (status:{r.status_code})", None
        data = r.json()
        price = data["data"][symbol.upper()]["quote"][convert]["price"]
        change_24h = data["data"][symbol.upper()]["quote"][convert]["percent_change_24h"]
        remaining = r.headers.get("X-RateLimit-Remaining")
        return price, change_24h, None, remaining
    except Exception as e:
        return None, None, f"CMC API 에러: {e}", None

def get_upbit_price_and_change(symbol, market="KRW"):
    try:
        m = market.upper()
        r = requests.get(f"https://api.upbit.com/v1/ticker?markets={m}-{symbol.upper()}", timeout=3)
        if r.status_code != 200:
            return None, None, f"Upbit API 접속 실패 (status:{r.status_code})"
        data = r.json()[0]
        price = float(data["trade_price"])
        change = float(data.get("signed_change_rate", 0)) * 100
        return price, change, None
    except Exception as e:
        return None, None, f"Upbit 시세 에러: {e}"

def get_bithumb_price_and_change(symbol):
    try:
        r = requests.get(f"https://api.bithumb.com/public/ticker/{symbol.upper()}_KRW", timeout=5)
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
        r = requests.get(url, timeout=5)
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

        upbit_market_type = "KRW"
        if is_korean:
            symbol, upbit_market_type = get_symbol_by_korean_name_krw_btc(query)
            if not symbol:
                return f"[{query}] 코인없음 (업비트에 미상장)"
        else:
            symbol = symbol.upper()

        # 환율
        krw_usd, ex_err = get_exchange_rate()
        if ex_err:
            error_msgs.append(f"환율: {ex_err}")

        # 글로벌(달러) 가격
        global_price, global_change, err1, cmc_remaining = get_cmc_price_and_change(symbol, convert="USD")
        upbit = None
        upbit_change = None
        # 업비트 가격 (마켓 타입 따라 다르게)
        if upbit_market_type == "KRW":
            upbit, upbit_change, err2 = get_upbit_price_and_change(symbol, "KRW")
        elif upbit_market_type == "BTC":
            # BTC마켓 가격을 KRW로 환산
            btc_price, _, _ = get_upbit_price_and_change("BTC", "KRW")
            coin_btc, upbit_change, err2 = get_upbit_price_and_change(symbol, "BTC")
            if coin_btc and btc_price:
                upbit = int(coin_btc * btc_price)
            else:
                upbit = None
        else:
            upbit = None
            err2 = "업비트 가격 없음"

        bithumb, bithumb_change, err3 = get_bithumb_price_and_change(symbol)

        if err1: error_msgs.append(f"글로벌가격: {err1}")
        if upbit is None: error_msgs.append(f"업비트: {err2}")
        if err3: error_msgs.append(f"빗썸: {err3}")

        # 글로벌가격 달러($) 표기 (김치프리미엄 계산은 기존과 동일)
        if global_price:
            global_str = f"${global_price:,.2f}"
            global_rate = f" ({global_change:+.2f}%)"
            if upbit:
                kimchi = ((upbit - global_price * krw_usd) / (global_price * krw_usd)) * 100
                kimchi_str = f"{kimchi:+.2f}%"
            else:
                kimchi_str = "계산불가"
        else:
            global_str = "정보 없음"
            global_rate = ""
            kimchi_str = "계산불가"

        result = f"""[{symbol}] {kr_name} 시세

💰 글로벌 가격 \n → {global_str}{global_rate} \n
🇰🇷 국내 거래소 가격
- 업비트 → {f'₩{upbit:,} ({upbit_change:+.2f}%)' if upbit else '정보 없음'}
- 빗썸 → {f'₩{bithumb:,} ({bithumb_change:+.2f}%)' if bithumb else '정보 없음'}

🧮 김치 프리미엄 → {kimchi_str}"""
        if cmc_remaining:
           result += f"\n\n🔄 CoinMarketCap 남은 호출 횟수: {cmc_remaining}"
        if error_msgs:
            result += "\n\n[접근 실패 정보]\n" + "\n".join(error_msgs)
        return result
    except Exception as e:
        return f"코인 시세 조회 중 오류 발생: {e}"
        
def get_korean_stock_price(query):
    try:
        code = STOCK_CODE_MAP.get(query.strip())
        if not code:
            return f"{query}: 종목코드를 찾을 수 없습니다."

        # 종목코드 → 한글명 매핑 (예: {'005930': '삼성전자'})
        kor_name = CODE_TO_KORNAME.get(code, query.strip())

        symbols = [f"{code}.KS", f"{code}.KQ"]
        info = None
        symbol_used = None
        for symbol in symbols:
            stock = yf.Ticker(symbol)
            info = stock.info
            price = info.get("regularMarketPrice")
            if price is not None:
                symbol_used = symbol
                break

        if info is None or info.get("regularMarketPrice") is None:
            return f"{kor_name}: 시세/변동률 정보 없음 (야후파이낸스 심볼 미일치)"

        price = info.get("regularMarketPrice")
        prev = info.get("regularMarketPreviousClose") or price
        volume = info.get("volume") or 0

        if price is None or prev is None:
            return f"{kor_name}: 시세/변동률 정보 없음"

        change = ((price - prev) / prev * 100) if prev else 0
        sign = "+" if change >= 0 else ""
        return (f"[{kor_name}] 주식 시세\n"
                f"💰 현재 가격 → ₩{int(price):,} ({sign}{change:.2f}%)\n"
                f"📊 거래량 → {int(volume):,}주")
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
    import requests
    from bs4 import BeautifulSoup

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        
        def parse_table(url):
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code != 200:
                return f"접속 실패 (status:{r.status_code})", []

            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table tbody tr")
            result = []
            for idx, tr in enumerate(rows[:30]):
                tds = tr.find_all("td")
                if len(tds) < 5:
                    continue
                a = tds[1].find("a")
                name = a.text.strip()
                code = a["href"].split("=")[-1]
                rate = tds[4].text.strip()
                result.append(f"{idx+1}. {name} ({code}) {rate}")
            return None, result

        # URL 구성
        if rise:
            kospi_url = "https://finance.daum.net/domestic/features/rise_stocks"
            kosdaq_url = "https://finance.daum.net/domestic/features/rise_stocks/kosdaq"
        else:
            kospi_url = "https://finance.daum.net/domestic/features/fall_stocks"
            kosdaq_url = "https://finance.daum.net/domestic/features/fall_stocks/kosdaq"

        kospi_err, kospi_list = parse_table(kospi_url)
        kosdaq_err, kosdaq_list = parse_table(kosdaq_url)

        if kospi_err and kosdaq_err:
            return f"코스피: {kospi_err}\n코스닥: {kosdaq_err}"

        res = "코스피 상승률\n" if rise else "코스피 하락률\n"
        res += "\n".join(kospi_list or ["정보 없음"])
        res += "\n\n코스닥 상승률\n" if rise else "\n\n코스닥 하락률\n"
        res += "\n".join(kosdaq_list or ["정보 없음"])
        return res
    except Exception as e:
        return f"한국주식 {'상승률' if rise else '하락률'} 정보를 불러오는 중 오류 발생: {e}"

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
        "✔️ 명령어 안내: /명령어"
    )

def get_market_indices():
    results = []

    # --- 한국: 코스피/코스닥 (야후파이낸스) ---
    try:
        indices = {
            "코스피": "^KS11",
            "코스닥": "^KQ11",
        }
        kr_lines = []
        for name, ticker in indices.items():
            stock = yf.Ticker(ticker)
            price = stock.info.get("regularMarketPrice")
            change = stock.info.get("regularMarketChangePercent")
            sign = "+" if change is not None and change >= 0 else ""
            if price is not None and change is not None:
                kr_lines.append(f"- {name}: {price:,} ({sign}{change:.2f}%)")
            else:
                kr_lines.append(f"- {name}: 정보없음")
        results.append("🇰🇷 한국\n" + "\n".join(kr_lines))
    except Exception:
        results.append("🇰🇷 한국\n- 코스피/코스닥 정보를 불러올 수 없습니다.")

    # --- 미국 주요지수/선물 ---
    try:
        indices = {
            "다우존스": "^DJI",
            "나스닥": "^IXIC",
            "S&P500": "^GSPC",
            "나스닥선물": "NQ=F",
        }
        us_lines = []
        for name, ticker in indices.items():
            stock = yf.Ticker(ticker)
            price = stock.info.get("regularMarketPrice")
            change = stock.info.get("regularMarketChangePercent")
            sign = "+" if change is not None and change >= 0 else ""
            if price is not None and change is not None:
                us_lines.append(f"- {name}: {price:,} ({sign}{change:.2f}%)")
            else:
                us_lines.append(f"- {name}: 정보없음")
        results.append("🇺🇸 미국\n" + "\n".join(us_lines))
    except Exception:
        results.append("🇺🇸 미국\n- 미국 지수 정보를 불러올 수 없습니다.")

    # --- 일본 니케이225 ---
    try:
        stock = yf.Ticker("^N225")
        price = stock.info.get("regularMarketPrice")
        change = stock.info.get("regularMarketChangePercent")
        sign = "+" if change is not None and change >= 0 else ""
        if price is not None and change is not None:
            results.append(f"🇯🇵 일본\n- 니케이225: {price:,} ({sign}{change:.2f}%)")
        else:
            results.append(f"🇯🇵 일본\n- 니케이225 정보없음")
    except Exception:
        results.append("🇯🇵 일본\n- 니케이225 정보를 불러올 수 없습니다.")

    # --- 중국 상해종합 ---
    try:
        stock = yf.Ticker("000001.SS")
        price = stock.info.get("regularMarketPrice")
        change = stock.info.get("regularMarketChangePercent")
        sign = "+" if change is not None and change >= 0 else ""
        if price is not None and change is not None:
            results.append(f"🇨🇳 중국\n- 상해종합: {price:,} ({sign}{change:.2f}%)")
        else:
            results.append(f"🇨🇳 중국\n- 상해종합 정보없음")
    except Exception:
        results.append("🇨🇳 중국\n- 상해종합 정보를 불러올 수 없습니다.")

    return "📈 주요 금융시장 지수\n\n" + "\n\n".join(results)

# --- Flask 라우터 ---

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()
    if utter == "/지수":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_market_indices()}}]}})
    if utter == "/명령어":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_help()}}]}})
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
