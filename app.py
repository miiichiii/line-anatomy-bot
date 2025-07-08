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
import math # mathモジュールをインポート

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
STUDENT_LIST_SHEET_NAME = "学生名簿"
ATTENDANCE_LOG_SHEET_NAME = "出席記録"
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
user_states = {} # key: user_id, value: 'awaiting_student_id'

# --- 関数定義 ---
def distance(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_student_info(user_id):
    """ 学生名簿シートからユーザーIDを検索し、学籍番号と氏名を返す """
    if not client: return None
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(STUDENT_LIST_SHEET_NAME)
        # B列（LINE User ID）を検索
        cell = sheet.find(user_id, in_column=2)
        if cell:
            row_values = sheet.row_values(cell.row)
            return {"student_id": row_values[2], "name": row_values[3]} # C列:学籍番号, D列:氏名
        return None
    except gspread.exceptions.WorksheetNotFound:
        logging.error(f"シート '{STUDENT_LIST_SHEET_NAME}' が見つかりません。")
        return None
    except Exception as e:
        logging.error(f"学生情報の取得エラー: {e}")
        return None

def register_student(user_id, student_id):
    """ 学生を名簿に登録する """
    if not client: return False
    try:
        profile = line_bot_api.get_profile(user_id)
        user_name = profile.display_name
        sheet = client.open(SPREADSHEET_NAME).worksheet(STUDENT_LIST_SHEET_NAME)
        
        # 既存登録チェック
        if sheet.find(user_id, in_column=2):
            return "already_registered"

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sheet.append_row([now, user_id, student_id, user_name])
        logging.info(f"学生登録成功: {user_name} ({student_id})")
        return "success"
    except Exception as e:
        logging.error(f"学生登録エラー: {e}")
        return "error"

def record_attendance(student_id, name):
    """ 出席記録シートに出席情報を記録する """
    if not client: return False
    try:
        sheet = client.open(SPREADSHEET_NAME).worksheet(ATTENDANCE_LOG_SHEET_NAME)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sheet.append_row([now, student_id, name, "出席"])
        return True
    except gspread.exceptions.WorksheetNotFound:
        logging.error(f"シート '{ATTENDANCE_LOG_SHEET_NAME}' が見つかりません。")
        return False
    except Exception as e:
        logging.error(f"出席記録エラー: {e}")
        return False

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
    """ テキストメッセージの処理 """
    user_id = event.source.user_id
    text = event.message.text.strip()

    # 登録フローの処理
    if user_states.get(user_id) == 'awaiting_student_id':
        student_id = text
        result = register_student(user_id, student_id)
        if result == "success":
            reply_text = "✅ 登録が完了しました。\n「出席」と送信して出席登録を開始してください。"
        elif result == "already_registered":
            reply_text = "💡 このLINEアカウントは既に登録済みです。"
        else:
            reply_text = "❌ 登録中にエラーが発生しました。時間をおいて再度お試しください。"
        del user_states[user_id] # 状態をリセット
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 通常コマンドの処理
    if text == "出席":
        buttons_template = ButtonsTemplate(
            title='出席登録', text="下のボタンを押して、現在地を送信してください。",
            actions=[URIAction(label='現在地を送信する', uri=LIFF_URL)]
        )
        line_bot_api.reply_message(event.reply_token, TemplateSendMessage(alt_text='出席登録を開始します。', template=buttons_template))
    
    elif text == "登録":
        user_states[user_id] = 'awaiting_student_id'
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="学籍番号を送信してください。"))

    else:
        reply_text = "「出席」または「登録」と送信してください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    """ 位置情報メッセージの処理 """
    user_id = event.source.user_id
    
    student_info = get_student_info(user_id)
    if not student_info:
        reply_text = "⚠️ 学籍番号が未登録です。\n「登録」と送信して、先に学籍番号を登録してください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    lat, lng = event.message.latitude, event.message.longitude
    d = distance(lat, lng, CLASS_LAT, CLASS_LNG)
    
    if d <= RADIUS_M:
        student_id = student_info["student_id"]
        name = student_info["name"]
        if record_attendance(student_id, name):
            reply_text = f"✅ {name}さん（{student_id}）の出席を登録しました。"
        else:
            reply_text = "❌ 出席を受け付けましたが、台帳への記録に失敗しました。管理者に連絡してください。"
    else:
        reply_text = f"❌ 教室の範囲外です（約{int(d)}m離れています）。"
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
