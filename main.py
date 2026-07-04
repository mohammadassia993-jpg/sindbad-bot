import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import psycopg2
from datetime import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
OWNER_ID = os.environ.get("OWNER_ID")
RENDER_URL = os.environ.get("RENDER_URL")

if not all([TELEGRAM_TOKEN, OPENROUTER_API_KEY, DATABASE_URL, OWNER_ID, RENDER_URL]):
    raise Exception("❌ تأكد من إضافة جميع المتغيرات البيئية في Render")

OWNER_ID = int(OWNER_ID)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    lang TEXT DEFAULT 'ar')''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    text TEXT,
                    response TEXT,
                    time TIMESTAMP)''')
    conn.commit()
    c.close()
    conn.close()

init_db()

def get_lang(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT lang FROM users WHERE user_id=%s", (uid,))
    r = c.fetchone()
    c.close()
    conn.close()
    return r[0] if r else 'ar'

def set_lang(uid, lang):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO users (user_id, lang) VALUES (%s,%s)
                 ON CONFLICT (user_id) DO UPDATE SET lang=%s""", (uid, lang, lang))
    conn.commit()
    c.close()
    conn.close()

def save_chat(uid, text, resp):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO chat (user_id, text, response, time) VALUES (%s,%s,%s,%s)",
              (uid, text, resp, datetime.now()))
    conn.commit()
    c.close()
    conn.close()

def get_recent_history(uid, limit=6):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT text, response FROM chat WHERE user_id=%s
                 ORDER BY id DESC LIMIT %s""", (uid, limit))
    rows = c.fetchall()
    c.close()
    conn.close()
    rows.reverse()
    messages = []
    for text, resp in rows:
        messages.append({"role": "user", "content": text})
        messages.append({"role": "assistant", "content": resp})
    return messages

def menu(uid):
    lang = get_lang(uid)
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == 'ar':
        btns = ["📜 الأرشيف", "🤖 النموذج", "📁 الوسائط", "🔔 الملاحظات", "🌐 اللغة", "🎙️ صوت"]
    else:
        btns = ["📜 Archives", "🤖 Model", "📁 Media", "🔔 Notes", "🌐 Language", "🎙️ Voice"]
    for b in btns:
        markup.add(KeyboardButton(b))
    return markup

def is_owner(m):
    return m.from_user.id == OWNER_ID

@bot.message_handler(commands=['start'])
def start(m):
    if not is_owner(m):
        bot.reply_to(m, "🚫 هذا البوت خاص.")
        return
    uid = m.from_user.id
    bot.send_message(m.chat.id, "مرحباً سندباد!" if get_lang(uid) == 'ar' else "Welcome Sindbad!",
                      reply_markup=menu(uid))

@bot.message_handler(func=lambda m: m.text in ["🌐 اللغة", "🌐 Language"])
def toggle(m):
    if not is_owner(m):
        return
    uid = m.from_user.id
    cur = get_lang(uid)
    new = 'en' if cur == 'ar' else 'ar'
    set_lang(uid, new)
    bot.send_message(m.chat.id, "Switched to English" if new == 'en' else "تم التبديل للعربية",
                      reply_markup=menu(uid))

@bot.message_handler(func=lambda m: m.text in ["📜 الأرشيف", "📜 Archives"])
def archive(m):
    if not is_owner(m):
        return
    uid = m.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT text, response, time FROM chat WHERE user_id=%s ORDER BY id DESC LIMIT 10", (uid,))
    rows = c.fetchall()
    c.close()
    conn.close()
    if not rows:
        bot.send_message(m.chat.id, "لا يوجد أرشيف بعد." if get_lang(uid) == 'ar' else "No archive yet.")
        return
    lines = []
    for text, resp, t in rows:
        lines.append(f"🕓 {t.strftime('%Y-%m-%d %H:%M')}\n👤 {text}\n🤖 {resp[:200]}")
    bot.send_message(m.chat.id, "\n\n".join(lines)[:4000])

@bot.message_handler(func=lambda m: True)
def reply(m):
    if not is_owner(m):
        bot.reply_to(m, "🚫 هذا البوت خاص.")
        return
    uid = m.from_user.id
    text = m.text
    bot.send_chat_action(m.chat.id, 'typing')
    try:
        history = get_recent_history(uid, limit=6)
        messages = history + [{"role": "user", "content": text}]

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "google/gemini-2.0-flash-exp:free",
                "messages": messages
            },
            timeout=30
        )
        data = response.json()
        if "choices" not in data:
            raise Exception(data.get("error", {}).get("message", "استجابة غير متوقعة"))

        resp = data['choices'][0]['message']['content']
        save_chat(uid, text, resp)
        bot.send_message(m.chat.id, resp[:4000])
    except Exception as e:
        bot.reply_to(m, f"⚠️ خطأ: {e}")

@app.route('/')
def home():
    return "✅ Bot is running"

@app.route('/health')
def health():
    return "OK", 200

@app.route('/' + (TELEGRAM_TOKEN or "hook"), methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

def setup_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}")

setup_webhook()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
