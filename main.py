# esco_seller_panel_bot.py
# Railway-ready Telegram "E$CO Seller Panel" bot
# Env (Railway): BOT_TOKEN, ADMIN_IDS (comma-sep), STORM_API_URL, STORM_USER_ID,
#                CARD_COST (default 0.35), SALE_PRICE_PER_CARD (default 5.0)
# Optional: DATA_DIR=/data  (persist JSON stats)

import os, re, json, random, asyncio, io
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# -------------------- CONFIG --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()}
STORM_API_URL = os.getenv("STORM_API_URL", "https://api.example-stormcheck.com")
STORM_USER_ID = os.getenv("STORM_USER_ID", "")
CARD_COST = float(os.getenv("CARD_COST", "0.35"))
SALE_PRICE = float(os.getenv("SALE_PRICE_PER_CARD", "5.0"))
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATS_FILE = DATA_DIR / "stats.json"
BIN_FILE = DATA_DIR / "bins.json"

# Conversation states
(
    WAIT_CARDS, WAIT_USA_FOREIGN, WAIT_FILENAME, WAIT_REMOVE,
    WAIT_CUSTOMER, WAIT_QTY, WAIT_TESTER_TYPE, WAIT_BIN,
    WAIT_VR, WAIT_RATE, WAIT_BAL_RATE, WAIT_SUGGEST, WAIT_FORCE_VR
) = range(13)

# -------------------- BIN DB --------------------
DEFAULT_BINS = {
    "410039": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "scheme": "visa", "rating": "8.5", "suggestion": "Amazon/Apple", "vr_force": None, "bal_rating": "7"},
    "410040": {"brand": "VISA", "type": "CREDIT", "level": "BUSINESS", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "scheme": "visa", "rating": "8.0", "suggestion": "B2B/Office", "vr_force": None, "bal_rating": "7"},
    "414720": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "scheme": "visa", "rating": "9.0", "suggestion": "Chase payees / Amazon", "vr_force": None, "bal_rating": "8"},
    "414740": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "scheme": "visa", "rating": "9.0", "suggestion": "Chase payees / Amazon", "vr_force": None, "bal_rating": "8"},
    "440066": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "BANK OF AMERICA - CONSUMER CREDIT", "country": "UNITED STATES", "scheme": "visa", "rating": "8.0", "suggestion": "Retail / digital", "vr_force": None, "bal_rating": "7"},
    "483312": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "scheme": "visa", "rating": "7.5", "suggestion": "Low-ticket auth", "vr_force": None, "bal_rating": "6"},
    "483316": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "scheme": "visa", "rating": "7.5", "suggestion": "Low-ticket auth", "vr_force": None, "bal_rating": "6"},
    "513371": {"brand": "MASTERCARD", "type": "CREDIT", "level": "STANDARD", "bank": "NEWDAY, LTD.", "country": "UNITED KINGDOM", "scheme": "mastercard", "rating": "6.5", "suggestion": "EU digital", "vr_force": None, "bal_rating": "5"},
    "513379": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "BANQUE FEDERATIVE DU CREDIT MUTUEL (BFCM)", "country": "FRANCE", "scheme": "mastercard", "rating": "6.0", "suggestion": "EU low-ticket", "vr_force": None, "bal_rating": "5"},
    "521729": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "COMMONWEALTH BANK OF AUSTRALIA", "country": "AUSTRALIA", "scheme": "mastercard", "rating": "6.5", "suggestion": "AU digital", "vr_force": None, "bal_rating": "5"},
    "534348": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CELTIC BANK CORPORATION", "country": "UNITED STATES", "scheme": "mastercard", "rating": "8.5", "suggestion": "US retail", "vr_force": None, "bal_rating": "7"},
    "542418": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "scheme": "mastercard", "rating": "9.0", "suggestion": "Amazon / high ticket", "vr_force": None, "bal_rating": "8"},
    "546616": {"brand": "MASTERCARD", "type": "CREDIT", "level": "WORLD", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "scheme": "mastercard", "rating": "9.0", "suggestion": "Premium digital", "vr_force": None, "bal_rating": "8"},
}

def load_bins() -> dict:
    if BIN_FILE.exists():
        try:
            return json.loads(BIN_FILE.read_text())
        except Exception:
            pass
    BIN_FILE.write_text(json.dumps(DEFAULT_BINS, indent=2))
    return dict(DEFAULT_BINS)

def save_bins(b: dict):
    BIN_FILE.write_text(json.dumps(b, indent=2))

BINS = load_bins()

# -------------------- STATS (per admin) --------------------
def default_stats():
    return {
        "cards_sold": 0,
        "total_sales": 0,
        "revenue": 0.0,
        "profit": 0.0,
        "testers_given": 0,
        "replacements_given": 0,
        "batches": 0,
    }

