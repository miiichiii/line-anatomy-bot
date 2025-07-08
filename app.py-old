from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import random
import logging

app = Flask(__name__)

#--- ロギング設定 -------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

#--- LINE Developers で発行した環境変数 --------------------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN / LINE_CHANNEL_SECRET が設定されていません。")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)

#--- 出題用クイズ -------------------------------------------------------------
ANATOMY_QUESTIONS = [
    "鎖骨の外側端はどの骨と関節を形成しますか？",
    "脳神経はいくつありますか？",
    "大腿四頭筋を構成する筋肉を4つ挙げてください。",
]

#===========================================================================
#  ✓ 追加: Render のルート URL ("/") にアクセスしたとき 200 を返す
#===========================================================================
@app.route("/", methods=["GET"])
def index():
    """Health-check 兼 起動確認エンドポイント。ブラウザで開けば 200 OK が返る。"""
    return "LINE Anatomy Bot is running.", 200

# optional: Render のヘルスチェック用 (JSON)
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200

#===========================================================================
#  Webhook エンドポイント (LINE からの POST)
#===========================================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    logger.info(f"[Webhook] body = {body[:200]} ...")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK", 200

#---------------------------------------------------------------------------
#  受信メッセージのハンドラ
#---------------------------------------------------------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()

    if "こんにちは" in user_message:
        reply_text = "こんちくは、今日も解剖がんばろう！"
    elif user_message == "解剖の問題":
        reply_text = random.choice(ANATOMY_QUESTIONS)
    else:
        reply_text = "ごめんね、まだその言葉は覚えてないの💦"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

#---------------------------------------------------------------------------
#  ローカル/本番 起動エントリ
#---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Render では debug=False 固定。ホストは 0.0.0.0。
    app.run(host="0.0.0.0", port=port, debug=False)
