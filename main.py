from flask import Flask, request, jsonify
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)

# CoinGecko 코인 한글/영문/심볼/ID 동적 매핑
def get_coingecko_map():
    url = "https://api.coingecko.com/api/v3/coins/list?include_platform=false"
    try:
        data = requests.get(url).json()
    except Exception:
        data = []
    name2id = {}
    symbol2id = {}
    id2name = {}
    for c in data:
        name = c.get("name", "").strip()
        symbol = c.get("symbol", "").upper()
        cid = c.get("id", "")
        # 한글이름 지원 여부 확인 후 매핑
        name2id[name] = cid
        symbol2id[symbol] = cid
        id2name[cid] = name
    return name2id, symbol2id, id2name

def get_coin_id(query):
    # 항상 최신 map을 바로 조회 (캐싱 X)
    name2id, symbol2id, id2name = get_coingecko_map()
    if not query.isascii():
        return name2id.get(query, None)
    query_up = query.upper()
    if query_up in symbol2id:
        return symbol2id[query_up]
    # 영어로 검색 시 id로도 직접 매칭 시도
    if query.lower() in id2name:
        return query.lower()
    return None

# 코인게코 실시간 시세
def get_coingecko_price(coin_id):
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "ids": coin_id}
    try:
        data = requests.get(url, params=params, timeout=5).json()
        if isinstance(data, list) and data:
            return float(data[0].get("current_price", 0)), data[0].get("name", ""), data[0].get("symbol", "").upper()
    except Exception:
        pass
    return None, None, None

# 환율 (네이버, 실패시 1400원)
def get_exchange_rate():
    try:
        url = "https://search.naver.com/p/csearch/content/qapirender.nhn?key=calculator&pkid=141&q=환율&where=m&u1=keb&u3=USD&u4=KRW&u2=1"
        data = requests.get(url, timeout=3).json()
        return float(data["country"][1]["value"].replace(",", ""))
    except Exception:
        return 1400.0

# 업비트 시세
def get_upbit_price(symbol):
    try:
        resp = requests.get(f"https://api.upbit.com/v1/ticker?markets=KRW-{symbol.upper()}", timeout=3)
        if resp.status_code == 200 and resp.json():
            return int(resp.json()[0]["trade_price"])
    except:
        pass
    return None

# 빗썸 시세
def get_bithumb_price(symbol):
    try:
        resp = requests.get(f"https://api.bithumb.com/public/ticker/{symbol.upper()}_KRW", timeout=3)
        data = resp.json()
        if data["status"] == "0000":
            return int(float(data["data"]["closing_price"]))
    except:
        pass
    return None

# 코인원 시세
def get_coinone_price(symbol):
    try:
        resp = requests.get(f"https://api.coinone.co.kr/ticker?currency={symbol.lower()}", timeout=3)
        data = resp.json()
        if data.get("last"):
            return int(float(data["last"]))
    except:
        pass
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

def get_coin_price(query):
    coin_id = get_coin_id(query)
    if not coin_id:
        return f"[{query}] 지원하지 않는 코인입니다."

    global_price, coin_name, symbol = get_coingecko_price(coin_id)
    ex = get_exchange_rate()
    kr_prices = get_korea_prices(symbol or query)

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
    return (
        f"[{symbol}] {coin_name or query} 시세\n\n"
        f"💰 글로벌 가격 → {global_str}\n\n"
        f"🇰🇷 국내 거래소 가격\n"
        f"- 업비트 → ₩{kr_prices['upbit']:,}\n"
        f"- 빗썸 → ₩{kr_prices['bithumb']:,}\n"
        f"- 코인원 → ₩{kr_prices['coinone']:,}\n\n"
        f"🧮 김치 프리미엄 → {kimchi_str}"
    )

# 한국 주식 시세
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
        # 거래대금 크롤링
        deal_amount = soup2.select_one("table.no_info td span.blind").text
        volume_tag = soup2.select("table.no_info td span.blind")
        # 일반적으로 [현재가, 전일대비, 거래량, 거래대금, ...] 구조이므로 거래대금은 4번째 또는 5번째에 위치
        deal_amount = volume_tag[5].text if len(volume_tag) > 5 else "정보없음"
        volume = volume_tag[3].text if len(volume_tag) > 3 else "정보없음"
        return f"[{query}] 주식 시세\n💰 현재 가격 → ₩{price}\n📊 거래대금 → ₩{deal_amount}\n🔄 거래량 → {volume}"
    except Exception:
        return "한국 주식 정보를 가져올 수 없습니다."
# 미국 주식 시세
def get_us_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]
        volume = stock.info.get("volume", 0)
        return f"[{ticker}] 주식 시세\n💰 현재 가격 → ${price:,}\n📊 거래대금 → {volume:,}"
    except Exception:
        return "미국 주식 정보를 가져올 수 없습니다."

# 한국 주식 상승률 TOP30
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

# 미국 주식 상승률 TOP30
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

# 경제일정 (1개월)
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
