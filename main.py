# main.py — Private Seller Panel (Telegram)
# Railway: set BOT_TOKEN, ADMIN_IDS (comma-sep), optional API_URL
# Fix for your crash: range(N) must match the exact number of unpacked names (was 28 vs 27).

import os, re, json, random, io
from datetime import datetime, timezone
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)

# ───────────────────────── CONFIG ─────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS = set(
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "123456789").split(",") if x.strip()
)
# Optional external checker URL (show-only; live rate forced 100%)
API_URL = os.environ.get("API_URL", "")

DATA_DIR = os.environ.get("DATA_DIR", ".")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
STOCK_FILE = os.path.join(DATA_DIR, "stockpile.json")
BINDB_FILE = os.path.join(DATA_DIR, "bins_db.json")
BATCH_FILE = os.path.join(DATA_DIR, "batch_counter.txt")

# Conversation states — MUST equal len(range(...)) on the right-hand side
(
    MENU,
    FMT_WAIT_CARDS, FMT_USA_FOR, FMT_PRE, FMT_POST, FMT_REMOVE, FMT_FNAME,
    SALE_NAME, SALE_QTY, SALE_WAIT_CARDS, SALE_USA_FOR, SALE_PRE, SALE_POST, SALE_REMOVE,
    REP_NAME, REP_QTY, REP_WAIT_CARDS, REP_USA_FOR, REP_PRE, REP_POST, REP_REMOVE,
    TEST_TYPE, TEST_WAIT_CARDS, TEST_USA_FOR, TEST_PRE, TEST_POST, TEST_REMOVE, TEST_FNAME,
    RATE_MENU, RATE_BIN, RATE_VALUE, RATE_SUGGEST, RATE_FORCE,
    SETTINGS_MENU, SETTINGS_VALUE,
    STOCK_MENU, STOCK_BIN, STOCK_AMT, STOCK_FNAME, STOCK_SEARCH,
) = range(40)  # 40 names ↔ range(40)  — fixes ValueError too many/few to unpack

# ───────────────────────── BIN DB (seed + file) ─────────────────────────
DEFAULT_BINS = {
    "410039": {"scheme": "visa", "brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL",
               "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "cc": "US",
               "rating": "10/10", "vr": 100, "balance_rating": "9/10", "suggestion": "Amazon/Digital", "force_vr": None},
    "410040": {"scheme": "visa", "brand": "VISA", "type": "CREDIT", "level": "BUSINESS",
               "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "cc": "US",
               "rating": "10/10", "vr": 100, "balance_rating": "9/10", "suggestion": "Amazon/Digital", "force_vr": None},
    "414720": {"scheme": "visa", "brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL",
               "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "cc": "US",
               "rating": "9/10", "vr": 100, "balance_rating": "8/10", "suggestion": "Retail/POS", "force_vr": None},
    "414740": {"scheme": "visa", "brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL",
               "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "cc": "US",
               "rating": "9/10", "vr": 100, "balance_rating": "8/10", "suggestion": "Retail/POS", "force_vr": None},
    "440066": {"scheme": "visa", "brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL",
               "bank": "BANK OF AMERICA - CONSUMER CREDIT", "country": "UNITED STATES", "cc": "US",
               "rating": "8/10", "vr": 100, "balance_rating": "8/10", "suggestion": "Online", "force_vr": None},
    "483312": {"scheme": "visa", "brand": "VISA", "type": "DEBIT", "level": "CLASSIC",
               "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "cc": "US",
               "rating": "7/10", "vr": 100, "balance_rating": "7/10", "suggestion": "Low ticket", "force_vr": None},
    "483316": {"scheme": "visa", "brand": "VISA", "type": "DEBIT", "level": "CLASSIC",
               "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "cc": "US",
               "rating": "7/10", "vr": 100, "balance_rating": "7/10", "suggestion": "Low ticket", "force_vr": None},
    "513371": {"scheme": "mastercard", "brand": "MASTERCARD", "type": "CREDIT", "level": "STANDARD",
               "bank": "NEWDAY, LTD.", "country": "UNITED KINGDOM", "cc": "GB",
               "rating": "6/10", "vr": 100, "balance_rating": "6/10", "suggestion": "EU digital", "force_vr": None},
    "513379": {"scheme": "mastercard", "brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD",
               "bank": "BANQUE FEDERATIVE DU CREDIT MUTUEL (BFCM)", "country": "FRANCE", "cc": "FR",
               "rating": "6/10", "vr": 100, "balance_rating": "6/10", "suggestion": "EU digital", "force_vr": None},
    "521729": {"scheme": "mastercard", "brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD",
               "bank": "COMMONWEALTH BANK OF AUSTRALIA", "country": "AUSTRALIA", "cc": "AU",
               "rating": "6/10", "vr": 100, "balance_rating": "6/10", "suggestion": "AU local", "force_vr": None},
    "534348": {"scheme": "mastercard", "brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM",
               "bank": "CELTIC BANK CORPORATION", "country": "UNITED STATES", "cc": "US",
               "rating": "8/10", "vr": 100, "balance_rating": "8/10", "suggestion": "Online", "force_vr": None},
    "542418": {"scheme": "mastercard", "brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM",
               "bank": "CITIBANK N.A.", "country": "UNITED STATES", "cc": "US",
               "rating": "9/10", "vr": 100, "balance_rating": "9/10", "suggestion": "Amazon", "force_vr": None},
    "546616": {"scheme": "mastercard", "brand": "MASTERCARD", "type": "CREDIT", "level": "WORLD",
               "bank": "CITIBANK N.A.", "country": "UNITED STATES", "cc": "US",
               "rating": "9/10", "vr": 100, "balance_rating": "9/10", "suggestion": "High ticket", "force_vr": None},
}

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_bins():
    db = load_json(BINDB_FILE, {})
    if not db:
        db = DEFAULT_BINS.copy()
        save_json(BINDB_FILE, db)
    # merge defaults for missing keys
    for k, v in DEFAULT_BINS.items():
        if k not in db:
            db[k] = v
    return db

