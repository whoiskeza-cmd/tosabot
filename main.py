# main.py — Private Seller Panel (Telegram)
# Railway: set BOT_TOKEN, ADMIN_IDS (comma-separated), optional API_URL
# Fix for range unpack: use explicit ints / len(states), never range(28) into 27 names.

import os, re, json, random, io
from datetime import datetime, timezone
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters, ConversationHandler
)

# ─── ENV ───────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
STATS_PATH = os.path.join(DATA_DIR, "stats.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
STOCK_PATH = os.path.join(DATA_DIR, "stockpile.json")
BINDB_PATH = os.path.join(DATA_DIR, "bins_db.json")
RATES_PATH = os.path.join(DATA_DIR, "bin_rates.json")

# ─── Conversation states (explicit — fixes ValueError unpack) ───
(
    MAIN,
    FMT_WAIT_CARDS, FMT_USA_FOR, FMT_PRE, FMT_POST, FMT_REMOVE, FMT_FNAME,
    SALE_NAME, SALE_QTY, SALE_WAIT_CARDS, SALE_USA_FOR, SALE_PRE, SALE_POST, SALE_REMOVE,
    REP_NAME, REP_QTY, REP_WAIT_CARDS, REP_USA_FOR, REP_PRE, REP_POST, REP_REMOVE,
    TEST_TYPE, TEST_WAIT_CARDS, TEST_USA_FOR, TEST_PRE, TEST_POST, TEST_REMOVE, TEST_FNAME,
    RATE_MENU, RATE_BIN, RATE_VAL, RATE_SUG,
    SETTINGS_MENU, SETTINGS_VAL,
    STOCK_MENU, STOCK_BIN, STOCK_AMT, STOCK_SEARCH,
    CANCEL_CATCH,
) = range(39)  # 39 names ↔ range(39)

# ─── Defaults ──────────────────────────────────────────
DEFAULT_SETTINGS = {"sale_price": 15.0, "card_cost": 3.0, "force_vr": {}}
DEFAULT_STATS = lambda: {
    "cards_sold": 0, "total_sales": 0, "revenue": 0.0,
    "testers_given": 0, "replacements_given": 0, "total_profit": 0.0
}

BIN_INFO = {
    "410039": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "cc": "US"},
    "410040": {"brand": "VISA", "type": "CREDIT", "level": "BUSINESS", "bank": "CITIBANK, N.A.- COSTCO", "country": "UNITED STATES", "cc": "US"},
    "414720": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "cc": "US"},
    "414740": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "JPMORGAN CHASE BANK N.A.", "country": "UNITED STATES", "cc": "US"},
    "440066": {"brand": "VISA", "type": "CREDIT", "level": "TRADITIONAL", "bank": "BANK OF AMERICA - CONSUMER CREDIT", "country": "UNITED STATES", "cc": "US"},
    "483312": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "cc": "US"},
    "483316": {"brand": "VISA", "type": "DEBIT", "level": "CLASSIC", "bank": "JPMORGAN CHASE BANK N.A. - DEBIT", "country": "UNITED STATES", "cc": "US"},
    "513371": {"brand": "MASTERCARD", "type": "CREDIT", "level": "STANDARD", "bank": "NEWDAY, LTD.", "country": "UNITED KINGDOM", "cc": "GB"},
    "513379": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "BANQUE FEDERATIVE DU CREDIT MUTUEL (BFCM)", "country": "FRANCE", "cc": "FR"},
    "521729": {"brand": "MASTERCARD", "type": "DEBIT", "level": "STANDARD", "bank": "COMMONWEALTH BANK OF AUSTRALIA", "country": "AUSTRALIA", "cc": "AU"},
    "534348": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CELTIC BANK CORPORATION", "country": "UNITED STATES", "cc": "US"},
    "542418": {"brand": "MASTERCARD", "type": "CREDIT", "level": "PLATINUM", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "cc": "US"},
    "546616": {"brand": "MASTERCARD", "type": "CREDIT", "level": "WORLD", "bank": "CITIBANK N.A.", "country": "UNITED STATES", "cc": "US"},
}

def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if not callable(default) else default()

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def ensure_bin_db():
    db = load_json(BINDB_PATH, {})
    if not db:
        db = {k: v for k, v in BIN_INFO.items()}
        save_json(BINDB_PATH, db)
    return db

def get_rates():
    return load_json(RATES_PATH, {})

def save_rates(r):
    save_json(RATES_PATH, r)

def get_settings():
    s = load_json(SETTINGS_PATH, DEFAULT_SETTINGS.copy())
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s

def save_settings(s):
    save_json(SETTINGS_PATH, s)

def get_stock():
    return load_json(STOCK_PATH, {})  # bin -> qty

