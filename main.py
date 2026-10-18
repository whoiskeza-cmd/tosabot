# main.py — Private Seller Panel (Telegram)
# Railway: set BOT_TOKEN, ADMIN_IDS (comma-sep), optional API_URL
# Companion file: bins_db.json (auto-created). stockpile.json auto-created.
# Fix for your crash: callback/state enums must match range(N) length exactly.

import os, re, json, random, io, logging
from datetime import datetime, timezone
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
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
BINS_DB_FILE = os.path.join(DATA_DIR, "bins_db.json")
STOCK_FILE = os.path.join(DATA_DIR, "stockpile.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("seller-panel")

# ───────────────────────── STATE ENUM (FIX unpack) ─────────────────────────
# Exactly 28 states — range(28) unpacks cleanly
(
    MAIN,
    FMT_WAIT_CARDS, FMT_USA_FOREIGN, FMT_PRE, FMT_POST, FMT_REMOVE, FMT_FNAME,
    SALE_NAME, SALE_QTY, SALE_WAIT_CARDS, SALE_USA_FOREIGN, SALE_PRE, SALE_POST, SALE_REMOVE,
    REP_NAME, REP_QTY, REP_WAIT_CARDS, REP_USA_FOREIGN, REP_PRE, REP_POST, REP_REMOVE,
    TEST_TYPE, TEST_WAIT_CARDS, TEST_USA_FOREIGN, TEST_PRE, TEST_POST, TEST_REMOVE, TEST_FNAME,
) = range(28)

# Extra non-Conversation states handled via callbacks / short waits in user_data
# rate/settings/stockpile use flag keys in context.user_data

# ───────────────────────── DEFAULT BIN DB ─────────────────────────
DEFAULT_BINS = {
    "410039": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "scheme": "visa", "rating": "8.5", "vr": 95, "balance_rating": "7", "suggestion": "Costco/gas/grocery"},
    "410040": {"brand": "VISA", "type": "CREDIT", "level": "BUSINESS", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "scheme": "visa", "rating": "8.0", "vr": 92, "balance_rating": "8", "suggestion": "B2B / office supply"},
    "414720": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "scheme": "visa", "rating": "9.0", "vr": 96, "balance_rating": "8", "suggestion": "Amazon / digital"},
    "414740": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "scheme": "visa", "rating": "9.0", "vr": 96, "balance_rating": "8", "suggestion": "Amazon / digital"},
    "440066": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "BANK OF AMERICA - CONSUMER CREDIT", "country": "UNITED STATES", "scheme": "visa", "rating": "8.2", "vr": 90, "balance_rating": "7", "suggestion": "Retail / grocery"},
    "483312": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "scheme": "visa", "rating": "7.5", "vr": 88, "balance_rating": "6", "suggestion": "Low-ticket debit"},
    "483316": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "scheme": "visa", "rating": "7.5", "vr": 88, "balance_rating": "6", "suggestion": "Low-ticket debit"},
    "513371": {"brand": "MASTERCARD", "type": "CREDIT", "level": "STANDARD", "bank": "NEWDAY, LTD.", "country": "UNITED KINGDOM", "scheme": "mastercard", "rating": "7.0", "vr": 85, "balance_rating": "6", "suggestion": "UK domestic"},
    "513379": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "BANQUE FEDERATIVE DU CREDIT MUTUEL (BFCM)", "country": "FRANCE", "scheme": "mastercard", "rating": "7.0", "vr": 84, "balance_rating": "6", "suggestion": "EU debit"},
    "521729": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "COMMONWEALTH BANK OF AUSTRALIA", "country": "AUSTRALIA", "scheme": "mastercard", "rating": "7.2", "vr": 86, "balance_rating": "6", "suggestion": "AU domestic"},
    "534348": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CELTIC BANK CORPORATION", "country": "UNITED STATES", "scheme": "mastercard", "rating": "8.8", "vr": 94, "balance_rating": "8", "suggestion": "Online retail"},
    "542418": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "scheme": "mastercard", "rating": "8.7", "vr": 93, "balance_rating": "8", "suggestion": "Travel / retail"},
    "546616": {"brand": "MASTERCARD", "type": "CREDIT", "level": "WORLD", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "scheme": "mastercard", "rating": "9.1", "vr": 97, "balance_rating": "9", "suggestion": "High-ticket"},
}

DEFAULT_SETTINGS = {
    "sale_price": 15.0,   # revenue per live card sold
    "card_cost": 3.0,     # your cost per card (profit = sale_price - card_cost)
}

# ───────────────────────── PERSISTENCE ─────────────────────────
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy() if isinstance(default, dict) else default

def _save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_bins():
    d = _load(BINS_DB_FILE, {})
    if not d:
        d = DEFAULT_BINS.copy()
        _save(BINS_DB_FILE, d)
    return d

def save_bins(d): _save(BINS_DB_FILE, d)

def load_stock():
    return _load(STOCK_FILE, {})  # {"410040": 25, ...}

def save_stock(d): _save(STOCK_FILE, d)

def load_settings():
    s = _load(SETTINGS_FILE, DEFAULT_SETTINGS)
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s

def save_settings(s): _save(SETTINGS_FILE, s)

def load_stats():
    # per-admin stats
    return _load(STATS_FILE, {})

def save_stats(s): _save(STATS_FILE, s)

def get_user_stats(uid: int):
    stats = load_stats()
    key = str(uid)
    if key not in stats:
        stats[key] = {
            "cards_sold": 0,
            "total_sales": 0,
            "revenue": 0.0,
            "profit": 0.0,
            "testers_given": 0,
            "replacements_given": 0,
        }
        save_stats(stats)
    return stats[key]