def load_all_stats() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except Exception:
            pass
    return {}

def save_all_stats(s: dict):
    STATS_FILE.write_text(json.dumps(s, indent=2))

def get_user_stats(uid: int) -> dict:
    all_s = load_all_stats()
    key = str(uid)
    if key not in all_s:
        all_s[key] = default_stats()
        save_all_stats(all_s)
    return all_s[key]

def update_user_stats(uid: int, **kwargs):
    all_s = load_all_stats()
    key = str(uid)
    st = all_s.get(key) or default_stats()
    for k, v in kwargs.items():
        if k in st and isinstance(st[k], (int, float)):
            st[k] = st[k] + v if isinstance(v, (int, float)) else v
        else:
            st[k] = v
    all_s[key] = st
    save_all_stats(all_s)

# -------------------- HELPERS --------------------
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def batch_id() -> str:
    return f"{random.randint(1000, 9999)}"

def get_random_ip() -> str:
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

CARD_RE = re.compile(
    r"(?P<pan>\d{13,19})[|/,:\s]+(?P<mm>\d{1,2})[|/,:\s]+(?P<yy>\d{2,4})[|/,:\s]+(?P<cvv>\d{3,4})"
    r"(?:[|/,:\s]+(?P<rest>.*))?",
    re.I
)

def parse_card_line(line: str) -> Optional[dict]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Prefer pipe-split (your dumps)
    parts = [p.strip() for p in line.split("|")]
    if len(parts) >= 3 and parts[0].isdigit():
        pan = re.sub(r"\D", "", parts[0])
        mm = parts[1].zfill(2)[-2:]
        yy = parts[2]
        if len(yy) == 4:
            yy = yy[-2:]
        cvv = parts[3] if len(parts) > 3 else "000"
        # name address city state zip country phone email — flexible
        name = parts[4] if len(parts) > 4 else "JOHN DOE"
        address = parts[5] if len(parts) > 5 else "123 MAIN ST"
        city = parts[6] if len(parts) > 6 else "CITY"
        state = parts[7] if len(parts) > 7 else "ST"
        zipcode = parts[8] if len(parts) > 8 else "00000"
        country = parts[9] if len(parts) > 9 else "US"
        phone = parts[10] if len(parts) > 10 else "0000000000"
        email = parts[11] if len(parts) > 11 else f"user{pan[-4:]}@gmail.com"
        return {
            "pan": pan, "mm": mm, "yy": yy[-2:], "cvv": cvv,
            "name": name, "address": address, "city": city, "state": state,
            "zipcode": zipcode, "country": country.upper()[:2] if len(country) <= 3 else country,
            "phone": phone, "email": email, "raw": line, "last4": pan[-4:],
            "bin": pan[:6], "live": True, "vr": 100,
        }
    m = CARD_RE.search(line)
    if not m:
        return None
    pan = m.group("pan")
    mm = m.group("mm").zfill(2)[-2:]
    yy = m.group("yy")[-2:]
    cvv = m.group("cvv")
    rest = (m.group("rest") or "").split("|")
    rest = [r.strip() for r in rest if r.strip()]
    name = rest[0] if rest else "JOHN DOE"
    address = rest[1] if len(rest) > 1 else "123 MAIN ST"
    city = rest[2] if len(rest) > 2 else "CITY"
    state = rest[3] if len(rest) > 3 else "ST"
    zipcode = rest[4] if len(rest) > 4 else "00000"
    country = rest[5] if len(rest) > 5 else "US"
    phone = rest[6] if len(rest) > 6 else "0000000000"
    email = rest[7] if len(rest) > 7 else f"user{pan[-4:]}@gmail.com"
    return {
        "pan": pan, "mm": mm, "yy": yy, "cvv": cvv,
        "name": name, "address": address, "city": city, "state": state,
        "zipcode": zipcode, "country": country, "phone": phone, "email": email,
        "raw": line, "last4": pan[-4:], "bin": pan[:6], "live": True, "vr": 100,
    }

def parse_cards_text(text: str) -> List[dict]:
    out = []
    for line in text.replace("\r", "\n").split("\n"):
        c = parse_card_line(line)
        if c:
            out.append(c)
    return out

def bin_info(bin6: str) -> dict:
    b = BINS.get(bin6) or {
        "brand": "UNKNOWN", "type": "CREDIT", "level": "STANDARD",
        "bank": "UNKNOWN", "country": "UNKNOWN", "scheme": "unknown",
        "rating": "5.0", "suggestion": "Test small", "vr_force": None, "bal_rating": "5"
    }
    return b

