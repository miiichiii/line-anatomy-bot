from flask import Flask, request
import os

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    return 'OK', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))  # ← Render が動的に割り当てる
    app.run(host='0.0.0.0', port=port)        # ← 外部からアクセス可能に