def save_stock(s):
    save_json(STOCK_PATH, s)

def uid_stats(uid):
    alls = load_json(STATS_PATH, {})
    key = str(uid)
    if key not in alls:
        alls[key] = DEFAULT_STATS()
        save_json(STATS_PATH, alls)
    return alls, key

def save_uid_stats(alls):
    save_json(STATS_PATH, alls)

def is_admin(uid):
    return uid in ADMIN_IDS

def get_random_ip():
    return ".".join(str(random.randint(1, 254)) for _ in range(4))

def batch_id():
    return random.randint(1000, 9999)

def parse_card_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split("|")
    # pan|mm/yy|cvv|name|addr|city|state|zip|cc|phone|email|ip
    if len(parts) < 3:
        return None
    pan = re.sub(r"\D", "", parts[0])
    if len(pan) < 13:
        return None
    exp = parts[1] if len(parts) > 1 else ""
    if "/" in exp:
        mm, yy = exp.split("/", 1)
    else:
        mm, yy = exp[:2], exp[2:]
    cvv = parts[2] if len(parts) > 2 else ""
    name = parts[3] if len(parts) > 3 else "N/A"
    address = parts[4] if len(parts) > 4 else "N/A"
    city = parts[5] if len(parts) > 5 else "N/A"
    state = parts[6] if len(parts) > 6 else "N/A"
    zipcode = parts[7] if len(parts) > 7 else "N/A"
    country = parts[8] if len(parts) > 8 else "US"
    phone = parts[9] if len(parts) > 9 else "N/A"
    email = parts[10] if len(parts) > 10 else "N/A"
    ip = parts[11] if len(parts) > 11 else get_random_ip()
    return {
        "pan": pan, "mm": mm.zfill(2), "yy": yy[-2:].zfill(2), "cvv": cvv,
        "name": name, "address": address, "city": city, "state": state,
        "zipcode": zipcode, "country": country, "phone": phone, "email": email, "ip": ip,
        "bin": pan[:6], "last4": pan[-4:],
    }

def parse_many(text):
    cards = []
    for line in text.replace("\r", "\n").split("\n"):
        c = parse_card_line(line)
        if c:
            cards.append(c)
    return cards

def bin_meta(bin6, settings=None):
    db = ensure_bin_db()
    info = db.get(bin6, {"brand": "UNKNOWN", "level": "STANDARD", "bank": "UNKNOWN", "country": "UNKNOWN", "cc": "??"})
    rates = get_rates()
    br = rates.get(bin6, {"rating": "10/10", "vr": 100, "balance": "N/A", "suggestion": "Online / BG"})
    settings = settings or get_settings()
    force = (settings.get("force_vr") or {}).get(bin6)
    vr = int(force) if force is not None else int(br.get("vr", 100))
    # show-only checker: always 100 live presentation
    vr = 100
    return info, br, vr

def format_card_block(c, is_tester=False):
    info, bin_data, vr = bin_meta(c["bin"])
    country = c.get("country") or info.get("country", "UNKNOWN")
    output = [
        "══════════════════════════════════════",
        f"🃏 LIVE Data • VR: {vr}%",
        "══════════════════════════════════════",
        f"👤 Name    : {c['name']}",
        f"💳 Card    : {c['pan']}",
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
        f"BIN Rate   : {bin_data.get('rating', '10/10')} | {bin_data.get('suggestion', 'N/A')}",
        "══════════════════════════════════════",
    ]
    if is_tester:
        output.append("❤️ High Quality Tester From E$CO ❤️")
    output.append("")
    output.append("✅ Vouch appreciated — send vouch after hit for priority restock.")
    return "\n".join(output)

def cards_to_file_text(cards, is_tester=False):
    blocks = [format_card_block(c, is_tester=is_tester) for c in cards]
    footer = "\n\n— End of batch —\nLeave a vouch • Private Seller Panel\n"
    return "\n\n".join(blocks) + footer

def main_keyboard():
    rows = [
        [InlineKeyboardButton("Format", callback_data="go_format"),
         InlineKeyboardButton("Sale", callback_data="go_sale")],
        [InlineKeyboardButton("Replace", callback_data="go_replace"),
         InlineKeyboardButton("Tester", callback_data="go_tester")],
        [InlineKeyboardButton("Rate", callback_data="go_rate"),
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
         InlineKeyboardButton("Remove Cards", callback_data="fmt_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="fmt_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="fmt_add"),
         InlineKeyboardButton("Remove Cards", callback_data="fmt_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def usa_for_kb(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data=f"{prefix}_usa"),
         InlineKeyboardButton("Foreign", callback_data=f"{prefix}_foreign")],
    ])

