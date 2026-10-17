# esco_seller_panel_bot.py
# Railway-ready Telegram bot: E$CO Seller Panel
# Env (Railway): BOT_TOKEN, ADMIN_IDS (comma-sep), STORM_API_URL, STORM_USER_ID, optional DB_PATH
# pip install python-telegram-bot==20.7 aiohttp aiosqlite python-dotenv

import os, re, json, random, asyncio, aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ───────────────────────── CONFIG ─────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()}
STORM_API_URL = os.getenv("STORM_API_URL", "https://api.example-stormcheck.com")
STORM_USER_ID = os.getenv("STORM_USER_ID", "")
DB_PATH = os.getenv("DB_PATH", "esco_panel.db")
CARD_COST = float(os.getenv("CARD_COST", "0.35"))      # your cost per live
SALE_PRICE = float(os.getenv("SALE_PRICE", "8.00"))    # sell price per live
BATCH_COUNTER_START = 1000

# Conversation states
(
    MAIN,
    FMT_WAIT_CARDS, FMT_USA_FOREIGN, FMT_PRE, FMT_POST,
    SALE_NAME, SALE_QTY, SALE_WAIT_CARDS, SALE_USA_FOREIGN, SALE_PRE, SALE_POST,
    REP_NAME, REP_QTY, REP_WAIT_CARDS, REP_USA_FOREIGN, REP_PRE, REP_POST,
    TEST_TYPE, TEST_WAIT_CARDS, TEST_USA_FOREIGN, TEST_PRE, TEST_POST,
    RATE_MENU, RATE_BIN_INPUT, RATE_VALUE_INPUT, RATE_SUGGEST_INPUT, RATE_FORCE_INPUT,
) = range(28)

# ───────────────────────── BIN DB ─────────────────────────
BIN_INFO = {
    "410039": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "scheme": "visa"},
    "410040": {"brand": "VISA", "type": "CREDIT", "level": "BUSINESS", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "scheme": "visa"},
    "414720": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "scheme": "visa"},
    "414740": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "scheme": "visa"},
    "440066": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "BANK OF AMERICA - CONSUMER CREDIT", "country": "UNITED STATES", "scheme": "visa"},
    "483312": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "scheme": "visa"},
    "483316": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "scheme": "visa"},
    "513371": {"brand": "MASTERCARD", "type": "CREDIT", "level": "STANDARD", "bank": "NEWDAY, LTD.", "country": "UNITED KINGDOM", "scheme": "mastercard"},
    "513379": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "BANQUE FEDERATIVE DU CREDIT MUTUEL (BFCM)", "country": "FRANCE", "scheme": "mastercard"},
    "521729": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "COMMONWEALTH BANK OF AUSTRALIA", "country": "AUSTRALIA", "scheme": "mastercard"},
    "534348": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CELTIC BANK CORPORATION", "country": "UNITED STATES", "scheme": "mastercard"},
    "542418": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "scheme": "mastercard"},
    "546616": {"brand": "MASTERCARD", "type": "CREDIT", "level": "WORLD", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "scheme": "mastercard"},
}

# runtime bin ratings (persisted)
# bin -> {rating, vr, balance_rating, suggestion, force_vr}
DEFAULT_BIN_META = {"rating": "9/10", "vr": 100, "balance_rating": "high", "suggestion": "Amazon / Apple / Digital", "force_vr": None}

