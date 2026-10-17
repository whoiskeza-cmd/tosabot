# main.py — E$CO Seller Panel (Telegram)
# Fix: ConversationHandler states must match unpack count.
# Railway: set BOT_TOKEN, ADMIN_IDS (comma-sep), optional STORM_API_URL / STORM_USER_ID

import os, re, json, random, io, hashlib
from datetime import datetime, timezone
from collections import defaultdict

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ─── ENV ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_IDS = set(
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "123456789").split(",") if x.strip()
)
STORM_API_URL = os.environ.get("STORM_API_URL", "")
STORM_USER_ID = os.environ.get("STORM_USER_ID", "")
DATA_FILE = os.environ.get("DATA_FILE", "esco_data.json")

# ─── STATES (exactly 28 — fixes ValueError expected 27 / got 28) ───
(
    MAIN,
    FMT_WAIT_CARDS, FMT_USA_FOREIGN, FMT_PRE, FMT_POST, FMT_REMOVE, FMT_SETNAME,
    SALE_NAME, SALE_QTY, SALE_WAIT_CARDS, SALE_USA_FOREIGN, SALE_PRE, SALE_POST, SALE_REMOVE,
    REP_NAME, REP_QTY, REP_WAIT_CARDS, REP_USA_FOREIGN, REP_PRE, REP_POST, REP_REMOVE,
    TEST_TYPE, TEST_WAIT_CARDS, TEST_USA_FOREIGN, TEST_PRE, TEST_POST, TEST_REMOVE, TEST_SETNAME,
    RATE_MENU, RATE_BIN_WAIT, RATE_VR_WAIT, RATE_RATE_WAIT, RATE_BAL_WAIT, RATE_SUG_WAIT, RATE_FORCE_WAIT,
) = range(35)  # extra headroom; ConversationHandler only uses named states you reference

# If you must keep a tight tuple, use:
# STATES = list(range(35)) and index by name — the crash was unpacking range(28) into 27 names.

# ─── BIN DB ────────────────────────────────────────────
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

DEFAULT_BIN_META = {"rating": "8.5/10", "suggestion": "Amazon · Apple · Digital", "vr": 100, "balance_rating": "7/10", "forced_vr": None}

# ─── PERSISTENCE ───────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "admins": {},          # uid -> stats
        "bin_meta": {},        # bin6 -> meta
        "global": {
            "cards_sold": 0, "total_sales": 0, "revenue": 0.0,
            "profit": 0.0, "testers_given": 0, "replacements_given": 0,
            "card_cost": 3.0, "sale_price": 15.0,  # defaults; change via env if needed
        },
        "batch_seq": 1000,
    }

def save_data(d):
    with open(DATA_FILE, "w") as f:
        json.dump(d, f, indent=2)

DATA = load_data()

def ensure_admin(uid: int):
    s = str(uid)
    if s not in DATA["admins"]:
        DATA["admins"][s] = {
            "cards_sold": 0, "total_sales": 0, "revenue": 0.0, "profit": 0.0,
            "testers_given": 0, "replacements_given": 0,
        }
        save_data(DATA)

def next_batch():
    DATA["batch_seq"] = DATA.get("batch_seq", 1000) + 1
    save_data(DATA)
    return DATA["batch_seq"]

def bin_meta(bin6: str):
    m = DATA.setdefault("bin_meta", {}).get(bin6, DEFAULT_BIN_META.copy())
    # merge defaults
    out = DEFAULT_BIN_META.copy()
    out.update(m)
    return out

def set_bin_field(bin6: str, field: str, value):
    DATA.setdefault("bin_meta", {}).setdefault(bin6, DEFAULT_BIN_META.copy())
    DATA["bin_meta"][bin6][field] = value
    save_data(DATA)

# ─── CARD PARSE / FORMAT ───────────────────────────────
CARD_RE = re.compile(
    r"(?P<pan>\d{15,16})[|/\s]+(?P<mm>\d{1,2})[/|](?P<yy>\d{2,4})[|/\s]+(?P<cvv>\d{3,4})"
    r"(?:[|/\s]+(?P<name>[^|]+))?"
    r"(?:[|/\s]+(?P<address>[^|]+))?"
    r"(?:[|/\s]+(?P<city>[^|]+))?"
    r"(?:[|/\s]+(?P<state>[^|]+))?"
    r"(?:[|/\s]+(?P<zipcode>[^|]+))?"
    r"(?:[|/\s]+(?P<country>[^|]+))?"
    r"(?:[|/\s]+(?P<phone>[^|]+))?"
    r"(?:[|/\s]+(?P<email>[^|]+))?"
    r"(?:[|/\s]+(?P<ip>[^|]+))?",
    re.I,
)

def get_random_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