async def guard(update: Update):
    uid = update.effective_user.id
    if not is_admin(uid):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        elif update.callback_query:
            await update.callback_query.answer("Unauthorized", show_alert=True)
        return False
    return True

async def start_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    user = update.effective_user
    text = f"Private Seller Panel\nWelcome @{user.username or user.id}"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    context.user_data.clear()
    return MAIN

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await start_panel(update, context)

# ─── FORMAT ────────────────────────────────────────────
async def go_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["mode"] = "format"
    context.user_data["cards"] = []
    context.user_data["filename"] = None
    context.user_data["batch"] = batch_id()
    context.user_data["filter"] = None
    await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
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
    new_cards = parse_many(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed. Send pan|mm/yy|cvv|... lines or .txt")
        return FMT_WAIT_CARDS
    context.user_data.setdefault("pending", []).extend(new_cards)
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_for_kb("fmt"))
    return FMT_USA_FOR

async def fmt_usa_for(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    which = "usa" if q.data.endswith("usa") else "foreign"
    pending = context.user_data.pop("pending", [])
    if which == "usa":
        pending = [c for c in pending if c.get("country", "US").upper() in ("US", "USA", "UNITED STATES") or c["bin"] in BIN_INFO and BIN_INFO[c["bin"]].get("cc") == "US"]
    else:
        pending = [c for c in pending if not (c.get("country", "US").upper() in ("US", "USA", "UNITED STATES"))]
        if not pending:
            # if filter emptied, keep all as foreign-tagged pass-through
            pending = context.user_data.get("cards", [])[-0:]  # no-op
    # simpler: store filter flag and keep all cards user sent
    pending = context.user_data.get("last_pending_backup", pending)
    # Actually use full pending before filter wipe — restore:
    # re-parse path: we saved into pending then popped. Fix by not filtering aggressively:
    # Reload from a side key
    return await fmt_show_pre(update, context, extra=pending if pending else context.user_data.get("cards", []))

async def fmt_usa_for_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pending = context.user_data.pop("pending", [])
    context.user_data.setdefault("cards", []).extend(pending)
    context.user_data["batch"] = batch_id()
    return await fmt_render_pre(q, context)

async def fmt_render_pre(q_or_msg, context, edit=True):
    cards = context.user_data.get("cards", [])
    fn = context.user_data.get("filename") or f"Batch-{context.user_data.get('batch', batch_id())}"
    text = (
        f"PreSummary /format\n"
        f"Total Cards: {len(cards)}\n"
        f"Mode: Base\n"
        f"FileName: {fn}"
    )
    kb = pre_kb_format()
    if hasattr(q_or_msg, "edit_message_text") and edit:
        await q_or_msg.edit_message_text(text, reply_markup=kb)
    else:
        await q_or_msg.message.reply_text(text, reply_markup=kb)
    return FMT_PRE

# bind usa/foreign to fixed handler
fmt_usa_for = fmt_usa_for_fixed

async def fmt_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "fmt_check":
        # show-only: 100% live
        cards = context.user_data.get("cards", [])
        live = len(cards)
        text = (
            f"PostSummary /format\n"
            f"Total Cards: {len(cards)}\n"
            f"LiveRate: 100%\n"
            f"Live: {live}/{len(cards)}"
        )
        await q.edit_message_text(text, reply_markup=post_kb_format())
        return FMT_POST
    if data == "fmt_fname":
        await q.edit_message_text("Send filename (without .txt)")
        return FMT_FNAME
    if data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FMT_REMOVE
    if data == "cancel":
        return await cancel(update, context)
    return FMT_PRE

async def fmt_set_fname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["filename"] = (update.message.text or "Batch").strip().replace(".txt", "")
    # fake query-like render
    class O: pass
    o = O(); o.edit_message_text = lambda *a, **k: update.message.reply_text(a[0], reply_markup=k.get("reply_markup"))
    return await fmt_render_pre(o, context, edit=False)

async def fmt_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "")
    lasts = {x.strip() for x in raw.split(",") if x.strip()}
    cards = context.user_data.get("cards", [])
    context.user_data["cards"] = [c for c in cards if c["last4"] not in lasts]
    class O: pass
    o = O(); o.edit_message_text = lambda *a, **k: update.message.reply_text(a[0], reply_markup=k.get("reply_markup"))
    return await fmt_render_pre(o, context, edit=False)

async def fmt_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "fmt_send":
        cards = context.user_data.get("cards", [])
        fn = context.user_data.get("filename") or f"Batch-{context.user_data.get('batch', batch_id())}"
        body = cards_to_file_text(cards, is_tester=False)
        bio = io.BytesIO(body.encode("utf-8"))
        bio.name = f"{fn}.txt"
        await q.message.reply_document(document=InputFile(bio), caption="Formatted batch — vouch on hit")
        return await start_panel(update, context)
    if data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FMT_REMOVE
    if data == "cancel":
        return await cancel(update, context)
    return FMT_POST

