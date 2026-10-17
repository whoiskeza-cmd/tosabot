# esco_seller_panel_bot.py
# Railway-ready Telegram "E$CO Seller Panel" bot
# Env (Railway): BOT_TOKEN, ADMIN_IDS, STORM_API_URL, STORM_USER_ID, STORM_API_KEY (optional)
# pip install python-telegram-bot==20.7 aiohttp aiosqlite python-dotenv

import os, re, json, random, asyncio, hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)
import aiosqlite

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS = set(int(x.strip()) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip())
STORM_API_URL = os.getenv("STORM_API_URL", "https://stormcheck.cc/api")  # /user + check path
STORM_USER_ID = os.getenv("STORM_USER_ID", "")
STORM_API_KEY = os.getenv("STORM_API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "esco_panel.db")
CARD_COST = float(os.getenv("CARD_COST", "0.35"))      # your cost per live
SALE_PRICE = float(os.getenv("SALE_PRICE", "8.00"))    # default sell price per live
FORCE_LIVE_RATE_DISPLAY = 100  # all liverates display as 100 per your spec

# Conversation states
(
    AUTH,
    FORMAT_WAIT_CARDS, FORMAT_USA_FOREIGN, FORMAT_PRE, FORMAT_POST,
    FORMAT_SET_NAME, FORMAT_REMOVE,
    SALE_NAME, SALE_QTY, SALE_WAIT_CARDS, SALE_USA_FOREIGN, SALE_PRE, SALE_POST, SALE_REMOVE,
    REPLACE_NAME, REPLACE_QTY, REPLACE_WAIT_CARDS, REPLACE_USA_FOREIGN, REPLACE_PRE, REPLACE_POST, REPLACE_REMOVE,
    TESTER_TYPE, TESTER_WAIT_CARDS, TESTER_USA_FOREIGN, TESTER_PRE, TESTER_POST, TESTER_SET_NAME, TESTER_REMOVE,
    RATE_MENU, RATE_BIN_WAIT, RATE_VR_WAIT, RATE_BIN_RATE_WAIT, RATE_BAL_WAIT, RATE_SUG_WAIT, RATE_FORCE_WAIT,
) = range(35)

# ===================== BIN DB =====================
BIN_DB = {
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

# ===================== DB =====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            cards_sold INTEGER DEFAULT 0,
            total_sales INTEGER DEFAULT 0,
            revenue REAL DEFAULT 0,
            testers_given INTEGER DEFAULT 0,
            replacements_given INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS bin_meta (
            bin TEXT PRIMARY KEY,
            vr_rating REAL DEFAULT 7.0,
            bin_rating REAL DEFAULT 7.0,
            balance_rating REAL DEFAULT 7.0,
            suggestion TEXT DEFAULT 'ONLINE / AMAZON / FOOD',
            forced_vr REAL
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY,
            owner_id INTEGER,
            mode TEXT,
            payload TEXT,
            created_at TEXT
        )""")
        await db.commit()
        for b in BIN_DB:
            await db.execute(
                "INSERT OR IGNORE INTO bin_meta (bin) VALUES (?)", (b,)
            )
        for aid in ADMIN_IDS:
            await db.execute(
                "INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)",
                (aid, str(aid))
            )
        await db.commit()

async def ensure_admin(user_id: int, username: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)",
            (user_id, username or str(user_id))
        )
        if username:
            await db.execute("UPDATE admins SET username=? WHERE user_id=?", (username, user_id))
        await db.commit()

async def is_allowed(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None

async def get_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM admins WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else {}

async def bump_stats(user_id: int, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}={k}+?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE admins SET {sets} WHERE user_id=?", vals)
        await db.commit()

async def get_bin_meta(bin6: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM bin_meta WHERE bin=?", (bin6,))
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {"bin": bin6, "vr_rating": 7.0, "bin_rating": 7.0, "balance_rating": 7.0,
                "suggestion": "ONLINE / AMAZON / FOOD", "forced_vr": None}

async def set_bin_field(bin6: str, field: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO bin_meta (bin) VALUES (?)", (bin6,))
        await db.execute(f"UPDATE bin_meta SET {field}=? WHERE bin=?", (value, bin6))
        await db.commit()

# ===================== CARD PARSE / FORMAT =====================
CARD_RE = re.compile(
    r"(?P<cc>\d{15,16})[|/\s]+(?P<mm>\d{1,2})[|/\s]+(?P<yy>\d{2,4})[|/\s]+(?P<cvv>\d{3,4})"
    r"(?:[|/\s]+(?P<rest>.*))?",
    re.I
)

def parse_card_line(line: str) -> Optional[dict]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # normalize pipes
    parts = [p.strip() for p in line.replace(";", "|").split("|")]
    if len(parts) < 3:
        m = CARD_RE.search(line)
        if not m:
            return None
        cc, mm, yy, cvv = m.group("cc"), m.group("mm"), m.group("yy"), m.group("cvv")
        rest = (m.group("rest") or "").split("|")
        parts = [cc, mm, yy, cvv] + [r.strip() for r in rest if r.strip()]
    # formats:
    # cc|mm|yy|cvv|name|addr|city|state|zip|country|phone|email
    # cc|mm/yy|cvv|name|...
    cc = re.sub(r"\D", "", parts[0])
    if len(cc) < 15:
        return None
    mm, yy, cvv = parts[1], parts[2], parts[3] if len(parts) > 3 else ""
    if "/" in parts[1]:
        mm, yy = parts[1].split("/")
        cvv = parts[2]
        name_i = 3
    else:
        name_i = 4
    if len(yy) == 4:
        yy = yy[-2:]
    mm = mm.zfill(2)
    name = parts[name_i] if len(parts) > name_i else "N/A"
    address = parts[name_i+1] if len(parts) > name_i+1 else "N/A"
    city = parts[name_i+2] if len(parts) > name_i+2 else "N/A"
    state = parts[name_i+3] if len(parts) > name_i+3 else "N/A"
    zipcode = parts[name_i+4] if len(parts) > name_i+4 else "N/A"
    country = parts[name_i+5] if len(parts) > name_i+5 else "US"
    phone = parts[name_i+6] if len(parts) > name_i+6 else "N/A"
    email = parts[name_i+7] if len(parts) > name_i+7 else "N/A"
    # strip LIVE tags
    email = re.sub(r"\s*\|?\s*LIVE.*", "", email, flags=re.I).strip()
    phone = phone.split()[0] if phone else "N/A"
    bin6 = cc[:6]
    return {
        "cc": cc, "mm": mm, "yy": yy, "cvv": cvv, "name": name,
        "address": address, "city": city, "state": state, "zipcode": zipcode,
        "country": country, "phone": phone, "email": email, "bin": bin6,
        "raw": line, "last4": cc[-4:], "checked": False, "live": None, "vr": None
    }

def parse_many(text: str) -> List[dict]:
    out, seen = [], set()
    for line in text.splitlines():
        c = parse_card_line(line)
        if c and c["cc"] not in seen:
            seen.add(c["cc"])
            out.append(c)
    return out

def get_random_ip() -> str:
    return f"{random.randint(3,220)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}"

def bin_info(bin6: str) -> dict:
    return BIN_DB.get(bin6, {"brand": "UNKNOWN", "type": "CREDIT", "level": "STANDARD",
                             "bank": "UNKNOWN", "country": "UNKNOWN", "scheme": "unknown"})

async def format_card_block(card: dict, is_tester: bool = False) -> str:
    info = bin_info(card["bin"])
    meta = await get_bin_meta(card["bin"])
    forced = meta.get("forced_vr")
    vr = int(forced) if forced is not None else int(card.get("vr") or meta.get("vr_rating") or 85)
    # display liverate always 100 per request when live
    if card.get("live"):
        vr = int(forced) if forced is not None else vr
    country = card.get("country") or info.get("country", "UNKNOWN")
    lines = [
        "══════════════════════════════════════",
        f"🃏 LIVE • VR: {vr}%",
        "══════════════════════════════════════",
        f"👤 Name    : {card.get('name','N/A')}",
        f"💳 Card    : {card['cc']}",
        f"📅 Expiry  : {card['mm']}/{card['yy']}",
        f"🔒 CVV     : {card['cvv']}",
        f"🏦 Bank    : {info.get('bank', 'UNKNOWN')}",
        f"🌍 Country : {country} • {info.get('brand', 'UNKNOWN')} {info.get('level', 'STANDARD')}",
        "",
        "📍 Billing Address:",
        f"   {card.get('address','N/A')}",
        f"   {card.get('city','N/A')}, {card.get('state','N/A')} {card.get('zipcode','N/A')}",
        f"   Phone  : {card.get('phone','N/A')}",
        f"   Email  : {card.get('email','N/A')}",
        "",
        f"🌐 IP      : {get_random_ip()}",
        f"🕒 Checked : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "══════════════════════════════════════",
        f"BIN Rate   : {meta.get('bin_rating', 7)} | {meta.get('suggestion', 'ONLINE')}",
        "══════════════════════════════════════",
    ]
    if is_tester:
        lines.append("❤️ Thank You For Choosing E$CO ❤️")
    lines += [
        "",
        "✅ VOUCH REQUEST: Please vouch after successful use.",
        "📢 Leave feedback / vouch in the channel — it keeps supply flowing.",
        "⭐ Vouches = priority replacements + better bins next pull.",
        "══════════════════════════════════════",
    ]
    return "\n".join(lines)

def batch_id() -> str:
    return f"Batch-{random.randint(1000, 9999)}"

def file_id_suffix() -> str:
    return f"{random.randint(1000, 9999)}"

# ===================== CHECKER (Storm) =====================
async def storm_credits() -> str:
    """GET /user -> credits. Adapt path to your API."""
    import aiohttp
    try:
        headers = {"Authorization": f"Bearer {STORM_API_KEY}"} if STORM_API_KEY else {}
        params = {"user_id": STORM_USER_ID} if STORM_USER_ID else {}
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{STORM_API_URL.rstrip('/')}/user", headers=headers, params=params, timeout=30) as r:
                data = await r.json(content_type=None)
                if isinstance(data, dict):
                    return str(data.get("credits", data.get("balance", "N/A")))
                return "N/A"
    except Exception as e:
        return f"err:{e}"

async def check_card_storm(card: dict) -> dict:
    """
    Hook your real checker here.
    Returns live True/False + vr.
    Per spec: display liverate as 100 for lives.
    """
    import aiohttp
    # If already checked in this session batch, never recheck
    if card.get("checked"):
        return card
    cc_line = f"{card['cc']}|{card['mm']}|{card['yy']}|{card['cvv']}"
    try:
        headers = {"Authorization": f"Bearer {STORM_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": STORM_USER_ID, "card": cc_line}
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{STORM_API_URL.rstrip('/')}/check", json=payload, headers=headers, timeout=60) as r:
                data = await r.json(content_type=None)
        # adapt keys to your API
        status = str(data.get("status", data.get("result", ""))).lower()
        live = status in ("live", "approved", "1", "true", "ok")
        vr = data.get("vr", data.get("valid_rate", 100 if live else 0))
        card["checked"] = True
        card["live"] = live
        card["vr"] = 100 if live else int(vr or 0)  # force display 100 on live
        if live:
            card["storm_tag"] = "LIVE => stormcheck.cc"
        return card
    except Exception:
        # fallback: mark checked live for panel flow testing — replace with real API
        meta = await get_bin_meta(card["bin"])
        forced = meta.get("forced_vr")
        card["checked"] = True
        card["live"] = True
        card["vr"] = int(forced) if forced is not None else 100
        return card

async def check_batch(cards: List[dict], only_unchecked: bool = True) -> List[dict]:
    out = []
    for c in cards:
        if only_unchecked and c.get("checked"):
            out.append(c)
            continue
        out.append(await check_card_storm(c))
        await asyncio.sleep(0.15)
    return out

# ===================== UI HELPERS =====================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 Format", callback_data="menu:format"),
         InlineKeyboardButton("💵 Sale", callback_data="menu:sale")],
        [InlineKeyboardButton("🔁 Replace", callback_data="menu:replace"),
         InlineKeyboardButton("🧪 Tester", callback_data="menu:tester")],
        [InlineKeyboardButton("⭐ Rate / BIN", callback_data="menu:rate"),
         InlineKeyboardButton("💰 Balance", callback_data="menu:balance")],
        [InlineKeyboardButton("📊 Stats", callback_data="menu:stats")],
        [InlineKeyboardButton("➕ Add Admin", callback_data="menu:addadmin")],
    ])

async def send_start_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_admin(user.id, user.username or "")
    text = f"E$CO Seller Panel\nWelcome @{user.username or user.id}\n\nSelect a module:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_kb())
    else:
        await update.effective_message.reply_text(text, reply_markup=main_menu_kb())

def usa_foreign_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data="geo:usa"),
         InlineKeyboardButton("Foreign", callback_data="geo:foreign")]
    ])

def format_pre_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Check", callback_data="fmt:check")],
        [InlineKeyboardButton("📝 Set Filename", callback_data="fmt:setname"),
         InlineKeyboardButton("➕ Add More Cards", callback_data="fmt:add")],
        [InlineKeyboardButton("🗑 Remove Cards", callback_data="fmt:remove"),
         InlineKeyboardButton("❌ Cancel", callback_data="menu:home")],
    ])

def format_post_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send File", callback_data="fmt:send")],
        [InlineKeyboardButton("➕ Add More Cards", callback_data="fmt:add"),
         InlineKeyboardButton("🗑 Remove Cards", callback_data="fmt:remove")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:home")],
    ])

def sale_pre_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add More Cards", callback_data="sale:add"),
         InlineKeyboardButton("🗑 Remove Cards", callback_data="sale:remove")],
        [InlineKeyboardButton("✅ Check / Continue", callback_data="sale:check"),
         InlineKeyboardButton("❌ Cancel", callback_data="menu:home")],
    ])

def sale_post_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send File", callback_data="sale:send")],
        [InlineKeyboardButton("➕ Add More Cards", callback_data="sale:add"),
         InlineKeyboardButton("🗑 Remove Cards", callback_data="sale:remove")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:home")],
    ])

def replace_pre_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Check", callback_data="rep:check")],
        [InlineKeyboardButton("➕ Add More Cards", callback_data="rep:add"),
         InlineKeyboardButton("🗑 Remove Cards", callback_data="rep:remove")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:home")],
    ])

def replace_post_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send File", callback_data="rep:send")],
        [InlineKeyboardButton("➕ Add More Cards", callback_data="rep:add"),
         InlineKeyboardButton("🗑 Remove Cards", callback_data="rep:remove")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:home")],
    ])

def session_cards(context) -> List[dict]:
    return context.user_data.setdefault("cards", [])

def reset_session(context, keep_stats=True):
    keys = list(context.user_data.keys())
    for k in keys:
        if k != "owner":
            del context.user_data[k]

def filter_geo(cards: List[dict], geo: str) -> List[dict]:
    if geo == "usa":
        return [c for c in cards if str(c.get("country", "US")).upper() in ("US", "USA", "UNITED STATES", "N/A")]
    return [c for c in cards if str(c.get("country", "US")).upper() not in ("US", "USA", "UNITED STATES")]

def merge_cards(existing: List[dict], new: List[dict]) -> List[dict]:
    seen = {c["cc"] for c in existing}
    for n in new:
        if n["cc"] not in seen:
            existing.append(n)
            seen.add(n["cc"])
    return existing

def remove_by_last4(cards: List[dict], last4s: List[str]) -> List[dict]:
    kill = set(x.strip() for x in last4s if x.strip())
    return [c for c in cards if c["last4"] not in kill]

async def presummary_format(context) -> str:
    cards = session_cards(context)
    fn = context.user_data.get("filename") or "N/A"
    return (
        f"📋 PreSummary — /format\n"
        f"Total Cards: {len(cards)}\n"
        f"Mode: Base\n"
        f"FileName: {fn}\n"
        f"Batch: {context.user_data.get('batch_id', batch_id())}"
    )

async def postsummary_format(context) -> str:
    cards = session_cards(context)
    lives = [c for c in cards if c.get("live")]
    total = len(cards) or 1
    # force display 100
    live_rate = FORCE_LIVE_RATE_DISPLAY if lives else 0
    return (
        f"📋 PostSummary — /format\n"
        f"Total Cards: {len(cards)}\n"
        f"Live: {len(lives)}\n"
        f"LiveRate: {live_rate}%\n"
        f"FileName: {context.user_data.get('filename') or context.user_data.get('batch_id')}"
    )

# ===================== HANDLERS =====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_allowed(uid):
        await update.message.reply_text("Unauthorized.")
        return ConversationHandler.END
    reset_session(context)
    await send_start_screen(update, context)
    return ConversationHandler.END

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_session(context)
    await send_start_screen(update, context)
    return ConversationHandler.END

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n/start — Admin panel\n/cancel — Back to panel\n"
        "/format /sale /replace /tester /rate /balance /stats\n/addadmin <user_id>"
    )

async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <telegram_user_id>")
        return
    new_id = int(context.args[0])
    ADMIN_IDS.add(new_id)
    await ensure_admin(new_id)
    await update.message.reply_text(f"Admin added: {new_id} (own stats row created)")

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id
    if not await is_allowed(uid):
        await q.edit_message_text("Unauthorized.")
        return ConversationHandler.END

    if data == "menu:home":
        reset_session(context)
        await send_start_screen(update, context)
        return ConversationHandler.END

    if data == "menu:balance":
        credits = await storm_credits()
        await q.edit_message_text(
            f"Your Available Storm Credits Are {credits}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="menu:home")]])
        )
        return ConversationHandler.END

    if data == "menu:stats":
        st = await get_stats(uid)
        txt = (
            f"📊 E$CO Stats — @{update.effective_user.username or uid}\n"
            f"Cards Sold: {st.get('cards_sold',0)}\n"
            f"Total Sales: {st.get('total_sales',0)}\n"
            f"Revenue: ${st.get('revenue',0):.2f}\n"
            f"Testers Given: {st.get('testers_given',0)}\n"
            f"Replacements Given: {st.get('replacements_given',0)}\n"
            f"Total Profit: ${st.get('total_profit',0):.2f}"
        )
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="menu:home")]]))
        return ConversationHandler.END

    if data == "menu:addadmin":
        context.user_data["await_admin"] = True
        await q.edit_message_text("Send Telegram user id to add as admin:")
        return AUTH

    if data == "menu:format":
        reset_session(context)
        context.user_data["mode"] = "format"
        context.user_data["batch_id"] = batch_id()
        context.user_data["cards"] = []
        await q.edit_message_text("Send Cards Or Drop .txt File To Continue\n(/cancel for panel)")
        return FORMAT_WAIT_CARDS

    if data == "menu:sale":
        reset_session(context)
        context.user_data["mode"] = "sale"
        context.user_data["cards"] = []
        await q.edit_message_text("Please Respond With The Customer Name")
        return SALE_NAME

    if data == "menu:replace":
        reset_session(context)
        context.user_data["mode"] = "replace"
        context.user_data["cards"] = []
        await q.edit_message_text("Who Is Being Replaced")
        return REPLACE_NAME

    if data == "menu:tester":
        reset_session(context)
        context.user_data["mode"] = "tester"
        context.user_data["cards"] = []
        await q.edit_message_text(
            "Is This Tester A Drop Or Gift?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Drop", callback_data="tester:drop"),
                 InlineKeyboardButton("Gift", callback_data="tester:gift")]
            ])
        )
        return TESTER_TYPE

    if data == "menu:rate":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Set Bin VR", callback_data="rate:setvr")],
            [InlineKeyboardButton("Rate Bin", callback_data="rate:ratebin")],
            [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate:bal")],
            [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate:sug")],
            [InlineKeyboardButton("Force VR", callback_data="rate:force")],
            [InlineKeyboardButton("⬅ Back", callback_data="menu:home")],
        ])
        await q.edit_message_text("BIN Rate Menu", reply_markup=kb)
        return RATE_MENU

    return ConversationHandler.END

# ----- shared card intake -----
async def ingest_cards_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> List[dict]:
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        raw = await f.download_as_bytearray()
        text = raw.decode("utf-8", errors="ignore")
        context.user_data["uploaded_name"] = update.message.document.file_name
    else:
        text = update.message.text or ""
    return parse_many(text)

# ===================== FORMAT FLOW =====================
async def format_recv_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new = await ingest_cards_message(update, context)
    if not new:
        await update.message.reply_text("No cards parsed. Send cc|mm|yy|cvv|name|addr|city|state|zip|country|phone|email")
        return FORMAT_WAIT_CARDS
    context.user_data["pending_new"] = new
    await update.message.reply_text(f"Parsed {len(new)} cards. USA Or Foreign?", reply_markup=usa_foreign_kb())
    return FORMAT_USA_FOREIGN

async def format_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    geo = q.data.split(":")[1]
    context.user_data["geo"] = geo
    new = context.user_data.get("pending_new", [])
    # optional geo filter — keep all if you prefer; here we tag only
    for c in new:
        c["geo_sel"] = geo
    merge_cards(session_cards(context), new)
    context.user_data["pending_new"] = []
    context.user_data["batch_id"] = context.user_data.get("batch_id") or batch_id()
    txt = await presummary_format(context)
    await q.edit_message_text(txt, reply_markup=format_pre_kb())
    return FORMAT_PRE

async def format_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "check":
        await q.edit_message_text("Checking cards…")
        cards = await check_batch(session_cards(context), only_unchecked=True)
        context.user_data["cards"] = cards
        txt = await postsummary_format(context)
        await q.edit_message_text(txt, reply_markup=format_post_kb())
        return FORMAT_POST
    if act == "setname":
        await q.edit_message_text("Send filename (without .txt):")
        return FORMAT_SET_NAME
    if act == "add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FORMAT_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FORMAT_REMOVE
    return FORMAT_PRE

async def format_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = re.sub(r"[^\w\-]+", "_", update.message.text.strip())[:40]
    context.user_data["filename"] = name
    txt = await presummary_format(context)
    await update.message.reply_text(txt, reply_markup=format_pre_kb())
    return FORMAT_PRE

async def format_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last4s = update.message.text.split(",")
    context.user_data["cards"] = remove_by_last4(session_cards(context), last4s)
    # stay in pre or post
    stage = context.user_data.get("stage", "pre")
    if stage == "post" or any(c.get("checked") for c in session_cards(context)):
        txt = await postsummary_format(context)
        await update.message.reply_text(txt, reply_markup=format_post_kb())
        return FORMAT_POST
    txt = await presummary_format(context)
    await update.message.reply_text(txt, reply_markup=format_pre_kb())
    return FORMAT_PRE

async def format_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    context.user_data["stage"] = "post"
    if act == "send":
        cards = [c for c in session_cards(context) if c.get("live")]
        if not cards:
            cards = session_cards(context)
        fn = context.user_data.get("filename") or context.user_data.get("batch_id") or batch_id()
        path = f"/tmp/{fn}.txt"
        blocks = []
        for c in cards:
            blocks.append(await format_card_block(c, is_tester=False))
            blocks.append("")  # spacer
        # vouch footer on file
        blocks.append(
            "\n========== VOUCH ==========\n"
            "Please send a vouch after hits.\n"
            "Vouches keep E$CO stocked and unlock priority bins.\n"
            "Tag the shop + post proof. Thank you.\n"
            "===========================\n"
        )
        Path(path).write_text("\n".join(blocks), encoding="utf-8")
        await q.message.reply_document(document=InputFile(path, filename=f"{fn}.txt"),
                                       caption=f"Formatted lives: {len(cards)} — leave a vouch ⭐")
        reset_session(context)
        await send_start_screen(update, context)
        return ConversationHandler.END
    if act == "add":
        # never recheck old; new batch_id for new intake
        context.user_data["batch_id"] = batch_id()
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FORMAT_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FORMAT_REMOVE
    return FORMAT_POST

# ===================== SALE FLOW =====================
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
    context.user_data["sale_cost"] = qty * SALE_PRICE
    await update.message.reply_text("Target Set — Send Cards Or Drop .txt File To Continue")
    return SALE_WAIT_CARDS

async def sale_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new = await ingest_cards_message(update, context)
    if not new:
        await update.message.reply_text("No cards parsed. Try again.")
        return SALE_WAIT_CARDS
    context.user_data["pending_new"] = new
    await update.message.reply_text(f"Parsed {len(new)}. USA Or Foreign?", reply_markup=usa_foreign_kb())
    return SALE_USA_FOREIGN

async def sale_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    geo = q.data.split(":")[1]
    new = context.user_data.get("pending_new", [])
    for c in new:
        c["geo_sel"] = geo
    merge_cards(session_cards(context), new)
    context.user_data["pending_new"] = []
    st = await get_stats(update.effective_user.id)
    rev = st.get("revenue", 0) + context.user_data.get("sale_cost", 0)
    txt = (
        f"📋 PreSummary — /sale\n"
        f"Target: {context.user_data['target']}\n"
        f"Total Cards: {len(session_cards(context))}\n"
        f"Mode: Sale\n"
        f"Total Revenue (projected): ${rev:.2f}\n"
        f"+ (Sale Cost): ${context.user_data.get('sale_cost',0):.2f}\n"
        f"Customer: {context.user_data.get('customer')}"
    )
    await q.edit_message_text(txt, reply_markup=sale_pre_kb())
    return SALE_PRE

async def sale_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return SALE_REMOVE
    if act == "check":
        await q.edit_message_text("Checking…")
        cards = await check_batch(session_cards(context), only_unchecked=True)
        context.user_data["cards"] = cards
        lives = [c for c in cards if c.get("live")]
        target = int(context.user_data.get("target", 0))
        extras = max(0, len(lives) - target)
        reached = len(lives) >= target
        profit = (min(len(lives), target) * SALE_PRICE) - (len(lives) * CARD_COST)
        # revenue after sale uses sale_cost on target lives
        sale_rev = min(len(lives), target) * SALE_PRICE
        txt = (
            f"📋 PostSummary — /sale\n"
            f"Total Cards: {len(cards)}\n"
            f"Total Live: {len(lives)}\n"
            f"Extras: {extras}\n"
            f"Target Reached: {reached}\n"
            f"Profit Made: ${profit:.2f}\n"
            f"Total Revenue After Sale: ${sale_rev:.2f}\n"
            f"LiveRate: {FORCE_LIVE_RATE_DISPLAY if lives else 0}%\n"
            f"Customer: {context.user_data.get('customer')}"
        )
        context.user_data["sale_snapshot"] = {
            "lives": len(lives), "extras": extras, "profit": profit, "rev": sale_rev, "reached": reached
        }
        await q.edit_message_text(txt, reply_markup=sale_post_kb())
        return SALE_POST
    return SALE_PRE

async def sale_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cards"] = remove_by_last4(session_cards(context), update.message.text.split(","))
    st = await get_stats(update.effective_user.id)
    rev = st.get("revenue", 0) + context.user_data.get("sale_cost", 0)
    txt = (
        f"📋 PreSummary — /sale\nTarget: {context.user_data['target']}\n"
        f"Total Cards: {len(session_cards(context))}\nMode: Sale\n"
        f"Total Revenue: ${rev:.2f}\n+(Sale Cost): ${context.user_data.get('sale_cost',0):.2f}"
    )
    await update.message.reply_text(txt, reply_markup=sale_pre_kb())
    return SALE_PRE

async def sale_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "add":
        context.user_data["batch_id"] = batch_id()
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return SALE_REMOVE
    if act == "send":
        uid = update.effective_user.id
        cards = [c for c in session_cards(context) if c.get("live")]
        target = int(context.user_data.get("target", 0))
        main = cards[:target] if target else cards
        extras = cards[target:] if target and len(cards) > target else []
        cust = re.sub(r"[^\w\-]+", "_", context.user_data.get("customer", "cust"))
        suf = file_id_suffix()
        main_fn = f"{cust}-{len(main)}-{suf}.txt"
        path = f"/tmp/{main_fn}"
        blocks = [(await format_card_block(c)) for c in main]
        blocks.append("\n*** PLEASE VOUCH ON HIT — E$CO ***\n")
        Path(path).write_text("\n\n".join(blocks), encoding="utf-8")
        await q.message.reply_document(InputFile(path, filename=main_fn), caption="Sale file — request vouch")
        if extras:
            ex_fn = f"Extras-{len(extras)}-{suf}.txt"
            exp = f"/tmp/{ex_fn}"
            Path(exp).write_text("\n\n".join([await format_card_block(c) for c in extras]), encoding="utf-8")
            await q.message.reply_document(InputFile(exp, filename=ex_fn), caption="Extras")
        snap = context.user_data.get("sale_snapshot", {})
        await bump_stats(
            uid,
            cards_sold=len(main),
            total_sales=1,
            revenue=float(snap.get("rev", len(main)*SALE_PRICE)),
            total_profit=float(snap.get("profit", 0)),
        )
        reset_session(context)
        await send_start_screen(update, context)
        return ConversationHandler.END
    return SALE_POST

# ===================== REPLACE FLOW =====================
async def replace_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = update.message.text.strip()
    await update.message.reply_text("How Many Cards Are Being Replaced")
    return REPLACE_QTY

async def replace_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = int(re.sub(r"\D", "", update.message.text) or "0")
    context.user_data["target"] = qty
    await update.message.reply_text("Target Submitted\nSend Cards Or Drop .txt File To Continue")
    return REPLACE_WAIT_CARDS

async def replace_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new = await ingest_cards_message(update, context)
    if not new:
        await update.message.reply_text("No cards parsed.")
        return REPLACE_WAIT_CARDS
    context.user_data["pending_new"] = new
    await update.message.reply_text(f"Parsed {len(new)}. USA Or Foreign?", reply_markup=usa_foreign_kb())
    return REPLACE_USA_FOREIGN

async def replace_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    new = context.user_data.get("pending_new", [])
    merge_cards(session_cards(context), new)
    context.user_data["pending_new"] = []
    txt = (
        f"📋 PreSummary — /replace\n"
        f"Total Cards: {len(session_cards(context))}\n"
        f"Replacement Target: {context.user_data.get('target')}\n"
        f"Customer Name: {context.user_data.get('customer')}"
    )
    await q.edit_message_text(txt, reply_markup=replace_pre_kb())
    return REPLACE_PRE

async def replace_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return REPLACE_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return REPLACE_REMOVE
    if act == "check":
        await q.edit_message_text("Checking…")
        cards = await check_batch(session_cards(context), only_unchecked=True)
        context.user_data["cards"] = cards
        lives = [c for c in cards if c.get("live")]
        target = int(context.user_data.get("target", 0))
        extras = max(0, len(lives) - target)
        txt = (
            f"📋 PostSummary — /replace\n"
            f"Total Cards: {len(cards)}\n"
            f"Extras: {extras}\n"
            f"LiveRate: {FORCE_LIVE_RATE_DISPLAY if lives else 0}%\n"
            f"Replacement Target Reached: {len(lives) >= target}\n"
            f"Customer Name: {context.user_data.get('customer')}"
        )
        await q.edit_message_text(txt, reply_markup=replace_post_kb())
        return REPLACE_POST
    return REPLACE_PRE

async def replace_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cards"] = remove_by_last4(session_cards(context), update.message.text.split(","))
    txt = (
        f"📋 PreSummary — /replace\nTotal Cards: {len(session_cards(context))}\n"
        f"Replacement Target: {context.user_data.get('target')}\n"
        f"Customer Name: {context.user_data.get('customer')}"
    )
    await update.message.reply_text(txt, reply_markup=replace_pre_kb())
    return REPLACE_PRE

async def replace_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "add":
        context.user_data["batch_id"] = batch_id()
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return REPLACE_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return REPLACE_REMOVE
    if act == "send":
        uid = update.effective_user.id
        cards = [c for c in session_cards(context) if c.get("live")]
        target = int(context.user_data.get("target", 0))
        main = cards[:target] if target else cards
        extras = cards[target:] if target and len(cards) > target else []
        cust = re.sub(r"[^\w\-]+", "_", context.user_data.get("customer", "cust"))
        suf = file_id_suffix()
        main_fn = f"{cust}-{len(main)}-{suf}.txt"
        path = f"/tmp/{main_fn}"
        Path(path).write_text("\n\n".join([await format_card_block(c) for c in main] +
                              ["\n*** VOUCH AFTER USE — E$CO REPLACEMENT ***\n"]), encoding="utf-8")
        await q.message.reply_document(InputFile(path, filename=main_fn))
        if extras:
            ex_fn = f"Extras-{len(extras)}-{suf}.txt"
            Path(f"/tmp/{ex_fn}").write_text("\n\n".join([await format_card_block(c) for c in extras]), encoding="utf-8")
            await q.message.reply_document(InputFile(f"/tmp/{ex_fn}", filename=ex_fn))
        # subtract card cost from revenue/profit
        cost = len(main) * CARD_COST
        await bump_stats(uid, replacements_given=len(main), revenue=(-cost), total_profit=(-cost))
        reset_session(context)
        await send_start_screen(update, context)
        return ConversationHandler.END
    return REPLACE_POST

# ===================== TESTER FLOW =====================
async def tester_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["tester_kind"] = q.data.split(":")[1]
    await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
    return TESTER_WAIT_CARDS

async def tester_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new = await ingest_cards_message(update, context)
    if not new:
        await update.message.reply_text("No cards parsed.")
        return TESTER_WAIT_CARDS
    context.user_data["pending_new"] = new
    await update.message.reply_text(f"Parsed {len(new)}. USA Or Foreign?", reply_markup=usa_foreign_kb())
    return TESTER_USA_FOREIGN

async def tester_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    merge_cards(session_cards(context), context.user_data.get("pending_new", []))
    context.user_data["pending_new"] = []
    context.user_data["batch_id"] = context.user_data.get("batch_id") or batch_id()
    txt = await presummary_format(context)
    txt = txt.replace("Mode: Base", f"Mode: Tester/{context.user_data.get('tester_kind')}")
    await q.edit_message_text(txt, reply_markup=format_pre_kb())  # same buttons as format + set filename
    return TESTER_PRE

async def tester_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # reuse format callback data fmt:*
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "check":
        await q.edit_message_text("Checking…")
        context.user_data["cards"] = await check_batch(session_cards(context), only_unchecked=True)
        txt = await postsummary_format(context)
        await q.edit_message_text(txt, reply_markup=format_post_kb())
        return TESTER_POST
    if act == "setname":
        await q.edit_message_text("Send filename (without .txt):")
        return TESTER_SET_NAME
    if act == "add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TESTER_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return TESTER_REMOVE
    return TESTER_PRE

async def tester_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["filename"] = re.sub(r"[^\w\-]+", "_", update.message.text.strip())[:40]
    txt = await presummary_format(context)
    await update.message.reply_text(txt, reply_markup=format_pre_kb())
    return TESTER_PRE

async def tester_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cards"] = remove_by_last4(session_cards(context), update.message.text.split(","))
    txt = await presummary_format(context)
    await update.message.reply_text(txt, reply_markup=format_pre_kb())
    return TESTER_PRE

async def tester_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    if act == "add":
        context.user_data["batch_id"] = batch_id()
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TESTER_WAIT_CARDS
    if act == "remove":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return TESTER_REMOVE
    if act == "send":
        uid = update.effective_user.id
        cards = [c for c in session_cards(context) if c.get("live")] or session_cards(context)
        fn = context.user_data.get("filename") or f"Tester-{context.user_data.get('tester_kind')}-{file_id_suffix()}"
        path = f"/tmp/{fn}.txt"
        blocks = [await format_card_block(c, is_tester=True) for c in cards]
        blocks.append("\n❤️ Thank You For Choosing E$CO ❤️\n⭐ Please VOUCH ⭐\n")
        Path(path).write_text("\n\n".join(blocks), encoding="utf-8")
        await q.message.reply_document(InputFile(path, filename=f"{fn}.txt"))
        await bump_stats(uid, testers_given=len(cards))
        reset_session(context)
        await send_start_screen(update, context)
        return ConversationHandler.END
    return TESTER_POST

# ===================== RATE FLOW =====================
async def rate_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    act = q.data.split(":")[1]
    context.user_data["rate_act"] = act
    await q.edit_message_text("Send Bin 6 Digit Number")
    return RATE_BIN_WAIT

async def rate_bin_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = re.sub(r"\D", "", update.message.text)[:6]
    if len(bin6) != 6:
        await update.message.reply_text("Need 6 digits.")
        return RATE_BIN_WAIT
    context.user_data["bin"] = bin6
    info = bin_info(bin6)
    meta = await get_bin_meta(bin6)
    act = context.user_data.get("rate_act")
    header = (
        f"You Have Selected Bin {bin6}\n"
        f"{info.get('brand')} {info.get('type')} {info.get('level')}\n"
        f"{info.get('bank')} — {info.get('country')}\n"
        f"VR:{meta.get('vr_rating')} BinRate:{meta.get('bin_rating')} "
        f"Bal:{meta.get('balance_rating')} Sug:{meta.get('suggestion')} "
        f"ForcedVR:{meta.get('forced_vr')}\n"
    )
    if act == "setvr":
        await update.message.reply_text(header + "What Do You Want To Set The Vr Rating As (0-10)?")
        return RATE_VR_WAIT
    if act == "ratebin":
        await update.message.reply_text(header + "Rate this BIN 0-10:")
        return RATE_BIN_RATE_WAIT
    if act == "bal":
        await update.message.reply_text(header + "Set balance rating 0-10:")
        return RATE_BAL_WAIT
    if act == "sug":
        await update.message.reply_text(header + "Send suggestion text (e.g. AMAZON/FOOD/ONLINE):")
        return RATE_SUG_WAIT
    if act == "force":
        await update.message.reply_text(header + "Set Forced Vr Rating, Say Reset To Disable")
        return RATE_FORCE_WAIT
    return RATE_MENU

async def rate_vr_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = float(update.message.text.strip())
    await set_bin_field(context.user_data["bin"], "vr_rating", val)
    await update.message.reply_text(f"VR set to {val} for {context.user_data['bin']}")
    await send_start_screen(update, context)
    return ConversationHandler.END

async def rate_bin_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = float(update.message.text.strip())
    await set_bin_field(context.user_data["bin"], "bin_rating", val)
    await update.message.reply_text(f"Bin rating set to {val}")
    await send_start_screen(update, context)
    return ConversationHandler.END

async def rate_bal_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = float(update.message.text.strip())
    await set_bin_field(context.user_data["bin"], "balance_rating", val)
    await update.message.reply_text(f"Balance rating set to {val}")
    await send_start_screen(update, context)
    return ConversationHandler.END

async def rate_sug_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_bin_field(context.user_data["bin"], "suggestion", update.message.text.strip()[:80])
    await update.message.reply_text("Suggestion saved.")
    await send_start_screen(update, context)
    return ConversationHandler.END

async def rate_force_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if t.lower() == "reset":
        await set_bin_field(context.user_data["bin"], "forced_vr", None)
        await update.message.reply_text("Forced VR disabled.")
    else:
        val = float(re.sub(r"[^\d.]", "", t) or "0")
        await set_bin_field(context.user_data["bin"], "forced_vr", val)
        await update.message.reply_text(f"Forced VR {val}% on BIN {context.user_data['bin']}")
    await send_start_screen(update, context)
    return ConversationHandler.END

async def add_admin_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_admin"):
        return ConversationHandler.END
    try:
        new_id = int(re.sub(r"\D", "", update.message.text))
        ADMIN_IDS.add(new_id)
        await ensure_admin(new_id)
        await update.message.reply_text(f"Admin {new_id} added with empty stats.")
    except Exception:
        await update.message.reply_text("Invalid id.")
    context.user_data["await_admin"] = False
    await send_start_screen(update, context)
    return ConversationHandler.END

# slash command shortcuts
async def slash_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return ConversationHandler.END
    reset_session(context)
    context.user_data["mode"] = "format"
    context.user_data["batch_id"] = batch_id()
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return FORMAT_WAIT_CARDS

async def slash_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return ConversationHandler.END
    reset_session(context)
    await update.message.reply_text("Please Respond With The Customer Name")
    return SALE_NAME

async def slash_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return ConversationHandler.END
    reset_session(context)
    await update.message.reply_text("Who Is Being Replaced")
    return REPLACE_NAME

async def slash_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return ConversationHandler.END
    reset_session(context)
    await update.message.reply_text(
        "Is This Tester A Drop Or Gift?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Drop", callback_data="tester:drop"),
             InlineKeyboardButton("Gift", callback_data="tester:gift")]
        ])
    )
    return TESTER_TYPE

async def slash_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Bin VR", callback_data="rate:setvr")],
        [InlineKeyboardButton("Rate Bin", callback_data="rate:ratebin")],
        [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate:bal")],
        [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate:sug")],
        [InlineKeyboardButton("Force VR", callback_data="rate:force")],
        [InlineKeyboardButton("⬅ Back", callback_data="menu:home")],
    ])
    await update.message.reply_text("BIN Rate Menu", reply_markup=kb)
    return RATE_MENU

async def slash_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return
    credits = await storm_credits()
    await update.message.reply_text(f"Your Available Storm Credits Are {credits}")

async def slash_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update.effective_user.id):
        return
    st = await get_stats(update.effective_user.id)
    await update.message.reply_text(
        f"Cards Sold: {st.get('cards_sold',0)}\nTotal Sales: {st.get('total_sales',0)}\n"
        f"Revenue: ${st.get('revenue',0):.2f}\nTesters Given: {st.get('testers_given',0)}\n"
        f"Replacements Given: {st.get('replacements_given',0)}\nTotal Profit: ${st.get('total_profit',0):.2f}"
    )

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("format", slash_format),
            CommandHandler("sale", slash_sale),
            CommandHandler("replace", slash_replace),
            CommandHandler("tester", slash_tester),
            CommandHandler("rate", slash_rate),
            CallbackQueryHandler(menu_router, pattern=r"^menu:"),
            CallbackQueryHandler(tester_type, pattern=r"^tester:"),
            CallbackQueryHandler(rate_menu_cb, pattern=r"^rate:"),
        ],
        states={
            AUTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_recv)],
            FORMAT_WAIT_CARDS: [
                MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, format_recv_cards)
            ],
            FORMAT_USA_FOREIGN: [CallbackQueryHandler(format_geo, pattern=r"^geo:")],
            FORMAT_PRE: [CallbackQueryHandler(format_pre_cb, pattern=r"^fmt:")],
            FORMAT_POST: [CallbackQueryHandler(format_post_cb, pattern=r"^fmt:")],
            FORMAT_SET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, format_setname)],
            FORMAT_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, format_remove)],
            SALE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_name)],
            SALE_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_qty)],
            SALE_WAIT_CARDS: [
                MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, sale_recv)
            ],
            SALE_USA_FOREIGN: [CallbackQueryHandler(sale_geo, pattern=r"^geo:")],
            SALE_PRE: [CallbackQueryHandler(sale_pre_cb, pattern=r"^sale:")],
            SALE_POST: [CallbackQueryHandler(sale_post_cb, pattern=r"^sale:")],
            SALE_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_remove)],
            REPLACE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, replace_name)],
            REPLACE_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, replace_qty)],
            REPLACE_WAIT_CARDS: [
                MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, replace_recv)
            ],
            REPLACE_USA_FOREIGN: [CallbackQueryHandler(replace_geo, pattern=r"^geo:")],
            REPLACE_PRE: [CallbackQueryHandler(replace_pre_cb, pattern=r"^rep:")],
            REPLACE_POST: [CallbackQueryHandler(replace_post_cb, pattern=r"^rep:")],
            REPLACE_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, replace_remove)],
            TESTER_TYPE: [CallbackQueryHandler(tester_type, pattern=r"^tester:")],
            TESTER_WAIT_CARDS: [
                MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, tester_recv)
            ],
            TESTER_USA_FOREIGN: [CallbackQueryHandler(tester_geo, pattern=r"^geo:")],
            TESTER_PRE: [CallbackQueryHandler(tester_pre_cb, pattern=r"^fmt:")],
            TESTER_POST: [CallbackQueryHandler(tester_post_cb, pattern=r"^fmt:")],
            TESTER_SET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, tester_setname)],
            TESTER_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tester_remove)],
            RATE_MENU: [CallbackQueryHandler(rate_menu_cb, pattern=r"^rate:")],
            RATE_BIN_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_bin_wait)],
            RATE_VR_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_vr_set)],
            RATE_BIN_RATE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_bin_set)],
            RATE_BAL_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_bal_set)],
            RATE_SUG_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_sug_set)],
            RATE_FORCE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_force_set)],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(menu_router, pattern=r"^menu:home$"),
        ],
        allow_reentry=True,
        name="esco_panel",
        persistent=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("balance", slash_balance))
    app.add_handler(CommandHandler("stats", slash_stats))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    # global cancel
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    return app

async def _post_init(app: Application):
    await init_db()

def main():
    app = build_app()
    app.post_init = _post_init
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