def save_bins(db):
    save_json(BINDB_FILE, db)

def default_settings():
    return {"sale_price": 5.0, "card_cost": 1.0}

def load_settings():
    s = load_json(SETTINGS_FILE, default_settings())
    for k, v in default_settings().items():
        s.setdefault(k, v)
    return s

def save_settings(s):
    save_json(SETTINGS_FILE, s)

def default_stats():
    return {
        "cards_sold": 0, "total_sales": 0, "revenue": 0.0,
        "testers_given": 0, "replacements_given": 0, "total_profit": 0.0
    }

def load_all_stats():
    return load_json(STATS_FILE, {})

def save_all_stats(st):
    save_json(STATS_FILE, st)

def get_user_stats(uid):
    st = load_all_stats()
    key = str(uid)
    if key not in st:
        st[key] = default_stats()
        save_all_stats(st)
    return st[key]

def set_user_stats(uid, user_st):
    st = load_all_stats()
    st[str(uid)] = user_st
    save_all_stats(st)

def load_stock():
    return load_json(STOCK_FILE, {})  # bin -> qty

def save_stock(stock):
    save_json(STOCK_FILE, stock)

def next_batch():
    try:
        n = int(open(BATCH_FILE).read().strip()) + 1
    except Exception:
        n = 1
    with open(BATCH_FILE, "w") as f:
        f.write(str(n))
    return n

# ───────────────────────── PARSE / FORMAT ─────────────────────────
# Input: pan|mm/yy|cvv|name|street|city|state|zip|cc|phone|email|ip
CARD_RE = re.compile(
    r"^\s*(\d{13,19})\|(\d{1,2}/\d{2,4})\|(\d{3,4})\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|?([^|]*)\s*$"
)

def get_random_ip():
    return ".".join(str(random.randint(1, 254)) for _ in range(4))

def parse_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = CARD_RE.match(line)
    if not m:
        # try loose split
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            return None
        while len(parts) < 12:
            parts.append("")
        pan, exp, cvv = parts[0], parts[1], parts[2]
        name, street, city, state, zipc, cc, phone, email, ip = parts[3:12]
    else:
        pan, exp, cvv, name, street, city, state, zipc, cc, phone, email, ip = m.groups()
    pan = re.sub(r"\D", "", pan)
    if len(pan) < 13:
        return None
    bin6 = pan[:6]
    return {
        "pan": pan, "exp": exp, "cvv": cvv, "name": name or "N/A",
        "street": street or "", "city": city or "", "state": state or "",
        "zip": zipc or "", "cc": (cc or "US").upper()[:2],
        "phone": phone or "", "email": email or "",
        "ip": ip or get_random_ip(), "bin": bin6, "raw": line
    }

def parse_cards_text(text):
    cards = []
    for line in text.replace("\r", "\n").split("\n"):
        c = parse_line(line)
        if c:
            cards.append(c)
    return cards

def bin_info(bin6, bins_db):
    b = bins_db.get(bin6) or {
        "scheme": "unknown", "brand": "UNKNOWN", "type": "", "level": "",
        "bank": "UNKNOWN", "country": "UNKNOWN", "cc": "US",
        "rating": "5/10", "vr": 100, "balance_rating": "5/10",
        "suggestion": "General", "force_vr": None
    }
    return b

def format_card_block(card, bins_db, is_tester=False):
    b = bin_info(card["bin"], bins_db)
    addr = ", ".join(x for x in [card["street"], card["city"], card["state"], card["zip"], card.get("cc") or b.get("cc", "US")] if x)
    brand = b.get("brand") or b.get("scheme") or "CARD"
    country = b.get("cc") or card.get("cc") or "US"
    bank = b.get("bank", "UNKNOWN")
    rating = b.get("rating", "10/10")
    suggestion = b.get("suggestion", "")
    vr = b.get("force_vr") if b.get("force_vr") is not None else 100  # show-only 100
    lines = [
        "══════════════════════════════════════",
        f"👤 Name:{card['name']}💳Card:{card['pan']}📅 Expiry:{card['exp']}🔒CVV:{card['cvv']}🏦Bank:{bank}🌍Country:{country}•{brand}📍Billing Address:{addr}📞Phone: {card['phone']}✉️ Email:{card['email']}🌐",
        "══════════════════════════════════════",
        f"🌐 IP      : {card.get('ip') or get_random_ip()}",
        f"🕒 Checked : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "══════════════════════════════════════",
        f"BIN Rate   : {rating} | {suggestion}",
        f"Live       : 100% (VR {vr})",
        "══════════════════════════════════════",
    ]
    if is_tester:
        lines.append("❤️ High Quality Tester From E$CO ❤️")
    lines.append("💬 Vouch the seller — send feedback after use")
    lines.append("══════════════════════════════════════")
    return "\n".join(lines)