# ───────────────────────── DB ─────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins_stats (
            user_id INTEGER PRIMARY KEY,
            cards_sold INTEGER DEFAULT 0,
            total_sales INTEGER DEFAULT 0,
            revenue REAL DEFAULT 0,
            testers_given INTEGER DEFAULT 0,
            replacements_given INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            batch_counter INTEGER DEFAULT 1000
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS bin_meta (
            bin TEXT PRIMARY KEY,
            rating TEXT,
            vr INTEGER,
            balance_rating TEXT,
            suggestion TEXT,
            force_vr INTEGER
        )""")
        await db.commit()
        for b in BIN_INFO:
            await db.execute(
                "INSERT OR IGNORE INTO bin_meta (bin, rating, vr, balance_rating, suggestion, force_vr) VALUES (?,?,?,?,?,?)",
                (b, "9/10", 100, "high", "Amazon / Apple / Digital", None)
            )
        for aid in ADMIN_IDS:
            await db.execute("INSERT OR IGNORE INTO admins_stats (user_id) VALUES (?)", (aid,))
        await db.commit()

async def get_stats(uid: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM admins_stats WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO admins_stats (user_id) VALUES (?)", (uid,))
            await db.commit()
            return {"cards_sold":0,"total_sales":0,"revenue":0.0,"testers_given":0,"replacements_given":0,"total_profit":0.0,"batch_counter":BATCH_COUNTER_START}
        return dict(row)

async def upd_stats(uid: int, **kwargs):
    if not kwargs: return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE admins_stats SET {sets} WHERE user_id=?", (*kwargs.values(), uid))
        await db.commit()

async def next_batch_id(uid: int) -> int:
    st = await get_stats(uid)
    nid = int(st["batch_counter"]) + 1
    await upd_stats(uid, batch_counter=nid)
    return nid

async def get_bin_meta(bin6: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM bin_meta WHERE bin=?", (bin6,))
        row = await cur.fetchone()
        if row:
            d = dict(row)
            return d
        return dict(DEFAULT_BIN_META, bin=bin6)

async def set_bin_meta(bin6: str, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO bin_meta (bin, rating, vr, balance_rating, suggestion, force_vr) VALUES (?,?,?,?,?,?)",
                         (bin6, "9/10", 100, "high", "Amazon / Apple / Digital", None))
        if kwargs:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            await db.execute(f"UPDATE bin_meta SET {sets} WHERE bin=?", (*kwargs.values(), bin6))
        await db.commit()

# ───────────────────────── PARSING / FORMAT ─────────────────────────
CARD_RE = re.compile(
    r"(?P<cc>\d{15,16})[|:,/\s]+(?P<mm>\d{1,2})[|:/,\s]+(?P<yy>\d{2,4})[|:,/\s]+(?P<cvv>\d{3,4})"
    r"(?:[|:,/\s]+(?P<name>[^|]+))?"
    r"(?:[|:,/\s]+(?P<address>[^|]+))?"
    r"(?:[|:,/\s]+(?P<city>[^|]+))?"
    r"(?:[|:,/\s]+(?P<state>[^|]+))?"
    r"(?:[|:,/\s]+(?P<zip>[^|]+))?"
    r"(?:[|:,/\s]+(?P<country>[^|]+))?"
    r"(?:[|:,/\s]+(?P<phone>[^|]+))?"
    r"(?:[|:,/\s]+(?P<email>[^|]+))?"
    r"(?:[|:,/\s]+(?P<ip>[^|]+))?",
    re.I
)

def parse_cards(text: str) -> List[dict]:
    cards = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # pipe-first fast path
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[0].isdigit():
            cc = re.sub(r"\D", "", parts[0])
            mm, yy, cvv = parts[1], parts[2], parts[3] if len(parts) > 3 else ""
            if "/" in parts[1]:
                mm, yy = parts[1].split("/")
                cvv = parts[2] if len(parts) > 2 else ""
                offset = 3
            else:
                offset = 4
            def g(i, default=""):
                return parts[i] if len(parts) > i else default
            # normalize yy
            yy = yy[-2:] if len(yy) == 4 else yy
            mm = mm.zfill(2)
            name = g(offset, "JOHN DOE")
            address = g(offset+1, "123 MAIN ST")
            city = g(offset+2, "CITY")
            state = g(offset+3, "ST")
            zipcode = g(offset+4, "00000")
            country = g(offset+5, "US")
            phone = g(offset+6, "0000000000")
            email = g(offset+7, "user@email.com")
            ip = g(offset+8, "")
            cards.append({
                "card": cc, "mm": mm, "yy": yy, "cvv": cvv,
                "name": name, "address": address, "city": city, "state": state,
                "zipcode": zipcode, "country": country, "phone": phone, "email": email,
                "ip": ip, "raw": line, "bin": cc[:6], "last4": cc[-4:]
            })
            continue
        m = CARD_RE.search(line)
        if m:
            d = m.groupdict()
            cc = d["cc"]
            yy = d["yy"][-2:]
            cards.append({
                "card": cc, "mm": d["mm"].zfill(2), "yy": yy, "cvv": d["cvv"],
                "name": (d.get("name") or "JOHN DOE").strip(),
                "address": (d.get("address") or "123 MAIN ST").strip(),
                "city": (d.get("city") or "CITY").strip(),
                "state": (d.get("state") or "ST").strip(),
                "zipcode": (d.get("zip") or "00000").strip(),
                "country": (d.get("country") or "US").strip(),
                "phone": (d.get("phone") or "0000000000").strip(),
                "email": (d.get("email") or "user@email.com").strip(),
                "ip": (d.get("ip") or "").strip(),
                "raw": line, "bin": cc[:6], "last4": cc[-4:]
            })
    return cards

def get_random_ip() -> str:
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

def is_usa_card(c: dict) -> bool:
    cc = (c.get("country") or "").upper()
    bin6 = c["bin"]
    info = BIN_INFO.get(bin6, {})
    if cc in ("US", "USA", "UNITED STATES", ""):
        # prefer BIN country
        bcountry = (info.get("country") or "").upper()
        if bcountry and bcountry not in ("UNITED STATES", "US", "USA"):
            return False
        return True
    return False

async def format_card_block(c: dict, is_tester: bool = False) -> str:
    bin6 = c["bin"]
    info = BIN_INFO.get(bin6, {"bank": "UNKNOWN", "brand": "UNKNOWN", "level": "STANDARD", "country": c.get("country", "US")})
    meta = await get_bin_meta(bin6)
    vr = meta.get("force_vr") if meta.get("force_vr") is not None else 100  # forced live-rate 100
    # always present liverate as 100 per request
    vr = 100
    country = info.get("country", c.get("country", "US"))
    ip = c.get("ip") or get_random_ip()
    lines = [
        "══════════════════════════════════════",
        f"🃏 LIVE • VR: {vr}%",
        "══════════════════════════════════════",
        f"👤 Name    : {c['name']}",
        f"💳 Card    : {c['card']}",
        f"📅 Expiry  : {c['mm']}/{c['yy']}",
        f"🔒 CVV     : {c['cvv']}",
        f"🏦 Bank    : {info.get('bank', 'UNKNOWN')}",
        f"🌍 Country : {country} • {info.get('brand', 'UNKNOWN')} {info.get('level', 'STANDARD')}",
        "",
        "📍 Billing Address:",
        f"   {c['address']}",
        f"   {c['city']}, {c['state']} {c['zipcode']}",
        f"   Phone  : {c['phone']}",
        f"   Email  : {c['email']}",
        "",
        f"🌐 IP      : {ip}",
        f"🕒 Checked : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "══════════════════════════════════════",
        f"BIN Rate   : {meta.get('rating', '9/10')} | {meta.get('suggestion', 'N/A')}",
        "══════════════════════════════════════",
    ]
    if is_tester:
        lines.append("❤️ Thank You For Choosing E$CO ❤️")
    lines.append("")
    lines.append("⭐ Leave a vouch after successful use — E$CO quality. ⭐")
    return "\n".join(lines)

async def build_output_file(cards: List[dict], is_tester: bool = False) -> str:
    blocks = [await format_card_block(c, is_tester=is_tester) for c in cards]
    header = (
        "E$CO FORMATTED LIVE CARDS\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"Count: {len(cards)} | LiveRate: 100%\n"
        "Send vouches in the group after hits — helps the whole desk.\n"
        + ("=" * 40) + "\n\n"
    )
    return header + "\n".join(blocks)

# Simulated checker — always 100% live as requested
async def check_cards(cards: List[dict]) -> Tuple[List[dict], float]:
    # mark all live
    for c in cards:
        c["live"] = True
        c["vr"] = 100
    return cards, 100.0

# Storm balance
async def storm_credits() -> str:
    # Wire your real /user path here
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{STORM_API_URL.rstrip('/')}/user", params={"id": STORM_USER_ID}, timeout=15) as r:
                data = await r.json()
                return str(data.get("credits", data.get("balance", "N/A")))
    except Exception:
        return "N/A (set STORM_API_URL)"

# ───────────────────────── AUTH ─────────────────────────
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

async def guard(update: Update) -> bool:
    uid = update.effective_user.id
    if not is_admin(uid):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        elif update.callback_query:
            await update.callback_query.answer("Unauthorized", show_alert=True)
        return False
    return True

# ───────────────────────── UI HELPERS ─────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Format", callback_data="menu_format"),
         InlineKeyboardButton("Sale", callback_data="menu_sale")],
        [InlineKeyboardButton("Replace", callback_data="menu_replace"),
         InlineKeyboardButton("Tester", callback_data="menu_tester")],
        [InlineKeyboardButton("Rate / BIN", callback_data="menu_rate"),
         InlineKeyboardButton("Balance", callback_data="menu_balance")],
        [InlineKeyboardButton("Stats", callback_data="menu_stats")],
    ])

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = None):
    user = update.effective_user
    msg = text or (
        f"E$CO Seller Panel\n"
        f"Welcome @{user.username or user.first_name or user.id}\n"
        f"Select a feature:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=main_keyboard())
    else:
        await update.message.reply_text(msg, reply_markup=main_keyboard())
    return MAIN

def pre_kb_format(has_file=False):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="fmt_check"),
         InlineKeyboardButton("Set Filename", callback_data="fmt_setfn")],
        [InlineKeyboardButton("Add More Cards", callback_data="fmt_add"),
         InlineKeyboardButton("Remove Cards", callback_data="fmt_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="fmt_send"),
         InlineKeyboardButton("Add More Cards", callback_data="fmt_add")],
        [InlineKeyboardButton("Remove Cards", callback_data="fmt_rm"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def pre_kb_sale():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add More Cards", callback_data="sale_add"),
         InlineKeyboardButton("Remove Cards", callback_data="sale_rm")],
        [InlineKeyboardButton("Check", callback_data="sale_check"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_sale():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="sale_send"),
         InlineKeyboardButton("Add More Cards", callback_data="sale_add")],
        [InlineKeyboardButton("Remove Cards", callback_data="sale_rm"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def pre_kb_rep():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="rep_check"),
         InlineKeyboardButton("Add More Cards", callback_data="rep_add")],
        [InlineKeyboardButton("Remove Cards", callback_data="rep_rm"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_rep():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="rep_send"),
         InlineKeyboardButton("Add More Cards", callback_data="rep_add")],
        [InlineKeyboardButton("Remove Cards", callback_data="rep_rm"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def usa_foreign_kb(prefix: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data=f"{prefix}_usa"),
         InlineKeyboardButton("Foreign", callback_data=f"{prefix}_foreign")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

# session store on context.user_data:
# cards: List[dict]
# mode: format|sale|replace|tester
# filename, customer, target, filter (usa|foreign|all), is_tester, tester_kind, batch_id
# awaiting: setfn|rm|...

def ensure_session(context, **defaults):
    ud = context.user_data
    for k, v in defaults.items():
        if k not in ud:
            ud[k] = v
    if "cards" not in ud:
        ud["cards"] = []
    return ud

# ───────────────────────── COMMANDS ─────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    context.user_data.clear()
    return await show_admin_panel(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
    return await show_admin_panel(update, context, "Cancelled. Back to E$CO Seller Panel.")

async def cmd_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await start_format(update, context)

async def cmd_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await start_sale(update, context)

async def cmd_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await start_replace(update, context)

async def cmd_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await start_tester(update, context)

async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await start_rate(update, context)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await show_stats(update, context)

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    return await show_balance(update, context)

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    bins = "\n".join(f"{b} | {BIN_INFO[b]['brand']} | {BIN_INFO[b]['bank']}" for b in BIN_INFO)
    await update.message.reply_text(f"BIN list:\n{bins}")
    return MAIN

# ───────────────────────── MENU CALLBACKS ─────────────────────────
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "menu_format":
        return await start_format(update, context)
    if data == "menu_sale":
        return await start_sale(update, context)
    if data == "menu_replace":
        return await start_replace(update, context)
    if data == "menu_tester":
        return await start_tester(update, context)
    if data == "menu_rate":
        return await start_rate(update, context)
    if data == "menu_balance":
        return await show_balance(update, context)
    if data == "menu_stats":
        return await show_stats(update, context)
    if data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context, "Cancelled. Admin panel.")
    return MAIN

# ───────────────────────── FORMAT FLOW ─────────────────────────
async def start_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    ud.clear()
    ensure_session(context, mode="format", cards=[], filename=None, filter="all", batch_id=None)
    text = "Send Cards Or Drop .txt File To Continue"
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
    return FMT_WAIT_CARDS

async def fmt_receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    ud = ensure_session(context, mode="format", cards=[])
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        data = await f.download_as_bytearray()
        text = data.decode("utf-8", errors="ignore")
        if not ud.get("filename"):
            ud["filename"] = update.message.document.file_name or None
    elif update.message.text:
        text = update.message.text
    else:
        await update.message.reply_text("Send cards text or .txt file.")
        return FMT_WAIT_CARDS
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed. Format:\ncc|mm/yy|cvv|name|address|city|state|zip|US|phone|email|ip")
        return FMT_WAIT_CARDS
    ud["cards"].extend(new_cards)
    ud["batch_id"] = await next_batch_id(update.effective_user.id)
    await update.message.reply_text(
        f"Parsed {len(new_cards)} (session total {len(ud['cards'])}).\nUSA Or Foreign?",
        reply_markup=usa_foreign_kb("fmt")
    )
    return FMT_USA_FOREIGN

async def fmt_usa_foreign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data.endswith("_usa"):
        ud["filter"] = "usa"
        ud["cards"] = [c for c in ud["cards"] if is_usa_card(c)]
    elif q.data.endswith("_foreign"):
        ud["filter"] = "foreign"
        ud["cards"] = [c for c in ud["cards"] if not is_usa_card(c)]
    else:
        ud["filter"] = "all"
    return await fmt_show_pre(update, context)

async def fmt_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    fn = ud.get("filename") or f"Batch-{ud.get('batch_id') or '0000'}"
    txt = (
        f"PreSummary /format\n"
        f"Total Cards: {len(ud.get('cards', []))}\n"
        f"Mode: Base\n"
        f"FileName: {fn}\n"
        f"Filter: {ud.get('filter','all')}"
    )
    kb = pre_kb_format()
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt, reply_markup=kb)
    return FMT_PRE

async def fmt_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    data = q.data
    if data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        ud["awaiting"] = "add"
        return FMT_WAIT_CARDS
    if data == "fmt_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        ud["awaiting"] = "rm"
        return FMT_PRE
    if data == "fmt_setfn":
        await q.edit_message_text("Send filename (without .txt):")
        ud["awaiting"] = "setfn"
        return FMT_PRE
    if data == "fmt_check":
        return await fmt_do_check(update, context)
    return FMT_PRE

async def fmt_pre_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    awaiting = ud.get("awaiting")
    text = (update.message.text or "").strip()
    if awaiting == "setfn":
        ud["filename"] = re.sub(r"[^\w\-\.]+", "_", text)[:80]
        ud["awaiting"] = None
        await update.message.reply_text(f"Filename set: {ud['filename']}.txt")
        return await fmt_show_pre(update, context)
    if awaiting == "rm":
        last4s = {x.strip() for x in text.split(",") if x.strip()}
        before = len(ud["cards"])
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        await update.message.reply_text(f"Removed {before - len(ud['cards'])} cards.")
        return await fmt_show_pre(update, context)
    # treat as more cards
    return await fmt_receive_cards(update, context)

async def fmt_do_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    cards, rate = await check_cards(list(ud.get("cards", [])))
    ud["cards"] = cards
    ud["live_rate"] = rate
    live = [c for c in cards if c.get("live")]
    fn = ud.get("filename") or f"Batch-{ud.get('batch_id')}"
    txt = (
        f"PostSummary /format\n"
        f"Total Cards: {len(cards)}\n"
        f"Live: {len(live)}\n"
        f"LiveRate: 100%\n"
        f"FileName: {fn}.txt"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=post_kb_format())
    else:
        await update.effective_message.reply_text(txt, reply_markup=post_kb_format())
    return FMT_POST

async def fmt_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    data = q.data
    if data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        ud["awaiting"] = "rm_post"
        return FMT_POST
    if data == "fmt_send":
        return await fmt_send_file(update, context)
    return FMT_POST

async def fmt_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "rm_post":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        await update.message.reply_text("Removed.")
        return await fmt_do_check(update, context)
    return await fmt_receive_cards(update, context)

async def fmt_send_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    cards = [c for c in ud.get("cards", []) if c.get("live", True)]
    if not cards:
        await update.callback_query.edit_message_text("No cards to send.")
        return await show_admin_panel(update, context)
    fn = ud.get("filename") or f"Batch-{ud.get('batch_id')}"
    if not fn.endswith(".txt"):
        fn += ".txt"
    content = await build_output_file(cards, is_tester=False)
    path = Path(f"/tmp/{fn}")
    path.write_text(content, encoding="utf-8")
    await update.callback_query.message.reply_document(
        document=InputFile(str(path), filename=fn),
        caption=f"E$CO Format • {len(cards)} live • LiveRate 100%\nVouch after hits."
    )
    context.user_data.clear()
    await update.callback_query.message.reply_text("Done. Admin panel:", reply_markup=main_keyboard())
    return MAIN

# ───────────────────────── SALE FLOW ─────────────────────────
async def start_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    ensure_session(context, mode="sale", cards=[], customer=None, target=0)
    text = "Please Respond With The Customer Name"
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
    return SALE_NAME

async def sale_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = update.message.text.strip()
    await update.message.reply_text(f'How Many Cards Is "{context.user_data["customer"]}" Purchasing? (number)')
    return SALE_QTY

async def sale_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(re.sub(r"\D", "", update.message.text) or "0")
    except Exception:
        await update.message.reply_text("Number only.")
        return SALE_QTY
    context.user_data["target"] = qty
    await update.message.reply_text("Target Set. Send Cards Or Drop .txt File To Continue")
    return SALE_WAIT_CARDS

async def sale_receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = ensure_session(context, mode="sale", cards=[])
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        text = (await f.download_as_bytearray()).decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed. Resend.")
        return SALE_WAIT_CARDS
    ud["cards"].extend(new_cards)
    ud["batch_id"] = await next_batch_id(update.effective_user.id)
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_foreign_kb("sale"))
    return SALE_USA_FOREIGN

async def sale_usa_foreign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data.endswith("_usa"):
        ud["cards"] = [c for c in ud["cards"] if is_usa_card(c)]
        ud["filter"] = "usa"
    elif q.data.endswith("_foreign"):
        ud["cards"] = [c for c in ud["cards"] if not is_usa_card(c)]
        ud["filter"] = "foreign"
    return await sale_show_pre(update, context)

async def sale_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    st = await get_stats(update.effective_user.id)
    rev = float(st["revenue"])
    txt = (
        f"PreSummary /sale\n"
        f"Customer: {ud.get('customer')}\n"
        f"Target: {ud.get('target')}\n"
        f"Total Cards: {len(ud.get('cards', []))}\n"
        f"Mode: Sale\n"
        f"Total Revenue: ${rev:.2f}\n"
        f"+ (Sale Cost ${SALE_PRICE:.2f} ea on send)"
    )
    kb = pre_kb_sale()
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt, reply_markup=kb)
    return SALE_PRE

async def sale_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if q.data == "sale_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if q.data == "sale_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        ud["awaiting"] = "rm"
        return SALE_PRE
    if q.data == "sale_check":
        return await sale_do_check(update, context)
    return SALE_PRE

async def sale_pre_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "rm":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        return await sale_show_pre(update, context)
    return await sale_receive_cards(update, context)

async def sale_do_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    cards, rate = await check_cards(list(ud.get("cards", [])))
    ud["cards"] = cards
    live = [c for c in cards if c.get("live")]
    target = int(ud.get("target") or 0)
    extras = max(0, len(live) - target)
    reached = len(live) >= target
    # projected
    sold = min(len(live), target) if target else len(live)
    revenue_add = sold * SALE_PRICE
    cost = len(live) * CARD_COST
    profit = revenue_add - cost
    st = await get_stats(update.effective_user.id)
    txt = (
        f"PostSummary /sale\n"
        f"Customer: {ud.get('customer')}\n"
        f"Total Cards: {len(cards)}\n"
        f"Total Live: {len(live)}\n"
        f"Extras: {extras}\n"
        f"Target Reached: {reached}\n"
        f"Profit Made (proj): ${profit:.2f}\n"
        f"Total Revenue After Sale (proj): ${float(st['revenue']) + revenue_add:.2f}\n"
        f"LiveRate: 100%"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=post_kb_sale())
    else:
        await update.effective_message.reply_text(txt, reply_markup=post_kb_sale())
    return SALE_POST

async def sale_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if q.data == "sale_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if q.data == "sale_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        ud["awaiting"] = "rm_post"
        return SALE_POST
    if q.data == "sale_send":
        return await sale_send(update, context)
    return SALE_POST

async def sale_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "rm_post":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        return await sale_do_check(update, context)
    return await sale_receive_cards(update, context)

async def sale_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    uid = update.effective_user.id
    live = [c for c in ud.get("cards", []) if c.get("live", True)]
    target = int(ud.get("target") or 0)
    customer = ud.get("customer") or "Customer"
    primary = live[:target] if target else live
    extras = live[target:] if target and len(live) > target else []
    batch = ud.get("batch_id") or await next_batch_id(uid)

    # files
    main_name = f"{customer}-{len(primary)}-{batch}.txt"
    content = await build_output_file(primary, is_tester=False)
    p = Path(f"/tmp/{main_name}")
    p.write_text(content, encoding="utf-8")
    await update.callback_query.message.reply_document(
        InputFile(str(p), filename=main_name),
        caption=f"Sale → {customer} • {len(primary)} live\nVouch please."
    )
    if extras:
        ex_name = f"Extras-{len(extras)}-{batch}.txt"
        ec = await build_output_file(extras, is_tester=False)
        ep = Path(f"/tmp/{ex_name}")
        ep.write_text(ec, encoding="utf-8")
        await update.callback_query.message.reply_document(InputFile(str(ep), filename=ex_name), caption="Extras")

    # accounting: add sale revenue, subtract card cost from profit
    sold_n = len(primary)
    all_live_n = len(live)
    rev_add = sold_n * SALE_PRICE
    cost = all_live_n * CARD_COST
    st = await get_stats(uid)
    new_rev = float(st["revenue"]) + rev_add
    new_profit = float(st["total_profit"]) + (rev_add - cost)
    await upd_stats(
        uid,
        cards_sold=int(st["cards_sold"]) + sold_n,
        total_sales=int(st["total_sales"]) + 1,
        revenue=new_rev,
        total_profit=new_profit,
    )
    context.user_data.clear()
    await update.callback_query.message.reply_text(
        f"Sale booked. +${rev_add:.2f} rev, cost ${cost:.2f}, profit Δ ${rev_add-cost:.2f}",
        reply_markup=main_keyboard()
    )
    return MAIN

# ───────────────────────── REPLACE FLOW ─────────────────────────
async def start_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    ensure_session(context, mode="replace", cards=[], customer=None, target=0)
    text = "Who Is Being Replaced?"
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
    return REP_NAME

async def rep_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = update.message.text.strip()
    await update.message.reply_text("How Many Cards Are Being Replaced? (number)")
    return REP_QTY

async def rep_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = int(re.sub(r"\D", "", update.message.text) or "0")
    context.user_data["target"] = qty
    await update.message.reply_text("Target Submitted. Send Cards Or Drop .txt File To Continue")
    return REP_WAIT_CARDS

async def rep_receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = ensure_session(context, mode="replace", cards=[])
    if update.message.document:
        f = await update.message.document.get_file()
        text = (await f.download_as_bytearray()).decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed.")
        return REP_WAIT_CARDS
    ud["cards"].extend(new_cards)
    ud["batch_id"] = await next_batch_id(update.effective_user.id)
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_foreign_kb("rep"))
    return REP_USA_FOREIGN

async def rep_usa_foreign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data.endswith("_usa"):
        ud["cards"] = [c for c in ud["cards"] if is_usa_card(c)]
    elif q.data.endswith("_foreign"):
        ud["cards"] = [c for c in ud["cards"] if not is_usa_card(c)]
    return await rep_show_pre(update, context)

async def rep_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    txt = (
        f"PreSummary /replace\n"
        f"Total Cards: {len(ud.get('cards', []))}\n"
        f"Replacement Target: {ud.get('target')}\n"
        f"Customer Name: {ud.get('customer')}"
    )
    kb = pre_kb_rep()
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt, reply_markup=kb)
    return REP_PRE

async def rep_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if q.data == "rep_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return REP_WAIT_CARDS
    if q.data == "rep_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        ud["awaiting"] = "rm"
        return REP_PRE
    if q.data == "rep_check":
        return await rep_do_check(update, context)
    return REP_PRE

async def rep_pre_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "rm":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        return await rep_show_pre(update, context)
    return await rep_receive_cards(update, context)

async def rep_do_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    cards, _ = await check_cards(list(ud.get("cards", [])))
    ud["cards"] = cards
    live = [c for c in cards if c.get("live")]
    target = int(ud.get("target") or 0)
    extras = max(0, len(live) - target)
    txt = (
        f"PostSummary /replace\n"
        f"Total Cards: {len(cards)}\n"
        f"Live: {len(live)}\n"
        f"Extras: {extras}\n"
        f"LiveRate: 100%\n"
        f"Replacement Target Reached: {len(live) >= target}\n"
        f"Customer Name: {ud.get('customer')}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=post_kb_rep())
    else:
        await update.effective_message.reply_text(txt, reply_markup=post_kb_rep())
    return REP_POST

async def rep_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if q.data == "rep_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return REP_WAIT_CARDS
    if q.data == "rep_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        ud["awaiting"] = "rm_post"
        return REP_POST
    if q.data == "rep_send":
        return await rep_send(update, context)
    return REP_POST

async def rep_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "rm_post":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        return await rep_do_check(update, context)
    return await rep_receive_cards(update, context)

async def rep_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    uid = update.effective_user.id
    live = [c for c in ud.get("cards", []) if c.get("live", True)]
    target = int(ud.get("target") or 0)
    customer = ud.get("customer") or "Customer"
    primary = live[:target] if target else live
    extras = live[target:] if target and len(live) > target else []
    batch = ud.get("batch_id") or await next_batch_id(uid)
    main_name = f"{customer}-{len(primary)}-{batch}.txt"
    p = Path(f"/tmp/{main_name}")
    p.write_text(await build_output_file(primary), encoding="utf-8")
    await update.callback_query.message.reply_document(InputFile(str(p), filename=main_name), caption=f"Replace → {customer}")
    if extras:
        ex_name = f"Extras-{len(extras)}-{batch}.txt"
        ep = Path(f"/tmp/{ex_name}")
        ep.write_text(await build_output_file(extras), encoding="utf-8")
        await update.callback_query.message.reply_document(InputFile(str(ep), filename=ex_name), caption="Extras")
    # subtract card cost from revenue/profit
    cost = len(live) * CARD_COST
    st = await get_stats(uid)
    await upd_stats(
        uid,
        replacements_given=int(st["replacements_given"]) + len(primary),
        revenue=float(st["revenue"]) - cost,  # cost of cards out
        total_profit=float(st["total_profit"]) - cost,
    )
    context.user_data.clear()
    await update.callback_query.message.reply_text(f"Replace sent. -${cost:.2f} card cost", reply_markup=main_keyboard())
    return MAIN

# ───────────────────────── TESTER FLOW ─────────────────────────
async def start_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    ensure_session(context, mode="tester", cards=[], is_tester=True, filename=None)
    text = "Is This Tester A Drop Or Gift?"
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Drop", callback_data="test_drop"),
                 InlineKeyboardButton("Gift", callback_data="test_gift")],
                [InlineKeyboardButton("Cancel", callback_data="cancel")],
            ])
        )
    else:
        await update.message.reply_text(text)
    return TEST_TYPE

async def test_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    context.user_data["tester_kind"] = "drop" if q.data == "test_drop" else "gift"
    await q.edit_message_text("Send Cards Or Drop .txt File To Continue (filename can be set in pre-summary)")
    return TEST_WAIT_CARDS

async def test_type_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip().lower()
    if t not in ("drop", "gift"):
        await update.message.reply_text("Reply Drop or Gift")
        return TEST_TYPE
    context.user_data["tester_kind"] = t
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return TEST_WAIT_CARDS

async def test_receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = ensure_session(context, mode="tester", cards=[], is_tester=True)
    if update.message.document:
        f = await update.message.document.get_file()
        text = (await f.download_as_bytearray()).decode("utf-8", errors="ignore")
        if not ud.get("filename"):
            ud["filename"] = update.message.document.file_name
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed.")
        return TEST_WAIT_CARDS
    ud["cards"].extend(new_cards)
    ud["batch_id"] = await next_batch_id(update.effective_user.id)
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_foreign_kb("test"))
    return TEST_USA_FOREIGN

async def test_usa_foreign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data.endswith("_usa"):
        ud["cards"] = [c for c in ud["cards"] if is_usa_card(c)]
    elif q.data.endswith("_foreign"):
        ud["cards"] = [c for c in ud["cards"] if not is_usa_card(c)]
    return await test_show_pre(update, context)

async def test_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    fn = ud.get("filename") or f"Batch-{ud.get('batch_id')}"
    txt = (
        f"PreSummary /tester ({ud.get('tester_kind')})\n"
        f"Total Cards: {len(ud.get('cards', []))}\n"
        f"Mode: Base/Tester\n"
        f"FileName: {fn}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=pre_kb_format())  # reuse: Check/SetFN/Add/Remove
    else:
        await update.effective_message.reply_text(txt, reply_markup=pre_kb_format())
    # remap callback prefix via test_ handlers
    return TEST_PRE

async def test_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    data = q.data
    if data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TEST_WAIT_CARDS
    if data == "fmt_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        ud["awaiting"] = "rm"
        return TEST_PRE
    if data == "fmt_setfn":
        await q.edit_message_text("Send filename (without .txt):")
        ud["awaiting"] = "setfn"
        return TEST_PRE
    if data == "fmt_check":
        return await test_do_check(update, context)
    return TEST_PRE

async def test_pre_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "setfn":
        ud["filename"] = re.sub(r"[^\w\-\.]+", "_", update.message.text.strip())[:80]
        ud["awaiting"] = None
        return await test_show_pre(update, context)
    if ud.get("awaiting") == "rm":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        return await test_show_pre(update, context)
    return await test_receive_cards(update, context)

async def test_do_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    cards, _ = await check_cards(list(ud.get("cards", [])))
    ud["cards"] = cards
    fn = ud.get("filename") or f"Batch-{ud.get('batch_id')}"
    txt = (
        f"PostSummary /tester\n"
        f"Total Cards: {len(cards)}\n"
        f"LiveRate: 100%\n"
        f"FileName: {fn}.txt\n"
        f"Kind: {ud.get('tester_kind')}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=post_kb_format())
    else:
        await update.effective_message.reply_text(txt, reply_markup=post_kb_format())
    return TEST_POST

async def test_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ud = context.user_data
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    if q.data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TEST_WAIT_CARDS
    if q.data == "fmt_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        ud["awaiting"] = "rm_post"
        return TEST_POST
    if q.data == "fmt_send":
        return await test_send(update, context)
    return TEST_POST

async def test_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("awaiting") == "rm_post":
        last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
        ud["cards"] = [c for c in ud["cards"] if c["last4"] not in last4s]
        ud["awaiting"] = None
        return await test_do_check(update, context)
    return await test_receive_cards(update, context)

async def test_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    uid = update.effective_user.id
    cards = [c for c in ud.get("cards", []) if c.get("live", True)]
    fn = ud.get("filename") or f"Batch-{ud.get('batch_id')}"
    if not fn.endswith(".txt"):
        fn += ".txt"
    content = await build_output_file(cards, is_tester=True)
    path = Path(f"/tmp/{fn}")
    path.write_text(content, encoding="utf-8")
    await update.callback_query.message.reply_document(
        InputFile(str(path), filename=fn),
        caption=f"Tester ({ud.get('tester_kind')}) • {len(cards)} • LiveRate 100%\n❤️ E$CO"
    )
    st = await get_stats(uid)
    cost = len(cards) * CARD_COST
    await upd_stats(
        uid,
        testers_given=int(st["testers_given"]) + len(cards),
        total_profit=float(st["total_profit"]) - cost,
    )
    context.user_data.clear()
    await update.callback_query.message.reply_text("Tester sent.", reply_markup=main_keyboard())
    return MAIN

# ───────────────────────── RATE / BIN ─────────────────────────
async def start_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Bin VR", callback_data="rate_set_vr")],
        [InlineKeyboardButton("Rate Bin", callback_data="rate_rate_bin")],
        [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate_set_bal")],
        [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate_suggest")],
        [InlineKeyboardButton("Force VR", callback_data="rate_force")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    text = "BIN Rate Menu"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)
    return RATE_MENU

async def rate_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        context.user_data.clear()
        return await show_admin_panel(update, context)
    context.user_data["rate_action"] = q.data
    await q.edit_message_text("Send Bin 6 Digit Number")
    return RATE_BIN_INPUT

async def rate_bin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = re.sub(r"\D", "", update.message.text)[:6]
    if len(bin6) != 6:
        await update.message.reply_text("Need 6 digits.")
        return RATE_BIN_INPUT
    context.user_data["rate_bin"] = bin6
    info = BIN_INFO.get(bin6, {"bank": "UNKNOWN", "brand": "?", "country": "?"})
    meta = await get_bin_meta(bin6)
    action = context.user_data.get("rate_action")
    head = (
        f"You Have Selected Bin {bin6}\n"
        f"{info.get('brand')} | {info.get('bank')} | {info.get('country')}\n"
        f"Current → rating {meta.get('rating')} | vr {meta.get('vr')} | bal {meta.get('balance_rating')} | sug {meta.get('suggestion')} | force {meta.get('force_vr')}\n"
    )
    if action == "rate_set_vr":
        await update.message.reply_text(head + "What Do You Want To Set The Vr Rating As? (0-100 or 0/10)")
        return RATE_VALUE_INPUT
    if action == "rate_rate_bin":
        await update.message.reply_text(head + "Rate this BIN (e.g. 8/10 or text):")
        return RATE_VALUE_INPUT
    if action == "rate_set_bal":
        await update.message.reply_text(head + "Set balance rating (high/med/low or free text):")
        return RATE_VALUE_INPUT
    if action == "rate_suggest":
        await update.message.reply_text(head + "Set suggestion places to use BIN:")
        return RATE_SUGGEST_INPUT
    if action == "rate_force":
        await update.message.reply_text(head + "Set Forced Vr Rating (number). Say Reset To Disable:")
        return RATE_FORCE_INPUT
    return RATE_MENU

async def rate_value_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = context.user_data["rate_bin"]
    action = context.user_data.get("rate_action")
    val = update.message.text.strip()
    if action == "rate_set_vr":
        num = int(re.sub(r"[^\d]", "", val) or "100")
        if num <= 10:  # 0/10 scale → percent
            num *= 10
        await set_bin_meta(bin6, vr=num)
        await update.message.reply_text(f"VR for {bin6} set to {num}% (format output still forced 100% live display per desk rule).")
    elif action == "rate_rate_bin":
        await set_bin_meta(bin6, rating=val)
        await update.message.reply_text(f"BIN {bin6} rating = {val}")
    elif action == "rate_set_bal":
        await set_bin_meta(bin6, balance_rating=val)
        await update.message.reply_text(f"BIN {bin6} balance rating = {val}")
    return await start_rate(update, context)

async def rate_suggest_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = context.user_data["rate_bin"]
    await set_bin_meta(bin6, suggestion=update.message.text.strip())
    await update.message.reply_text(f"Suggestion saved for {bin6}.")
    return await start_rate(update, context)

async def rate_force_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = context.user_data["rate_bin"]
    t = update.message.text.strip().lower()
    if t == "reset":
        await set_bin_meta(bin6, force_vr=None)
        await update.message.reply_text("Force VR disabled.")
    else:
        num = int(re.sub(r"[^\d]", "", t) or "100")
        await set_bin_meta(bin6, force_vr=num)
        await update.message.reply_text(f"Force VR {num}% on BIN {bin6}")
    return await start_rate(update, context)

# ───────────────────────── BALANCE / STATS ─────────────────────────
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    credits = await storm_credits()
    text = f"Your Available Storm Credits Are {credits}"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    return MAIN

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = await get_stats(update.effective_user.id)
    text = (
        f"E$CO Stats @{update.effective_user.username or update.effective_user.id}\n"
        f"Cards Sold: {st['cards_sold']}\n"
        f"Total Sales: {st['total_sales']}\n"
        f"Revenue: ${float(st['revenue']):.2f}\n"
        f"Testers Given: {st['testers_given']}\n"
        f"Replacements Given: {st['replacements_given']}\n"
        f"Total Profit: ${float(st['total_profit']):.2f}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    return MAIN

# ───────────────────────── ADD ADMIN ON THE FLY ─────────────────────────
async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <telegram_user_id>")
        return MAIN
    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Numeric user id required.")
        return MAIN
    ADMIN_IDS.add(new_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admins_stats (user_id) VALUES (?)", (new_id,))
        await db.commit()
    # note: persist ADMIN_IDS via Railway env for reboot; runtime set works until restart
    await update.message.reply_text(f"Admin {new_id} added (also add to ADMIN_IDS env for persistence). Own stats row created.")
    return MAIN

# ───────────────────────── APP ─────────────────────────
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("format", cmd_format),
            CommandHandler("sale", cmd_sale),
            CommandHandler("replace", cmd_replace),
            CommandHandler("tester", cmd_tester),
            CommandHandler("rate", cmd_rate),
            CommandHandler("stats", cmd_stats),
            CommandHandler("balance", cmd_balance),
            CommandHandler("list", cmd_list),
            CommandHandler("cancel", cmd_cancel),
            CallbackQueryHandler(on_menu, pattern=r"^(menu_|cancel)"),
        ],
        states={
            MAIN: [
                CallbackQueryHandler(on_menu),
                CommandHandler("format", cmd_format),
                CommandHandler("sale", cmd_sale),
                CommandHandler("replace", cmd_replace),
                CommandHandler("tester", cmd_tester),
                CommandHandler("rate", cmd_rate),
                CommandHandler("stats", cmd_stats),
                CommandHandler("balance", cmd_balance),
                CommandHandler("list", cmd_list),
                CommandHandler("addadmin", cmd_addadmin),
                CommandHandler("cancel", cmd_cancel),
            ],
            # format
            FMT_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, fmt_receive_cards),
                             CallbackQueryHandler(on_menu, pattern="^cancel$"),
                             CommandHandler("cancel", cmd_cancel)],
            FMT_USA_FOREIGN: [CallbackQueryHandler(fmt_usa_foreign, pattern=r"^fmt_(usa|foreign)$"),
                              CallbackQueryHandler(on_menu, pattern="^cancel$")],
            FMT_PRE: [CallbackQueryHandler(fmt_pre_cb, pattern=r"^(fmt_|cancel)"),
                      MessageHandler(filters.TEXT | filters.Document.ALL, fmt_pre_text),
                      CommandHandler("cancel", cmd_cancel)],
            FMT_POST: [CallbackQueryHandler(fmt_post_cb, pattern=r"^(fmt_|cancel)"),
                       MessageHandler(filters.TEXT | filters.Document.ALL, fmt_post_text),
                       CommandHandler("cancel", cmd_cancel)],
            # sale
            SALE_NAME: [MessageHandler(filters.TEXT, sale_name), CommandHandler("cancel", cmd_cancel)],
            SALE_QTY: [MessageHandler(filters.TEXT, sale_qty), CommandHandler("cancel", cmd_cancel)],
            SALE_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, sale_receive_cards),
                              CommandHandler("cancel", cmd_cancel)],
            SALE_USA_FOREIGN: [CallbackQueryHandler(sale_usa_foreign, pattern=r"^sale_(usa|foreign)$"),
                               CallbackQueryHandler(on_menu, pattern="^cancel$")],
            SALE_PRE: [CallbackQueryHandler(sale_pre_cb, pattern=r"^(sale_|cancel)"),
                       MessageHandler(filters.TEXT | filters.Document.ALL, sale_pre_text),
                       CommandHandler("cancel", cmd_cancel)],
            SALE_POST: [CallbackQueryHandler(sale_post_cb, pattern=r"^(sale_|cancel)"),
                        MessageHandler(filters.TEXT | filters.Document.ALL, sale_post_text),
                        CommandHandler("cancel", cmd_cancel)],
            # replace
            REP_NAME: [MessageHandler(filters.TEXT, rep_name), CommandHandler("cancel", cmd_cancel)],
            REP_QTY: [MessageHandler(filters.TEXT, rep_qty), CommandHandler("cancel", cmd_cancel)],
            REP_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, rep_receive_cards),
                             CommandHandler("cancel", cmd_cancel)],
            REP_USA_FOREIGN: [CallbackQueryHandler(rep_usa_foreign, pattern=r"^rep_(usa|foreign)$"),
                              CallbackQueryHandler(on_menu, pattern="^cancel$")],
            REP_PRE: [CallbackQueryHandler(rep_pre_cb, pattern=r"^(rep_|cancel)"),
                      MessageHandler(filters.TEXT | filters.Document.ALL, rep_pre_text),
                      CommandHandler("cancel", cmd_cancel)],
            REP_POST: [CallbackQueryHandler(rep_post_cb, pattern=r"^(rep_|cancel)"),
                       MessageHandler(filters.TEXT | filters.Document.ALL, rep_post_text),
                       CommandHandler("cancel", cmd_cancel)],
            # tester
            TEST_TYPE: [CallbackQueryHandler(test_type_cb, pattern=r"^(test_|cancel)"),
                        MessageHandler(filters.TEXT, test_type_text),
                        CommandHandler("cancel", cmd_cancel)],
            TEST_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, test_receive_cards),
                              CommandHandler("cancel", cmd_cancel)],
            TEST_USA_FOREIGN: [CallbackQueryHandler(test_usa_foreign, pattern=r"^test_(usa|foreign)$"),
                               CallbackQueryHandler(on_menu, pattern="^cancel$")],
            TEST_PRE: [CallbackQueryHandler(test_pre_cb, pattern=r"^(fmt_|cancel)"),
                       MessageHandler(filters.TEXT | filters.Document.ALL, test_pre_text),
                       CommandHandler("cancel", cmd_cancel)],
            TEST_POST: [CallbackQueryHandler(test_post_cb, pattern=r"^(fmt_|cancel)"),
                        MessageHandler(filters.TEXT | filters.Document.ALL, test_post_text),
                        CommandHandler("cancel", cmd_cancel)],
            # rate
            RATE_MENU: [CallbackQueryHandler(rate_menu_cb), CommandHandler("cancel", cmd_cancel)],
            RATE_BIN_INPUT: [MessageHandler(filters.TEXT, rate_bin_input), CommandHandler("cancel", cmd_cancel)],
            RATE_VALUE_INPUT: [MessageHandler(filters.TEXT, rate_value_input), CommandHandler("cancel", cmd_cancel)],
            RATE_SUGGEST_INPUT: [MessageHandler(filters.TEXT, rate_suggest_input), CommandHandler("cancel", cmd_cancel)],
            RATE_FORCE_INPUT: [MessageHandler(filters.TEXT, rate_force_input), CommandHandler("cancel", cmd_cancel)],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_menu, pattern="^cancel$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    return app

async def _post_init(app: Application):
    await init_db()

def main():
    app = build_app()
    app.post_init = _post_init
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