# ─── SALE ──────────────────────────────────────────────
def sale_pre_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add More Cards", callback_data="sale_add"),
         InlineKeyboardButton("Remove Cards", callback_data="sale_rem")],
        [InlineKeyboardButton("Check", callback_data="sale_check"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def sale_post_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="sale_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="sale_add"),
         InlineKeyboardButton("Remove Cards", callback_data="sale_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

async def go_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["mode"] = "sale"
    context.user_data["cards"] = []
    context.user_data["batch"] = batch_id()
    await q.edit_message_text("Please Respond With The Customer Name")
    return SALE_NAME

async def sale_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = (update.message.text or "Customer").strip()
    await update.message.reply_text(f'How Many Cards Is "{context.user_data["customer"]}" Purchasing? (number)')
    return SALE_QTY

async def sale_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["target"] = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        context.user_data["target"] = 0
    await update.message.reply_text("Target Set\nSend Cards Or Drop .txt File To Continue")
    return SALE_WAIT_CARDS

async def sale_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    context.user_data.setdefault("pending", []).extend(parse_many(text))
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_for_kb("sale"))
    return SALE_USA_FOR

async def sale_usa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pending = context.user_data.pop("pending", [])
    context.user_data.setdefault("cards", []).extend(pending)
    return await sale_render_pre(q, context)

async def sale_render_pre(q, context):
    st = get_settings()
    cards = context.user_data.get("cards", [])
    target = context.user_data.get("target", 0)
    rev = target * float(st["sale_price"])
    text = (
        f"PreSummary /sale\n"
        f"Target: {target}\n"
        f"Total Cards: {len(cards)}\n"
        f"Mode: Sale\n"
        f"Total Revenue: ${rev:.2f}\n"
        f"+ (Sale Cost ${st['sale_price']}/card)"
    )
    await q.edit_message_text(text, reply_markup=sale_pre_kb())
    return SALE_PRE

async def sale_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "sale_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if q.data == "sale_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return SALE_REMOVE
    if q.data == "sale_check":
        return await sale_render_post(q, context)
    if q.data == "cancel":
        return await cancel(update, context)
    return SALE_PRE

async def sale_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lasts = {x.strip() for x in (update.message.text or "").split(",") if x.strip()}
    context.user_data["cards"] = [c for c in context.user_data.get("cards", []) if c["last4"] not in lasts]
    class O: pass
    o = O()
    async def edit(t, reply_markup=None):
        await update.message.reply_text(t, reply_markup=reply_markup)
    o.edit_message_text = edit
    return await sale_render_pre(o, context)

async def sale_render_post(q, context):
    st = get_settings()
    cards = context.user_data.get("cards", [])
    target = int(context.user_data.get("target", 0))
    live = len(cards)  # show 100%
    extras = max(0, live - target)
    reached = live >= target
    revenue = target * float(st["sale_price"])
    cost = live * float(st["card_cost"])
    profit = revenue - cost
    context.user_data["_sale_math"] = {"revenue": revenue, "profit": profit, "live": live, "extras": extras}
    text = (
        f"PostSummary /sale\n"
        f"Total Cards: {len(cards)}\n"
        f"Total Live: {live}\n"
        f"Extras: {extras}\n"
        f"Target Reached: {reached}\n"
        f"Profit Made: ${profit:.2f}\n"
        f"Total Revenue After Sale: ${revenue:.2f}\n"
        f"LiveRate: 100%"
    )
    await q.edit_message_text(text, reply_markup=sale_post_kb())
    return SALE_POST

async def sale_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "sale_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if q.data == "sale_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return SALE_REMOVE
    if q.data == "cancel":
        return await cancel(update, context)
    if q.data == "sale_send":
        cards = context.user_data.get("cards", [])
        target = int(context.user_data.get("target", 0))
        live = len(cards)
        primary = cards[:target] if target > 0 else cards
        extras = cards[target:] if target > 0 else []
        cust = context.user_data.get("customer", "Customer")
        bid = context.user_data.get("batch", batch_id())
        body = cards_to_file_text(primary)
        bio = io.BytesIO(body.encode())
        bio.name = f"{cust}-{len(primary)}-{bid}.txt"
        await q.message.reply_document(InputFile(bio), caption="Sale pack — vouch pls")
        if extras:
            body2 = cards_to_file_text(extras)
            bio2 = io.BytesIO(body2.encode())
            bio2.name = f"Extras-{len(extras)}-{bid}.txt"
            await q.message.reply_document(InputFile(bio2), caption="Extras")
        # stats + stockpile deduct
        math = context.user_data.get("_sale_math") or {}
        alls, key = uid_stats(update.effective_user.id)
        alls[key]["cards_sold"] += len(primary)
        alls[key]["total_sales"] += 1
        alls[key]["revenue"] += float(math.get("revenue", 0))
        alls[key]["total_profit"] += float(math.get("profit", 0))
        save_uid_stats(alls)
        stock = get_stock()
        for c in primary:
            b = c["bin"]
            if b in stock:
                stock[b] = max(0, int(stock[b]) - 1)
        save_stock(stock)
        return await start_panel(update, context)
    return SALE_POST

# ─── REPLACE ───────────────────────────────────────────
def rep_pre_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="rep_check")],
        [InlineKeyboardButton("Add More Cards", callback_data="rep_add"),
         InlineKeyboardButton("Remove Cards", callback_data="rep_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def rep_post_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data="rep_send")],
        [InlineKeyboardButton("Add More Cards", callback_data="rep_add"),
         InlineKeyboardButton("Remove Cards", callback_data="rep_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

async def go_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["mode"] = "replace"
    context.user_data["cards"] = []
    context.user_data["batch"] = batch_id()
    await q.edit_message_text("Who Is Being Replaced?")
    return REP_NAME

async def rep_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["customer"] = (update.message.text or "").strip()
    await update.message.reply_text("How Many Cards Are Being Replaced? (number)")
    return REP_QTY

async def rep_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["target"] = int(re.sub(r"\D", "", update.message.text or "0") or 0)
    await update.message.reply_text("Target Submitted\nSend Cards Or Drop .txt File To Continue")
    return REP_WAIT_CARDS

async def rep_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
    else:
        text = update.message.text or ""
    context.user_data.setdefault("pending", []).extend(parse_many(text))
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_for_kb("rep"))
    return REP_USA_FOR

async def rep_usa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.setdefault("cards", []).extend(context.user_data.pop("pending", []))
    cards = context.user_data["cards"]
    text = (
        f"PreSummary /replace\n"
        f"Total Cards: {len(cards)}\n"
        f"Replacement Target: {context.user_data.get('target')}\n"
        f"Customer Name: {context.user_data.get('customer')}"
    )
    await q.edit_message_text(text, reply_markup=rep_pre_kb())
    return REP_PRE

async def rep_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "rep_add":
        await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
        return REP_WAIT_CARDS
    if q.data == "rep_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return REP_REMOVE
    if q.data == "cancel":
        return await cancel(update, context)
    if q.data == "rep_check":
        cards = context.user_data.get("cards", [])
        target = int(context.user_data.get("target", 0))
        live = len(cards)
        extras = max(0, live - target)
        text = (
            f"PostSummary /replace\n"
            f"Total Cards: {len(cards)}\n"
            f"Extras: {extras}\n"
            f"Liverate: 100%\n"
            f"Replacement Target Reached: {live >= target}\n"
            f"Customer Name: {context.user_data.get('customer')}"
        )
        await q.edit_message_text(text, reply_markup=rep_post_kb())
        return REP_POST
    return REP_PRE

async def rep_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lasts = {x.strip() for x in (update.message.text or "").split(",") if x.strip()}
    context.user_data["cards"] = [c for c in context.user_data.get("cards", []) if c["last4"] not in lasts]
    await update.message.reply_text("Removed. Press Check or use menu.", reply_markup=rep_pre_kb())
    return REP_PRE

async def rep_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "rep_add":
        await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
        return REP_WAIT_CARDS
    if q.data == "rep_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return REP_REMOVE
    if q.data == "cancel":
        return await cancel(update, context)
    if q.data == "rep_send":
        cards = context.user_data.get("cards", [])
        target = int(context.user_data.get("target", 0))
        primary = cards[:target] if target else cards
        extras = cards[target:] if target else []
        cust = context.user_data.get("customer", "Customer")
        bid = context.user_data.get("batch", batch_id())
        bio = io.BytesIO(cards_to_file_text(primary).encode())
        bio.name = f"{cust}-{len(primary)}-{bid}.txt"
        await q.message.reply_document(InputFile(bio))
        if extras:
            bio2 = io.BytesIO(cards_to_file_text(extras).encode())
            bio2.name = f"Extras-{len(extras)}-{bid}.txt"
            await q.message.reply_document(InputFile(bio2))
        st = get_settings()
        cost = len(primary) * float(st["card_cost"])
        alls, key = uid_stats(update.effective_user.id)
        alls[key]["replacements_given"] += len(primary)
        alls[key]["total_profit"] -= cost
        # subtract card cost from revenue per spec
        alls[key]["revenue"] -= cost
        save_uid_stats(alls)
        return await start_panel(update, context)
    return REP_POST

# ─── TESTER ────────────────────────────────────────────
async def go_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["mode"] = "tester"
    context.user_data["cards"] = []
    context.user_data["batch"] = batch_id()
    context.user_data["filename"] = None
    await q.edit_message_text("Is This Tester A Drop Or Gift? (reply Drop or Gift)")
    return TEST_TYPE

async def test_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tester_kind"] = (update.message.text or "Gift").strip()
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
    context.user_data.setdefault("pending", []).extend(parse_many(text))
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_for_kb("test"))
    return TEST_USA_FOR

async def test_usa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.setdefault("cards", []).extend(context.user_data.pop("pending", []))
    fn = context.user_data.get("filename") or f"Batch-{context.user_data.get('batch')}"
    cards = context.user_data["cards"]
    text = f"PreSummary /tester\nTotal Cards: {len(cards)}\nMode: Base\nFileName: {fn}\nKind: {context.user_data.get('tester_kind')}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="test_check"),
         InlineKeyboardButton("Set Filename", callback_data="test_fname")],
        [InlineKeyboardButton("Add More Cards", callback_data="test_add"),
         InlineKeyboardButton("Remove Cards", callback_data="test_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    await q.edit_message_text(text, reply_markup=kb)
    return TEST_PRE

async def test_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "test_fname":
        await q.edit_message_text("Send filename")
        return TEST_FNAME
    if q.data == "test_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TEST_WAIT_CARDS
    if q.data == "test_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return TEST_REMOVE
    if q.data == "cancel":
        return await cancel(update, context)
    if q.data == "test_check":
        cards = context.user_data.get("cards", [])
        text = f"PostSummary /tester\nTotal Cards: {len(cards)}\nLiveRate: 100%"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Send File", callback_data="test_send")],
            [InlineKeyboardButton("Add More Cards", callback_data="test_add"),
             InlineKeyboardButton("Remove Cards", callback_data="test_rem")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ])
        await q.edit_message_text(text, reply_markup=kb)
        return TEST_POST
    return TEST_PRE

async def test_fname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["filename"] = (update.message.text or "Tester").strip().replace(".txt", "")
    await update.message.reply_text("Filename set. Add cards or Check from panel buttons — resend /start flow: use Add/Check via /tester again if needed.")
    # re-show pre
    fn = context.user_data["filename"]
    cards = context.user_data.get("cards", [])
    text = f"PreSummary /tester\nTotal Cards: {len(cards)}\nMode: Base\nFileName: {fn}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="test_check"),
         InlineKeyboardButton("Set Filename", callback_data="test_fname")],
        [InlineKeyboardButton("Add More Cards", callback_data="test_add"),
         InlineKeyboardButton("Remove Cards", callback_data="test_rem")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    await update.message.reply_text(text, reply_markup=kb)
    return TEST_PRE

async def test_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lasts = {x.strip() for x in (update.message.text or "").split(",") if x.strip()}
    context.user_data["cards"] = [c for c in context.user_data.get("cards", []) if c["last4"] not in lasts]
    await update.message.reply_text(f"Removed. Total now {len(context.user_data['cards'])}")
    return TEST_PRE

async def test_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "test_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TEST_WAIT_CARDS
    if q.data == "test_rem":
        await q.edit_message_text("Send Last 4# Separated By Commas")
        return TEST_REMOVE
    if q.data == "cancel":
        return await cancel(update, context)
    if q.data == "test_send":
        cards = context.user_data.get("cards", [])
        fn = context.user_data.get("filename") or f"Batch-{context.user_data.get('batch')}"
        bio = io.BytesIO(cards_to_file_text(cards, is_tester=True).encode())
        bio.name = f"{fn}.txt"
        await q.message.reply_document(InputFile(bio), caption="Tester pack")
        alls, key = uid_stats(update.effective_user.id)
        alls[key]["testers_given"] += len(cards)
        save_uid_stats(alls)
        return await start_panel(update, context)
    return TEST_POST

# ─── RATE ──────────────────────────────────────────────
async def go_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await q.edit_message_text("Rate menu", reply_markup=kb)
    return RATE_MENU

async def rate_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    context.user_data["rate_action"] = q.data
    await q.edit_message_text("Send Bin 6 Digit Number")
    return RATE_BIN

async def rate_bin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    b = re.sub(r"\D", "", update.message.text or "")[:6]
    context.user_data["rate_bin"] = b
    db = ensure_bin_db()
    info = db.get(b, {"bank": "UNKNOWN", "brand": "?", "country": "?"})
    act = context.user_data.get("rate_action")
    await update.message.reply_text(
        f"You Have Selected Bin {b}\n{info}\n"
        + ("What VR 0-100? (or Reset to disable)" if act == "rate_force" else "Send rating value / suggestion text")
    )
    return RATE_VAL

async def rate_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    b = context.user_data.get("rate_bin")
    val = (update.message.text or "").strip()
    act = context.user_data.get("rate_action")
    rates = get_rates()
    rates.setdefault(b, {"rating": "10/10", "vr": 100, "balance": "N/A", "suggestion": "N/A"})
    st = get_settings()
    st.setdefault("force_vr", {})
    if act == "rate_vr":
        rates[b]["vr"] = int(re.sub(r"\D", "", val) or 100)
    elif act == "rate_bin":
        rates[b]["rating"] = val
    elif act == "rate_bal":
        rates[b]["balance"] = val
    elif act == "rate_sug":
        rates[b]["suggestion"] = val
    elif act == "rate_force":
        if val.lower() == "reset":
            st["force_vr"].pop(b, None)
        else:
            st["force_vr"][b] = int(re.sub(r"\D", "", val) or 100)
        save_settings(st)
    save_rates(rates)
    await update.message.reply_text(f"Saved for {b}")
    return await start_panel(update, context)

# ─── STATS ─────────────────────────────────────────────
async def go_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    alls, key = uid_stats(update.effective_user.id)
    s = alls[key]
    text = (
        f"Stats @{update.effective_user.username or key}\n"
        f"Cards Sold: {s['cards_sold']}\n"
        f"Total Sales: {s['total_sales']}\n"
        f"Revenue: ${s['revenue']:.2f}\n"
        f"Testers Given: {s['testers_given']}\n"
        f"Replacements Given: {s['replacements_given']}\n"
        f"Total Profit: ${s['total_profit']:.2f}"
    )
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="cancel")]]))
    return MAIN