def filter_usa_foreign(cards, usa=True):
    out = []
    for c in cards:
        cc = (c.get("cc") or "").upper()
        if usa and cc in ("US", "USA", ""):
            out.append(c)
        elif not usa and cc not in ("US", "USA", ""):
            out.append(c)
        elif usa and cc in ("US", "USA"):
            out.append(c)
    # if empty after filter, keep all (user mistake safety)
    return out or cards

def is_admin(uid):
    return uid in ADMIN_IDS

# ───────────────────────── UI ─────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Format", callback_data="go_format"),
         InlineKeyboardButton("Sale", callback_data="go_sale")],
        [InlineKeyboardButton("Replace", callback_data="go_replace"),
         InlineKeyboardButton("Tester", callback_data="go_tester")],
        [InlineKeyboardButton("Rate", callback_data="go_rate"),
         InlineKeyboardButton("Stats", callback_data="go_stats")],
        [InlineKeyboardButton("Stockpile", callback_data="go_stock"),
         InlineKeyboardButton("Settings", callback_data="go_settings")],
    ])

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name or str(uid)
    text = f"Private Seller Panel\nWelcome @{uname}"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    return MENU

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return ConversationHandler.END
    context.user_data.clear()
    return await show_admin_panel(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
    return await show_admin_panel(update, context)

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cmd_start(update, context)

# ───────────────────────── SESSION HELPERS ─────────────────────────
def sess(context):
    return context.user_data.setdefault("sess", {
        "mode": "base", "cards": [], "filename": None, "customer": None,
        "target": 0, "usa": True, "is_tester": False, "tester_kind": None,
        "batch_id": None
    })

def ensure_batch(context):
    s = sess(context)
    if not s.get("batch_id"):
        s["batch_id"] = next_batch()
    return s["batch_id"]

def pre_summary_text(context, extra_lines=None):
    s = sess(context)
    fn = s.get("filename") or f"Batch-{ensure_batch(context)}"
    lines = [
        f"Total Cards: {len(s['cards'])}",
        f"Mode: {s.get('mode', 'base').capitalize()}",
        f"FileName: {fn if s.get('filename') else 'N/A (will use ' + fn + ')'}",
    ]
    if s.get("mode") == "sale":
        st = load_settings()
        rev = s.get("target", 0) * st["sale_price"]
        lines = [
            f"Target: {s.get('target', 0)}",
            f"Total Cards: {len(s['cards'])}",
            "Mode: Sale",
            f"Total Revenue: ${rev:.2f}",
            f"+ (Sale Cost ${st['sale_price']:.2f}/card)",
            f"Customer: {s.get('customer')}",
        ]
    if s.get("mode") == "replace":
        lines = [
            f"Total Cards: {len(s['cards'])}",
            f"Replacement Target: {s.get('target', 0)}",
            f"Customer Name: {s.get('customer')}",
        ]
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines)

def post_summary_text(context):
    s = sess(context)
    n = len(s["cards"])
    live = n  # forced 100% live for show
    live_rate = "100%"
    st = load_settings()
    if s.get("mode") == "sale":
        target = int(s.get("target") or 0)
        extras = max(0, live - target)
        reached = live >= target
        revenue = target * st["sale_price"]  # charge target
        profit = revenue - (live * st["card_cost"])  # cost on all live pulled
        return "\n".join([
            f"Total Cards: {n}",
            f"Total Live: {live}",
            f"Extras: {extras}",
            f"Target Reached: {reached}",
            f"Profit Made: ${profit:.2f}",
            f"Total Revenue After Sale: ${revenue:.2f}",
            f"LiveRate: {live_rate}",
        ])
    if s.get("mode") == "replace":
        target = int(s.get("target") or 0)
        extras = max(0, live - target)
        return "\n".join([
            f"Total Cards: {n}",
            f"Extras: {extras}",
            f"Liverate: {live_rate}",
            f"Replacement Target Reached: {live >= target}",
            f"Customer Name: {s.get('customer')}",
        ])
    # format / tester
    return "\n".join([
        f"Total Cards: {n}",
        f"LiveRate: {live_rate}",
    ])