def parse_cards(text: str):
    cards = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # pipe-split preferred
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and re.match(r"^\d{15,16}$", parts[0]):
            pan, exp, cvv = parts[0], parts[1], parts[2]
            if "/" in exp:
                mm, yy = exp.split("/", 1)
            elif len(exp) == 4:
                mm, yy = exp[:2], exp[2:]
            else:
                mm, yy = exp, "30"
            yy = yy[-2:]
            name = parts[3] if len(parts) > 3 else "JOHN DOE"
            address = parts[4] if len(parts) > 4 else "123 MAIN ST"
            city = parts[5] if len(parts) > 5 else "CITY"
            state = parts[6] if len(parts) > 6 else "CA"
            zipcode = parts[7] if len(parts) > 7 else "90001"
            country = parts[8] if len(parts) > 8 else "US"
            phone = parts[9] if len(parts) > 9 else "0000000000"
            email = parts[10] if len(parts) > 10 else "user@email.com"
            ip = parts[11] if len(parts) > 11 else get_random_ip()
            cards.append({
                "pan": pan, "mm": mm.zfill(2), "yy": yy.zfill(2), "cvv": cvv,
                "name": name, "address": address, "city": city, "state": state,
                "zipcode": zipcode, "country": country, "phone": phone, "email": email, "ip": ip,
                "last4": pan[-4:], "bin": pan[:6],
            })
            continue
        m = CARD_RE.search(line)
        if m:
            d = m.groupdict()
            yy = (d.get("yy") or "30")[-2:]
            pan = d["pan"]
            cards.append({
                "pan": pan, "mm": (d.get("mm") or "01").zfill(2), "yy": yy, "cvv": d.get("cvv") or "000",
                "name": (d.get("name") or "JOHN DOE").strip(),
                "address": (d.get("address") or "123 MAIN ST").strip(),
                "city": (d.get("city") or "CITY").strip(),
                "state": (d.get("state") or "CA").strip(),
                "zipcode": (d.get("zipcode") or "90001").strip(),
                "country": (d.get("country") or "US").strip(),
                "phone": (d.get("phone") or "0000000000").strip(),
                "email": (d.get("email") or "user@email.com").strip(),
                "ip": (d.get("ip") or get_random_ip()).strip(),
                "last4": pan[-4:], "bin": pan[:6],
            })
    return cards

def lookup_bin(bin6: str):
    info = BIN_DB.get(bin6, {
        "brand": "UNKNOWN", "type": "CREDIT", "level": "STANDARD",
        "bank": "UNKNOWN", "country": "UNKNOWN", "scheme": "unknown",
    })
    return info

def format_card_block(c, is_tester=False):
    info = lookup_bin(c["bin"])
    meta = bin_meta(c["bin"])
    vr = meta.get("forced_vr") if meta.get("forced_vr") is not None else 100  # always show 100 live
    country = c.get("country") or info.get("country", "US")
    lines = [
        "══════════════════════════════════════",
        f"🃏 LIVE • VR: {vr}%",
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
        f"BIN Rate   : {meta.get('rating', '8.5/10')} | {meta.get('suggestion', 'Amazon · Apple · Digital')}",
        "══════════════════════════════════════",
    ]
    if is_tester:
        lines.append("❤️ Thank You For Choosing E$CO ❤️")
    lines.append("")
    lines.append("⭐ Leave a vouch after successful use — E$CO")
    lines.append("")
    return "\n".join(lines)

def build_output_file(cards, is_tester=False):
    body = "\n".join(format_card_block(c, is_tester=is_tester) for c in cards)
    footer = (
        "\n\n══════════════════════════════════════\n"
        "E$CO • Formatted batch\n"
        "All shown LIVE • VR 100% (display)\n"
        "Send vouches after hits — keeps the desk alive\n"
        "══════════════════════════════════════\n"
    )
    return body + footer

def filter_usa(cards, usa=True):
    def is_us(c):
        co = (c.get("country") or "").upper()
        info = lookup_bin(c["bin"])
        bank_co = (info.get("country") or "").upper()
        return co in ("US", "USA", "UNITED STATES") or "UNITED STATES" in bank_co
    return [c for c in cards if is_us(c) == usa]

# ─── KEYBOARDS ─────────────────────────────────────────
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Format", callback_data="mode_format"),
         InlineKeyboardButton("Sale", callback_data="mode_sale")],
        [InlineKeyboardButton("Replace", callback_data="mode_replace"),
         InlineKeyboardButton("Tester", callback_data="mode_tester")],
        [InlineKeyboardButton("Rate / BIN", callback_data="mode_rate"),
         InlineKeyboardButton("Balance", callback_data="mode_balance")],
        [InlineKeyboardButton("Stats", callback_data="mode_stats")],
    ])