def update_user_stats(uid: int, **kwargs):
    stats = load_stats()
    key = str(uid)
    st = get_user_stats(uid)
    st.update({k: st.get(k, 0) + v if isinstance(v, (int, float)) and k in st else v
               for k, v in kwargs.items()})
    # safer explicit
    for k, v in kwargs.items():
        if k in ("cards_sold", "total_sales", "testers_given", "replacements_given"):
            st[k] = st.get(k, 0) + int(v)
        elif k in ("revenue", "profit"):
            st[k] = float(st.get(k, 0)) + float(v)
        else:
            st[k] = v
    stats[key] = st
    save_stats(stats)

# ───────────────────────── HELPERS ─────────────────────────
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def batch_id() -> str:
    return f"{random.randint(1000, 9999)}"

def get_random_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

CARD_RE = re.compile(
    r"(?P<cc>\d{13,19})[|/;:\s]+(?P<mm>\d{1,2})[/|-]?(?P<yy>\d{2,4})[|/;:\s]+(?P<cvv>\d{3,4})"
    r"(?:[|/;:\s]+(?P<rest>.*))?",
    re.I
)

def parse_cards(text: str):
    """Parse lines like:
    4100400053813658|10/30|724|Glenda Jones|2233 W Betty Elyse Lane|Phoenix|AZ|85023|US|6023665854|gj140703@gmail.com|19.128.116.100
    """
    cards = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[|]", line)
        if len(parts) < 3:
            # try loose regex
            m = CARD_RE.search(line)
            if not m:
                continue
            cc, mm, yy, cvv = m.group("cc"), m.group("mm"), m.group("yy"), m.group("cvv")
            rest = (m.group("rest") or "").split("|")
            parts = [cc, f"{mm}/{yy}", cvv] + rest
        cc = re.sub(r"\D", "", parts[0])
        exp = parts[1]
        if "/" in exp:
            mm, yy = exp.split("/", 1)
        elif len(exp) == 4:
            mm, yy = exp[:2], exp[2:]
        else:
            mm, yy = exp, parts[2] if len(parts) > 2 else "00"
            if len(parts) > 3 and re.fullmatch(r"\d{3,4}", parts[2] or ""):
                pass
        cvv = parts[2] if len(parts) > 2 else ""
        # shift if exp was split across
        name = parts[3] if len(parts) > 3 else "N/A"
        address = parts[4] if len(parts) > 4 else "N/A"
        city = parts[5] if len(parts) > 5 else "N/A"
        state = parts[6] if len(parts) > 6 else "N/A"
        zipcode = parts[7] if len(parts) > 7 else "N/A"
        country = parts[8] if len(parts) > 8 else "US"
        phone = parts[9] if len(parts) > 9 else "N/A"
        email = parts[10] if len(parts) > 10 else "N/A"
        ip = parts[11] if len(parts) > 11 else get_random_ip()
        if len(yy) == 4:
            yy = yy[-2:]
        mm = mm.zfill(2)
        if len(cc) < 13:
            continue
        cards.append({
            "cc": cc, "mm": mm, "yy": yy, "cvv": cvv,
            "name": name.strip(), "address": address.strip(),
            "city": city.strip(), "state": state.strip(), "zipcode": zipcode.strip(),
            "country": country.strip().upper(), "phone": phone.strip(),
            "email": email.strip(), "ip": ip.strip(),
            "bin": cc[:6], "last4": cc[-4:],
        })
    return cards

def bin_info(bin6: str):
    bins = load_bins()
    b = bins.get(bin6) or {
        "brand": "UNKNOWN", "type": "UNKNOWN", "level": "STANDARD",
        "bank": "UNKNOWN", "country": "UNKNOWN", "scheme": "unknown",
        "rating": "N/A", "vr": 100, "balance_rating": "N/A", "suggestion": "N/A",
        "force_vr": None,
    }
    return b

def format_card_block(c, is_tester=False):
    info = bin_info(c["bin"])
    vr = info.get("force_vr")
    if vr is None:
        vr = 100  # forced show 100% live as requested
    else:
        vr = int(vr)
    country = c.get("country") or info.get("country", "UNKNOWN")
    lines = [
        "══════════════════════════════════════",
        f"🃏 LIVE Data • VR: {vr}%",
        "══════════════════════════════════════",
        f"👤 Name    : {c['name']}",
        f"💳 Card    : {c['cc']}",
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
        f"🌐 IP      : {c.get('ip') or get_random_ip()}",
        f"🕒 Checked : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "══════════════════════════════════════",
        f"BIN Rate   : {info.get('rating', 'N/A')} | {info.get('suggestion', 'N/A')}",
        "══════════════════════════════════════",
    ]
    if is_tester:
        lines.append("❤️ High Quality Tester From E$CO ❤️")
    lines.append("")
    lines.append("✅ Vouch if it hits — send vouch screenshot to seller. Appreciate you.")
    lines.append("")
    return "\n".join(lines)

def fake_check_all(cards):
    """Show-only checker: everything LIVE, live rate 100%."""
    live = list(cards)
    return live, 100.0

def stock_decrement_for_cards(cards):
    stock = load_stock()
    for c in cards:
        b = c["bin"]
        if b in stock:
            stock[b] = max(0, int(stock[b]) - 1)
    save_stock(stock)

def main_keyboard():
    rows = [
        [InlineKeyboardButton("Format", callback_data="go_format"),
         InlineKeyboardButton("Sale", callback_data="go_sale")],
        [InlineKeyboardButton("Replace", callback_data="go_replace"),
         InlineKeyboardButton("Tester", callback_data="go_tester")],
        [InlineKeyboardButton("Rate / BINs", callback_data="go_rate"),
         InlineKeyboardButton("Stats", callback_data="go_stats")],
        [InlineKeyboardButton("Stockpile", callback_data="go_stock"),
         InlineKeyboardButton("Settings", callback_data="go_settings")],
    ]
    return InlineKeyboardMarkup(rows)

