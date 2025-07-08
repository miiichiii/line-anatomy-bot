from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    LocationMessage,
    # --- LIFF対応のために以下を追加 ---
    TemplateSendMessage, ButtonsTemplate, URIAction
)
import os, random, math, logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- 環境変数の設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★【要設定 1/1】ご自身のLIFF URLを設定してください ★
# ★ LINE Developersコンソールで取得したLIFF URLを貼り付けます ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
LIFF_URL = "https://liff.line.me/2007710462-pABrKoAv" # 例: "https://liff.line.me/123456-abcdefg"


# --- グローバル設定 ---
CLASS_LAT, CLASS_LNG = 36.015, 140.110  # 教室の中心座標
RADIUS_M = 50                           # 50m以内を「出席可能範囲」とする

# --- 一時的なデータストレージ ---
location_store = {}  # key: user_id, value: {"lat":…, "lng":…, "ts":…}
expected_code = None # 今回のワンタイムコード


def distance(lat1, lng1, lat2, lng2):
    """ 2点間の緯度経度からハーサイン公式を用いて距離（メートル）を計算する """
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.route("/webhook", methods=["POST"])
def webhook():
    """ LINE Platformからのリクエストを処理するメインのエンドポイント """
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    logging.info(f"Request body: {body[:200]}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@app.route("/health")
def health_check():
    """ Renderのヘルスチェック用エンドポイント """
    # このURLにアクセスされたら、正常を示す「OK」を返す
    return "OK", 200


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    """ テキストメッセージを受信したときの処理 """
    global expected_code

    text = event.message.text.strip()
    user_id = event.source.user_id

    # 1) 「出席」というキーワードでプロセスを開始
    if text == "出席":
        expected_code = f"{random.randint(0, 9999):04d}"
        
        # LIFFアプリを開くためのボタン付きメッセージを作成
        buttons_template = ButtonsTemplate(
            title='出席登録',
            text=f"スライドに表示されている4桁コード: {expected_code}\n\n下のボタンを押して、現在地を送信してください。",
            actions=[
                URIAction(
                    label='現在地を送信する', # ボタンに表示されるテキスト
                    uri=LIFF_URL          # ボタンを押したときに開くLIFF URL
                )
            ]
        )
        
        line_bot_api.reply_message(
            event.reply_token,
            TemplateSendMessage(
                alt_text='出席登録を開始します。スマートフォンでご確認ください。',
                template=buttons_template
            )
        )
        return

    # 2) 4桁の数字（コード）が入力された場合の処理
    if text.isdigit() and len(text) == 4:
        if expected_code is None:
            reply = "先に「出席」と入力してからコードを送信してください。"
        elif text != expected_code:
            reply = "❌ コードが正しくありません。もう一度確認してください。"
        else:
            loc = location_store.get(user_id)
            if not loc:
                reply = "❌ まだ位置情報を受け取っていません。「現在地を送信する」ボタンを押してください。"
            else:
                d = distance(loc["lat"], loc["lng"], CLASS_LAT, CLASS_LNG)
                if d <= RADIUS_M:
                    reply = "✅ 出席登録を完了しました。"
                else:
                    reply = f"❌ 教室の範囲外です（約{int(d)}m 離れています）。"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 3) 上記のどの条件にも当てはまらないテキストが送信された場合
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="「出席」と入力すると出席登録が始まります。")
    )


@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    """ (LIFFから送信された)位置情報メッセージを受信したときの処理 """
    user_id = event.source.user_id
    
    # 受信した位置情報を一時ストレージに保存
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
