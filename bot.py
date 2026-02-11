import asyncio
import json
import os
import requests
import websockets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")
STATE_FILE = "state.json"

# ===== State management =====
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["symbols"] = set(data.get("symbols", []))
            data["last_alert"] = data.get("last_alert", {})
            return data
    return {
        "symbols": set(["BTCUSDT"]),
        "threshold": 5.0,
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

# ===== Telegram Menu =====
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

# ===== Telegram Handlers =====
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

    context.user_data["awaiting"] = None

# ===== WebSocket Listener =====
ws_task = None

async def ws_listener(app):
    while True:
        try:
            if not state["symbols"]:
                await asyncio.sleep(5)
                continue

            streams = "/".join([f"{s.lower()}@kline_{state['timeframe']}" for s in state["symbols"]])
            url = f"wss://fstream.binance.com/stream?streams={streams}"

            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    k = data["data"]["k"]
                    symbol = data["data"]["s"]
                    open_p = float(k["o"])
                    close_p = float(k["c"])
                    open_time = str(k["t"])
                    change = (close_p - open_p) / open_p * 100

                    last = state["last_alert"].get(symbol)
                    if last:
                        last_change, last_time = last
                        if last_time == open_time:
                            continue

                    if abs(change) >= state["threshold"]:
                        direction = "🚀 ПАМП" if change > 0 else "📉 ДАМП"
                        text = f"{direction} {symbol} ({state['timeframe']})\nЗміна: {change:.2f}%"
                        await app.bot.send_message(chat_id=app.chat_id, text=text)
                        state["last_alert"][symbol] = (change, open_time)
                        save_state(state)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print("WS error:", e)
            await asyncio.sleep(3)

async def reset_ws(app):
    global ws_task
    if ws_task:
        ws_task.cancel()
        try:
            await ws_task
        except:
            pass
    ws_task = app.create_task(ws_listener(app))

# ===== Auto-update liquid symbols =====
async def update_symbols_task(app):
    while True:
        try:
            info = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=10).json()
            tickers = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10).json()
            volumes = {t["symbol"]: float(t["quoteVolume"]) for t in tickers}

            symbols = []
            for s in info["symbols"]:
                symbol = s["symbol"]
                if (
                    s["contractType"] == "PERPETUAL"
                    and s["quoteAsset"] == "USDT"
                    and s["status"] == "TRADING"
                    and volumes.get(symbol, 0) >= 20_000_000
                ):
                    symbols.append(symbol)

            state["symbols"] = set(symbols)
            save_state(state)
            print(f"🔄 Updated {len(symbols)} liquid symbols")
            await reset_ws(app)

        except Exception as e:
            print("Error updating symbols:", e)

        await asyncio.sleep(3600)

# ===== Main =====
def main():
    if not TOKEN:
        raise RuntimeError("TOKEN env var is not set")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    async def post_init(app):