def kb_pre_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="pre_check"),
         InlineKeyboardButton("Set Filename", callback_data="pre_fname")],
        [InlineKeyboardButton("Add More Cards", callback_data="pre_add"),
         InlineKeyboardButton("Remove Cards", callback_data="pre_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def kb_pre_sale_rep():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="pre_check")],
        [InlineKeyboardButton("Add More Cards", callback_data="pre_add"),
         InlineKeyboardButton("Remove Cards", callback_data="pre_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def kb_post():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="post_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="post_add"),
         InlineKeyboardButton("Remove Cards", callback_data="post_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def kb_usa():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data="geo_usa"),
         InlineKeyboardButton("Foreign", callback_data="geo_foreign")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

# ───────────────────────── FORMAT FLOW ─────────────────────────
async def go_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["sess"] = {
        "mode": "base", "cards": [], "filename": None, "customer": None,
        "target": 0, "usa": True, "is_tester": False, "batch_id": next_batch()
    }
    await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
    return FMT_WAIT_CARDS

async def recv_cards_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, next_state_usa):
    s = sess(context)
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        data = await f.download_as_bytearray()
        text = data.decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards_text(text)
    if not new_cards:
        await update.message.reply_text("No valid cards found. Format:\npan|mm/yy|cvv|name|street|city|state|zip|CC|phone|email|ip")
        return next_state_usa  # stay
    s.setdefault("pending", []).extend(new_cards)
    await update.message.reply_text("USA Or Foreign?", reply_markup=kb_usa())
    return next_state_usa

async def fmt_wait_cards(update, context):
    return await recv_cards_generic(update, context, FMT_USA_FOR)

async def geo_choice(update, context):
    q = update.callback_query
    await q.answer()
    s = sess(context)
    s["usa"] = q.data == "geo_usa"
    pending = s.pop("pending", [])
    filtered = filter_usa_foreign(pending, usa=s["usa"])
    s["cards"].extend(filtered)
    ensure_batch(context)
    await q.edit_message_text(pre_summary_text(context), reply_markup=kb_pre_format() if s["mode"] in ("base", "tester") else kb_pre_sale_rep())
    mode = s["mode"]
    if mode == "sale":
        return SALE_PRE
    if mode == "replace":
        return REP_PRE
    if mode == "tester":
        return TEST_PRE
    return FMT_PRE

async def pre_buttons(update, context):
    q = update.callback_query
    await q.answer()
    s = sess(context)
    data = q.data
    if data == "cancel":
        return await cmd_cancel(update, context)
    if data == "pre_fname":
        await q.edit_message_text("Send filename (without .txt):")
        return FMT_FNAME if s["mode"] == "base" else TEST_FNAME
    if data == "pre_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return {
            "base": FMT_WAIT_CARDS, "sale": SALE_WAIT_CARDS,
            "replace": REP_WAIT_CARDS, "tester": TEST_WAIT_CARDS
        }[s["mode"]]
    if data == "pre_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return {
            "base": FMT_REMOVE, "sale": SALE_REMOVE,
            "replace": REP_REMOVE, "tester": TEST_REMOVE
        }[s["mode"]]
    if data == "pre_check":
        # show-only checker — all live 100%
        await q.edit_message_text(post_summary_text(context), reply_markup=kb_post())
        return {
            "base": FMT_POST, "sale": SALE_POST,
            "replace": REP_POST, "tester": TEST_POST
        }[s["mode"]]
    return MENU

async def set_fname(update, context):
    s = sess(context)
    name = (update.message.text or "Batch").strip().replace(".txt", "")
    s["filename"] = name
    await update.message.reply_text(pre_summary_text(context), reply_markup=kb_pre_format())
    return FMT_PRE if s["mode"] == "base" else TEST_PRE

async def remove_cards(update, context):
    s = sess(context)
    raw = (update.message.text or "")
    lasts = [x.strip() for x in raw.split(",") if x.strip()]
    before = len(s["cards"])
    s["cards"] = [c for c in s["cards"] if c["pan"][-4:] not in lasts]
    await update.message.reply_text(
        f"Removed {before - len(s['cards'])} card(s).\n" + pre_summary_text(context),
        reply_markup=kb_pre_format() if s["mode"] in ("base", "tester") else kb_pre_sale_rep()
    )
    return {
        "base": FMT_PRE, "sale": SALE_PRE, "replace": REP_PRE, "tester": TEST_PRE
    }[s["mode"]]

async def post_buttons(update, context):
    q = update.callback_query
    await q.answer()
    s = sess(context)
    data = q.data
    if data == "cancel":
        return await cmd_cancel(update, context)
    if data == "post_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return {
            "base": FMT_WAIT_CARDS, "sale": SALE_WAIT_CARDS,
            "replace": REP_WAIT_CARDS, "tester": TEST_WAIT_CARDS
        }[s["mode"]]
    if data == "post_rm":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return {
            "base": FMT_REMOVE, "sale": SALE_REMOVE,
            "replace": REP_REMOVE, "tester": TEST_REMOVE
        }[s["mode"]]
    if data == "post_send":
        return await send_out_file(update, context)
    return MENU

