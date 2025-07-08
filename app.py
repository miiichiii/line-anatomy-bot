from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    LocationMessage,
    TemplateSendMessage, ButtonsTemplate, URIAction
)
import os, logging, json
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import math

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- 環境変数とAPIクライアントの設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)

# --- LIFF URL ---
LIFF_URL = "https://liff.line.me/2007710462-pABrKoAv"

# --- 教室の座標と判定範囲 ---
CLASS_LAT, CLASS_LNG = 36.0266, 140.210
RADIUS_M = 300

# --- Google Sheets 設定 ---
SPREADSHEET_NAME = "解剖学出席簿"
SHEET_NAME = "出席簿"

client = None
try:
    creds_json_str = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_json = json.loads(creds_json_str)
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
    client = gspread.authorize(creds)
except Exception as e:
    logging.error(f"Google Sheetsの認証情報読み込みエラー: {e}")

# --- ユーザーの状態を管理する一時ストレージ ---
user_states = {}

# --- 関数定義 ---
def distance(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_student_info(user_id):
    """ シートからユーザーIDを検索し、登録情報（学籍番号と氏名）を返す """
    if not client: return None
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_NAME)
        all_records = sheet.get_all_records()
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        # ★【修正点】必ず「初回登録・出席」の記録を探して、そこから情報を取得する ★
        # ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        for record in reversed(all_records): # 新しい記録から探す方が効率的
            if record.get('LINE User ID') == user_id and record.get('種別') == '初回登録・出席':
                return {"student_id": record.get('学籍番号'), "name": record.get('氏名')}
        
        # 初回登録の記録が見つからなければNoneを返す
        return None
    except Exception as e:
        logging.error(f"学生情報の取得エラー: {e}")
        return None

def record_event(user_id, student_id, name, event_type):
    """ シートにイベント（登録 or 出席）を記録する """
    if not client: return False
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_NAME)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sheet.append_row([now, user_id, student_id, name, event_type])
        logging.info(f"記録成功: {name} ({student_id}) - {event_type}")
        return True
    except Exception as e:
        logging.error(f"記録エラー: {e}")
        return False

def send_liff_button(reply_token, text):
    buttons_template = ButtonsTemplate(
        title='出席登録', text=text,
        actions=[URIAction(label='現在地を送信する', uri=LIFF_URL)]
    )
    line_bot_api.reply_message(reply_token, TemplateSendMessage(alt_text='出席登録を開始します。', template=buttons_template))

# --- Webhookルート ---
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@app.route("/health")
def health_check():
    return "OK", 200

# --- メッセージハンドラ ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    current_state = user_states.get(user_id, {}).get('state')

    if current_state == 'awaiting_student_id':
        user_states[user_id] = {'state': 'awaiting_name', 'student_id': text}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="次に、氏名をフルネームで送信してください。"))
    
    elif current_state == 'awaiting_name':
        user_states[user_id]['name'] = text
        user_states[user_id]['state'] = 'awaiting_location'
        send_liff_button(event.reply_token, "✅ 登録情報を受け付けました。\n最後に、下のボタンから現在地を送信して、初回出席を完了してください。")

    elif text == "出席":
        student_info = get_student_info(user_id)
        if student_info:
            send_liff_button(event.reply_token, "出席登録を開始します。\n下のボタンから現在地を送信してください。")
        else:
            user_states[user_id] = {'state': 'awaiting_student_id'}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="出席登録の前に、初回登録が必要です。\n学籍番号を送信してください。"))
    
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="「出席」と送信してください。"))

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    lat, lng = event.message.latitude, event.message.longitude
    d = distance(lat, lng, CLASS_LAT, LNG)

    if d > RADIUS_M:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"❌ 教室の範囲外です（約{int(d)}m離れています）。"))
        return

    if user_states.get(user_id, {}).get('state') == 'awaiting_location':
        student_id = user_states[user_id]['student_id']
        name = user_states[user_id]['name']
        if record_event(user_id, student_id, name, "初回登録・出席"):
            reply_text = f"✅ {name}さん（{student_id}）の初回登録と出席を完了しました。"
        else:
            reply_text = "❌ 登録・出席処理中にエラーが発生しました。"
        del user_states[user_id]
    else:
        student_info = get_student_info(user_id)
        if not student_info:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ エラー：学生情報が見つかりません。お手数ですが、再度「出席」と送信してください。"))
            return
        
        student_id = student_info["student_id"]
        name = student_info["name"]
        if record_event(user_id, student_id, name, "出席"):
            reply_text = f"✅ {name}さん（{student_id}）の出席を登録しました。"
        else:
            reply_text = "❌ 出席を受け付けましたが、台帳への記録に失敗しました。"
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
