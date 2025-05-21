from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)

def get_coingecko_kor_map():
    url = "https://api.coingecko.com/api/v3/coins/list?include_platform=false"
    r = requests.get(url)
    try:
        data = r.json()
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

def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        data = requests.get(url).json()
        return float(data["country"][1]["value"].replace(",", ""))
    except Exception:
        return 1400.0

def get_binance_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
        data = requests.get(url).json()
        return float(data["price"])
    except:
        return None

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

def get_coin_price(symbol):
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

    result = (
        f"[{symbol.upper()}] {krname} 시세\n\n"
        f"글로벌 가격: {global_str}\n\n"
        f"국내 거래소 가격\n"
        f"- 업비트: {kr_prices['upbit']:,} KRW\n"
        f"- 빗썸: {kr_prices['bithumb']:,} KRW\n"
        f"- 코인원: {kr_prices['coinone']:,} KRW\n\n"
        f"김치 프리미엄: {kimchi_str}"
    )
    return result

@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()
    utter = req.get("userRequest", {}).get("utterance", "").strip()
    if utter.startswith("!"):
        return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": get_coin_price(utter[1:])}}]}})
    return jsonify({"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "[알림] 지원하지 않는 명령어입니다."}}]}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)