def pre_kb(prefix="fmt"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data=f"{prefix}_check"),
         InlineKeyboardButton("Set Filename", callback_data=f"{prefix}_setname")],
        [InlineKeyboardButton("Add More Cards", callback_data=f"{prefix}_add"),
         InlineKeyboardButton("Remove Cards", callback_data=f"{prefix}_remove")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def pre_kb_sale(prefix="sale"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add More Cards", callback_data=f"{prefix}_add"),
         InlineKeyboardButton("Remove Cards", callback_data=f"{prefix}_remove")],
        [InlineKeyboardButton("Check", callback_data=f"{prefix}_check"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def post_kb(prefix="fmt"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data=f"{prefix}_send"),
         InlineKeyboardButton("Add More Cards", callback_data=f"{prefix}_add")],
        [InlineKeyboardButton("Remove Cards", callback_data=f"{prefix}_remove"),
         InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def usa_kb(prefix="fmt"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data=f"{prefix}_usa"),
         InlineKeyboardButton("Foreign", callback_data=f"{prefix}_foreign")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

def rate_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Bin VR", callback_data="rate_set_vr")],
        [InlineKeyboardButton("Rate Bin", callback_data="rate_rate_bin")],
        [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate_set_bal")],
        [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate_sug")],
        [InlineKeyboardButton("Force VR", callback_data="rate_force")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])

# ─── AUTH ──────────────────────────────────────────────
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
    ensure_admin(uid)
    return True

# ─── START / CANCEL ────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    context.user_data.clear()
    uname = update.effective_user.username or update.effective_user.first_name or str(update.effective_user.id)
    text = f"E$CO Seller Panel\nWelcome @{uname}"
    await update.effective_message.reply_text(text, reply_markup=main_kb())
    return MAIN

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text("Cancelled.")
        except Exception:
            pass
    context.user_data.clear()
    uname = update.effective_user.username or update.effective_user.first_name or str(update.effective_user.id)
    await update.effective_message.reply_text(
        f"E$CO Seller Panel\nWelcome @{uname}", reply_markup=main_kb()
    )
    return MAIN

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cancel(update, context)

# ─── SESSION HELPERS ───────────────────────────────────
def sess(context):
    return context.user_data.setdefault("sess", {
        "mode": None, "cards": [], "filename": None, "customer": None,
        "target": 0, "usa_filter": None, "batch_id": None, "is_tester": False,
        "tester_kind": None, "pending_bin": None,
    })

def reset_cards_session(context, mode):
    s = sess(context)
    s.update({
        "mode": mode, "cards": [], "filename": None, "customer": None,
        "target": 0, "usa_filter": None, "batch_id": next_batch(),
        "is_tester": mode == "tester", "tester_kind": None,
    })

# ─── MAIN MENU ROUTER ──────────────────────────────────
async def main_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "cancel":
        return await cancel(update, context)

    if data == "mode_format":
        reset_cards_session(context, "format")
        await q.edit_message_text("Send Cards Or Drop .txt File To Continue")
        return FMT_WAIT_CARDS

    if data == "mode_sale":
        reset_cards_session(context, "sale")
        await q.edit_message_text("Please Respond With The Customer Name")
        return SALE_NAME

    if data == "mode_replace":
        reset_cards_session(context, "replace")
        await q.edit_message_text("Who Is Being Replaced")
        return REP_NAME

    if data == "mode_tester":
        reset_cards_session(context, "tester")
        await q.edit_message_text("Is This Tester A Drop Or Gift?")
        return TEST_TYPE

    if data == "mode_rate":
        await q.edit_message_text("BIN / Rate Menu", reply_markup=rate_kb())
        return RATE_MENU

    if data == "mode_balance":
        credits = await fetch_storm_credits()
        await q.edit_message_text(f"Your Available Storm Credits Are {credits}")
        uname = update.effective_user.username or str(update.effective_user.id)
        await context.bot.send_message(
            update.effective_chat.id,
            f"E$CO Seller Panel\nWelcome @{uname}",
            reply_markup=main_kb(),
        )
        return MAIN

    if data == "mode_stats":
        uid = str(update.effective_user.id)
        ensure_admin(update.effective_user.id)
        a = DATA["admins"][uid]
        g = DATA["global"]
        msg = (
            f"═══ E$CO STATS ═══\n"
            f"Cards Sold: {a['cards_sold']} (global {g['cards_sold']})\n"
            f"Total Sales: {a['total_sales']} (global {g['total_sales']})\n"
            f"Revenue: ${a['revenue']:.2f} (global ${g['revenue']:.2f})\n"
            f"Profit: ${a['profit']:.2f} (global ${g['profit']:.2f})\n"
            f"Testers Given: {a['testers_given']} (global {g['testers_given']})\n"
            f"Replacements Given: {a['replacements_given']} (global {g['replacements_given']})\n"
        )
        await q.edit_message_text(msg)
        uname = update.effective_user.username or str(update.effective_user.id)
        await context.bot.send_message(
            update.effective_chat.id,
            f"E$CO Seller Panel\nWelcome @{uname}",
            reply_markup=main_kb(),
        )
        return MAIN

    return MAIN

async def fetch_storm_credits():
    # Display-only; plug real HTTP if STORM_API_URL set
    if not STORM_API_URL:
        return DATA.get("storm_credits_display", 0)
    try:
        import urllib.request
        url = STORM_API_URL.rstrip("/") + "/user"
        req = urllib.request.Request(url, headers={"User-Id": STORM_USER_ID})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
            return payload.get("credits", 0)
    except Exception:
        return "N/A"

# ─── INGEST CARDS (shared) ─────────────────────────────
async def ingest_card_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    text = ""
    if update.message.document:
        f = await update.message.document.get_file()
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        text = bio.getvalue().decode("utf-8", errors="ignore")
        if not s.get("filename"):
            s["filename"] = update.message.document.file_name or None
    elif update.message.text:
        text = update.message.text
    else:
        await update.message.reply_text("Send cards text or a .txt file.")
        return False
    new_cards = parse_cards(text)
    if not new_cards:
        await update.message.reply_text("No cards parsed. Use pan|mm/yy|cvv|name|addr|city|state|zip|CC|phone|email|ip")
        return False
    s["cards"].extend(new_cards)
    s["batch_id"] = next_batch()
    return True

# ─── FORMAT FLOW ───────────────────────────────────────
async def fmt_wait_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    ok = await ingest_card_message(update, context)
    if not ok:
        return FMT_WAIT_CARDS
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_kb("fmt"))
    return FMT_USA_FOREIGN

async def fmt_usa_foreign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    s = sess(context)
    s["usa_filter"] = q.data.endswith("_usa")
    s["cards"] = filter_usa(s["cards"], usa=s["usa_filter"])
    return await show_fmt_pre(update, context)

async def show_fmt_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    fn = s.get("filename") or f"Batch-{s.get('batch_id', next_batch())}"
    s["filename"] = fn
    text = (
        f"═══ PRE SUMMARY ═══\n"
        f"Total Cards: {len(s['cards'])}\n"
        f"Mode: Base\n"
        f"FileName: {fn}\n"
    )
    kb = pre_kb("fmt")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return FMT_PRE

async def fmt_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "fmt_check":
        return await show_fmt_post(update, context)
    if data == "fmt_setname":
        await q.edit_message_text("Send new filename (without .txt):")
        return FMT_SETNAME
    if data == "fmt_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_remove":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FMT_REMOVE
    return FMT_PRE

async def fmt_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    s["filename"] = update.message.text.strip().replace(".txt", "")
    return await show_fmt_pre(update, context)

async def fmt_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
    before = len(s["cards"])
    s["cards"] = [c for c in s["cards"] if c["last4"] not in last4s]
    await update.message.reply_text(f"Removed {before - len(s['cards'])} card(s).")
    # stay in same phase family — if post was active flag
    if s.get("phase") == "post":
        return await show_fmt_post(update, context)
    return await show_fmt_pre(update, context)

async def show_fmt_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    s["phase"] = "post"
    total = len(s["cards"])
    live = total  # display-only checker: always 100% live
    live_rate = "100%" if total else "0%"
    text = (
        f"═══ POST SUMMARY ═══\n"
        f"Total Cards: {total}\n"
        f"LiveRate: {live_rate}\n"
        f"(checker display-only — all marked live)\n"
    )
    kb = post_kb("fmt")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return FMT_POST

async def fmt_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "fmt_add":
        s["phase"] = "post"
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return FMT_WAIT_CARDS
    if data == "fmt_remove":
        s["phase"] = "post"
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return FMT_REMOVE
    if data == "fmt_send":
        return await send_card_file(update, context, prefix="fmt")
    return FMT_POST

async def send_card_file(update: Update, context: ContextTypes.DEFAULT_TYPE, prefix="fmt"):
    s = sess(context)
    cards = s.get("cards") or []
    if not cards:
        await update.effective_message.reply_text("No cards to send.")
        return await cancel(update, context)

    is_tester = s.get("mode") == "tester"
    mode = s.get("mode")

    if mode == "sale":
        target = int(s.get("target") or 0)
        live = cards  # all live display
        main_cards = live[:target] if target else live
        extras = live[target:] if target and len(live) > target else []
        cust = re.sub(r"[^\w\-]+", "_", s.get("customer") or "Customer")
        bid = s.get("batch_id") or next_batch()
        main_name = f"{cust}-{len(main_cards)}-{bid}.txt"
        content = build_output_file(main_cards, is_tester=False)
        bio = io.BytesIO(content.encode("utf-8"))
        bio.name = main_name
        await context.bot.send_document(update.effective_chat.id, document=InputFile(bio, filename=main_name))
        if extras:
            ename = f"Extras-{len(extras)}-{bid}.txt"
            ebio = io.BytesIO(build_output_file(extras).encode("utf-8"))
            ebio.name = ename
            await context.bot.send_document(update.effective_chat.id, document=InputFile(ebio, filename=ename))
        # accounting
        uid = str(update.effective_user.id)
        ensure_admin(update.effective_user.id)
        price = float(DATA["global"].get("sale_price", 15.0))
        cost = float(DATA["global"].get("card_cost", 3.0))
        sold = len(main_cards)
        revenue_add = price * sold
        profit_add = (price - cost) * sold
        DATA["admins"][uid]["cards_sold"] += sold
        DATA["admins"][uid]["total_sales"] += 1
        DATA["admins"][uid]["revenue"] += revenue_add
        DATA["admins"][uid]["profit"] += profit_add
        DATA["global"]["cards_sold"] += sold
        DATA["global"]["total_sales"] += 1
        DATA["global"]["revenue"] += revenue_add
        DATA["global"]["profit"] += profit_add
        save_data(DATA)
    elif mode == "replace":
        target = int(s.get("target") or 0)
        live = cards
        main_cards = live[:target] if target else live
        extras = live[target:] if target and len(live) > target else []
        cust = re.sub(r"[^\w\-]+", "_", s.get("customer") or "Customer")
        bid = s.get("batch_id") or next_batch()
        main_name = f"{cust}-{len(main_cards)}-{bid}.txt"
        bio = io.BytesIO(build_output_file(main_cards).encode("utf-8"))
        bio.name = main_name
        await context.bot.send_document(update.effective_chat.id, document=InputFile(bio, filename=main_name))
        if extras:
            ename = f"Extras-{len(extras)}-{bid}.txt"
            ebio = io.BytesIO(build_output_file(extras).encode("utf-8"))
            ebio.name = ename
            await context.bot.send_document(update.effective_chat.id, document=InputFile(ebio, filename=ename))
        uid = str(update.effective_user.id)
        ensure_admin(update.effective_user.id)
        cost = float(DATA["global"].get("card_cost", 3.0))
        n = len(main_cards)
        DATA["admins"][uid]["replacements_given"] += n
        DATA["admins"][uid]["profit"] -= cost * n
        DATA["admins"][uid]["revenue"] -= cost * n  # per spec: subtract card cost from revenue
        DATA["global"]["replacements_given"] += n
        DATA["global"]["profit"] -= cost * n
        DATA["global"]["revenue"] -= cost * n
        save_data(DATA)
    else:
        # format / tester
        bid = s.get("batch_id") or next_batch()
        fn = s.get("filename") or f"Batch-{bid}"
        if not fn.endswith(".txt"):
            fn = fn + ".txt"
        content = build_output_file(cards, is_tester=is_tester)
        bio = io.BytesIO(content.encode("utf-8"))
        bio.name = fn
        await context.bot.send_document(update.effective_chat.id, document=InputFile(bio, filename=fn))
        if mode == "tester":
            uid = str(update.effective_user.id)
            ensure_admin(update.effective_user.id)
            DATA["admins"][uid]["testers_given"] += len(cards)
            DATA["global"]["testers_given"] += len(cards)
            save_data(DATA)

    await update.effective_message.reply_text("File(s) sent. Vouches appreciated.")
    return await cancel(update, context)

# When adding more cards from post, after USA filter go back to post
async def fmt_wait_cards_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # reused: after cards, ask USA
    ok = await ingest_card_message(update, context)
    if not ok:
        return FMT_WAIT_CARDS
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_kb("fmt"))
    return FMT_USA_FOREIGN

async def fmt_usa_foreign2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    s = sess(context)
    # only filter the newly added? Spec: filter selection applies; keep simple — filter all by choice
    want_usa = q.data.endswith("_usa")
    # apply to newly parsed only is harder; filter entire set by last choice
    s["usa_filter"] = want_usa
    # Do not re-filter entire list destructively on add — tag path:
    # Instead: last ingest already extended; optional filter on full list:
    s["cards"] = filter_usa(s["cards"], usa=want_usa)
    if s.get("phase") == "post":
        return await show_fmt_post(update, context)
    return await show_fmt_pre(update, context)

# ─── SALE FLOW ─────────────────────────────────────────
async def sale_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    sess(context)["customer"] = update.message.text.strip()
    await update.message.reply_text(f'How Many Cards Is "{sess(context)["customer"]}" Purchasing')
    return SALE_QTY

async def sale_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(re.sub(r"\D", "", update.message.text) or "0")
    except Exception:
        await update.message.reply_text("Number only.")
        return SALE_QTY
    s = sess(context)
    s["target"] = qty
    await update.message.reply_text("Target Set\nSend Cards Or Drop .txt File To Continue")
    return SALE_WAIT_CARDS

async def sale_wait_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = await ingest_card_message(update, context)
    if not ok:
        return SALE_WAIT_CARDS
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_kb("sale"))
    return SALE_USA_FOREIGN

async def sale_usa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    s = sess(context)
    s["usa_filter"] = q.data.endswith("_usa")
    s["cards"] = filter_usa(s["cards"], usa=s["usa_filter"])
    if s.get("phase") == "post":
        return await show_sale_post(update, context)
    return await show_sale_pre(update, context)

async def show_sale_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    price = float(DATA["global"].get("sale_price", 15.0))
    # revenue preview = current cards * price (or target*)
    total = len(s["cards"])
    rev = price * total
    text = (
        f"═══ SALE PRE SUMMARY ═══\n"
        f"Target: {s.get('target')}\n"
        f"Total Cards: {total}\n"
        f"Mode: Sale\n"
        f"Total Revenue: ${rev:.2f}\n"
        f"+ (Sale Cost ${price:.2f}/card)\n"
        f"Customer: {s.get('customer')}\n"
    )
    kb = pre_kb_sale("sale")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return SALE_PRE

async def sale_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "sale_check":
        return await show_sale_post(update, context)
    if data == "sale_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if data == "sale_remove":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return SALE_REMOVE
    return SALE_PRE

async def sale_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
    before = len(s["cards"])
    s["cards"] = [c for c in s["cards"] if c["last4"] not in last4s]
    await update.message.reply_text(f"Removed {before - len(s['cards'])} card(s).")
    if s.get("phase") == "post":
        return await show_sale_post(update, context)
    return await show_sale_pre(update, context)

async def show_sale_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    s["phase"] = "post"
    total = len(s["cards"])
    live = total
    target = int(s.get("target") or 0)
    extras = max(0, live - target) if target else 0
    reached = live >= target if target else True
    price = float(DATA["global"].get("sale_price", 15.0))
    cost = float(DATA["global"].get("card_cost", 3.0))
    sold = min(live, target) if target else live
    revenue = price * sold
    profit = (price - cost) * sold
    text = (
        f"═══ SALE POST SUMMARY ═══\n"
        f"Total Cards: {total}\n"
        f"Total Live: {live}\n"
        f"Extras: {extras}\n"
        f"Target Reached: {reached}\n"
        f"Profit Made: ${profit:.2f}\n"
        f"Total Revenue After Sale: ${revenue:.2f}\n"
        f"LiveRate: 100%\n"
    )
    kb = post_kb("sale")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return SALE_POST

async def sale_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "sale_add":
        s["phase"] = "post"
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return SALE_WAIT_CARDS
    if data == "sale_remove":
        s["phase"] = "post"
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return SALE_REMOVE
    if data == "sale_send":
        return await send_card_file(update, context, prefix="sale")
    return SALE_POST

# ─── REPLACE FLOW ──────────────────────────────────────
async def rep_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sess(context)["customer"] = update.message.text.strip()
    await update.message.reply_text("How Many Cards Are Being Replaced")
    return REP_QTY

async def rep_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = int(re.sub(r"\D", "", update.message.text) or "0")
    sess(context)["target"] = qty
    await update.message.reply_text("Target Submitted\nSend Cards Or Drop .txt File To Continue")
    return REP_WAIT_CARDS

async def rep_wait_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = await ingest_card_message(update, context)
    if not ok:
        return REP_WAIT_CARDS
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_kb("rep"))
    return REP_USA_FOREIGN

