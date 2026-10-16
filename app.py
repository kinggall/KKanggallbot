from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "카카오톡 봇 서버가 실행 중입니다."


@app.route("/keyboard", methods=["POST"])
def keyboard():
    data = request.get_json()

    user_message = data.get("userRequest", {}).get("utterance", "")

    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": f"받은 메시지: {user_message}"
                    }
                }
            ]
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
