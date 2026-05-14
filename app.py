import os
import threading
from datetime import datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, JoinEvent
from google import genai
import schedule

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
INTERNAL_GROUP_ID = os.environ.get('INTERNAL_GROUP_ID')

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

message_store = {}
TRIGGER_WORDS = ['整理', '摘要', '/summary', '重點']

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
        return "目前尚無訊息記錄，請等群組有對話後再使用摘要功能。"
    msgs = message_store[group_id]
    text_block = "\n".join([f"[{m['time']}] {m['text']}" for m in msgs])
    prompt = f"""以下是今日群組對話記錄，請整理成重點摘要，條列重要事項、待辦事項、結論：

{text_block}

請用繁體中文回覆，格式清楚。"""
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
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
        full_msg = "\n\n".join(all_summaries) if all_summaries else "今日所有群組無訊息記錄。"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=INTERNAL_GROUP_ID,
                    messages=[TextMessage(text=f"📊 每日17:00訊息摘要\n\n{full_msg}")]
                )
            )
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
    source_type = event.source.type
    text = event.message.text.strip()
    is_trigger = text in TRIGGER_WORDS

    if source_type in ['group', 'room']:
        group_id = event.source.group_id if source_type == 'group' else event.source.room_id
        user_id = event.source.user_id or 'unknown'

        # 只有非觸發指令才存入記錄
        if not is_trigger:
            store_message(group_id, user_id, text)

        if is_trigger:
            summary = summarize_messages(group_id)
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"📋 目前訊息摘要：\n\n{summary}")]
                    )
                )
                if INTERNAL_GROUP_ID:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=INTERNAL_GROUP_ID,
                            messages=[TextMessage(text=f"📋 手動觸發摘要（群組 {group_id[-6:]}）：\n\n{summary}")]
                        )
                    )

    elif source_type == 'user':
        user_id = event.source.user_id

        # 只有非觸發指令才存入記錄
        if not is_trigger:
            store_message(user_id, user_id, text)

        if is_trigger:
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
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