def format_card_block(c: dict, is_tester: bool = False) -> str:
    info = bin_info(c["bin"])
    vr = info.get("vr_force")
    if vr is None:
        vr = c.get("vr", 100)
    # Forced live rate display always 100 per your request
    vr_disp = 100
    country = c.get("country") or info.get("country", "US")
    lines = [
        "══════════════════════════════════════",
        f"🃏 LIVE • VR: {vr_disp}%",
        "══════════════════════════════════════",
        f"👤 Name    : {c.get('name', 'N/A')}",
        f"💳 Card    : {c['pan']}",
        f"📅 Expiry  : {c['mm']}/{c['yy']}",
        f"🔒 CVV     : {c['cvv']}",
        f"🏦 Bank    : {info.get('bank', 'UNKNOWN')}",
        f"🌍 Country : {country} • {info.get('brand', 'UNKNOWN')} {info.get('level', 'STANDARD')}",
        "",
        "📍 Billing Address:",
        f"   {c.get('address', 'N/A')}",
        f"   {c.get('city', '')}, {c.get('state', '')} {c.get('zipcode', '')}",
        f"   Phone  : {c.get('phone', 'N/A')}",
        f"   Email  : {c.get('email', 'N/A')}",
        "",
        f"🌐 IP      : {get_random_ip()}",
        f"🕒 Checked : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "══════════════════════════════════════",
        f"BIN Rate   : {info.get('rating', 'N/A')} | {info.get('suggestion', '')}",
        "══════════════════════════════════════",
    ]
    if is_tester:
        lines.append("❤️ Thank You For Choosing E$CO ❤️")
    lines.append("")
    lines.append("⭐ VOUCH E$CO — send voucher proof after hit. Fast replaces. ⭐")
    lines.append("⭐ Drop a vouch in the group / to seller. Quality > quantity. ⭐")
    return "\n".join(lines)

def format_file_content(cards: List[dict], is_tester: bool = False) -> str:
    header = [
        "╔════════════════════════════════════════╗",
        "║         E$CO FORMATTED LIVE CARDS      ║",
        "║   VOUCH AFTER HIT — KEEPS QUEUE FAST   ║",
        "║   Replaces on dead within window       ║",
        "╚════════════════════════════════════════╝",
        "",
    ]
    body = [format_card_block(c, is_tester=is_tester) for c in cards]
    footer = [
        "",
        "══════════════════════════════════════",
        "ALWAYS VOUCH — screenshots help next pull.",
        "E$CO Seller Panel — not responsible for misuse.",
        "══════════════════════════════════════",
    ]
    return "\n".join(header + body + footer)

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Format", callback_data="mode:format"),
         InlineKeyboardButton("Sale", callback_data="mode:sale")],
        [InlineKeyboardButton("Replace", callback_data="mode:replace"),
         InlineKeyboardButton("Tester", callback_data="mode:tester")],
        [InlineKeyboardButton("Rate / BIN", callback_data="mode:rate"),
         InlineKeyboardButton("Balance", callback_data="mode:balance")],
        [InlineKeyboardButton("Stats", callback_data="mode:stats")],
    ])

def pre_kb(mode: str):
    rows = [
        [InlineKeyboardButton("Check", callback_data="act:check"),
         InlineKeyboardButton("Set Filename", callback_data="act:setfn")],
        [InlineKeyboardButton("Add More Cards", callback_data="act:add"),
         InlineKeyboardButton("Remove Cards", callback_data="act:remove")],
        [InlineKeyboardButton("Cancel", callback_data="act:cancel")],
    ]
    if mode == "sale":
        rows = [
            [InlineKeyboardButton("Add More Cards", callback_data="act:add"),
             InlineKeyboardButton("Remove Cards", callback_data="act:remove")],
            [InlineKeyboardButton("Check", callback_data="act:check"),
             InlineKeyboardButton("Cancel", callback_data="act:cancel")],
        ]
    return InlineKeyboardMarkup(rows)

def post_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="act:send"),
         InlineKeyboardButton("Add More Cards", callback_data="act:add")],
        [InlineKeyboardButton("Remove Cards", callback_data="act:remove"),
         InlineKeyboardButton("Cancel", callback_data="act:cancel")],
    ])

def usa_foreign_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data="geo:usa"),
         InlineKeyboardButton("Foreign", callback_data="geo:foreign")],
    ])

def rate_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Bin VR", callback_data="rate:setvr")],
        [InlineKeyboardButton("Rate Bin", callback_data="rate:ratebin")],
        [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate:bal")],
        [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate:suggest")],
        [InlineKeyboardButton("Force VR", callback_data="rate:force")],
        [InlineKeyboardButton("Cancel", callback_data="act:cancel")],
    ])