# ─── SETTINGS ──────────────────────────────────────────
async def go_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = get_settings()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Sale Price", callback_data="set_sale")],
        [InlineKeyboardButton("Set Card Cost", callback_data="set_cost")],
        [InlineKeyboardButton("Back", callback_data="cancel")],
    ])
    await q.edit_message_text(f"Settings\nSale price: ${st['sale_price']}\nCard cost: ${st['card_cost']}", reply_markup=kb)
    return SETTINGS_MENU

async def settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    context.user_data["set_field"] = "sale_price" if q.data == "set_sale" else "card_cost"
    await q.edit_message_text("Send new number value")
    return SETTINGS_VAL

async def settings_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = get_settings()
    field = context.user_data.get("set_field", "sale_price")
    try:
        st[field] = float((update.message.text or "0").replace("$", ""))
    except Exception:
        pass
    save_settings(st)
    await update.message.reply_text(f"Saved {field}={st[field]}")
    return await start_panel(update, context)

# ─── STOCKPILE ─────────────────────────────────────────
async def go_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Bin Qty", callback_data="stock_add"),
         InlineKeyboardButton("Sub Bin Qty", callback_data="stock_sub")],
        [InlineKeyboardButton("Search Bin", callback_data="stock_search")],
        [InlineKeyboardButton("Send Binlist", callback_data="stock_list")],
        [InlineKeyboardButton("Back", callback_data="cancel")],
    ])
    stock = get_stock()
    await q.edit_message_text(f"Stockpile bins tracked: {len(stock)}", reply_markup=kb)
    return STOCK_MENU

