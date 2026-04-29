import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime
import google.generativeai as genai
import re
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ بوت سندباد يعمل!"

@app.route('/health')
def health():
    return "OK", 200

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

if not TOKEN or not GEMINI_KEY:
    raise Exception("❌ مفاتيح البوت غير موجودة في البيئة")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")
bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect('sindbad.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ar')''')
c.execute('''CREATE TABLE IF NOT EXISTS chat (id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, response TEXT, time TEXT)''')
conn.commit()

def get_lang(uid):
    c.execute("SELECT lang FROM users WHERE user_id=?", (uid,))
    r = c.fetchone()
    return r[0] if r else 'ar'

def set_lang(uid, lang):
    c.execute("INSERT OR REPLACE INTO users (user_id, lang) VALUES (?,?)", (uid, lang))
    conn.commit()

def menu(uid):
    lang = get_lang(uid)
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btns = ["📜 الأرشيف", "🤖 النموذج", "📁 الوسائط", "🔔 الملاحظات", "🌐 اللغة", "🎙️ صوت"] if lang == 'ar' else ["📜 Archives", "🤖 Model", "📁 Media", "🔔 Notes", "🌐 Language", "🎙️ Voice"]
    for b in btns:
        markup.add(KeyboardButton(b))
    return markup

@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    bot.send_message(m.chat.id, "مرحباً سندباد!" if get_lang(uid)=='ar' else "Welcome Sindbad!", reply_markup=menu(uid))

@bot.message_handler(func=lambda m: m.text in ["🌐 اللغة", "🌐 Language"])
def toggle(m):
    uid = m.from_user.id
    cur = get_lang(uid)
    new = 'en' if cur=='ar' else 'ar'
    set_lang(uid, new)
    bot.send_message(m.chat.id, "Switched to English" if new=='en' else "تم التبديل للعربية", reply_markup=menu(uid))

@bot.message_handler(func=lambda m: True)
def reply(m):
    uid = m.from_user.id
    text = m.text
    lang = get_lang(uid)
    bot.send_chat_action(m.chat.id, 'typing')
    try:
        resp = model.generate_content(text).text
        c.execute("INSERT INTO chat (user_id, text, response, time) VALUES (?,?,?,?)", (uid, text, resp, datetime.now().isoformat()))
        conn.commit()
        bot.send_message(m.chat.id, resp[:4000])
    except Exception as e:
        bot.reply_to(m, f"خطأ: {e}")

def run_bot():
    print("✅ بوت سندباد يعمل...")
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
