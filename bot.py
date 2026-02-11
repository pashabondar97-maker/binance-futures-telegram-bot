import asyncio
import json
import os
import threading
import websockets
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")
STATE_FILE = "state.json"

# ===== Simple HTTP server for Render =====
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Binance Futures Telegram Bot is running")

def start_http_server():
    port = int(os.getenv("PORT", 5000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"HTTP server running on port {port}")
    server.serve_forever()

threading.Thread(target=start_http_server, daemon=True).start()

# ===== State =====
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["symbols"] = set(data.get("symbols", []))
            return data
    return {
        "symbols": set(["BTCUSDT"]),
        "threshold": 3.0,
        "timeframe": "5m",
        "last_alert": {}
    }

def save_state(state):
    data = {
        "symbols": list(state["symbols"]),
        "threshold": state["threshold"],
        "timeframe": state["timeframe"],
        "last_alert": state["last_alert"]
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

state = load_state()

# ===== UI =====
def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати монету", callback_data="add"),
         InlineKeyboardButton("🗑 Прибрати монету", callback_data="remove")],
        [InlineKeyboardButton("🎯 Встановити %", callback_data="set_threshold")],
        [InlineKeyboardButton("⏱ 5м", callback_data="tf_5m"),
         InlineKeyboardButton("⏱ 15м", callback_data="tf_15m"),
         InlineKeyboardButton("⏱ 1г", callback_data="tf_1h")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")]
    ])

# ===== Telegram =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.application.chat_id = update.effective_chat.id
    context.user_data["awaiting"] = None
    await update.message.reply_text("🤖 Керування ботом:", reply_markup=menu())

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "add":
        context.user_data["awaiting"] = "add"
        await q.edit_message_text("Введи монету (BTCUSDT):")

    elif data == "remove":
        context.user_data["awaiting"] = "remove"
        await q.edit_message_text("Введи монету для видалення:")

    elif data == "set_threshold":
        context.user_data["awaiting"] = "threshold"
        await q.edit_message_text("Введи %:")

    elif data.startswith("tf_"):
        tf = data.replace("tf_", "")
        state["timeframe"] = tf
        save_state(state)
        await reset_ws(context.application)
        await q.edit_message_text(f"⏱ Таймфрейм: {tf}", reply_markup=menu())

    elif data == "status":
        await q.edit_message_text(
            f"📊 Статус:\nМонети: {', '.join(state['symbols'])}\nПоріг: {state['threshold']}%\nTF: {state['timeframe']}",
            reply_markup=menu()
        )

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waiting = context.user_data.get("awaiting")
    txt = update.message.text.strip().upper()

    if waiting == "add":
        state["symbols"].add(txt)
        save_state(state)
        await reset_ws(context.application)
        await update.message.reply_text(f"✅ Додано {txt}", reply_markup=menu())

    elif waiting == "remove":
        state["symbols"].discard(txt)
        save_state(state)
        await reset_ws(context.application)
        await update.message.reply_text(f"🗑 Видалено {txt}", reply_markup=menu())

    elif waiting == "threshold":
        try:
            state["threshold"] = float(update.message.text)
            save_state(state)
            await update.message.reply_text(f"🎯 Поріг: {state['threshold']}%", reply_markup=menu())
        except:
            await update.message.reply_text("Введи число", reply_markup=menu())

    context.user_data["aw]()_
