from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    LocationMessage,
    QuickReply, QuickReplyButton, LocationAction
)
import os, random, math, logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler       = WebhookHandler(LINE_CHANNEL_SECRET)

# ─── グローバル設定 ───
CLASS_LAT, CLASS_LNG = 36.015, 140.110  # 教室中心
RADIUS_M = 50                          # 50m以内を「OK」とする
# 一時的ストレージ（実運用ではDBやSheetsで管理）
location_store = {}    # userId → {"lat":…, "lng":…, "ts":…}
expected_code = None   # 今回のワンタイムコード


def distance(lat1, lng1, lat2, lng2):
    # ハーサイン距離でメートル単位を帰す
    R=6371000
    φ1,φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2-lat1)
    dλ = math.radians(lng2-lng1)
    a = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R*2*math.atan2(math.sqrt(a), math.sqrt(1-a))


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    logging.info(f"Request body: {body[:200]}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    global expected_code

    text = event.message.text.strip()
    user_id = event.source.userId

    # 1) 「出席」のトリガー
    if text == "出席":
        # ワンタイムコード生成
        expected_code = f"{random.randint(0,9999):04d}"
        # QuickReplyで位置送信ボタンを表示
        qr = QuickReply(items=[
            QuickReplyButton(action=LocationAction(label="現在地を送信"))
        ])
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"📌 出席登録を開始します。\n"
                     f"スライドに表示されている4桁コード: {expected_code}\n"
                     "まずは下のボタンから現在地を送信してください。",
                quick_reply=qr
            )
        )
        return

    # 3) コード入力フェーズ
    if text.isdigit() and len(text) == 4:
        if expected_code is None:
            reply = "先に「出席」と入力してからコードを送信してください。"
        elif text != expected_code:
            reply = "❌ コードが正しくありません。もう一度確認してください。"
        else:
            loc = location_store.get(user_id)
            if not loc:
                reply = "❌ まだ位置情報を受け取っていません。位置情報を先に送信してください。"
            else:
                d = distance(loc["lat"], loc["lng"], CLASS_LAT, CLASS_LNG)
                if d <= RADIUS_M:
                    # --- ここで実際の出席記録処理（DB/Sheets等）を呼ぶ ---
                    reply = "✅ 出席登録を完了しました。"
                else:
                    reply = f"❌ 教室の範囲外です（{int(d)}m 離れています）。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # それ以外のテキスト
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="「出席」と入力すると出席登録が始まります。")
    )


@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.userId
    loc = {
        "lat": event.message.latitude,
        "lng": event.message.longitude,
        "ts": event.timestamp
    }
    location_store[user_id] = loc
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="📍 位置情報を受け取りました。次にスライドの4桁コードを送信してください。")
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