async def send_out_file(update, context):
    q = update.callback_query
    s = sess(context)
    bins_db = load_bins()
    st_set = load_settings()
    uid = update.effective_user.id
    ust = get_user_stats(uid)
    is_tester = s.get("mode") == "tester" or s.get("is_tester")
    blocks = [format_card_block(c, bins_db, is_tester=is_tester) for c in s["cards"]]
    body = "\n\n".join(blocks)
    body += "\n\n══════════════════════════════════════\n✅ Please vouch after successful use.\n══════════════════════════════════════\n"

    bid = ensure_batch(context)
    live = len(s["cards"])
    extras = []
    primary = s["cards"]

    if s["mode"] == "sale":
        target = int(s.get("target") or 0)
        primary = s["cards"][:target] if target else s["cards"]
        extras = s["cards"][target:] if target and len(s["cards"]) > target else []
        fname = f"{s.get('customer','Customer')}-{len(primary)}-{bid}.txt"
        # stockpile deduct
        stock = load_stock()
        for c in s["cards"]:
            b = c["bin"]
            if b in stock:
                stock[b] = max(0, int(stock[b]) - 1)
        save_stock(stock)
        # stats
        revenue = target * st_set["sale_price"]
        cost = live * st_set["card_cost"]
        ust["cards_sold"] += target
        ust["total_sales"] += 1
        ust["revenue"] += revenue
        ust["total_profit"] += (revenue - cost)
        set_user_stats(uid, ust)
    elif s["mode"] == "replace":
        target = int(s.get("target") or 0)
        primary = s["cards"][:target] if target else s["cards"]
        extras = s["cards"][target:] if target and len(s["cards"]) > target else []
        fname = f"{s.get('customer','Customer')}-{len(primary)}-{bid}.txt"
        cost = live * st_set["card_cost"]
        ust["replacements_given"] += target
        ust["revenue"] -= cost  # subtract card cost from revenue per spec
        ust["total_profit"] -= cost
        set_user_stats(uid, ust)
        stock = load_stock()
        for c in s["cards"]:
            b = c["bin"]
            if b in stock:
                stock[b] = max(0, int(stock[b]) - 1)
        save_stock(stock)
    elif s["mode"] == "tester":
        fname = (s.get("filename") or f"Tester-{bid}") + ".txt"
        ust["testers_given"] += live
        set_user_stats(uid, ust)
    else:
        fname = (s.get("filename") or f"Batch-{bid}") + ".txt"

    # rebuild body for primary
    def file_bytes(card_list):
        t = "\n\n".join(format_card_block(c, bins_db, is_tester=is_tester) for c in card_list)
        t += "\n\n══════════════════════════════════════\n✅ Vouch the seller — forward feedback.\n══════════════════════════════════════\n"
        return io.BytesIO(t.encode("utf-8"))

    bio = file_bytes(primary if s["mode"] in ("sale", "replace") else s["cards"])
    bio.name = fname
    chat_id = q.message.chat_id
    await context.bot.send_document(chat_id, document=InputFile(bio, filename=fname), caption=f"Formatted • LiveRate 100% • {fname}")

    if extras:
        ebio = file_bytes(extras)
        ename = f"Extras-{len(extras)}-{bid}.txt"
        ebio.name = ename
        await context.bot.send_document(chat_id, document=InputFile(ebio, filename=ename), caption=ename)

    await q.edit_message_text("File(s) sent. Returning to Admin panel.")
    context.user_data.clear()
    await context.bot.send_message(chat_id, "Private Seller Panel\nWelcome back", reply_markup=main_keyboard())
    return MENU

# ───────────────────────── SALE ─────────────────────────
async def go_sale(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["sess"] = {
        "mode": "sale", "cards": [], "filename": None, "customer": None,
        "target": 0, "usa": True, "is_tester": False, "batch_id": next_batch()
    }
    await q.edit_message_text("Please Respond With The Customer Name")
    return SALE_NAME

async def sale_name(update, context):
    sess(context)["customer"] = (update.message.text or "Customer").strip()
    await update.message.reply_text(f'How Many Cards Is "{sess(context)["customer"]}" Purchasing? (number only)')
    return SALE_QTY

async def sale_qty(update, context):
    try:
        qty = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        qty = 0
    s = sess(context)
    s["target"] = qty
    await update.message.reply_text("Target Set\nSend Cards Or Drop .txt File To Continue")
    return SALE_WAIT_CARDS

async def sale_wait_cards(update, context):
    return await recv_cards_generic(update, context, SALE_USA_FOR)

# ───────────────────────── REPLACE ─────────────────────────
async def go_replace(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["sess"] = {
        "mode": "replace", "cards": [], "filename": None, "customer": None,
        "target": 0, "usa": True, "is_tester": False, "batch_id": next_batch()
    }
    await q.edit_message_text("Who Is Being Replaced?")
    return REP_NAME

async def rep_name(update, context):
    sess(context)["customer"] = (update.message.text or "Customer").strip()
    await update.message.reply_text("How Many Cards Are Being Replaced? (number)")
    return REP_QTY

async def rep_qty(update, context):
    try:
        qty = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        qty = 0
    sess(context)["target"] = qty
    await update.message.reply_text("Target Submitted\nSend Cards Or Drop .txt File To Continue")
    return REP_WAIT_CARDS

async def rep_wait_cards(update, context):
    return await recv_cards_generic(update, context, REP_USA_FOR)

# ───────────────────────── TESTER ─────────────────────────
async def go_tester(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["sess"] = {
        "mode": "tester", "cards": [], "filename": None, "customer": None,
        "target": 0, "usa": True, "is_tester": True, "batch_id": next_batch()
    }
    await q.edit_message_text(
        "Is This Tester A Drop Or Gift?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Drop", callback_data="test_drop"),
             InlineKeyboardButton("Gift", callback_data="test_gift")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ])
    )
    return TEST_TYPE