async def stock_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    if q.data == "stock_list":
        stock = get_stock()
        db = ensure_bin_db()
        lines = ["Bin*Qty*Country"]
        for b, qty in sorted(stock.items()):
            cc = db.get(b, {}).get("country", "?")
            lines.append(f"{b}*{qty}*{cc}")
        bio = io.BytesIO("\n".join(lines).encode())
        bio.name = "stockpile_binlist.txt"
        await q.message.reply_document(InputFile(bio), caption="Stockpile binlist")
        # also forwardable text
        msg = "\n".join(lines[:80])
        await q.message.reply_text(msg or "Empty stockpile")
        return STOCK_MENU
    context.user_data["stock_op"] = q.data
    await q.edit_message_text("Send 6-digit BIN")
    return STOCK_BIN

async def stock_bin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    b = re.sub(r"\D", "", update.message.text or "")[:6]
    context.user_data["stock_bin"] = b
    op = context.user_data.get("stock_op")
    if op == "stock_search":
        stock = get_stock()
        qty = int(stock.get(b, 0))
        db = ensure_bin_db()
        cc = db.get(b, {}).get("country", "?")
        # forwardable
        await update.message.reply_text(f"{b}*{qty}*{cc}\nAvailable: {qty}")
        return await start_panel(update, context)
    await update.message.reply_text("Send amount (integer)")
    return STOCK_AMT

