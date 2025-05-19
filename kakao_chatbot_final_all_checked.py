# 여기에 실제 챗봇의 최종 전체 코드가 들어가야 합니다.
# 테스트 환경에서는 placeholder로 대체합니다.
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": "[테스트 응답] 챗봇이 정상 작동 중입니다."
                    }
                }
            ]
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)