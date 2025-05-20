from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup

app = Flask(__name__)

# 환율
def get_exchange_rate():
    try:
        r = requests.get("https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1")
        data = r.json()
        return float(data["country"][1]["value"].replace(",", ""))
    except:
        return 1350.0

# Binance 가격
def get_binance_price(symbol):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT")
        return float(r.json()["price"])
    except:
        return None

# 코인 시세
def get_coin_price(symbol):
    binance = get_binance_price(symbol)
    exchange = get_exchange_rate()
    upbit = 136520000
    bithumb = 136430000
    coinone = 136440000
    if binance:
        kimchi = ((upbit - binance * exchange) / (binance * exchange)) * 100
        return f"[{symbol.upper()}] {symbol.upper()} 시세\n\n💰 글로벌 가격 → ${binance:,.2f}\n\n🇰🇷 국내 거래소 가격\n- 업비트 → ₩{upbit:,}\n- 빗썸 → ₩{bithumb:,}\n- 코인원 → ₩{coinone:,}\n\n🧮 김치 프리미엄 → +{kimchi:.2f}%"
    else:
        return "[오류] 글로벌 가격을 가져올 수 없습니다."

# 한국주식
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
        return f"[{query}] 주식 시세\n💰 현재 가격 → ₩{price}\n📊 거래대금 → (지원예정)"
    except:
        return "한국 주식 정보를 가져올 수 없습니다."

# 미국주식
def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        volume = stock.info.get("volume", 0)
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,}\n📊 거래대금 → {volume:,}"
    except:
        return "미국 주식 정보를 가져올 수 없습니다."

# 명령어 안내
def get_help():
    return (
        "📌 사용 가능한 명령어 목록\n\n"
        "✔️ 코인 시세: !BTC / !ETH\n"
        "✔️ 한국 주식: @삼성전자\n"
        "✔️ 미국 주식: #TSLA\n"
        "✔️ 한국 주식 TOP30: /한국주식 TOP30\n"
        "✔️ 미국 주식 TOP30: /미국주식 TOP30\n"
        "✔️ 코인 차트: !차트 BTC\n"
        "✔️ 한국 차트: @차트 삼성전자\n"
        "✔️ 미국 차트: #차트 TSLA\n"
        "✔️ 네이버 검색: /네이버 키워드\n"
        "✔️ 구글 검색: /구글 키워드\n"
        "✔️ 경제 일정: /일정"
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()

    if utter.startswith("!차트") or utter.startswith("@차트") or utter.startswith("#차트"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "[차트 분석 기능 준비 중]"}}]}})

    if utter.startswith("!"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_coin_price(utter[1:])}}]}})

    if utter.startswith("@"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_korean_stock_price(utter[1:])}}]}})

    if utter.startswith("#"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_us_stock_price(utter[1:])}}]}})

    if utter == "/명령어":
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_help()}}]}})

    return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "[알림] 지원하지 않는 명령어입니다."}}]}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)