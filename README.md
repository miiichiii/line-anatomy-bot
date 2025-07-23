# line-anatomy-bot

LINE自動出席管理システム 運用・設定マニュアル
作成日: 2025年7月23日
作成者: 濱田 理人 教授（茨城県立医療大学）
担当コンサルタント: Gemini

1. はじめに
本マニュアルは、茨城県立医療大学の講義における出席管理を自動化するために構築した「LINE自動出席管理システム」の運用および設定に関する情報をまとめたものである。将来的なメンテナンスや設定変更、あるいはシステム複製時の参照資料とすることを目的とする。

2. システム概要
本システムは、学生が自身のLINEアカウントから「出席」と送信するだけで、セキュアな位置情報判定を経て、クラウドデータベース（Firestore）に出席状況が自動記録される仕組みである。初回利用時には、学籍番号と氏名の登録が自動的に行われる。また、教員は専用のWebページから、日付ごとに出席状況を一覧で確認できる。

(https://storage.googleapis.com/gemini-prod-us-west1-assets/images/student_attendance_diagram_ja.png)

3. 利用サービス・URL一覧
本システムの運用には、以下の外部サービスを利用している。各サービスへのリンクと役割を以下に示す。

サービス名

役割

URL / ログイン先

LINE Developers

Bot本体とLIFFアプリの管理

https://developers.line.biz/console/

GitHub (Bot本体)

Pythonコードの保管場所

https://github.com/miichiii/line-anatomy-bot (想定)

Render (Bot本体)

Botの「脳」を動かすサーバー

https://dashboard.render.com/

Firebase (Firestore)

出席簿データベース

https://console.firebase.google.com/

UptimeRobot

Botの自動ウォームアップ

https://uptimerobot.com/dashboard

4. 主要な設定値とURL
システムを構成する上で最も重要な、各サービスを連携させるための設定値は以下の通り。

BotのサーバーURL (Webhook用):
https://line-anatomy-bot.onrender.com/webhook
(LINE DevelopersコンソールのMessaging API設定で利用)

BotのヘルスチェックURL:
https://line-anatomy-bot.onrender.com/health
(UptimeRobotの監視対象URLとして利用)

出席状況ビューアURL:
https://line-anatomy-bot.onrender.com/viewer
(教員がブックマークしておくURL)

LIFFページのURL (エンドポイントURL):
https://liff-wbfn.onrender.com
(LINE DevelopersコンソールのLIFF設定で利用)

LIFF ID:
2007710462-pABrKoAv
(index.htmlファイル内で利用)

LIFF URL:
https://liff.line.me/2007710462-pABrKoAv
(app.pyファイル内で利用)

Googleサービスアカウント メールアドレス:
line-attendance-bot@...iam.gserviceaccount.com (例)
(Firestoreの権限管理で利用)

ビューア・エクスポート用 秘密鍵:
anatomyipu (例)
(Renderの環境変数 EXPORT_SECRET_KEY に設定)

5. 授業前の運用手順
UptimeRobotによる全自動化設定が完了しているため、授業前に教員が特別な操作を行う必要は一切ない。

ただし、学生の出席状況をリアルタイムで確認したい場合は、PCで「出席状況ビューア」のページを開いておくと良い。

6. メンテナンスと設定変更
教室の場所や判定範囲を変更する場合
GitHub上のBot本体のリポジトリ (line-anatomy-bot) にある app.py ファイルを開く。

以下の部分を修正する。

# --- 教室の座標と判定範囲 ---
CLASS_LAT, CLASS_LNG = 36.0266, 140.210  # Googleマップで取得した新しい緯度・経度
RADIUS_M = 300                          # 判定する半径（メートル）

変更を保存（コミット）すれば、Renderが自動でデプロイし、設定が更新される。

新学期などで出席データをリセットする場合
FirebaseコンソールのFirestore Database画面を開く。

studentsとattendance_logsの各コレクションの横にある「︙」メニューから、「コレクションを削除」を実行する。

（推奨） 前年度のデータは、必要であればエクスポート機能でGoogleスプレッドシートに書き出してから削除すると良い。

7. トラブルシューティング
Botが「出席」と送っても全く反応しない
原因: Renderのサーバーに何らかの問題が発生している可能性がある。

対策: Renderのダッシュボードにログインし、line-anatomy-botサービスの「Logs」を確認する。エラーログが出ていれば、その内容を元に対応する。

出席状況ビューアにデータが表示されない
原因1: 入力した「秘密鍵」が間違っている。

対策1: Renderの環境変数 EXPORT_SECRET_KEY に設定した値と、入力した値が完全に一致しているか確認する。

原因2: Firestoreのデータ構造が変更された、またはデータがない。

対策2: Firebaseコンソールで、attendance_logsコレクションにデータが正しく記録されているか確認する。
