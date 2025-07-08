from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    LocationMessage,
    TemplateSendMessage, ButtonsTemplate, URIAction
)
import os, random, math, logging, json
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- 環境変数の設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)

# --- LIFF URLの設定 ---
LIFF_URL = "https://liff.line.me/2007710462-pABrKoAv" # 先生のLIFF URL

# --- 教室の座標と判定範囲の設定 ---
CLASS_LAT, CLASS_LNG = 36.0266, 140.210  # 教室の中心座標
RADIUS_M = 300                          # 300m以内を「出席可能範囲」とする

# --- Google Sheetsの設定 ---
# Renderの環境変数から認証情報を読み込む
try:
    creds_json_str = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_json = json.loads(creds_json_str)
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
    # 記録したいGoogleスプレッドシートの名前を指定
    SPREADSHEET_NAME = "解剖学出席簿" 
except Exception as e:
    logging.error(f"Google Sheetsの認証情報読み込みエラー: {e}")
    client = None

def distance(lat1, lng1, lat2, lng2):
    """ 2点間の緯度経度から距離（メートル）を計算する """
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def record_attendance_to_sheet(user_id, user_name):
    """ Googleスプレッドシートに出席情報を記録する """
    if not client:
        logging.error("Google Sheets clientが初期化されていません。")
        return False
    try:
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.sheet1 # 最初のシートに記録
        
        # タイムスタンプを日本時間でフォーマット
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # スプレッドシートに追記
        worksheet.append_row([now, user_id, user_name, "出席"])
        logging.info(f"記録成功: {user_name} ({user_id})")
        return True
    except Exception as e:
        logging.error(f"スプレッドシートへの書き込みエラー: {e}")
        return False

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@app.route("/health")
def health_check():
    return "OK", 200

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    """ テキストメッセージを受信したときの処理 """
    text = event.message.text.strip()
    if text == "出席":
        buttons_template = ButtonsTemplate(
            title='出席登録',
            text="下のボタンを押して、現在地を送信してください。",
            actions=[URIAction(label='現在地を送信する', uri=LIFF_URL)]
        )
        line_bot_api.reply_message(
            event.reply_token,
            TemplateSendMessage(
                alt_text='出席登録を開始します。', template=buttons_template
            )
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="「出席」と入力すると出席登録が始まります。")
        )

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    """ 位置情報メッセージを受信したときの処理 """
    user_id = event.source.user_id
    lat = event.message.latitude
    lng = event.message.longitude
    
    # 教室からの距離を計算
    d = distance(lat, lng, CLASS_LAT, CLASS_LNG)
    
    if d <= RADIUS_M:
        try:
            # ユーザーのLINEプロフィール情報を取得
            profile = line_bot_api.get_profile(user_id)
            user_name = profile.display_name
            
            # スプレッドシートに記録
            if record_attendance_to_sheet(user_id, user_name):
                reply_text = f"✅ {user_name}さんの出席を登録しました。"
            else:
                reply_text = "✅ 出席を受け付けましたが、台帳への記録に失敗しました。管理者に連絡してください。"

        except Exception as e:
            logging.error(f"プロフィール取得または記録処理のエラー: {e}")
            reply_text = "✅ 出席を受け付けましたが、処理中にエラーが発生しました。"
    else:
        reply_text = f"❌ 教室の範囲外です（約{int(d)}m離れています）。教室棟の近くで再度お試しください。"
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
