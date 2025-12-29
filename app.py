from flask import Flask, request, abort, render_template, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    LocationMessage,
    TemplateSendMessage, ButtonsTemplate, URIAction
)
import os, logging, json, math
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- 環境変数とAPIクライアントの設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
EXPORT_SECRET_KEY         = os.environ.get("EXPORT_SECRET_KEY", "default_secret_key")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)

# --- Firebase Admin SDKの初期化 ---
try:
    creds_json_str = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_json = json.loads(creds_json_str)
    cred = credentials.Certificate(creds_json)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    logging.error(f"Firestoreの初期化エラー: {e}")
    db = None

# --- LIFF URL ---
LIFF_URL = "https://liff.line.me/2007710462-pABrKoAv"

# --- 教室の座標と判定範囲 ---
CLASS_LAT, CLASS_LNG = 36.0266, 140.210
RADIUS_M = 300

# --- ユーザーの状態を管理 ---
user_states = {}

# --- 関数定義 (省略... 変更なし) ---
def distance(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_student_info(user_id):
    if not db: return None
    try:
        doc_ref = db.collection('students').document(user_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logging.error(f"Firestoreからの学生情報取得エラー: {e}")
        return None

def record_attendance(user_id, student_info):
    if not db: return False
    try:
        doc_ref = db.collection('attendance_logs').document()
        doc_ref.set({
            'user_id': user_id,
            'student_id': student_info.get('student_id'),
            'name': student_info.get('name'),
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        logging.error(f"Firestoreへの出席記録エラー: {e}")
        return False

def register_and_attend(user_id, student_id, name):
    if not db: return False
    try:
        batch = db.batch()
        student_ref = db.collection('students').document(user_id)
        batch.set(student_ref, {
            'student_id': student_id,
            'name': name,
            'registered_at': firestore.SERVER_TIMESTAMP
        })
        log_ref = db.collection('attendance_logs').document()
        batch.set(log_ref, {
            'user_id': user_id,
            'student_id': student_id,
            'name': name,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'is_first_time': True
        })
        batch.commit()
        return True
    except Exception as e:
        logging.error(f"Firestoreへの初回登録・出席エラー: {e}")
        return False

def send_liff_button(reply_token, text):
    buttons_template = ButtonsTemplate(
        title='出席登録', text=text,
        actions=[URIAction(label='現在地を送信する', uri=LIFF_URL)]
    )
    line_bot_api.reply_message(reply_token, TemplateSendMessage(alt_text='出席登録を開始します。', template=buttons_template))

def fetch_attendance_logs(date_str):
    if not db:
        raise RuntimeError("データベース接続エラー")

    # JSTタイムゾーンを定義
    jst = timezone(timedelta(hours=9))

    # 指定された日付の開始時刻 (JST)
    start_dt_jst = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=jst)

    # 指定された日付の終了時刻 (JST)
    end_dt_jst = start_dt_jst + timedelta(days=1)

    # FirestoreはUTCでクエリをかけるため、UTCに変換
    start_dt_utc = start_dt_jst.astimezone(timezone.utc)
    end_dt_utc = end_dt_jst.astimezone(timezone.utc)

    # Firestoreからデータをクエリ
    logs_ref = db.collection('attendance_logs')
    query = logs_ref.where('timestamp', '>=', start_dt_utc).where('timestamp', '<', end_dt_utc).order_by('timestamp')

    docs = query.stream()

    results = []
    for doc in docs:
        log = doc.to_dict()
        ts = log.get('timestamp')
        if ts:
            # 表示用にJSTの文字列に変換
            timestamp_str = ts.astimezone(jst).strftime('%H:%M:%S')
        else:
            timestamp_str = "N/A"

        results.append({
            "log_id": doc.id,
            "timestamp": timestamp_str,
            "student_id": log.get('student_id', 'N/A'),
            "name": log.get('name', 'N/A'),
            "is_first_time": log.get('is_first_time', False),
            "user_id": log.get('user_id'),
            "course": log.get('course')
        })

    return results

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

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★【新規追加】ビューアページを表示するためのルート ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
@app.route("/viewer")
def viewer():
    return render_template('viewer.html')

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★【新規追加】日付ごとの出席データをFirestoreから取得するためのAPIルート ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
@app.route("/get_attendance")
def get_attendance():
    secret_key = request.args.get('key')
    if secret_key != EXPORT_SECRET_KEY:
        return jsonify({"error": "アクセス権がありません。"}), 403

    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "日付が指定されていません。"}), 400

    try:
        results = fetch_attendance_logs(date_str)
        sanitized = [
            {k: v for k, v in log.items() if k != "user_id"}
            for log in results
        ]
        return jsonify(sanitized)

    except Exception as e:
        logging.error(f"出席データ取得エラー: {e}")
        return jsonify({"error": f"データ取得中にエラーが発生しました: {e}"}), 500

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★【新規追加】日付ごとの出席者にメッセージを送信するAPIルート ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.get_json(silent=True) or {}
    secret_key = data.get('key')
    if secret_key != EXPORT_SECRET_KEY:
        return jsonify({"error": "アクセス権がありません。"}), 403

    date_str = data.get('date')
    course = (data.get('course') or '').strip().upper()
    message = (data.get('message') or '').strip()
    if not date_str:
        return jsonify({"error": "日付が指定されていません。"}), 400
    if not message:
        return jsonify({"error": "メッセージが空です。"}), 400
    if course and course not in {"PT", "OT", "NS"}:
        return jsonify({"error": "コース指定が不正です。"}), 400

    try:
        logs = fetch_attendance_logs(date_str)
        if course:
            logs = [log for log in logs if (log.get('course') or '').upper() == course]
        user_ids = [log.get('user_id') for log in logs if log.get('user_id')]

        # 重複を除外（順序維持）
        seen = set()
        targets = []
        for uid in user_ids:
            if uid in seen:
                continue
            seen.add(uid)
            targets.append(uid)

        if not targets:
            return jsonify({"sent": 0, "target": 0, "failed": 0})

        failed = 0
        for uid in targets:
            try:
                line_bot_api.push_message(uid, TextSendMessage(text=message))
            except Exception as e:
                logging.error(f"メッセージ送信エラー: {uid} {e}")
                failed += 1

        return jsonify({"sent": len(targets) - failed, "target": len(targets), "failed": failed})

    except Exception as e:
        logging.error(f"メッセージ送信APIエラー: {e}")
        return jsonify({"error": f"送信中にエラーが発生しました: {e}"}), 500

# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# ★【新規追加】出席ログのコース(PT/OT/NS)を更新するAPIルート ★
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
@app.route("/set_course", methods=["POST"])
def set_course():
    data = request.get_json(silent=True) or {}
    secret_key = data.get('key')
    if secret_key != EXPORT_SECRET_KEY:
        return jsonify({"error": "アクセス権がありません。"}), 403

    log_id = (data.get('log_id') or '').strip()
    course = (data.get('course') or '').strip().upper()
    if not log_id:
        return jsonify({"error": "log_idが指定されていません。"}), 400
    if course not in {"PT", "OT", "NS", ""}:
        return jsonify({"error": "コース指定が不正です。"}), 400

    if not db:
        return jsonify({"error": "データベース接続エラー"}), 500

    try:
        doc_ref = db.collection('attendance_logs').document(log_id)
        if course == "":
            doc_ref.update({"course": firestore.DELETE_FIELD})
        else:
            doc_ref.update({"course": course})
        return jsonify({"ok": True, "course": course})
    except Exception as e:
        logging.error(f"コース更新エラー: {e}")
        return jsonify({"error": f"更新中にエラーが発生しました: {e}"}), 500

# --- メッセージハンドラ (省略... 変更なし) ---
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
    d = distance(lat, lng, CLASS_LAT, CLASS_LNG)

    if d > RADIUS_M:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"❌ 教室の範囲外です（約{int(d)}m離れています）。"))
        return

    if user_states.get(user_id, {}).get('state') == 'awaiting_location':
        student_id = user_states[user_id]['student_id']
        name = user_states[user_id]['name']
        if register_and_attend(user_id, student_id, name):
            reply_text = f"✅ {name}さん（{student_id}）の初回登録と出席を完了しました。"
        else:
            reply_text = "❌ 登録・出席処理中にエラーが発生しました。"
        del user_states[user_id]
    else:
        student_info = get_student_info(user_id)
        if not student_info:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ エラー：学生情報が見つかりません。お手数ですが、再度「出席」と送信してください。"))
            return
        
        if record_attendance(user_id, student_info):
            reply_text = f"✅ {student_info.get('name')}さん（{student_info.get('student_id')}）の出席を登録しました。"
        else:
            reply_text = "❌ 出席を受け付けましたが、台帳への記録に失敗しました。"
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