def session_clear(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

def ensure_session(context, mode: str):
    ud = context.user_data
    ud.setdefault("mode", mode)
    ud.setdefault("cards", [])
    ud.setdefault("filename", None)
    ud.setdefault("batch", batch_id())
    ud.setdefault("geo", None)
    ud.setdefault("customer", None)
    ud.setdefault("target", 0)
    ud.setdefault("tester_type", None)
    ud.setdefault("phase", "pre")  # pre | post
    ud.setdefault("checked", False)

# -------------------- AUTH + START --------------------
async def guard(update: Update) -> bool:
    uid = update.effective_user.id
    if not is_admin(uid):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        elif update.callback_query:
            await update.callback_query.answer("Unauthorized", show_alert=True)
        return False
    return True

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    session_clear(context)
    u = update.effective_user
    text = f"E$CO Seller Panel\nWelcome @{u.username or u.first_name or u.id}"
    await update.message.reply_text(text, reply_markup=main_keyboard())
    return ConversationHandler.END

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    session_clear(context)
    u = update.effective_user
    await update.message.reply_text(
        f"E$CO Seller Panel\nWelcome @{u.username or u.first_name or u.id}\nAdmin panel:",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        "Commands:\n/start — panel\n/cancel — admin panel\n/format /sale /replace /tester /rate /stats /balance /list"
    )

async def show_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    text = f"E$CO Seller Panel\nWelcome @{u.username or u.first_name or u.id}"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_keyboard())

# -------------------- PRE/POST SUMMARY TEXT --------------------
def pre_summary_text(ud: dict) -> str:
    mode = ud.get("mode", "format")
    cards = ud.get("cards", [])
    fn = ud.get("filename") or f"Batch-{ud.get('batch', '0000')}"
    if mode == "format" or mode == "tester":
        return (
            f"PreSummary\n"
            f"Total Cards: {len(cards)}\n"
            f"Mode: {'Base' if mode=='format' else 'Tester'}\n"
            f"FileName: {fn if ud.get('filename') else 'N/A'}\n"
            f"Geo: {ud.get('geo') or 'N/A'}\n"
            f"TesterType: {ud.get('tester_type') or 'N/A'}"
        )
    if mode == "sale":
        target = int(ud.get("target") or 0)
        rev = target * SALE_PRICE
        return (
            f"PreSummary\n"
            f"Customer: {ud.get('customer')}\n"
            f"Target: {target}\n"
            f"Total Cards: {len(cards)}\n"
            f"Mode: Sale\n"
            f"Total Revenue (est): ${rev:.2f}\n"
            f"+ (Sale Cost ${SALE_PRICE:.2f}/card)"
        )
    if mode == "replace":
        return (
            f"PreSummary\n"
            f"Total Cards: {len(cards)}\n"
            f"Replacement Target: {ud.get('target')}\n"
            f"Customer Name: {ud.get('customer')}"
        )
    return f"PreSummary\nTotal Cards: {len(cards)}"

def post_summary_text(ud: dict) -> str:
    mode = ud.get("mode", "format")
    cards = ud.get("cards", [])
    # All live rates = 100 → all cards "live"
    live = [c for c in cards if c.get("live", True)]
    live_n = len(live)
    total = len(cards)
    live_rate = 100.0 if total else 0.0
    if mode in ("format", "tester"):
        return (
            f"PostSummary\n"
            f"Total Cards: {total}\n"
            f"LiveRate: {live_rate:.0f}%\n"
            f"Total Live: {live_n}"
        )
    if mode == "sale":
        target = int(ud.get("target") or 0)
        extras = max(0, live_n - target)
        reached = live_n >= target
        sold = min(live_n, target) if target else live_n
        revenue = sold * SALE_PRICE
        profit = revenue - (live_n * CARD_COST)
        return (
            f"PostSummary\n"
            f"Total Cards: {total}\n"
            f"Total Live: {live_n}\n"
            f"Extras: {extras}\n"
            f"Target Reached: {reached}\n"
            f"Profit Made: ${profit:.2f}\n"
            f"Total Revenue After Sale: ${revenue:.2f}"
        )
    if mode == "replace":
        target = int(ud.get("target") or 0)
        extras = max(0, live_n - target)
        reached = live_n >= target
        return (
            f"PostSummary\n"
            f"Total Cards: {total}\n"
            f"Extras: {extras}\n"
            f"LiveRate: {live_rate:.0f}%\n"
            f"Replacement Target Reached: {reached}\n"
            f"Customer Name: {ud.get('customer')}"
        )
    return f"PostSummary\nTotal: {total}"

