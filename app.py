import os
import json
import threading
from datetime import datetime, time
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, JoinEvent
import google.generativeai as genai
import schedule

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
INTERNAL_GROUP_ID = os.environ.get('INTERNAL_GROUP_ID')  # 內部群組ID

# LINE SDK 設定
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Gemini 設定
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 儲存訊息（記憶體，重啟會清空）
message_store = {}  # {group_id: [{time, user, text}]}

def store_message(group_id, user_id, text):
    if group_id not in message_store:
        message_store[group_id] = []
    message_store[group_id].append({
        'time': datetime.now().strftime('%H:%M'),
        'user': user_id,
        'text': text
    })

def summarize_messages(group_id):
    if group_id not in message_store or not message_store[group_id]:
        return "今日無訊息記錄。"
    msgs = message_store[group_id]
    text_block = "\n".join([f"[{m['time']}] {m['text']}" for m in msgs])
    prompt = f"""以下是今日群組對話記錄，請整理成重點摘要，條列重要事項、待辦事項、結論：

{text_block}

請用繁體中文回覆，格式清楚。"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"摘要失敗：{str(e)}"

def send_daily_summary():
    with app.app_context():
        if not INTERNAL_GROUP_ID:
            return
        all_summaries = []
        for group_id, msgs in message_store.items():
            if msgs:
                summary = summarize_messages(group_id)
                all_summaries.append(f"📋 群組 {group_id[-6:]} 今日摘要：\n{summary}")
        if all_summaries:
            full_msg = "\n\n".join(all_summaries)
        else:
            full_msg = "今日所有群組無訊息記錄。"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=INTERNAL_GROUP_ID,
                    messages=[TextMessage(text=f"📊 每日17:00訊息摘要\n\n{full_msg}")]
                )
            )
        # 清空當日記錄
        message_store.clear()

def run_scheduler():
    schedule.every().day.at("17:00").do(send_daily_summary)
    while True:
        schedule.run_pending()
        import time as t
        t.sleep(30)

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    source_type = event.source.type  # 'group', 'room', 'user'
    text = event.message.text
    
    if source_type in ['group', 'room']:
        group_id = event.source.group_id if source_type == 'group' else event.source.room_id
        user_id = event.source.user_id or 'unknown'
        store_message(group_id, user_id, text)
        
        # 手動觸發摘要指令
        if text.strip() in ['整理', '摘要', '/summary', '重點']:
            summary = summarize_messages(group_id)
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                # 回覆到當前群組
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📋 目前訊息摘要：\n\n{summary}")]
                    )
                )
                # 同時推送到內部群組
                if INTERNAL_GROUP_ID:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=INTERNAL_GROUP_ID,
                            messages=[TextMessage(text=f"📋 手動觸發摘要（群組 {group_id[-6:]}）：\n\n{summary}")]
                        )
                    )
    elif source_type == 'user':
        user_id = event.source.user_id
        # 1對1 訊息也記錄
        store_message(user_id, user_id, text)
        if text.strip() in ['整理', '摘要', '/summary', '重點']:
            summary = summarize_messages(user_id)
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📋 訊息摘要：\n\n{summary}")]
                    )
                )

@handler.add(JoinEvent)
def handle_join(event):
    source_type = event.source.type
    group_id = None
    if source_type == 'group':
        group_id = event.source.group_id
    elif source_type == 'room':
        group_id = event.source.room_id
    if group_id:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="大家好！我是訊息助理 Bot 🤖\n\n我會記錄群組對話，每天 17:00 自動整理重點。\n\n你也可以隨時輸入「整理」讓我立即產生摘要！")]
                )
            )

@app.route("/health", methods=['GET'])
def health():
    return 'OK'

if __name__ == "__main__":
    # 啟動排程執行緒
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