async def test_type(update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cmd_cancel(update, context)
    sess(context)["tester_kind"] = "drop" if q.data == "test_drop" else "gift"
    await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
    return TEST_WAIT_CARDS

async def test_wait_cards(update, context):
    return await recv_cards_generic(update, context, TEST_USA_FOR)

# ───────────────────────── RATE ─────────────────────────
async def go_rate(update, context):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Bin VR", callback_data="rate_vr")],
        [InlineKeyboardButton("Rate Bin", callback_data="rate_bin")],
        [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate_bal")],
        [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate_sug")],
        [InlineKeyboardButton("Force VR", callback_data="rate_force")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    await q.edit_message_text("Rate Menu", reply_markup=kb)
    return RATE_MENU

async def rate_menu(update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cmd_cancel(update, context)
    context.user_data["rate_action"] = q.data
    await q.edit_message_text("Send Bin 6 Digit Number")
    return RATE_BIN

async def rate_bin(update, context):
    bin6 = re.sub(r"\D", "", update.message.text or "")[:6]
    bins = load_bins()
    if bin6 not in bins:
        bins[bin6] = {
            "scheme": "unknown", "brand": "UNKNOWN", "type": "", "level": "",
            "bank": "UNKNOWN", "country": "UNKNOWN", "cc": "US",
            "rating": "5/10", "vr": 100, "balance_rating": "5/10",
            "suggestion": "General", "force_vr": None
        }
        save_bins(bins)
    context.user_data["rate_bin"] = bin6
    b = bins[bin6]
    info = f"You Have Selected Bin {bin6}\nBank: {b.get('bank')}\nCountry: {b.get('country')}\nRating: {b.get('rating')}\nVR: {b.get('vr')}\nBal: {b.get('balance_rating')}\nSuggest: {b.get('suggestion')}\nForceVR: {b.get('force_vr')}"
    action = context.user_data.get("rate_action")
    if action == "rate_force":
        await update.message.reply_text(info + "\n\nSet Forced Vr Rating, Say Reset To Disable")
    elif action == "rate_sug":
        await update.message.reply_text(info + "\n\nSend suggestion text (places to use bin):")
    elif action == "rate_vr":
        await update.message.reply_text(info + "\n\nWhat Do You Want To Set The Vr Rating As? (0-10 or %)")
    elif action == "rate_bal":
        await update.message.reply_text(info + "\n\nSet balance rating (e.g. 8/10):")
    else:
        await update.message.reply_text(info + "\n\nRate Bin itself (e.g. 9/10):")
    return RATE_VALUE

async def rate_value(update, context):
    bins = load_bins()
    bin6 = context.user_data.get("rate_bin")
    val = (update.message.text or "").strip()
    action = context.user_data.get("rate_action")
    b = bins[bin6]
    if action == "rate_force":
        if val.lower() == "reset":
            b["force_vr"] = None
        else:
            b["force_vr"] = int(re.sub(r"\D", "", val) or "100")
    elif action == "rate_sug":
        b["suggestion"] = val
    elif action == "rate_vr":
        b["vr"] = int(re.sub(r"\D", "", val) or "100")
        if "/" not in val and val.isdigit():
            b["vr"] = int(val) if int(val) > 10 else int(val) * 10
    elif action == "rate_bal":
        b["balance_rating"] = val if "/" in val else f"{val}/10"
    else:
        b["rating"] = val if "/" in val else f"{val}/10"
    bins[bin6] = b
    save_bins(bins)
    await update.message.reply_text(f"Updated {bin6}.\n{b}")
    return await show_admin_panel(update, context)

# ───────────────────────── STATS ─────────────────────────
async def go_stats(update, context):
    q = update.callback_query
    await q.answer()
    ust = get_user_stats(update.effective_user.id)
    text = (
        f"Cards Sold: {ust['cards_sold']}\n"
        f"Total Sales: {ust['total_sales']}\n"
        f"Revenue: ${ust['revenue']:.2f}\n"
        f"Testers Given: {ust['testers_given']}\n"
        f"Replacements Given: {ust['replacements_given']}\n"
        f"Total Profit: ${ust['total_profit']:.2f}"
    )
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="cancel")]]))
    return MENU

# ───────────────────────── SETTINGS ─────────────────────────
async def go_settings(update, context):
    q = update.callback_query
    await q.answer()
    st = load_settings()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Sale Price (${st['sale_price']})", callback_data="set_sale")],
        [InlineKeyboardButton(f"Card Cost (${st['card_cost']})", callback_data="set_cost")],
        [InlineKeyboardButton("Back", callback_data="cancel")],
    ])
    await q.edit_message_text("Settings", reply_markup=kb)
    return SETTINGS_MENU