async def send_pre(update, context):
    ud = context.user_data
    ud["phase"] = "pre"
    q = update.callback_query
    text = pre_summary_text(ud)
    kb = pre_kb(ud.get("mode", "format"))
    if q:
        await q.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)

async def send_post(update, context):
    ud = context.user_data
    ud["phase"] = "post"
    ud["checked"] = True
    # Mark all live @ 100%
    for c in ud.get("cards", []):
        c["live"] = True
        c["vr"] = 100
    q = update.callback_query
    text = post_summary_text(ud)
    if q:
        await q.edit_message_text(text, reply_markup=post_kb())
    else:
        await update.effective_message.reply_text(text, reply_markup=post_kb())

# -------------------- MODE ENTRY --------------------
async def on_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await guard(update):
        return ConversationHandler.END
    data = q.data.split(":", 1)[1]
    session_clear(context)

    if data == "stats":
        st = get_user_stats(update.effective_user.id)
        await q.edit_message_text(
            f"Stats\n"
            f"Cards Sold: {st['cards_sold']}\n"
            f"Total Sales: {st['total_sales']}\n"
            f"Revenue: ${st['revenue']:.2f}\n"
            f"Testers Given: {st['testers_given']}\n"
            f"Replacements Given: {st['replacements_given']}\n"
            f"Total Profit: ${st['profit']:.2f}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="act:cancel")]])
        )
        return ConversationHandler.END

    if data == "balance":
        # Storm credits via /user path — plug your real HTTP client
        credits = await fetch_storm_credits()
        await q.edit_message_text(
            f"Your Available Storm Credits Are {credits}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="act:cancel")]])
        )
        return ConversationHandler.END

    if data == "rate":
        ensure_session(context, "rate")
        await q.edit_message_text("BIN Rate Menu", reply_markup=rate_menu_kb())
        return WAIT_BIN

    ensure_session(context, data)

    if data == "format":
        await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
        return WAIT_CARDS

    if data == "sale":
        await q.edit_message_text("Please Respond With The Customer Name")
        return WAIT_CUSTOMER

    if data == "replace":
        await q.edit_message_text("Who Is Being Replaced")
        return WAIT_CUSTOMER

    if data == "tester":
        await q.edit_message_text(
            "Is This Tester A Drop Or Gift?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Drop", callback_data="tester:drop"),
                 InlineKeyboardButton("Gift", callback_data="tester:gift")],
                [InlineKeyboardButton("Cancel", callback_data="act:cancel")],
            ])
        )
        return WAIT_TESTER_TYPE

    return ConversationHandler.END

async def fetch_storm_credits() -> str:
    """GET STORM_API_URL/user — parse credits. Replace with real request."""
    try:
        import urllib.request
        url = f"{STORM_API_URL.rstrip('/')}/user"
        if STORM_USER_ID:
            url += f"?id={STORM_USER_ID}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            js = json.loads(raw)
            # common shapes
            if isinstance(js, dict):
                if "credits" in js:
                    return str(js["credits"])
                if "data" in js and isinstance(js["data"], dict) and "credits" in js["data"]:
                    return str(js["data"]["credits"])
            return "N/A"
    except Exception:
        return "N/A (set STORM_API_URL)"

# -------------------- CUSTOMER / QTY / TESTER --------------------
async def on_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    name = update.message.text.strip()
    context.user_data["customer"] = name
    mode = context.user_data.get("mode")
    if mode == "sale":
        await update.message.reply_text(f'How Many Cards Is "{name}" Purchasing')
        return WAIT_QTY
    if mode == "replace":
        await update.message.reply_text("How Many Cards Are Being Replaced")
        return WAIT_QTY
    return WAIT_CARDS

async def on_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("Number only.")
        return WAIT_QTY
    context.user_data["target"] = int(txt)
    mode = context.user_data.get("mode")
    if mode == "sale":
        await update.message.reply_text("Target Set")
        # sale: can go pre with 0 cards then add
        await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
        return WAIT_CARDS
    if mode == "replace":
        await update.message.reply_text("Target Submitted")
        await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
        return WAIT_CARDS
    return WAIT_CARDS

async def on_tester_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("tester:"):
        context.user_data["tester_type"] = q.data.split(":")[1]
        context.user_data["mode"] = "tester"
        await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
        return WAIT_CARDS
    return ConversationHandler.END