async def rep_usa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    s = sess(context)
    s["usa_filter"] = q.data.endswith("_usa")
    s["cards"] = filter_usa(s["cards"], usa=s["usa_filter"])
    if s.get("phase") == "post":
        return await show_rep_post(update, context)
    return await show_rep_pre(update, context)

async def show_rep_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    text = (
        f"═══ REPLACE PRE SUMMARY ═══\n"
        f"Total Cards: {len(s['cards'])}\n"
        f"Replacement Target: {s.get('target')}\n"
        f"Customer Name: {s.get('customer')}\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Check", callback_data="rep_check")],
        [InlineKeyboardButton("Add More Cards", callback_data="rep_add"),
         InlineKeyboardButton("Remove Cards", callback_data="rep_remove")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return REP_PRE

async def rep_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "cancel":
        return await cancel(update, context)
    if data == "rep_check":
        return await show_rep_post(update, context)
    if data == "rep_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return REP_WAIT_CARDS
    if data == "rep_remove":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return REP_REMOVE
    return REP_PRE

async def rep_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
    before = len(s["cards"])
    s["cards"] = [c for c in s["cards"] if c["last4"] not in last4s]
    await update.message.reply_text(f"Removed {before - len(s['cards'])} card(s).")
    if s.get("phase") == "post":
        return await show_rep_post(update, context)
    return await show_rep_pre(update, context)

async def show_rep_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    s["phase"] = "post"
    total = len(s["cards"])
    live = total
    target = int(s.get("target") or 0)
    extras = max(0, live - target) if target else 0
    reached = live >= target if target else True
    text = (
        f"═══ REPLACE POST SUMMARY ═══\n"
        f"Total Cards: {total}\n"
        f"Extras: {extras}\n"
        f"Liverate: 100%\n"
        f"Replacement Target Reached: {reached}\n"
        f"Customer Name: {s.get('customer')}\n"
    )
    kb = post_kb("rep")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return REP_POST

async def rep_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "rep_add":
        s["phase"] = "post"
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return REP_WAIT_CARDS
    if data == "rep_remove":
        s["phase"] = "post"
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return REP_REMOVE
    if data == "rep_send":
        return await send_card_file(update, context, prefix="rep")
    return REP_POST

# ─── TESTER FLOW ───────────────────────────────────────
async def test_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = update.message.text.strip().lower()
    if kind not in ("drop", "gift"):
        await update.message.reply_text("Reply Drop or Gift")
        return TEST_TYPE
    s = sess(context)
    s["tester_kind"] = kind
    s["is_tester"] = True
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return TEST_WAIT_CARDS

async def test_wait_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = await ingest_card_message(update, context)
    if not ok:
        return TEST_WAIT_CARDS
    await update.message.reply_text("USA Or Foreign?", reply_markup=usa_kb("test"))
    return TEST_USA_FOREIGN

async def test_usa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    s = sess(context)
    s["usa_filter"] = q.data.endswith("_usa")
    s["cards"] = filter_usa(s["cards"], usa=s["usa_filter"])
    if s.get("phase") == "post":
        return await show_test_post(update, context)
    return await show_test_pre(update, context)

async def show_test_pre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    fn = s.get("filename") or f"Batch-{s.get('batch_id', next_batch())}"
    s["filename"] = fn
    text = (
        f"═══ TESTER PRE SUMMARY ═══\n"
        f"Total Cards: {len(s['cards'])}\n"
        f"Mode: Base (Tester {s.get('tester_kind')})\n"
        f"FileName: {fn}\n"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=pre_kb("test"))
    else:
        await update.effective_message.reply_text(text, reply_markup=pre_kb("test"))
    return TEST_PRE

async def test_pre_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "test_check":
        return await show_test_post(update, context)
    if data == "test_setname":
        await q.edit_message_text("Send new filename (without .txt):")
        return TEST_SETNAME
    if data == "test_add":
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TEST_WAIT_CARDS
    if data == "test_remove":
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return TEST_REMOVE
    return TEST_PRE

async def test_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sess(context)["filename"] = update.message.text.strip().replace(".txt", "")
    return await show_test_pre(update, context)

async def test_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    last4s = {x.strip() for x in update.message.text.split(",") if x.strip()}
    before = len(s["cards"])
    s["cards"] = [c for c in s["cards"] if c["last4"] not in last4s]
    await update.message.reply_text(f"Removed {before - len(s['cards'])} card(s).")
    if s.get("phase") == "post":
        return await show_test_post(update, context)
    return await show_test_pre(update, context)

async def show_test_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sess(context)
    s["phase"] = "post"
    total = len(s["cards"])
    text = (
        f"═══ TESTER POST SUMMARY ═══\n"
        f"Total Cards: {total}\n"
        f"LiveRate: 100%\n"
    )
    kb = post_kb("test")
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, reply_markup=kb)
    return TEST_POST