async def settings_menu(update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cmd_cancel(update, context)
    context.user_data["set_key"] = "sale_price" if q.data == "set_sale" else "card_cost"
    await q.edit_message_text("Send new dollar value (e.g. 5 or 1.5):")
    return SETTINGS_VALUE

async def settings_value(update, context):
    try:
        val = float((update.message.text or "0").replace("$", "").strip())
    except Exception:
        val = 0.0
    st = load_settings()
    st[context.user_data.get("set_key", "sale_price")] = val
    save_settings(st)
    await update.message.reply_text(f"Saved settings: {st}")
    return await show_admin_panel(update, context)

# ───────────────────────── STOCKPILE ─────────────────────────
async def go_stock(update, context):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Bins", callback_data="stock_add"),
         InlineKeyboardButton("Subtract Bins", callback_data="stock_sub")],
        [InlineKeyboardButton("Search Bin", callback_data="stock_search")],
        [InlineKeyboardButton("Send Binlist", callback_data="stock_send")],
        [InlineKeyboardButton("Back", callback_data="cancel")],
    ])
    stock = load_stock()
    preview = "\n".join(f"{b}*{qtp}*?" for b, qtp in sorted(stock.items())[:20]) or "(empty)"
    await q.edit_message_text(f"Stockpile\n{preview}", reply_markup=kb)
    return STOCK_MENU