# -------------------- CARDS INGEST --------------------
async def on_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = await f.download_as_bytearray()
        text = bytes(bio).decode("utf-8", errors="ignore")
    elif update.message.text:
        text = update.message.text
    else:
        await update.message.reply_text("Send cards text or .txt file")
        return WAIT_CARDS

    new_cards = parse_cards_text(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed. Use pan|mm|yy|cvv|name|addr|city|state|zip|cc|phone|email")
        return WAIT_CARDS

    ud = context.user_data
    ud.setdefault("cards", [])
    # new batch id whenever cards added
    ud["batch"] = batch_id()
    ud["cards"].extend(new_cards)
    update_user_stats(update.effective_user.id, batches=1)

    await update.message.reply_text(
        f"Parsed {len(new_cards)} cards (session total {len(ud['cards'])}).\nUSA Or Foreign?",
        reply_markup=usa_foreign_kb(),
    )
    return WAIT_USA_FOREIGN

async def on_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    geo = q.data.split(":")[1]
    context.user_data["geo"] = geo
    # optional filter display only — keep all cards stored
    await send_pre(update, context)
    return WAIT_CARDS  # stay in flow; actions via callback

# -------------------- ACTIONS (check/add/remove/send/cancel/setfn) --------------------
async def on_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await guard(update):
        return ConversationHandler.END
    act = q.data.split(":", 1)[1]
    ud = context.user_data

    if act == "cancel":
        session_clear(context)
        await show_panel(update, context)
        return ConversationHandler.END

    if act == "add":
        ud["phase"] = ud.get("phase") or "pre"
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return WAIT_CARDS

    if act == "remove":
        await q.edit_message_text("Send Last 4# Seperated By Commas Of The Card(s) You Want Removed")
        return WAIT_REMOVE

    if act == "setfn":
        await q.edit_message_text("Send filename (without .txt)")
        return WAIT_FILENAME

    if act == "check":
        # "check" → all live 100%
        await send_post(update, context)
        return WAIT_CARDS

    if act == "send":
        cards = ud.get("cards") or []
        if not cards:
            await q.edit_message_text("No cards.", reply_markup=main_keyboard())
            return ConversationHandler.END
        mode = ud.get("mode")
        is_tester = mode == "tester"
        live = [c for c in cards if c.get("live", True)]
        # force live
        live = cards
        for c in live:
            c["live"] = True
            c["vr"] = 100

        bid = ud.get("batch") or batch_id()
        uid = update.effective_user.id

        if mode == "format" or mode == "tester":
            fn = ud.get("filename") or f"Batch-{bid}"
            if not fn.endswith(".txt"):
                fn += ".txt"
            content = format_file_content(live, is_tester=is_tester)
            buf = io.BytesIO(content.encode("utf-8"))
            buf.name = fn
            await q.message.reply_document(document=InputFile(buf), caption="E$CO formatted — VOUCH after hits")
            if mode == "tester":
                update_user_stats(uid, testers_given=len(live))
            await q.message.reply_text("File sent.", reply_markup=main_keyboard())
            session_clear(context)
            return ConversationHandler.END

        if mode == "sale":
            target = int(ud.get("target") or 0)
            customer = ud.get("customer") or "Customer"
            primary = live[:target] if target else live
            extras = live[target:] if target and len(live) > target else []
            sold_n = len(primary)
            revenue = sold_n * SALE_PRICE
            cost = len(live) * CARD_COST
            profit = revenue - cost
            fn = f"{customer}-{len(primary)}-{bid}.txt"
            content = format_file_content(primary, is_tester=False)
            buf = io.BytesIO(content.encode("utf-8"))
            buf.name = fn
            await q.message.reply_document(document=InputFile(buf), caption=f"Sale {customer} — VOUCH pls")
            if extras:
                fn2 = f"Extras-{len(extras)}-{bid}.txt"
                buf2 = io.BytesIO(format_file_content(extras).encode("utf-8"))
                buf2.name = fn2
                await q.message.reply_document(document=InputFile(buf2), caption="Extras")
            update_user_stats(
                uid,
                cards_sold=sold_n,
                total_sales=1,
                revenue=revenue,
                profit=profit,
            )
            await q.message.reply_text(
                f"Sale booked. Revenue +${revenue:.2f} Profit ${profit:.2f}",
                reply_markup=main_keyboard(),
            )
            session_clear(context)
            return ConversationHandler.END

        if mode == "replace":
            target = int(ud.get("target") or 0)
            customer = ud.get("customer") or "Customer"
            primary = live[:target] if target else live
            extras = live[target:] if target and len(live) > target else []
            cost = len(live) * CARD_COST
            # subtract card cost from revenue/profit
            update_user_stats(uid, replacements_given=len(primary), revenue=(-cost), profit=(-cost))
            fn = f"{customer}-{len(primary)}-{bid}.txt"
            buf = io.BytesIO(format_file_content(primary).encode("utf-8"))
            buf.name = fn
            await q.message.reply_document(document=InputFile(buf), caption=f"Replace {customer}")
            if extras:
                fn2 = f"Extras-{len(extras)}-{bid}.txt"
                buf2 = io.BytesIO(format_file_content(extras).encode("utf-8"))
                buf2.name = fn2
                await q.message.reply_document(document=InputFile(buf2), caption="Extras")
            await q.message.reply_text("Replace file(s) sent. Card cost subtracted.", reply_markup=main_keyboard())
            session_clear(context)
            return ConversationHandler.END

        await q.message.reply_text("Done", reply_markup=main_keyboard())
        session_clear(context)
        return ConversationHandler.END

    return WAIT_CARDS

async def on_remove_last4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    last4s = {x.strip() for x in raw.split(",") if x.strip()}
    cards = context.user_data.get("cards") or []
    kept = [c for c in cards if c.get("last4") not in last4s]
    removed = len(cards) - len(kept)
    context.user_data["cards"] = kept
    context.user_data["batch"] = batch_id()
    await update.message.reply_text(f"Removed {removed}. Remaining {len(kept)}.")
    # re-show current phase summary
    class Fake:
        pass
    # send as new message
    if context.user_data.get("phase") == "post":
        await update.message.reply_text(post_summary_text(context.user_data), reply_markup=post_kb())
    else:
        await update.message.reply_text(pre_summary_text(context.user_data), reply_markup=pre_kb(context.user_data.get("mode", "format")))
    return WAIT_CARDS

async def on_filename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    fn = update.message.text.strip().replace(".txt", "")
    context.user_data["filename"] = fn
    await update.message.reply_text(f"Filename set: {fn}.txt")
    await update.message.reply_text(pre_summary_text(context.user_data), reply_markup=pre_kb(context.user_data.get("mode", "format")))
    return WAIT_CARDS

# -------------------- RATE / BIN FLOW --------------------
async def on_rate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await guard(update):
        return ConversationHandler.END
    if q.data == "act:cancel":
        session_clear(context)
        await show_panel(update, context)
        return ConversationHandler.END
    kind = q.data.split(":")[1]
    context.user_data["rate_kind"] = kind
    await q.edit_message_text("Send Bin 6 Digit Number")
    return WAIT_BIN

async def on_bin_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    # may come from rate callbacks already set kind
    txt = update.message.text.strip() if update.message else ""
    if update.callback_query and update.callback_query.data.startswith("rate:"):
        return await on_rate_menu(update, context)

    bin6 = re.sub(r"\D", "", txt)[:6]
    if len(bin6) != 6:
        await update.message.reply_text("Need 6-digit BIN")
        return WAIT_BIN
    context.user_data["bin"] = bin6
    info = bin_info(bin6)
    if bin6 not in BINS:
        BINS[bin6] = info
        save_bins(BINS)
    kind = context.user_data.get("rate_kind", "setvr")
    await update.message.reply_text(
        f"You Have Selected Bin {bin6}\n"
        f"Brand: {info.get('brand')} | {info.get('level')}\n"
        f"Bank: {info.get('bank')}\n"
        f"Country: {info.get('country')}\n"
        f"VR force: {info.get('vr_force')}\n"
        f"Rating: {info.get('rating')} | Bal: {info.get('bal_rating')}\n"
        f"Suggestion: {info.get('suggestion')}"
    )
    if kind == "setvr":
        await update.message.reply_text("What Do You Want To Set The Vr Rating As (0-10)")
        return WAIT_VR
    if kind == "ratebin":
        await update.message.reply_text("Rate this BIN 0-10")
        return WAIT_RATE
    if kind == "bal":
        await update.message.reply_text("Set Bin Balance Rating 0-10")
        return WAIT_BAL_RATE
    if kind == "suggest":
        await update.message.reply_text("Send suggestion places to use BIN")
        return WAIT_SUGGEST
    if kind == "force":
        await update.message.reply_text("Set Forced Vr Rating, Say Reset To Disable")
        return WAIT_FORCE_VR
    return ConversationHandler.END

async def _save_bin_field(update, context, field, value):
    bin6 = context.user_data.get("bin")
    if bin6 not in BINS:
        BINS[bin6] = bin_info(bin6)
    BINS[bin6][field] = value
    save_bins(BINS)
    await update.message.reply_text(f"BIN {bin6} {field} = {value}")
    await update.message.reply_text("E$CO Seller Panel", reply_markup=main_keyboard())

async def on_vr(update, context):
    v = update.message.text.strip()
    await _save_bin_field(update, context, "rating", v)  # VR rating store on rating field too
    # also mirror
    bin6 = context.user_data.get("bin")
    BINS[bin6]["vr_rating"] = v
    save_bins(BINS)
    return ConversationHandler.END

async def on_rate_val(update, context):
    v = update.message.text.strip()
    await _save_bin_field(update, context, "rating", v)
    return ConversationHandler.END

async def on_bal_rate(update, context):
    v = update.message.text.strip()
    await _save_bin_field(update, context, "bal_rating", v)
    return ConversationHandler.END

async def on_suggest(update, context):
    v = update.message.text.strip()
    await _save_bin_field(update, context, "suggestion", v)
    return ConversationHandler.END

async def on_force_vr(update, context):
    v = update.message.text.strip()
    if v.lower() == "reset":
        v = None
    await _save_bin_field(update, context, "vr_force", v if v is None else v.replace("%", ""))
    return ConversationHandler.END

# -------------------- COMMAND SHORTCUTS --------------------
async def cmd_format(update, context):
    if not await guard(update):
        return ConversationHandler.END
    session_clear(context)
    ensure_session(context, "format")
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return WAIT_CARDS

async def cmd_sale(update, context):
    if not await guard(update):
        return ConversationHandler.END
    session_clear(context)
    ensure_session(context, "sale")
    await update.message.reply_text("Please Respond With The Customer Name")
    return WAIT_CUSTOMER

async def cmd_replace(update, context):
    if not await guard(update):
        return ConversationHandler.END
    session_clear(context)
    ensure_session(context, "replace")
    await update.message.reply_text("Who Is Being Replaced")
    return WAIT_CUSTOMER

async def cmd_tester(update, context):
    if not await guard(update):
        return ConversationHandler.END
    session_clear(context)
    ensure_session(context, "tester")
    await update.message.reply_text(
        "Is This Tester A Drop Or Gift?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Drop", callback_data="tester:drop"),
             InlineKeyboardButton("Gift", callback_data="tester:gift")],
        ])
    )
    return WAIT_TESTER_TYPE

