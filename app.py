from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import random

app = Flask(__name__)

# 環境変数から取得（LINE Developers で発行された値）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

ANATOMY_QUESTIONS = [
    "鎖骨の外側端はどの骨と関節を形成しますか？",
    "脳神経はいくつありますか？",
    "大腿四頭筋を構成する筋肉を4つ挙げてください。",
]

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    if "こんにちは" in user_message:
        reply_text = "こんにちは、今日も解剖がんばろう！"
    elif user_message.strip() == "解剖の問題":
        reply_text = random.choice(ANATOMY_QUESTIONS)
    else:
        reply_text = "ごめんね、まだその言葉は覚えてないの💦"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