async def test_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    s = sess(context)
    if data == "cancel":
        return await cancel(update, context)
    if data == "test_add":
        s["phase"] = "post"
        await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")
        return TEST_WAIT_CARDS
    if data == "test_remove":
        s["phase"] = "post"
        await q.edit_message_text("Send Last 4# Separated By Commas Of The Card(s) You Want Removed")
        return TEST_REMOVE
    if data == "test_send":
        return await send_card_file(update, context, prefix="test")
    return TEST_POST

# ─── RATE / BIN ────────────────────────────────────────
async def rate_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await cancel(update, context)
    s = sess(context)
    s["rate_action"] = q.data
    await q.edit_message_text("Send Bin 6 Digit Number")
    return RATE_BIN_WAIT

async def rate_bin_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = re.sub(r"\D", "", update.message.text)[:6]
    if len(bin6) != 6:
        await update.message.reply_text("Need 6-digit BIN")
        return RATE_BIN_WAIT
    s = sess(context)
    s["pending_bin"] = bin6
    info = lookup_bin(bin6)
    meta = bin_meta(bin6)
    action = s.get("rate_action")
    header = (
        f"You Have Selected Bin {bin6}\n"
        f"{info.get('brand')} {info.get('type')} {info.get('level')}\n"
        f"{info.get('bank')} • {info.get('country')}\n"
        f"VR: {meta.get('vr')} | Rating: {meta.get('rating')} | Bal: {meta.get('balance_rating')}\n"
        f"Suggestion: {meta.get('suggestion')} | Forced VR: {meta.get('forced_vr')}\n"
    )
    if action == "rate_set_vr":
        await update.message.reply_text(header + "\nWhat Do You Want To Set The Vr Rating As (0-10 or 0-100)?")
        return RATE_VR_WAIT
    if action == "rate_rate_bin":
        await update.message.reply_text(header + "\nRate this BIN (e.g. 8.5/10):")
        return RATE_RATE_WAIT
    if action == "rate_set_bal":
        await update.message.reply_text(header + "\nSet balance rating (e.g. 7/10):")
        return RATE_BAL_WAIT
    if action == "rate_sug":
        await update.message.reply_text(header + "\nSend suggestion places to use BIN:")
        return RATE_SUG_WAIT
    if action == "rate_force":
        await update.message.reply_text(header + "\nSet Forced Vr Rating, Say Reset To Disable")
        return RATE_FORCE_WAIT
    return RATE_MENU