async def cmd_rate(update, context):
    if not await guard(update):
        return ConversationHandler.END
    ensure_session(context, "rate")
    await update.message.reply_text("BIN Rate Menu", reply_markup=rate_menu_kb())
    return WAIT_BIN

async def cmd_stats(update, context):
    if not await guard(update):
        return
    st = get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        f"Stats\nCards Sold: {st['cards_sold']}\nTotal Sales: {st['total_sales']}\n"
        f"Revenue: ${st['revenue']:.2f}\nTesters Given: {st['testers_given']}\n"
        f"Replacements Given: {st['replacements_given']}\nTotal Profit: ${st['profit']:.2f}"
    )

async def cmd_balance(update, context):
    if not await guard(update):
        return
    credits = await fetch_storm_credits()
    await update.message.reply_text(f"Your Available Storm Credits Are {credits}")

# -------------------- MAIN --------------------
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
            CallbackQueryHandler(on_mode, pattern=r"^mode:"),
            CallbackQueryHandler(on_rate_menu, pattern=r"^rate:"),
            CallbackQueryHandler(on_tester_type, pattern=r"^tester:"),
        ],
        states={
            WAIT_CARDS: [
                MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, on_cards),
                CallbackQueryHandler(on_geo, pattern=r"^geo:"),
                CallbackQueryHandler(on_action, pattern=r"^act:"),
                CallbackQueryHandler(on_tester_type, pattern=r"^tester:"),
            ],
            WAIT_USA_FOREIGN: [
                CallbackQueryHandler(on_geo, pattern=r"^geo:"),
                CallbackQueryHandler(on_action, pattern=r"^act:"),
            ],
            WAIT_FILENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_filename)],
            WAIT_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_remove_last4)],
            WAIT_CUSTOMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_customer)],
            WAIT_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_qty)],
            WAIT_TESTER_TYPE: [CallbackQueryHandler(on_tester_type, pattern=r"^tester:"),
                               CallbackQueryHandler(on_action, pattern=r"^act:")],
            WAIT_BIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_bin_number),
                CallbackQueryHandler(on_rate_menu, pattern=r"^rate:"),
                CallbackQueryHandler(on_action, pattern=r"^act:"),
            ],
            WAIT_VR: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_vr)],
            WAIT_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_rate_val)],
            WAIT_BAL_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_bal_rate)],
            WAIT_SUGGEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_suggest)],
            WAIT_FORCE_VR: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_force_vr)],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_action, pattern=r"^act:cancel$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("balance", cmd_balance))
    # global cancel button
    app.add_handler(CallbackQueryHandler(on_action, pattern=r"^act:"))
    return app

if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN.startswith("YOUR_"):
        raise SystemExit("Set BOT_TOKEN env")
    application = build_app()
    print("E$CO Seller Panel bot starting…")
    application.run_polling(drop_pending_updates=True)
