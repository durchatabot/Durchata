# main.py
# Requirements: python-telegram-bot==21.9 nest_asyncio flask requests
import os
import asyncio
import logging
import uuid
import requests
from threading import Thread
from flask import Flask, request, jsonify

import nest_asyncio
nest_asyncio.apply()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ENV variables (set these in Render / Railway)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_KEY = os.environ.get("CRYPTOCLOUD_API_KEY")
BASE_URL = os.environ.get("BASE_URL")
SHOP_ID = os.environ.get("SHOP_ID")
SECRET = os.environ.get("CRYPTOCLOUD_SECRET")


if not BOT_TOKEN or not API_KEY or not BASE_URL:
    log.error("Missing required environment variables. Set BOT_TOKEN, CRYPTOCLOUD_API_KEY and BASE_URL.")
    raise SystemExit("Please set BOT_TOKEN, CRYPTOCLOUD_API_KEY and BASE_URL in environment variables.")

# Flask app for webhook
app_flask = Flask(__name__)

# In-memory mapping invoice_id -> chat_id (persistent storage recommended for production)
user_invoices = {}

# Create invoice function using CryptoCloud
def create_invoice(amount_usdt, description, chat_id):
    url = "https://api.cryptocloud.plus/v3/invoice-create"
    headers = {
    "Authorization": f"Token {API_KEY}",
    "Content-Type": "application/json",
    "X-Secret": SECRET
}

    data = {
        "shop_id": SHOP_ID,
        "amount": str(amount_usdt),       # must be string per API spec
        "currency": "USDT",               # stablecoin used for payment
        "order_id": str(uuid.uuid4()),    # unique order identifier
        "description": description,
        "lifetime": 1800,                 # seconds (30 minutes)
        "callback_url": f"{BASE_URL}/cryptocloud/webhook",
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        log.info("CryptoCloud response: %s", resp.text)
        resp.raise_for_status()
        res = resp.json()

        # successful response example:
        # { "result": { "id": "...", "url": "https://pay.cryptocloud.plus/invoice/..." } }
        if res.get("result") and res["result"].get("url"):
            invoice_id = res["result"].get("invoice_id") or res["result"].get("id")
            if invoice_id:
                user_invoices[str(invoice_id)] = chat_id
            return res["result"]["url"]

        log.error("Unexpected response from CryptoCloud: %s", res)
        return None

    except requests.exceptions.HTTPError as e:
        if resp.status_code == 401:
            log.error("❌ Unauthorized — invalid API key.")
        elif resp.status_code == 403:
            log.error("❌ Forbidden — check SHOP_ID or API key permissions.")
        elif resp.status_code == 404:
            log.error("❌ Endpoint not found. Check API version (should be /v3/invoice-create).")
        else:
            log.error("❌ HTTP error: %s", e)
        return None
    except Exception as e:
        log.exception("Failed to create invoice: %s", e)
        return None


# Telegram handlers
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎯 Dienos statymai", callback_data="menu:daily")],
        [InlineKeyboardButton("ℹ️ Info", callback_data="menu:info")],
        [InlineKeyboardButton("📊 Rezultatai", callback_data="menu:results")],
    ]
    await update.message.reply_text(
        "Pasirink, ką nori peržiūrėti 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def handle_menu(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]

    if choice == "daily":
        await show_daily_bets(query)
    elif choice == "info":
        await show_info(query)
    elif choice == "results":
        await show_results(query)

async def show_daily_bets(query):
    keyboard = [
        [InlineKeyboardButton("🥇 Auksinis", callback_data="buy:gold")],
        [InlineKeyboardButton("🥈 Sidabrinis", callback_data="buy:silver")],
        [InlineKeyboardButton("🥉 Bronzinis", callback_data="buy:bronze")],
        [InlineKeyboardButton("🔙 Grįžti į meniu", callback_data="menu:back")],
    ]
    await query.message.edit_text(
        "Pasirink lygį ir apmokėk – po apmokėjimo iškart gausi statymą:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def show_info(query):
    text = (
        "📘 *Apie šį botą:*\n\n"
        "Šis botas kasdien pateikia 3 statymus:\n"
        "🥇 Auksinis – brangiausias, bet patikimiausias.\n"
        "🥈 Sidabrinis – vidutinės rizikos.\n"
        "🥉 Bronzinis – pigiausias, bet rizikingiausias.\n\n"
        "Po apmokėjimo automatiškai gausi statymą.\n"
        "Mokėjimai vykdomi per CryptoCloud (USDT)."
    )
    keyboard = [[InlineKeyboardButton("🔙 Grįžti į meniu", callback_data="menu:back")]]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_results(query):
    text = (
        "📊 *Savaitės rezultatai:*\n\n"
        "✅ 10 Pergalių\n"
        "❌ 3 Pralaimėjimai\n"
        "📈 Tikslumas: *77%*\n\n"
        "_Duomenys atnaujinami._"
    )
    keyboard = [[InlineKeyboardButton("🔙 Grįžti į meniu", callback_data="menu:back")]]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_back(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🎯 Dienos statymai", callback_data="menu:daily")],
        [InlineKeyboardButton("ℹ️ Info", callback_data="menu:info")],
        [InlineKeyboardButton("📊 Rezultatai", callback_data="menu:results")],
    ]
    await query.message.edit_text("Grįžai į pagrindinį meniu 👇", reply_markup=InlineKeyboardMarkup(keyboard))

async def choose_tier(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tier = query.data.split(":")[1]
    plans = {
        "gold": {"price": 10.0, "name": "🥇 Auksinis planas"},
        "silver": {"price": 6.0, "name": "🥈 Sidabrinis planas"},
        "bronze": {"price": 3.0, "name": "🥉 Bronzinis planas"},
    }
    plan = plans.get(tier)
    if not plan:
        await query.message.reply_text("⚠️ Klaida: nežinomas planas.")
        return

    chat_id = query.message.chat_id
    invoice_url = create_invoice(plan["price"], plan["name"], chat_id)

    if invoice_url:
        text = (f"Pasirinkai {plan['name']}.\n\nKaina: *{plan['price']} USDT* 💰\n"
                "Paspausk mygtuką žemiau, kad apmokėtum 👇")
        keyboard = [[InlineKeyboardButton("💸 Apmokėti dabar", url=invoice_url)]]
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text("⚠️ Nepavyko sukurti mokėjimo nuorodos. Bandyk vėliau.")

# Flask webhook endpoint for CryptoCloud
@app_flask.route("/cryptocloud/webhook", methods=["POST"])
def cryptocloud_webhook():
    data = request.json or {}
    log.info("Webhook received: %s", data)
    status = data.get("status")
    invoice_id = str(data.get("invoice_id") or data.get("id") or "")
    if status == "paid" and invoice_id:
        chat_id = user_invoices.get(invoice_id)
        if chat_id:
            # send bet message to user (async)
            asyncio.create_task(send_bet_to_user(chat_id))
    return jsonify({"ok": True})

async def send_bet_to_user(chat_id):
    bot = Bot(token=BOT_TOKEN)
    msg = (
        "✅ *Apmokėjimas gautas!*\n\n"
        "Tavo šiandienos statymas:\n"
        "📈 Komanda A – Komanda B | Statymas: Over 2.5 Goals\n\n"
        "Sėkmės! 🍀"
    )
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.exception("Failed to send bet to user %s: %s", chat_id, e)

# Start Flask in a thread and Telegram app in main loop
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_menu, pattern=r"^menu:(?!back)"))
    app.add_handler(CallbackQueryHandler(handle_back, pattern=r"^menu:back"))
    app.add_handler(CallbackQueryHandler(choose_tier, pattern=r"^buy:"))

    # start flask app on $PORT in separate thread
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app_flask.run(host="0.0.0.0", port=port)).start()
    log.info("Started Flask on port %s", port)

    log.info("Starting Telegram polling...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())