async def stock_menu(update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cmd_cancel(update, context)
    if q.data == "stock_send":
        await q.edit_message_text("Choose output filename for binlist (without .txt):")
        context.user_data["stock_action"] = "send"
        return STOCK_FNAME
    if q.data == "stock_search":
        await q.edit_message_text("Type the BIN to search (forwardable result):")
        return STOCK_SEARCH
    context.user_data["stock_action"] = "add" if q.data == "stock_add" else "sub"
    await q.edit_message_text("Send bin 6-digit number:")
    return STOCK_BIN

async def stock_bin(update, context):
    bin6 = re.sub(r"\D", "", update.message.text or "")[:6]
    context.user_data["stock_bin"] = bin6
    # ensure bins_db knows it
    bins = load_bins()
    if bin6 not in bins:
        bins[bin6] = DEFAULT_BINS.get(bin6, {
            "scheme": "unknown", "brand": "UNKNOWN", "type": "", "level": "",
            "bank": "UNKNOWN", "country": "UNKNOWN", "cc": "US",
            "rating": "5/10", "vr": 100, "balance_rating": "5/10",
            "suggestion": "General", "force_vr": None
        })
        save_bins(bins)
    await update.message.reply_text(f"Bin {bin6}. Send amount to {context.user_data.get('stock_action')}:")
    return STOCK_AMT

async def stock_amt(update, context):
    try:
        amt = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        amt = 0
    bin6 = context.user_data.get("stock_bin")
    stock = load_stock()
    cur = int(stock.get(bin6, 0))
    if context.user_data.get("stock_action") == "add":
        stock[bin6] = cur + amt
    else:
        stock[bin6] = max(0, cur - amt)
    save_stock(stock)
    await update.message.reply_text(f"Stock {bin6} = {stock[bin6]}")
    return await show_admin_panel(update, context)

async def stock_search(update, context):
    bin6 = re.sub(r"\D", "", update.message.text or "")[:6]
    stock = load_stock()
    bins = load_bins()
    qty = int(stock.get(bin6, 0))
    b = bin_info(bin6, bins)
    # forwardable plain text
    msg = (
        f"BIN STOCK CHECK\n"
        f"Bin: {bin6}\n"
        f"Qty: {qty}\n"
        f"Bank: {b.get('bank')}\n"
        f"Country: {b.get('country')}\n"
        f"Scheme: {b.get('brand')}\n"
        f"Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
    )
    await update.message.reply_text(msg)
    return await show_admin_panel(update, context)

async def stock_fname(update, context):
    fname = (update.message.text or "stockpile").strip().replace(".txt", "") + ".txt"
    stock = load_stock()
    bins = load_bins()
    lines = []
    for b, qty in sorted(stock.items()):
        info = bin_info(b, bins)
        cc = info.get("cc") or info.get("country") or "?"
        lines.append(f"{b}*{qty}*{cc}")
    text = "\n".join(lines) or "EMPTY"
    bio = io.BytesIO(text.encode("utf-8"))
    bio.name = fname
    await update.message.reply_document(document=InputFile(bio, filename=fname), caption="Stockpile binlist Bin*Qty*Country")
    return await show_admin_panel(update, context)

# ───────────────────────── MENU ROUTER ─────────────────────────
async def menu_router(update, context):
    q = update.callback_query
    await q.answer()
    d = q.data
    if d == "cancel":
        return await cmd_cancel(update, context)
    if d == "go_format":
        return await go_format(update, context)
    if d == "go_sale":
        return await go_sale(update, context)
    if d == "go_replace":
        return await go_replace(update, context)
    if d == "go_tester":
        return await go_tester(update, context)
    if d == "go_rate":
        return await go_rate(update, context)
    if d == "go_stats":
        return await go_stats(update, context)
    if d == "go_settings":
        return await go_settings(update, context)
    if d == "go_stock":
        return await go_stock(update, context)
    return MENU

# ───────────────────────── BUILD APP ─────────────────────────
def main():
    # seed files
    load_bins()
    load_settings()
    load_stock()
    if not os.path.exists(STATS_FILE):
        save_all_stats({})

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("list", cmd_list),
            CommandHandler("format", lambda u, c: go_format(u, c) if u.callback_query else cmd_start(u, c)),
        ],
        states={
            MENU: [
                CallbackQueryHandler(menu_router),
                CommandHandler("cancel", cmd_cancel),
            ],
            FMT_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, fmt_wait_cards), CommandHandler("cancel", cmd_cancel)],
            FMT_USA_FOR: [CallbackQueryHandler(geo_choice, pattern="^geo_"), CallbackQueryHandler(cmd_cancel, pattern="^cancel$")],
            FMT_PRE: [CallbackQueryHandler(pre_buttons), CommandHandler("cancel", cmd_cancel)],
            FMT_POST: [CallbackQueryHandler(post_buttons), CommandHandler("cancel", cmd_cancel)],
            FMT_REMOVE: [MessageHandler(filters.TEXT, remove_cards), CommandHandler("cancel", cmd_cancel)],
            FMT_FNAME: [MessageHandler(filters.TEXT, set_fname), CommandHandler("cancel", cmd_cancel)],

            SALE_NAME: [MessageHandler(filters.TEXT, sale_name), CommandHandler("cancel", cmd_cancel)],
            SALE_QTY: [MessageHandler(filters.TEXT, sale_qty), CommandHandler("cancel", cmd_cancel)],
            SALE_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, sale_wait_cards), CommandHandler("cancel", cmd_cancel)],
            SALE_USA_FOR: [CallbackQueryHandler(geo_choice, pattern="^geo_"), CallbackQueryHandler(cmd_cancel, pattern="^cancel$")],
            SALE_PRE: [CallbackQueryHandler(pre_buttons), CommandHandler("cancel", cmd_cancel)],
            SALE_POST: [CallbackQueryHandler(post_buttons), CommandHandler("cancel", cmd_cancel)],
            SALE_REMOVE: [MessageHandler(filters.TEXT, remove_cards), CommandHandler("cancel", cmd_cancel)],

            REP_NAME: [MessageHandler(filters.TEXT, rep_name), CommandHandler("cancel", cmd_cancel)],
            REP_QTY: [MessageHandler(filters.TEXT, rep_qty), CommandHandler("cancel", cmd_cancel)],
            REP_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, rep_wait_cards), CommandHandler("cancel", cmd_cancel)],
            REP_USA_FOR: [CallbackQueryHandler(geo_choice, pattern="^geo_"), CallbackQueryHandler(cmd_cancel, pattern="^cancel$")],
            REP_PRE: [CallbackQueryHandler(pre_buttons), CommandHandler("cancel", cmd_cancel)],
            REP_POST: [CallbackQueryHandler(post_buttons), CommandHandler("cancel", cmd_cancel)],
            REP_REMOVE: [MessageHandler(filters.TEXT, remove_cards), CommandHandler("cancel", cmd_cancel)],

            TEST_TYPE: [CallbackQueryHandler(test_type), CommandHandler("cancel", cmd_cancel)],
            TEST_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, test_wait_cards), CommandHandler("cancel", cmd_cancel)],
            TEST_USA_FOR: [CallbackQueryHandler(geo_choice, pattern="^geo_"), CallbackQueryHandler(cmd_cancel, pattern="^cancel$")],
            TEST_PRE: [CallbackQueryHandler(pre_buttons), CommandHandler("cancel", cmd_cancel)],
            TEST_POST: [CallbackQueryHandler(post_buttons), CommandHandler("cancel", cmd_cancel)],
            TEST_REMOVE: [MessageHandler(filters.TEXT, remove_cards), CommandHandler("cancel", cmd_cancel)],
            TEST_FNAME: [MessageHandler(filters.TEXT, set_fname), CommandHandler("cancel", cmd_cancel)],

            RATE_MENU: [CallbackQueryHandler(rate_menu), CommandHandler("cancel", cmd_cancel)],
            RATE_BIN: [MessageHandler(filters.TEXT, rate_bin), CommandHandler("cancel", cmd_cancel)],
            RATE_VALUE: [MessageHandler(filters.TEXT, rate_value), CommandHandler("cancel", cmd_cancel)],

            SETTINGS_MENU: [CallbackQueryHandler(settings_menu), CommandHandler("cancel", cmd_cancel)],
            SETTINGS_VALUE: [MessageHandler(filters.TEXT, settings_value), CommandHandler("cancel", cmd_cancel)],

            STOCK_MENU: [CallbackQueryHandler(stock_menu), CommandHandler("cancel", cmd_cancel)],
            STOCK_BIN: [MessageHandler(filters.TEXT, stock_bin), CommandHandler("cancel", cmd_cancel)],
            STOCK_AMT: [MessageHandler(filters.TEXT, stock_amt), CommandHandler("cancel", cmd_cancel)],
            STOCK_FNAME: [MessageHandler(filters.TEXT, stock_fname), CommandHandler("cancel", cmd_cancel)],
            STOCK_SEARCH: [MessageHandler(filters.TEXT, stock_search), CommandHandler("cancel", cmd_cancel)],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(cmd_cancel, pattern="^cancel$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("stats", lambda u, c: go_stats(u, c) if u.callback_query else cmd_start(u, c)))
    print("Private Seller Panel bot running…")
    app.run_polling()

if __name__ == "__main__":
    main()