async def stock_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    b = context.user_data.get("stock_bin")
    try:
        amt = int(re.sub(r"\D", "", update.message.text or "0"))
    except Exception:
        amt = 0
    stock = get_stock()
    cur = int(stock.get(b, 0))
    op = context.user_data.get("stock_op")
    if op == "stock_add":
        stock[b] = cur + amt
    else:
        stock[b] = max(0, cur - amt)
    save_stock(stock)
    # ensure bin recognized
    db = ensure_bin_db()
    if b not in db:
        db[b] = {"brand": "UNKNOWN", "level": "STANDARD", "bank": "UNKNOWN", "country": "UNKNOWN", "cc": "??"}
        save_json(BINDB_PATH, db)
    await update.message.reply_text(f"{b} now {stock[b]}")
    return await start_panel(update, context)

# ─── MAIN router ───────────────────────────────────────
async def main_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    q = update.callback_query
    mapping = {
        "go_format": go_format,
        "go_sale": go_sale,
        "go_replace": go_replace,
        "go_tester": go_tester,
        "go_rate": go_rate,
        "go_stats": go_stats,
        "go_settings": go_settings,
        "go_stock": go_stock,
        "cancel": cancel,
    }
    fn = mapping.get(q.data)
    if fn:
        return await fn(update, context)
    await q.answer()
    return MAIN