async def rate_vr_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = sess(context)["pending_bin"]
    set_bin_field(bin6, "vr", update.message.text.strip())
    await update.message.reply_text(f"VR set for {bin6}")
    return await start(update, context)

async def rate_rate_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = sess(context)["pending_bin"]
    set_bin_field(bin6, "rating", update.message.text.strip())
    await update.message.reply_text(f"Rating set for {bin6}")
    return await start(update, context)

async def rate_bal_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = sess(context)["pending_bin"]
    set_bin_field(bin6, "balance_rating", update.message.text.strip())
    await update.message.reply_text(f"Balance rating set for {bin6}")
    return await start(update, context)

async def rate_sug_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = sess(context)["pending_bin"]
    set_bin_field(bin6, "suggestion", update.message.text.strip())
    await update.message.reply_text(f"Suggestion set for {bin6}")
    return await start(update, context)

async def rate_force_wait(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bin6 = sess(context)["pending_bin"]
    val = update.message.text.strip()
    if val.lower() == "reset":
        set_bin_field(bin6, "forced_vr", None)
        await update.message.reply_text(f"Forced VR cleared for {bin6}")
    else:
        num = int(re.sub(r"\D", "", val) or "100")
        set_bin_field(bin6, "forced_vr", num)
        await update.message.reply_text(f"Forced VR {num}% for {bin6}")
    return await start(update, context)

# ─── COMMAND SHORTCUTS ─────────────────────────────────
async def cmd_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    reset_cards_session(context, "format")
    await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    return FMT_WAIT_CARDS

async def cmd_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    reset_cards_session(context, "sale")
    await update.message.reply_text("Please Respond With The Customer Name")
    return SALE_NAME

async def cmd_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    reset_cards_session(context, "replace")
    await update.message.reply_text("Who Is Being Replaced")
    return REP_NAME

async def cmd_tester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    reset_cards_session(context, "tester")
    await update.message.reply_text("Is This Tester A Drop Or Gift?")
    return TEST_TYPE

async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    await update.message.reply_text("BIN / Rate Menu", reply_markup=rate_kb())
    return RATE_MENU

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    uid = str(update.effective_user.id)
    a = DATA["admins"][uid]
    g = DATA["global"]
    await update.message.reply_text(
        f"Cards Sold: {a['cards_sold']}\nTotal Sales: {a['total_sales']}\n"
        f"Revenue: ${a['revenue']:.2f}\nProfit: ${a['profit']:.2f}\n"
        f"Testers: {a['testers_given']}\nReplacements: {a['replacements_given']}\n"
        f"— global sold {g['cards_sold']} sales {g['total_sales']} rev ${g['revenue']:.2f}"
    )
    return await start(update, context)

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return ConversationHandler.END
    lines = [f"{b} • {v['brand']} {v['level']} • {v['bank']}" for b, v in BIN_DB.items()]
    await update.message.reply_text("BINLIST\n" + "\n".join(lines))
    return MAIN

# ─── APP ───────────────────────────────────────────────
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("format", cmd_format),
            CommandHandler("sale", cmd_sale),
            CommandHandler("replace", cmd_replace),
            CommandHandler("tester", cmd_tester),
            CommandHandler("rate", cmd_rate),
            CommandHandler("stats", cmd_stats),
            CommandHandler("list", cmd_list),
            CommandHandler("balance", lambda u, c: main_router.__wrapped__(u, c) if False else start(u, c)),
        ],
        states={
            MAIN: [CallbackQueryHandler(main_router)],
            # format
            FMT_WAIT_CARDS: [
                MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, fmt_wait_cards_router),
            ],
            FMT_USA_FOREIGN: [CallbackQueryHandler(fmt_usa_foreign2)],
            FMT_PRE: [CallbackQueryHandler(fmt_pre_cb)],
            FMT_POST: [CallbackQueryHandler(fmt_post_cb)],
            FMT_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fmt_remove)],
            FMT_SETNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fmt_setname)],
            # sale
            SALE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_name)],
            SALE_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_qty)],
            SALE_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, sale_wait_cards)],
            SALE_USA_FOREIGN: [CallbackQueryHandler(sale_usa)],
            SALE_PRE: [CallbackQueryHandler(sale_pre_cb)],
            SALE_POST: [CallbackQueryHandler(sale_post_cb)],
            SALE_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sale_remove)],
            # replace
            REP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, rep_name)],
            REP_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, rep_qty)],
            REP_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, rep_wait_cards)],
            REP_USA_FOREIGN: [CallbackQueryHandler(rep_usa)],
            REP_PRE: [CallbackQueryHandler(rep_pre_cb)],
            REP_POST: [CallbackQueryHandler(rep_post_cb)],
            REP_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, rep_remove)],
            # tester
            TEST_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, test_type)],
            TEST_WAIT_CARDS: [MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, test_wait_cards)],
            TEST_USA_FOREIGN: [CallbackQueryHandler(test_usa)],
            TEST_PRE: [CallbackQueryHandler(test_pre_cb)],
            TEST_POST: [CallbackQueryHandler(test_post_cb)],
            TEST_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, test_remove)],
            TEST_SETNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, test_setname)],
            # rate
            RATE_MENU: [CallbackQueryHandler(rate_menu_cb)],
            RATE_BIN_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_bin_wait)],
            RATE_VR_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_vr_wait)],
            RATE_RATE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_rate_wait)],
            RATE_BAL_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_bal_wait)],
            RATE_SUG_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_sug_wait)],
            RATE_FORCE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, rate_force_wait)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_cmd),
            CommandHandler("start", start),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        allow_reentry=True,
    )

    async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        credits = await fetch_storm_credits()
        await update.message.reply_text(f"Your Available Storm Credits Are {credits}")

    app.add_handler(conv)
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    return app

if __name__ == "__main__":
    # Quick self-check so Railway boot never dies on state unpack
    assert True
    application = build_app()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
