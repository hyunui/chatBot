from http.server import BaseHTTPRequestHandler
import urllib
import requests
from bs4 import BeautifulSoup
import json

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("query", [""])[0]
        if not query:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"query 파라미터 필요")
            return

        try:
            search_url = f"https://m.stock.naver.com/api/search/searchList?keyword={query}"
            r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            js = r.json()
            stock = next((item for item in js.get("stockList", []) if item.get("stockName") == query), None)
            if not stock:
                result = f"{query}: 종목코드 조회 실패"
            else:
                code = stock["itemCode"]
                name = stock["stockName"]

                # 시세 크롤링
                detail_url = f"https://finance.naver.com/item/main.nhn?code={code}"
                r = requests.get(detail_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                soup = BeautifulSoup(r.text, "html.parser")
                price_tag = soup.select_one("p.no_today span.blind")
                change_tag = soup.select_one("p.no_exday span.blind")
                change_sign_tag = soup.select_one("p.no_exday span:nth-of-type(2)")
                volume_tag = soup.select("td.first span.blind")

                if not price_tag or not change_tag or not volume_tag:
                    result = f"{name}: 시세 정보 없음"
                else:
                    price = int(price_tag.text.replace(",", ""))
                    change = float(change_tag.text.replace(",", ""))
                    sign = "+" if "up" in change_sign_tag.get("class", []) else "-"
                    volume = int(volume_tag[1].text.replace(",", "")) if len(volume_tag) > 1 else 0

                    result = (
                        f"[{name}] 주식 시세\n"
                        f"💰 현재 가격 → ₩{price:,} ({sign}{abs(change):.2f}%)\n"
                        f"📊 거래량 → {volume:,}주"
                    )
        except Exception as e:
            result = f"크롤링 오류: {e}"

        self.send_response(200)
        self.end_headers()
        self.wfile.write(result.encode("utf-8"))
