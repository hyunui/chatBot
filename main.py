from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup

try:
    print("====== 서버 시작! ======")
    # 이하 기존 코드
app = Flask(__name__)

# 1. 업비트 코인명-심볼 자동매핑
def get_upbit_korean_map():
    url = "https://api.upbit.com/v1/market/all"
    resp = requests.get(url)
    markets = resp.json()
    kr_map = {}
    for m in markets:
        if m["market"].startswith("KRW-"):
            symbol = m["market"].replace("KRW-", "")
            kr_name = m["korean_name"].strip()
            kr_map[kr_name] = symbol
            kr_map[symbol] = kr_name
    return kr_map

# 2. 빗썸 코인명-심볼 자동매핑 (홈페이지 파싱)
def get_bithumb_korean_map():
    try:
        resp2 = requests.get("https://www.bithumb.com/")
        soup = BeautifulSoup(resp2.text, "html.parser")
        kr_map = {}
        for tr in soup.select("table[class*=coin_table] tbody tr"):
            try:
                name = tr.select_one("p.coin_list_coin").text.strip()
                symbol = tr.select_one("strong.tit_coin").text.strip()
                kr_map[name] = symbol
                kr_map[symbol] = name
            except:
                continue
        return kr_map
    except:
        return {}

# 3. 코인원 코인명-심볼 자동매핑 (홈페이지 파싱)
def get_coinone_korean_map():
    try:
        resp2 = requests.get("https://coinone.co.kr/exchange/trade/krw/all")
        soup = BeautifulSoup(resp2.text, "html.parser")
        kr_map = {}
        for item in soup.select("div.coin-info"):
            try:
                name = item.select_one("strong.coin-name").text.strip()
                symbol = item.select_one("span.coin-symbol").text.strip()
                kr_map[name] = symbol
                kr_map[symbol] = name
            except:
                continue
        return kr_map
    except:
        return {}

# 서버 시작 시 한 번씩 캐싱
print("업비트 매핑시도")
UPBIT_KR_MAP = get_upbit_korean_map()
print("빗썸 매핑시도")
BITHUMB_KR_MAP = get_bithumb_korean_map()
print("코인원 매핑시도")
COINONE_KR_MAP = get_coinone_korean_map()

def kr_to_symbol(name):
    for m in [UPBIT_KR_MAP, BITHUMB_KR_MAP, COINONE_KR_MAP]:
        if name in m:
            return m[name]
    return name.upper()

def symbol_to_kr(symbol):
    for m in [UPBIT_KR_MAP, BITHUMB_KR_MAP, COINONE_KR_MAP]:
        if symbol.upper() in m:
            return m[symbol.upper()]
    return symbol.upper()

# 환율
def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        data = requests.get(url).json()
        return float(data["country"][1]["value"].replace(",", ""))
    except Exception:
        return 1400.0

# Binance
def get_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
        data = requests.get(url).json()
        return float(data["price"])
    except Exception:
        return None

# 업비트
def get_upbit_price(symbol):
    try:
        symbol = symbol.upper()
        resp = requests.get("https://api.upbit.com/v1/ticker?markets=KRW-" + symbol)
        if resp.status_code == 200 and resp.json():
            return int(resp.json()[0]["trade_price"])
    except:
        return None

# 빗썸
def get_bithumb_price(symbol):
    try:
        symbol = symbol.upper()
        resp = requests.get(f"https://api.bithumb.com/public/ticker/{symbol}_KRW")
        data = resp.json()
        if data["status"] == "0000":
            return int(float(data["data"]["closing_price"]))
    except:
        return None

# 코인원
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
    u = get_upbit_price(symbol)
    b = get_bithumb_price(symbol)
    c = get_coinone_price(symbol)
    return {
        "upbit": u if u else 0,
        "bithumb": b if b else 0,
        "coinone": c if c else 0
    }

def get_coin_price(symbol):
    # 한글 자동 매핑
    if not symbol.isascii():
        symbol = kr_to_symbol(symbol)
    krname = symbol_to_kr(symbol)
    global_price = get_binance_price(symbol)
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
    return f"""[{symbol.upper()}] {krname} 시세

💰 글로벌 가격 → {global_str}

🇰🇷 국내 거래소 가격
- 업비트 → ₩{kr_prices["upbit"]:,}
- 빗썸 → ₩{kr_prices["bithumb"]:,}
- 코인원 → ₩{kr_prices["coinone"]:,}

🧮 김치 프리미엄 → {kimchi_str}
"""

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

def get_help():
    return (
        "📌 사용 가능한 명령어 목록\n\n"
        "✔️ 코인 시세: !BTC / !비트코인 / !ETH / !이더리움 등 (한글/영문 모두)\n"
        "✔️ 한국 주식: @삼성전자\n"
        "✔️ 미국 주식: #TSLA\n"
        "✔️ 한국 주식 TOP30: /한국주식 TOP30\n"
        "✔️ 미국 주식 TOP30: /미국주식 TOP30\n"
        "✔️ 차트 분석: !차트 BTC / @차트 삼성전자 / #차트 TSLA\n"
        "✔️ 명령어 안내: /명령어"
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()

    if utter == "/명령어":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_help()}}]}})

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

except Exception as e:
    print("초기화 중 에러 발생:", e)