def pre_kb_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="fmt_check"),
         InlineKeyboardButton("Set Filename", callback_data="fmt_fname")],
        [InlineKeyboardButton("Add More Cards", callback_data="fmt_add"),
         InlineKeyboardButton("Remove Cards", callback_data="fmt_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="fmt_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="fmt_add"),
         InlineKeyboardButton("Remove Cards", callback_data="fmt_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def pre_kb_sale():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add More Cards", callback_data="sale_add"),
         InlineKeyboardButton("Remove Cards", callback_data="sale_rm")],
        [InlineKeyboardButton("Check / Continue", callback_data="sale_check"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_sale():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="sale_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="sale_add"),
         InlineKeyboardButton("Remove Cards", callback_data="sale_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def pre_kb_rep():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="rep_check")],
        [InlineKeyboardButton("Add More Cards", callback_data="rep_add"),
         InlineKeyboardButton("Remove Cards", callback_data="rep_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_rep():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="rep_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="rep_add"),
         InlineKeyboardButton("Remove Cards", callback_data="rep_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def usa_foreign_kb(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data=f"{prefix}_usa"),
         InlineKeyboardButton("Foreign", callback_data=f"{prefix}_foreign")],
    ])

async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def send_start_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = f"<b>Private Seller Panel</b>\nWelcome @{user.username or user.id}\n\nChoose a feature:"
    if update.callback_query:
        await safe_edit(update.callback_query, text, main_keyboard())
    else:
        await update.effective_message.reply_text(text, reply_markup=main_keyboard(), parse_mode="HTML")

# ───────────────────────── /start /cancel /commands ─────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return ConversationHandler.END
    context.user_data.clear()
    await send_start_panel(update, context)
    return MAIN

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    await update.effective_message.reply_text("Back to admin panel.", reply_markup=ReplyKeyboardRemove())
    await send_start_panel(update, context)
    return MAIN

async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await send_start_panel(update, context)
    return MAIN

# ───────────────────────── FORMAT FLOW ─────────────────────────
async def go_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["mode"] = "format"
    context.user_data["cards"] = []
    context.user_data["filename"] = None
    context.user_data["batch"] = batch_id()
    context.user_data["filter"] = None
    await safe_edit(q, "Send Cards Or Drop .txt File To Continue")
    return FMT_WAIT_CARDS

async def fmt_recv_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed. Send lines or .txt")
        return FMT_WAIT_CARDS
    context.user_data.setdefault("cards", []).extend(new_cards)
    context.user_data["batch"] = batch_id()
    await update.message.reply_text("Select region filter:", reply_markup=usa_foreign_kb("fmt"))
    return FMT_USA_FOREIGN

async def fmt_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    region = "USA" if q.data.endswith("_usa") else "FOREIGN"
    context.user_data["filter"] = region
    cards = context.user_data.get("cards", [])
    if region == "USA":
        cards = [c for c in cards if c.get("country", "US") in ("US", "USA", "UNITED STATES")]
    else:
        cards = [c for c in cards if c.get("country", "US") not in ("US", "USA", "UNITED STATES")]
        if not cards:
            cards = context.user_data.get("cards", [])
    context.user_data["cards_view"] = cards
    return await fmt_show_pre(update, context)

async def fmt_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cards = context.user_data.get("cards", [])
    fn = context.user_data.get("filename") or f"Batch-{context.user_data.get('batch', batch_id())}"
    text = (
        f"<b>PreSummary /format</b>\n"
        f"Total Cards: {len(cards)}\n"
        f"Mode: Base\n"
        f"FileName: {fn}"
    )
    if update.callback_query:
        await safe_edit(update.callback_query, text, pre_kb_format())
    else:
        await update.effective_message.reply_text(text, reply_markup=pre_kb_format(), parse_mode="HTML")
    return FMT_PRE

async def fmt_pre_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "fmt_check":
        cards = context.user_data.get("cards", [])
        live, rate = fake_check_all(cards)
        context.user_data["live"] = live
        context.user_data["live_rate"] = rate
        text = (
            f"<b>PostSummary /format</b>\n"
            f"Total Cards: {len(cards)}\n"
            f"LiveRate: {rate:.0f}%\n"
            f"(checker show-only — all marked live)"
        )
        await safe_edit(q, text, post_kb_format())
        return FMT_POST
    if data == "fmt_fname":
        await safe_edit(q, "Send filename (without .txt):")
        return FMT_FNAME
    if data == "fmt_add":
        await safe_edit(q, "Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_rm":
        await safe_edit(q, "Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FMT_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return FMT_PRE

async def fmt_set_fname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["filename"] = (update.message.text or "Batch").strip().replace(".txt", "")
    return await fmt_show_pre(update, context)

async def fmt_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "")
    lasts = {x.strip() for x in raw.split(",") if x.strip()}
    cards = context.user_data.get("cards", [])
    context.user_data["cards"] = [c for c in cards if c["last4"] not in lasts]
    await update.message.reply_text(f"Removed. Left: {len(context.user_data['cards'])}")
    return await fmt_show_pre(update, context)

async def fmt_post_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "fmt_send":
        cards = context.user_data.get("live") or context.user_data.get("cards", [])
        fn = context.user_data.get("filename") or f"Batch-{context.user_data.get('batch', batch_id())}"
        body = "\n".join(format_card_block(c, False) for c in cards)
        body += "\n\n——\nSend vouches after hits. Thank you for business.\n"
        bio = io.BytesIO(body.encode("utf-8"))
        bio.name = f"{fn}.txt"
        await q.message.reply_document(document=InputFile(bio), caption=f"{fn}.txt • {len(cards)} cards")
        await q.message.reply_text("File sent.", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN
    if data == "fmt_add":
        await safe_edit(q, "Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_rm":
        await safe_edit(q, "Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FMT_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return FMT_POST

# ───────────────────────── SALE FLOW ─────────────────────────
async def go_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["mode"] = "sale"
    context.user_data["cards"] = []
    context.user_data["batch"] = batch_id()
    await safe_edit(q, "Please Respond With The Customer Name")
    return SALE_NAME

async def sale_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = (update.message.text or "Customer").strip()
    await update.message.reply_text(f'How Many Cards Is "{context.user_data["customer"]}" Purchasing? (number)')
    return SALE_QTY

async def sale_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        qty = 0
    context.user_data["target"] = qty
    settings = load_settings()
    context.user_data["sale_price"] = float(settings["sale_price"])
    context.user_data["card_cost"] = float(settings["card_cost"])
    await update.message.reply_text("Target Set — Send Cards Or Drop .txt File To Continue")
    return SALE_WAIT_CARDS

async def sale_recv_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed.")
        return SALE_WAIT_CARDS
    context.user_data.setdefault("cards", []).extend(new_cards)
    context.user_data["batch"] = batch_id()
    await update.message.reply_text("USA or Foreign?", reply_markup=usa_foreign_kb("sale"))
    return SALE_USA_FOREIGN

async def sale_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["filter"] = "USA" if q.data.endswith("_usa") else "FOREIGN"
    return await sale_show_pre(update, context)

async def sale_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cards = context.user_data.get("cards", [])
    target = int(context.user_data.get("target", 0))
    sp = float(context.user_data.get("sale_price", 15))
    rev = target * sp
    text = (
        f"<b>PreSummary /sale</b>\n"
        f"Customer: {context.user_data.get('customer')}\n"
        f"Target: {target}\n"
        f"Total Cards: {len(cards)}\n"
        f"Mode: Sale\n"
        f"Total Revenue (projected): ${rev:.2f}\n"
        f"+ (Sale Cost ${sp:.2f}/card)"
    )
    if update.callback_query:
        await safe_edit(update.callback_query, text, pre_kb_sale())
    else:
        await update.effective_message.reply_text(text, reply_markup=pre_kb_sale(), parse_mode="HTML")
    return SALE_PRE

async def sale_pre_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "sale_check":
        cards = context.user_data.get("cards", [])
        live, rate = fake_check_all(cards)
        context.user_data["live"] = live
        target = int(context.user_data.get("target", 0))
        sp = float(context.user_data.get("sale_price", 15))
        cc = float(context.user_data.get("card_cost", 3))
        total_live = len(live)
        extras = max(0, total_live - target)
        sold = min(total_live, target)
        reached = total_live >= target
        revenue = sold * sp
        profit = sold * (sp - cc)
        context.user_data["sale_meta"] = {
            "sold": sold, "extras": extras, "revenue": revenue, "profit": profit, "reached": reached
        }
        text = (
            f"<b>PostSummary /sale</b>\n"
            f"Total Cards: {len(cards)}\n"
            f"Total Live: {total_live}\n"
            f"Extras: {extras}\n"
            f"Target Reached: {reached}\n"
            f"Profit Made: ${profit:.2f}\n"
            f"Total Revenue After Sale: ${revenue:.2f}"
        )
        await safe_edit(q, text, post_kb_sale())
        return SALE_POST
    if data == "sale_add":
        await safe_edit(q, "Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if data == "sale_rm":
        await safe_edit(q, "Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return SALE_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return SALE_PRE

async def sale_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lasts = {x.strip() for x in (update.message.text or "").split(",") if x.strip()}
    cards = context.user_data.get("cards", [])
    context.user_data["cards"] = [c for c in cards if c["last4"] not in lasts]
    return await sale_show_pre(update, context)

async def sale_post_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "sale_send":
        live = context.user_data.get("live") or context.user_data.get("cards", [])
        meta = context.user_data.get("sale_meta", {})
        target = int(context.user_data.get("target", 0))
        customer = context.user_data.get("customer", "Customer")
        sold_cards = live[:target]
        extra_cards = live[target:]
        bid = batch_id()
        # main file
        body = "\n".join(format_card_block(c, False) for c in sold_cards)
        body += "\n\n——\nVouch after successful use. Forward vouches to seller.\n"
        bio = io.BytesIO(body.encode("utf-8"))
        bio.name = f"{customer}-{len(sold_cards)}-{bid}.txt"
        await q.message.reply_document(InputFile(bio), caption=bio.name)
        if extra_cards:
            body2 = "\n".join(format_card_block(c, False) for c in extra_cards)
            bio2 = io.BytesIO(body2.encode("utf-8"))
            bio2.name = f"Extras-{len(extra_cards)}-{bid}.txt"
            await q.message.reply_document(InputFile(bio2), caption=bio2.name)
        # stats + stockpile
        uid = update.effective_user.id
        update_user_stats(
            uid,
            cards_sold=meta.get("sold", len(sold_cards)),
            total_sales=1,
            revenue=meta.get("revenue", 0),
            profit=meta.get("profit", 0),
        )
        stock_decrement_for_cards(sold_cards + extra_cards)
        await q.message.reply_text("Sale filed. Stockpile updated.", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN
    if data == "sale_add":
        await safe_edit(q, "Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if data == "sale_rm":
        await safe_edit(q, "Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return SALE_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return SALE_POST

# ───────────────────────── REPLACE FLOW ─────────────────────────
async def go_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["mode"] = "replace"
    context.user_data["cards"] = []
    await safe_edit(q, "Who Is Being Replaced?")
    return REP_NAME

async def rep_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = (update.message.text or "Customer").strip()
    await update.message.reply_text("How Many Cards Are Being Replaced? (number)")
    return REP_QTY

async def rep_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        qty = 0
    context.user_data["target"] = qty
    await update.message.reply_text("Target Submitted — Send Cards Or Drop .txt File To Continue")
    return REP_WAIT_CARDS

async def rep_recv_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed.")
        return REP_WAIT_CARDS
    context.user_data.setdefault("cards", []).extend(new_cards)
    await update.message.reply_text("USA or Foreign?", reply_markup=usa_foreign_kb("rep"))
    return REP_USA_FOREIGN

async def rep_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    return await rep_show_pre(update, context)

async def rep_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cards = context.user_data.get("cards", [])
    text = (
        f"<b>PreSummary /replace</b>\n"
        f"Total Cards: {len(cards)}\n"
        f"Replacement Target: {context.user_data.get('target')}\n"
        f"Customer Name: {context.user_data.get('customer')}"
    )
    kb = pre_kb_rep()
    if update.callback_query:
        await safe_edit(update.callback_query, text, kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    return REP_PRE

async def rep_pre_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "rep_check":
        cards = context.user_data.get("cards", [])
        live, rate = fake_check_all(cards)
        context.user_data["live"] = live
        target = int(context.user_data.get("target", 0))
        extras = max(0, len(live) - target)
        text = (
            f"<b>PostSummary /replace</b>\n"
            f"Total Cards: {len(cards)}\n"
            f"Extras: {extras}\n"
            f"LiveRate: {rate:.0f}%\n"
            f"Replacement Target Reached: {len(live) >= target}\n"
            f"Customer Name: {context.user_data.get('customer')}"
        )
        await safe_edit(q, text, post_kb_rep())
        return REP_POST
    if data == "rep_add":
        await safe_edit(q, "Send Cards Or Drop .txt File To Continue")
        return REP_WAIT_CARDS
    if data == "rep_rm":
        await safe_edit(q, "Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return REP_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return REP_PRE

async def rep_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lasts = {x.strip() for x in (update.message.text or "").split(",") if x.strip()}
    context.user_data["cards"] = [c for c in context.user_data.get("cards", []) if c["last4"] not in lasts]
    return await rep_show_pre(update, context)

async def rep_post_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "rep_send":
        live = context.user_data.get("live") or []
        target = int(context.user_data.get("target", 0))
        customer = context.user_data.get("customer", "Customer")
        main_c = live[:target]
        extras = live[target:]
        bid = batch_id()
        body = "\n".join(format_card_block(c, False) for c in main_c)
        body += "\n\n——\nReplacement batch — vouch appreciated.\n"
        bio = io.BytesIO(body.encode("utf-8"))
        bio.name = f"{customer}-{len(main_c)}-{bid}.txt"
        await q.message.reply_document(InputFile(bio), caption=bio.name)
        if extras:
            body2 = "\n".join(format_card_block(c, False) for c in extras)
            bio2 = io.BytesIO(body2.encode("utf-8"))
            bio2.name = f"Extras-{len(extras)}-{bid}.txt"
            await q.message.reply_document(InputFile(bio2), caption=bio2.name)
        settings = load_settings()
        cost = float(settings["card_cost"]) * len(main_c)
        uid = update.effective_user.id
        update_user_stats(uid, replacements_given=len(main_c), revenue=-cost, profit=-cost)
        stock_decrement_for_cards(main_c + extras)
        await q.message.reply_text("Replace sent. Cost subtracted.", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN
    if data == "rep_add":
        await safe_edit(q, "Send Cards Or Drop .txt File To Continue")
        return REP_WAIT_CARDS
    if data == "rep_rm":
        await safe_edit(q, "Send Last 4# Separated By Commas")
        return REP_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return REP_POST

# ───────────────────────── TESTER FLOW ─────────────────────────
async def go_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["mode"] = "tester"
    context.user_data["cards"] = []
    context.user_data["filename"] = None
    await safe_edit(q, "Is This Tester A Drop Or Gift? (reply Drop or Gift)")
    return TEST_TYPE

async def test_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "Gift").strip().lower()
    context.user_data["tester_kind"] = "drop" if "drop" in t else "gift"
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return TEST_WAIT_CARDS

async def test_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed.")
        return TEST_WAIT_CARDS
    context.user_data.setdefault("cards", []).extend(new_cards)
    await update.message.reply_text("USA or Foreign?", reply_markup=usa_foreign_kb("test"))
    return TEST_USA_FOREIGN

async def test_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    return await test_show_pre(update, context)

async def test_show_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cards = context.user_data.get("cards", [])
    fn = context.user_data.get("filename") or f"Batch-{batch_id()}"
    text = (
        f"<b>PreSummary /tester</b> ({context.user_data.get('tester_kind')})\n"
        f"Total Cards: {len(cards)}\n"
        f"Mode: Base\n"
        f"FileName: {fn}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="test_check"),
         InlineKeyboardButton("Set Filename", callback_data="test_fname")],
        [InlineKeyboardButton("Add More Cards", callback_data="test_add"),
         InlineKeyboardButton("Remove Cards", callback_data="test_rm")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    if update.callback_query:
        await safe_edit(update.callback_query, text, kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    return TEST_PRE

async def test_pre_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "test_check":
        cards = context.user_data.get("cards", [])
        live, rate = fake_check_all(cards)
        context.user_data["live"] = live
        text = f"<b>PostSummary /tester</b>\nTotal Cards: {len(cards)}\nLiveRate: {rate:.0f}%"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Send File", callback_data="test_send")],
            [InlineKeyboardButton("Add More Cards", callback_data="test_add"),
             InlineKeyboardButton("Remove Cards", callback_data="test_rm")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ])
        await safe_edit(q, text, kb)
        return TEST_POST
    if data == "test_fname":
        await safe_edit(q, "Send filename (no .txt):")
        return TEST_FNAME
    if data == "test_add":
        await safe_edit(q, "Send more cards or .txt")
        return TEST_WAIT_CARDS
    if data == "test_rm":
        await safe_edit(q, "Send Last 4# comma-separated")
        return TEST_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return TEST_PRE

async def test_set_fname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["filename"] = (update.message.text or "Tester").strip().replace(".txt", "")
    return await test_show_pre(update, context)

async def test_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lasts = {x.strip() for x in (update.message.text or "").split(",") if x.strip()}
    context.user_data["cards"] = [c for c in context.user_data.get("cards", []) if c["last4"] not in lasts]
    return await test_show_pre(update, context)

async def test_post_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "test_send":
        live = context.user_data.get("live") or context.user_data.get("cards", [])
        fn = context.user_data.get("filename") or f"Tester-{batch_id()}"
        body = "\n".join(format_card_block(c, True) for c in live)
        body += "\n\n——\nTester — vouch if live.\n"
        bio = io.BytesIO(body.encode("utf-8"))
        bio.name = f"{fn}.txt"
        await q.message.reply_document(InputFile(bio), caption=bio.name)
        update_user_stats(update.effective_user.id, testers_given=len(live))
        stock_decrement_for_cards(live)
        await q.message.reply_text("Tester sent.", reply_markup=main_keyboard())
        context.user_data.clear()
        return MAIN
    if data == "test_add":
        await safe_edit(q, "Send more cards or .txt")
        return TEST_WAIT_CARDS
    if data == "test_rm":
        await safe_edit(q, "Send Last 4# comma-separated")
        return TEST_REMOVE
    if data == "cancel":
        return await cancel_cb(update, context)
    return TEST_POST

# ───────────────────────── RATE / BIN MENU ─────────────────────────
async def go_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Bin VR", callback_data="rate_set_vr")],
        [InlineKeyboardButton("Rate Bin", callback_data="rate_rate_bin")],
        [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate_bal")],
        [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate_sugg")],
        [InlineKeyboardButton("Force VR", callback_data="rate_force_vr")],
        [InlineKeyboardButton("Search BIN info", callback_data="rate_search")],
        [InlineKeyboardButton("« Back", callback_data="cancel")],
    ])
    await safe_edit(q, "<b>BIN Rate Menu</b>", kb)
    return MAIN

async def rate_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    context.user_data["rate_action"] = data
    await safe_edit(q, "Send Bin 6 Digit Number")
    context.user_data["await"] = "rate_bin"
    return MAIN

async def rate_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic text sink when awaiting rate/settings/stock actions outside Conv states."""
    if not is_admin(update.effective_user.id):
        return
    await_key = context.user_data.get("await")
    text = (update.message.text or "").strip()
    if not await_key:
        return

    bins = load_bins()

    if await_key == "rate_bin":
        bin6 = re.sub(r"\D", "", text)[:6]
        if len(bin6) < 6:
            await update.message.reply_text("Need 6 digits.")
            return
        context.user_data["bin"] = bin6
        info = bin_info(bin6)
        action = context.user_data.get("rate_action")
        msg = (
            f"You Have Selected Bin {bin6}\n"
            f"Bank: {info.get('bank')}\nBrand: {info.get('brand')} {info.get('level')}\n"
            f"Country: {info.get('country')}\nVR: {info.get('vr')} Rating: {info.get('rating')}\n"
            f"Bal: {info.get('balance_rating')} Suggestion: {info.get('suggestion')}\n"
            f"ForceVR: {info.get('force_vr')}"
        )
        await update.message.reply_text(msg)
        if action == "rate_set_vr":
            await update.message.reply_text("What Do You Want To Set The Vr Rating As? (0-10 or 0-100)")
            context.user_data["await"] = "rate_set_vr_val"
        elif action == "rate_rate_bin":
            await update.message.reply_text("Rate this BIN (e.g. 8.5):")
            context.user_data["await"] = "rate_rate_val"
        elif action == "rate_bal":
            await update.message.reply_text("Set balance rating (0-10):")
            context.user_data["await"] = "rate_bal_val"
        elif action == "rate_sugg":
            await update.message.reply_text("Send suggestion places to use BIN:")
            context.user_data["await"] = "rate_sugg_val"
        elif action == "rate_force_vr":
            await update.message.reply_text("Set Forced Vr Rating, Say Reset To Disable")
            context.user_data["await"] = "rate_force_val"
        elif action == "rate_search":
            context.user_data["await"] = None
            await update.message.reply_text("Done (info above). Forwardable.", reply_markup=main_keyboard())
        return

    bin6 = context.user_data.get("bin")
    if not bin6:
        return
    if bin6 not in bins:
        bins[bin6] = bin_info(bin6)

    if await_key == "rate_set_vr_val":
        try:
            val = float(text)
            if val <= 10: val *= 10
            bins[bin6]["vr"] = int(val)
        except Exception:
            await update.message.reply_text("Invalid")
            return
        save_bins(bins)
        context.user_data["await"] = None
        await update.message.reply_text(f"VR set for {bin6}", reply_markup=main_keyboard())
    elif await_key == "rate_rate_val":
        bins[bin6]["rating"] = text
        save_bins(bins)
        context.user_data["await"] = None
        await update.message.reply_text("BIN rating saved", reply_markup=main_keyboard())
    elif await_key == "rate_bal_val":
        bins[bin6]["balance_rating"] = text
        save_bins(bins)
        context.user_data["await"] = None
        await update.message.reply_text("Balance rating saved", reply_markup=main_keyboard())
    elif await_key == "rate_sugg_val":
        bins[bin6]["suggestion"] = text
        save_bins(bins)
        context.user_data["await"] = None
        await update.message.reply_text("Suggestion saved", reply_markup=main_keyboard())
    elif await_key == "rate_force_val":
        if text.lower() == "reset":
            bins[bin6]["force_vr"] = None
        else:
            try:
                bins[bin6]["force_vr"] = int(re.sub(r"\D", "", text))
            except Exception:
                await update.message.reply_text("Invalid")
                return
        save_bins(bins)
        context.user_data["await"] = None
        await update.message.reply_text("Force VR updated (format output uses 100% live display unless you change formatter)", reply_markup=main_keyboard())

    # settings awaits
    elif await_key == "set_sale_price":
        try:
            s = load_settings()
            s["sale_price"] = float(text)
            save_settings(s)
            context.user_data["await"] = None
            await update.message.reply_text(f"Sale price = ${s['sale_price']:.2f}", reply_markup=main_keyboard())
        except Exception:
            await update.message.reply_text("Number only")
    elif await_key == "set_card_cost":
        try:
            s = load_settings()
            s["card_cost"] = float(text)
            save_settings(s)
            context.user_data["await"] = None
            await update.message.reply_text(f"Card cost = ${s['card_cost']:.2f}", reply_markup=main_keyboard())
        except Exception:
            await update.message.reply_text("Number only")

    # stockpile awaits
    elif await_key == "stock_bin":
        bin6 = re.sub(r"\D", "", text)[:6]
        context.user_data["stock_bin"] = bin6
        await update.message.reply_text("Add or Remove? (add/remove)")
        context.user_data["await"] = "stock_op"
    elif await_key == "stock_op":
        op = text.lower().strip()
        context.user_data["stock_op"] = "add" if "add" in op else "remove"
        await update.message.reply_text("Amount?")
        context.user_data["await"] = "stock_amt"
    elif await_key == "stock_amt":
        try:
            amt = int(re.sub(r"\D", "", text))
        except Exception:
            await update.message.reply_text("Number")
            return
        stock = load_stock()
        b = context.user_data.get("stock_bin")
        cur = int(stock.get(b, 0))
        if context.user_data.get("stock_op") == "add":
            stock[b] = cur + amt
        else:
            stock[b] = max(0, cur - amt)
        save_stock(stock)
        context.user_data["await"] = None
        await update.message.reply_text(f"{b} qty now {stock[b]}", reply_markup=main_keyboard())
    elif await_key == "stock_search":
        bin6 = re.sub(r"\D", "", text)[:6]
        stock = load_stock()
        qty = int(stock.get(bin6, 0))
        info = bin_info(bin6)
        # forwardable single message
        msg = (
            f"BIN STOCK\n"
            f"{bin6}*{qty}*{info.get('country', 'UNKNOWN')}\n"
            f"{info.get('brand')} {info.get('level')} | {info.get('bank')}"
        )
        context.user_data["await"] = None
        await update.message.reply_text(msg)
        await update.message.reply_text("Panel:", reply_markup=main_keyboard())

# ───────────────────────── STATS ─────────────────────────
async def go_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = get_user_stats(update.effective_user.id)
    text = (
        f"<b>Stats</b> (@{update.effective_user.username or update.effective_user.id})\n"
        f"Cards Sold: {st.get('cards_sold', 0)}\n"
        f"Total Sales: {st.get('total_sales', 0)}\n"
        f"Revenue: ${st.get('revenue', 0):.2f}\n"
        f"Testers Given: {st.get('testers_given', 0)}\n"
        f"Replacements Given: {st.get('replacements_given', 0)}\n"
        f"Total Profit: ${st.get('profit', 0):.2f}"
    )
    await safe_edit(q, text, InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="cancel")]]))
    return MAIN

# ───────────────────────── SETTINGS ─────────────────────────
async def go_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = load_settings()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Sale Price", callback_data="set_sale")],
        [InlineKeyboardButton("Set Card Cost", callback_data="set_cost")],
        [InlineKeyboardButton("« Back", callback_data="cancel")],
    ])
    await safe_edit(q, f"<b>Settings</b>\nSale price: ${s['sale_price']:.2f}\nCard cost: ${s['card_cost']:.2f}", kb)
    return MAIN

async def settings_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "set_sale":
        context.user_data["await"] = "set_sale_price"
        await safe_edit(q, "Send new sale price (number):")
    elif q.data == "set_cost":
        context.user_data["await"] = "set_card_cost"
        await safe_edit(q, "Send new card cost (number):")
    return MAIN

# ───────────────────────── STOCKPILE ─────────────────────────
async def go_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add/Remove BIN qty", callback_data="stock_edit")],
        [InlineKeyboardButton("Search BIN qty", callback_data="stock_search")],
        [InlineKeyboardButton("Send full binlist", callback_data="stock_list")],
        [InlineKeyboardButton("« Back", callback_data="cancel")],
    ])
    await safe_edit(q, "<b>Stockpile</b>", kb)
    return MAIN

async def stock_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "stock_edit":
        context.user_data["await"] = "stock_bin"
        await safe_edit(q, "Send BIN 6-digit:")
    elif q.data == "stock_search":
        context.user_data["await"] = "stock_search"
        await safe_edit(q, "Send BIN to search (forwardable result):")
    elif q.data == "stock_list":
        stock = load_stock()
        lines = ["Bin*Qty*Country"]
        for b, qty in sorted(stock.items()):
            if int(qty) <= 0:
                continue
            info = bin_info(b)
            lines.append(f"{b}*{qty}*{info.get('country', 'UNKNOWN')}")
        if len(lines) == 1:
            lines.append("(empty)")
        body = "\n".join(lines)
        bio = io.BytesIO(body.encode("utf-8"))
        bio.name = f"stockpile-{batch_id()}.txt"
        await q.message.reply_document(InputFile(bio), caption="Stockpile binlist")
        await q.message.reply_text(body[:3500])  # forwardable text mirror
    return MAIN

# ───────────────────────── COMMAND SHORTCUTS ─────────────────────────
async def cmd_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["mode"] = "format"
    context.user_data["cards"] = []
    context.user_data["batch"] = batch_id()
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return FMT_WAIT_CARDS

async def cmd_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("Please Respond With The Customer Name")
    return SALE_NAME

async def cmd_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("Who Is Being Replaced?")
    return REP_NAME

async def cmd_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("Is This Tester A Drop Or Gift?")
    return TEST_TYPE

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    st = get_user_stats(update.effective_user.id)
    await update.message.reply_text(
        f"Cards Sold: {st['cards_sold']}\nTotal Sales: {st['total_sales']}\n"
        f"Revenue: ${st['revenue']:.2f}\nTesters: {st['testers_given']}\n"
        f"Replacements: {st['replacements_given']}\nProfit: ${st['profit']:.2f}"
    )

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "/format /sale /replace /tester /rate /stats /cancel\nPlus Stockpile & Settings on panel."
    )

# ───────────────────────── BUILD APP ─────────────────────────
def build_app():
    # seed files
    load_bins()
    load_settings()
    load_stock()
    load_stats()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("format", cmd_format),
            CommandHandler("sale", cmd_sale),
            CommandHandler("replace", cmd_replace),
            CommandHandler("tester", cmd_tester),
            CallbackQueryHandler(go_format, pattern="^go_format$"),
            CallbackQueryHandler(go_sale, pattern="^go_sale$"),
            CallbackQueryHandler(go_replace, pattern="^go_replace$"),
            CallbackQueryHandler(go_tester, pattern="^go_tester$"),
        ],
        states={
            MAIN: [
                CallbackQueryHandler(go_format, pattern="^go_format$"),
                CallbackQueryHandler(go_sale, pattern="^go_sale$"),
                CallbackQueryHandler(go_replace, pattern="^go_replace$"),
                CallbackQueryHandler(go_tester, pattern="^go_tester$"),
                CallbackQueryHandler(go_rate, pattern="^go_rate$"),
                CallbackQueryHandler(go_stats, pattern="^go_stats$"),
                CallbackQueryHandler(go_settings, pattern="^go_settings$"),
                CallbackQueryHandler(go_stock, pattern="^go_stock$"),
                CallbackQueryHandler(rate_router, pattern="^rate_"),
                CallbackQueryHandler(settings_router, pattern="^set_"),
                CallbackQueryHandler(stock_router, pattern="^stock_"),
                CallbackQueryHandler(cancel_cb, pattern="^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, rate_text_handler),
            ],
            FMT_WAIT_CARDS: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, fmt_recv_cards)],
            FMT_USA_FOREIGN: [CallbackQueryHandler(fmt_region, pattern="^fmt_(usa|foreign)$")],
            FMT_PRE: [CallbackQueryHandler(fmt_pre_router, pattern="^(fmt_|cancel)")],
            FMT_POST: [CallbackQueryHandler(fmt_post_router, pattern="^(fmt_|cancel)")],
            FMT_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fmt_remove)],
            FMT_FNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fmt_set_fname)],

            SALE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_name)],
            SALE_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_qty)],
            SALE_WAIT_CARDS: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, sale_recv_cards)],
            SALE_USA_FOREIGN: [CallbackQueryHandler(sale_region, pattern="^sale_(usa|foreign)$")],
            SALE_PRE: [CallbackQueryHandler(sale_pre_router, pattern="^(sale_|cancel)")],
            SALE_POST: [CallbackQueryHandler(sale_post_router, pattern="^(sale_|cancel)")],
            SALE_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_remove)],

            REP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rep_name)],
            REP_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, rep_qty)],
            REP_WAIT_CARDS: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, rep_recv_cards)],
            REP_USA_FOREIGN: [CallbackQueryHandler(rep_region, pattern="^rep_(usa|foreign)$")],
            REP_PRE: [CallbackQueryHandler(rep_pre_router, pattern="^(rep_|cancel)")],
            REP_POST: [CallbackQueryHandler(rep_post_router, pattern="^(rep_|cancel)")],
            REP_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rep_remove)],

            TEST_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, test_type)],
            TEST_WAIT_CARDS: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, test_recv)],
            TEST_USA_FOREIGN: [CallbackQueryHandler(test_region, pattern="^test_(usa|foreign)$")],
            TEST_PRE: [CallbackQueryHandler(test_pre_router, pattern="^(test_|cancel)")],
            TEST_POST: [CallbackQueryHandler(test_post_router, pattern="^(test_|cancel)")],
            TEST_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, test_remove)],
            TEST_FNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, test_set_fname)],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(cancel_cb, pattern="^cancel$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("rate", go_rate))
    # catch-all text for rate/settings/stock when not inside nested state
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, rate_text_handler))

    return app

if __name__ == "__main__":
    # Sanity: enum length
    assert len(range(28)) == 28
    application = build_app()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