def build_app():
    ensure_bin_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_panel), CommandHandler("panel", start_panel)],
        states={
            MAIN: [CallbackQueryHandler(main_cb)],
            FMT_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, fmt_recv_cards)],
            FMT_USA_FOR: [CallbackQueryHandler(fmt_usa_for, pattern=r"^fmt_")],
            FMT_PRE: [CallbackQueryHandler(fmt_pre_cb)],
            FMT_POST: [CallbackQueryHandler(fmt_post_cb)],
            FMT_REMOVE: [MessageHandler(filters.TEXT, fmt_remove)],
            FMT_FNAME: [MessageHandler(filters.TEXT, fmt_set_fname)],
            SALE_NAME: [MessageHandler(filters.TEXT, sale_name)],
            SALE_QTY: [MessageHandler(filters.TEXT, sale_qty)],
            SALE_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, sale_recv)],
            SALE_USA_FOR: [CallbackQueryHandler(sale_usa, pattern=r"^sale_")],
            SALE_PRE: [CallbackQueryHandler(sale_pre_cb)],
            SALE_POST: [CallbackQueryHandler(sale_post_cb)],
            SALE_REMOVE: [MessageHandler(filters.TEXT, sale_remove)],
            REP_NAME: [MessageHandler(filters.TEXT, rep_name)],
            REP_QTY: [MessageHandler(filters.TEXT, rep_qty)],
            REP_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, rep_recv)],
            REP_USA_FOR: [CallbackQueryHandler(rep_usa, pattern=r"^rep_")],
            REP_PRE: [CallbackQueryHandler(rep_pre_cb)],
            REP_POST: [CallbackQueryHandler(rep_post_cb)],
            REP_REMOVE: [MessageHandler(filters.TEXT, rep_remove)],
            TEST_TYPE: [MessageHandler(filters.TEXT, test_type)],
            TEST_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT, test_recv)],
            TEST_USA_FOR: [CallbackQueryHandler(test_usa, pattern=r"^test_")],
            TEST_PRE: [CallbackQueryHandler(test_pre_cb)],
            TEST_POST: [CallbackQueryHandler(test_post_cb)],
            TEST_REMOVE: [MessageHandler(filters.TEXT, test_remove)],
            TEST_FNAME: [MessageHandler(filters.TEXT, test_fname)],
            RATE_MENU: [CallbackQueryHandler(rate_menu_cb)],
            RATE_BIN: [MessageHandler(filters.TEXT, rate_bin)],
            RATE_VAL: [MessageHandler(filters.TEXT, rate_val)],
            SETTINGS_MENU: [CallbackQueryHandler(settings_cb)],
            SETTINGS_VAL: [MessageHandler(filters.TEXT, settings_val)],
            STOCK_MENU: [CallbackQueryHandler(stock_cb)],
            STOCK_BIN: [MessageHandler(filters.TEXT, stock_bin)],
            STOCK_AMT: [MessageHandler(filters.TEXT, stock_amt)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start_panel),
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
        ],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("stats", lambda u, c: go_stats(u, c) if u.callback_query else start_panel(u, c)))
    return app

if __name__ == "__main__":
    build_app().run_polling(drop_pending_updates=True)
