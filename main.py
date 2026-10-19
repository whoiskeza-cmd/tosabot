import os, re, json, random, io
from datetime import datetime, timezone
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ADMIN_IDS = set()
_raw_admins = os.getenv("ADMIN_IDS", "")
if _raw_admins.strip():
    ADMIN_IDS = {int(x.strip()) for x in _raw_admins.split(",") if x.strip()}
ADMIN_IDS.add(OWNER_ID)

DATA = Path(".")
BINS_DB = DATA / "bins_db.json"
STOCK_DB = DATA / "stockpile.json"
STATS_DB = DATA / "stats.json"
SETTINGS_DB = DATA / "settings.json"

DEFAULT_SETTINGS = {
    "sale_price": 15.0,   # revenue per live card sold
    "card_cost": 3.0,     # your cost per card (profit = sale_price - card_cost)
}

# conversation keys in context.user_data
# mode: format|sale|replace|tester|stock|rate|settings|None

def load_json(path, default):
    if not path.exists():
        path.write_text(json.dumps(default, indent=2))
        return json.loads(json.dumps(default))
    return json.loads(path.read_text())

def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2))

def bins():
    return load_json(BINS_DB, {})

def save_bins(d):
    save_json(BINS_DB, d)

def stock():
    return load_json(STOCK_DB, {})

def save_stock(d):
    save_json(STOCK_DB, d)

def settings():
    return load_json(SETTINGS_DB, DEFAULT_SETTINGS)

def save_settings(d):
    save_json(SETTINGS_DB, d)

def all_stats():
    return load_json(STATS_DB, {})

def save_all_stats(d):
    save_json(STATS_DB, d)

def user_stats(uid: int):
    s = all_stats()
    k = str(uid)
    if k not in s:
        s[k] = {
            "cards_sold": 0,
            "total_sales": 0,
            "revenue": 0.0,
            "testers_given": 0,
            "replacements_given": 0,
            "total_profit": 0.0,
        }
        save_all_stats(s)
    return s[k]

def put_user_stats(uid: int, st):
    s = all_stats()
    s[str(uid)] = st
    save_all_stats(s)

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def get_random_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

def batch_id():
    return f"{random.randint(1000,9999)}"

CARD_LINE_RE = re.compile(
    r"^(?P<cc>\d{13,19})\|(?P<mm>\d{1,2})/(?P<yy>\d{2,4})\|(?P<cvv>\d{3,4})\|(?P<name>[^|]*)\|(?P<street>[^|]*)\|(?P<city>[^|]*)\|(?P<state>[^|]*)\|(?P<zip>[^|]*)\|(?P<country>[^|]*)\|(?P<phone>[^|]*)\|(?P<email>[^|]*)\|?(?P<ip>[^|]*)?$"
)

def parse_cards(text: str):
    cards = []
    for raw in text.replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # pipe format
        if "|" in line:
            parts = line.split("|")
            while len(parts) < 12:
                parts.append("")
            cc, exp, cvv, name, street, city, state, zipc, country, phone, email = parts[:11]
            ip = parts[11] if len(parts) > 11 else ""
            mm, yy = (exp.split("/") + [""])[:2] if "/" in exp else ("", "")
            cards.append({
                "cc": cc.strip(),
                "mm": mm.strip().zfill(2),
                "yy": yy.strip()[-2:].zfill(2) if yy else "",
                "cvv": cvv.strip(),
                "name": name.strip(),
                "street": street.strip(),
                "city": city.strip(),
                "state": state.strip(),
                "zip": zipc.strip(),
                "country": country.strip() or "US",
                "phone": phone.strip(),
                "email": email.strip(),
                "ip": ip.strip() or get_random_ip(),
            })
            continue
        # loose: number exp cvv
        m = re.search(r"(\d{13,19}).*?(\d{2})\s*/\s*(\d{2,4}).*?(\d{3,4})", line)
        if m:
            cards.append({
                "cc": m.group(1), "mm": m.group(2), "yy": m.group(3)[-2:], "cvv": m.group(4),
                "name": "", "street": "", "city": "", "state": "", "zip": "",
                "country": "US", "phone": "", "email": "", "ip": get_random_ip(),
            })
    return cards

def bin6(cc: str) -> str:
    return cc[:6]

def bin_info(cc: str):
    b = bins()
    key = bin6(cc)
    if key in b:
        return b[key]
    return {
        "brand": "UNKNOWN", "type": "", "level": "", "bank": "UNKNOWN",
        "country": "UNKNOWN", "cc": "XX", "rating": "10/10", "vr": 10,
        "balance_rating": 10, "suggestion": "General", "forced_vr": None
    }

def country_flag_bucket(card):
    info = bin_info(card["cc"])
    cc = (info.get("cc") or card.get("country") or "US").upper()
    return "USA" if cc in ("US", "USA", "UNITED STATES") else "FOREIGN"

def format_card_block(card, is_tester=False):
    info = bin_info(card["cc"])
    brand = info.get("brand", "VISA")
    bank = info.get("bank", "UNKNOWN")
    country = info.get("country", card.get("country", "US"))
    cc_short = info.get("cc", "US")
    rating = info.get("rating", "10/10")
    suggestion = info.get("suggestion", "General")
    forced = info.get("forced_vr")
    if forced is not None:
        rating = f"{forced}/10 FORCE"
    exp = f"{card['mm']}/{card['yy']}"
    addr = ", ".join(x for x in [card.get("street"), card.get("city"), card.get("state"), card.get("zip"), country] if x)
    name = card.get("name") or "N/A"
    lines = [
        " ══════════════════════════════════════ ",
        f"👤 Name:{name}💳",
        f"Card:{card['cc']}📅 Expiry:{exp}🔒CVV:{card['cvv']}",
        f"🏦Bank:{bank}🌍Country:{cc_short}•{brand.title()}📍",
        f"Billing Address:{addr or 'N/A'}",
        f"📞Phone:{card.get('phone') or 'N/A'}✉️",
        f"Email:{card.get('email') or 'N/A'}🌐",
        " ══════════════════════════════════════",
        f"🌐 IP      : {card.get('ip') or get_random_ip()}",
        f"🕒 Checked : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"BIN Rate   : {rating} | {suggestion}",
        "LiveRate   : 100%",
    ]
    return "\n".join(lines)

def build_output_file(cards, is_tester=False, vouch=True):
    blocks = [format_card_block(c, is_tester=is_tester) for c in cards]
    body = "\n\n".join(blocks)
    footer = []
    if is_tester:
        footer.append("❤️ High Quality Tester From E$CO ❤️")
    if vouch:
        footer.append("")
        footer.append("✅ Please send vouches after pull — helps the desk stay stocked.")
        footer.append("Vouch format: speed | live | pack quality")
    if footer:
        body = body + "\n\n" + "\n".join(footer)
    return body

def main_menu_kb():
    rows = [
        [InlineKeyboardButton("Format", callback_data="menu:format"),
         InlineKeyboardButton("Sale", callback_data="menu:sale")],
        [InlineKeyboardButton("Replace", callback_data="menu:replace"),
         InlineKeyboardButton("Tester", callback_data="menu:tester")],
        [InlineKeyboardButton("Rate", callback_data="menu:rate"),
         InlineKeyboardButton("Stats", callback_data="menu:stats")],
        [InlineKeyboardButton("Stockpile", callback_data="menu:stock"),
         InlineKeyboardButton("Settings", callback_data="menu:settings")],
        [InlineKeyboardButton("Cancel / Home", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(rows)

def pre_kb(mode):
    buttons = [
        [InlineKeyboardButton("Check", callback_data=f"{mode}:check"),
         InlineKeyboardButton("Set Filename", callback_data=f"{mode}:setfn")],
        [InlineKeyboardButton("Add More Cards", callback_data=f"{mode}:add"),
         InlineKeyboardButton("Remove Cards", callback_data=f"{mode}:remove")],
        [InlineKeyboardButton("Cancel", callback_data="menu:home")],
    ]
    if mode == "sale":
        buttons = [
            [InlineKeyboardButton("Add More Cards", callback_data=f"{mode}:add"),
             InlineKeyboardButton("Remove Cards", callback_data=f"{mode}:remove")],
            [InlineKeyboardButton("Check", callback_data=f"{mode}:check")],
            [InlineKeyboardButton("Cancel", callback_data="menu:home")],
        ]
    return InlineKeyboardMarkup(buttons)

def post_kb(mode):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Send File", callback_data=f"{mode}:send"),
         InlineKeyboardButton("Add More Cards", callback_data=f"{mode}:add")],
        [InlineKeyboardButton("Remove Cards", callback_data=f"{mode}:remove"),
         InlineKeyboardButton("Cancel", callback_data="menu:home")],
    ])

def usa_foreign_kb(mode):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("USA", callback_data=f"{mode}:bucket:USA"),
         InlineKeyboardButton("Foreign", callback_data=f"{mode}:bucket:FOREIGN")],
    ])

async def deny(update: Update):
    if update.callback_query:
        await update.callback_query.answer("Not authorized", show_alert=True)
    elif update.message:
        await update.message.reply_text("Not authorized.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await deny(update)
    context.user_data.clear()
    uname = update.effective_user.username or update.effective_user.first_name or str(uid)
    text = f"Private Seller Panel\nWelcome @{uname}"
    await update.effective_message.reply_text(text, reply_markup=main_menu_kb())

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = user_stats(uid)
    txt = (
        "📊 Stats\n"
        f"Cards Sold: {st['cards_sold']}\n"
        f"Total Sales: {st['total_sales']}\n"
        f"Revenue: ${st['revenue']:.2f}\n"
        f"Testers Given: {st['testers_given']}\n"
        f"Replacements Given: {st['replacements_given']}\n"
        f"Total Profit: ${st['total_profit']:.2f}"
    )
    await update.effective_message.reply_text(txt, reply_markup=main_menu_kb())

def session_cards(ud):
    return ud.setdefault("cards", [])

def presummary_text(ud):
    mode = ud.get("mode")
    cards = session_cards(ud)
    fn = ud.get("filename") or f"Batch-{ud.get('batch', batch_id())}"
    conf = settings()
    if mode == "format" or mode == "tester":
        return (
            f"PreSummary\n"
            f"Total Cards: {len(cards)}\n"
            f"Mode:{'Tester' if mode=='tester' else 'Base'}\n"
            f"FileName:{fn}\n"
            f"TesterType:{ud.get('tester_type','N/A')}"
        )
    if mode == "sale":
        target = int(ud.get("target") or 0)
        rev = target * float(conf["sale_price"])
        return (
            f"PreSummary\n"
            f"Target: {target}\n"
            f"Total Cards: {len(cards)}\n"
            f"Mode:Sale\n"
            f"Customer: {ud.get('customer','N/A')}\n"
            f"Total Revenue (projected): ${rev:.2f}\n"
            f"+ (Sale Cost ${conf['sale_price']:.2f}/card)"
        )
    if mode == "replace":
        return (
            f"PreSummary\n"
            f"Total Cards: {len(cards)}\n"
            f"Replacement Target: {ud.get('target')}\n"
            f"Customer Name: {ud.get('customer')}"
        )
    return f"Total Cards: {len(cards)}"

def postsummary_text(ud):
    mode = ud.get("mode")
    cards = session_cards(ud)
    # fake checker: everything live 100%
    live = list(cards)
    live_n = len(live)
    conf = settings()
    ud["live_cards"] = live
    if mode in ("format", "tester"):
        return (
            f"PostSummary\n"
            f"Total Cards: {len(cards)}\n"
            f"LiveRate: 100%\n"
            f"Live: {live_n}"
        )
    if mode == "sale":
        target = int(ud.get("target") or 0)
        extras = max(0, live_n - target)
        reached = live_n >= target
        sold = min(live_n, target) if target else live_n
        revenue = sold * float(conf["sale_price"])
        profit = sold * (float(conf["sale_price"]) - float(conf["card_cost"]))
        ud["last_sold"] = sold
        ud["last_revenue"] = revenue
        ud["last_profit"] = profit
        ud["extras_count"] = extras
        return (
            f"PostSummary\n"
            f"Total Cards: {len(cards)}\n"
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
        ud["extras_count"] = extras
        return (
            f"PostSummary\n"
            f"Total Cards: {len(cards)}\n"
            f"Extras: {extras}\n"
            f"LiveRate: 100%\n"
            f"Replacement Target Reached: {reached}\n"
            f"Customer Name: {ud.get('customer')}"
        )
    return "PostSummary"

def stock_decrement_for_cards(cards):
    st = stock()
    for c in cards:
        b = bin6(c["cc"])
        if b in st:
            st[b] = max(0, int(st[b]) - 1)
    save_stock(st)

async def send_pre(update, context):
    ud = context.user_data
    mode = ud.get("mode")
    txt = presummary_text(ud)
    await update.effective_message.reply_text(txt, reply_markup=pre_kb(mode))

async def send_post(update, context):
    ud = context.user_data
    mode = ud.get("mode")
    txt = postsummary_text(ud)
    await update.effective_message.reply_text(txt, reply_markup=post_kb(mode))

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if not is_admin(uid):
        return await deny(update)
    data = q.data or ""
    ud = context.user_data

    if data == "menu:home":
        ud.clear()
        uname = update.effective_user.username or str(uid)
        return await q.edit_message_text(
            f"Private Seller Panel\nWelcome @{uname}",
            reply_markup=main_menu_kb(),
        )

    if data == "menu:stats":
        st = user_stats(uid)
        txt = (
            "📊 Stats\n"
            f"Cards Sold: {st['cards_sold']}\n"
            f"Total Sales: {st['total_sales']}\n"
            f"Revenue: ${st['revenue']:.2f}\n"
            f"Testers Given: {st['testers_given']}\n"
            f"Replacements Given: {st['replacements_given']}\n"
            f"Total Profit: ${st['total_profit']:.2f}"
        )
        return await q.edit_message_text(txt, reply_markup=main_menu_kb())

    if data == "menu:settings":
        conf = settings()
        ud["mode"] = "settings"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Set Sale Price", callback_data="settings:sale_price")],
            [InlineKeyboardButton("Set Card Cost", callback_data="settings:card_cost")],
            [InlineKeyboardButton("Add Admin ID", callback_data="settings:add_admin")],
            [InlineKeyboardButton("Home", callback_data="menu:home")],
        ])
        return await q.edit_message_text(
            f"Settings\nSale price: ${conf['sale_price']}\nCard cost: ${conf['card_cost']}\nAdmins: {sorted(ADMIN_IDS)}",
            reply_markup=kb,
        )

    if data.startswith("settings:"):
        field = data.split(":",1)[1]
        ud["mode"] = "settings"
        ud["settings_field"] = field
        prompts = {
            "sale_price": "Send new sale price (number).",
            "card_cost": "Send new card cost (number).",
            "add_admin": "Send numeric Telegram user id to add as admin.",
        }
        return await q.edit_message_text(prompts.get(field, "Send value"))

    if data == "menu:format":
        ud.clear()
        ud["mode"] = "format"
        ud["batch"] = batch_id()
        ud["cards"] = []
        ud["await"] = "cards"
        return await q.edit_message_text("Send Cards Or Drop .txt File To Continue")

    if data == "menu:sale":
        ud.clear()
        ud["mode"] = "sale"
        ud["batch"] = batch_id()
        ud["cards"] = []
        ud["await"] = "customer"
        return await q.edit_message_text("Please Respond With The Customer Name")

    if data == "menu:replace":
        ud.clear()
        ud["mode"] = "replace"
        ud["batch"] = batch_id()
        ud["cards"] = []
        ud["await"] = "customer"
        return await q.edit_message_text("Who Is Being Replaced")

    if data == "menu:tester":
        ud.clear()
        ud["mode"] = "tester"
        ud["batch"] = batch_id()
        ud["cards"] = []
        ud["await"] = "tester_type"
        return await q.edit_message_text("Is This Tester A Drop Or Gift?")

    if data == "menu:rate":
        ud["mode"] = "rate"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Set Bin VR", callback_data="rate:set_vr")],
            [InlineKeyboardButton("Rate Bin", callback_data="rate:rate_bin")],
            [InlineKeyboardButton("Set Bin Balance Rating", callback_data="rate:set_bal")],
            [InlineKeyboardButton("Bin Use Suggestion", callback_data="rate:suggest")],
            [InlineKeyboardButton("Force VR", callback_data="rate:force_vr")],
            [InlineKeyboardButton("Home", callback_data="menu:home")],
        ])
        return await q.edit_message_text("Rate menu", reply_markup=kb)

    if data.startswith("rate:"):
        action = data.split(":",1)[1]
        ud["mode"] = "rate"
        ud["rate_action"] = action
        ud["await"] = "bin"
        return await q.edit_message_text("Send Bin 6 Digit Number")

    if data == "menu:stock":
        ud["mode"] = "stock"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Bins", callback_data="stock:add")],
            [InlineKeyboardButton("Subtract Bins", callback_data="stock:sub")],
            [InlineKeyboardButton("Search Bin", callback_data="stock:search")],
            [InlineKeyboardButton("Send Binlist", callback_data="stock:send")],
            [InlineKeyboardButton("Set Binlist Filename", callback_data="stock:setfn")],
            [InlineKeyboardButton("Home", callback_data="menu:home")],
        ])
        st = stock()
        total = sum(int(v) for v in st.values()) if st else 0
        return await q.edit_message_text(
            f"Stockpile\nBins tracked: {len(st)}\nTotal qty: {total}\nFilename: {ud.get('stock_fn','stockpile-binlist.txt')}",
            reply_markup=kb,
        )

    if data.startswith("stock:"):
        act = data.split(":",1)[1]
        ud["mode"] = "stock"
        if act == "add":
            ud["await"] = "stock_bin"
            ud["stock_op"] = "add"
            return await q.edit_message_text("Send BIN (6 digits) to ADD")
        if act == "sub":
            ud["await"] = "stock_bin"
            ud["stock_op"] = "sub"
            return await q.edit_message_text("Send BIN (6 digits) to SUBTRACT")
        if act == "search":
            ud["await"] = "stock_search"
            return await q.edit_message_text("Send BIN to search (reply is forwardable)")
        if act == "setfn":
            ud["await"] = "stock_fn"
            return await q.edit_message_text("Send filename for stockpile binlist export")
        if act == "send":
            st = stock()
            bdb = bins()
            lines = []
            for b, qty in sorted(st.items()):
                info = bdb.get(b, {})
                country = info.get("country") or info.get("cc") or "UNKNOWN"
                lines.append(f"{b}*{qty}*{country}")
            fn = ud.get("stock_fn") or "stockpile-binlist.txt"
            content = "\n".join(lines) if lines else "EMPTY"
            bio = io.BytesIO(content.encode())
            bio.name = fn
            await context.bot.send_document(uid, document=InputFile(bio), caption="Stockpile binlist")
            return

    # mode shared actions: format/sale/replace/tester
    if ":" in data:
        mode, action = data.split(":", 1)
        if mode in ("format", "sale", "replace", "tester"):
            ud["mode"] = mode
            if action.startswith("bucket:"):
                bucket = action.split(":",1)[1]
                # filter last added batch by bucket if desired; keep all by default, store preference
                ud["bucket"] = bucket
                return await send_pre(update, context)

            if action == "add":
                ud["await"] = "cards"
                return await q.edit_message_text("Please Send More Cards Or Drop Another .txt File To Continue")

            if action == "remove":
                ud["await"] = "remove"
                return await q.edit_message_text("Send Last 4# Seperated By Commas Of The Card(s) You Want Removed")

            if action == "setfn":
                ud["await"] = "filename"
                return await q.edit_message_text("Send filename (without path). Example: BatchCust-01")

            if action == "check":
                # show-only checker
                return await send_post(update, context)

            if action == "send":
                cards = ud.get("live_cards") or session_cards(ud)
                conf = settings()
                mode = ud.get("mode")
                is_tester = mode == "tester"
                if mode == "format":
                    fn = ud.get("filename") or f"Batch-{ud.get('batch', batch_id())}.txt"
                    if not fn.endswith(".txt"):
                        fn += ".txt"
                    content = build_output_file(cards, is_tester=False)
                    bio = io.BytesIO(content.encode())
                    bio.name = fn
                    await context.bot.send_document(uid, document=InputFile(bio), caption="Formatted pack")
                elif mode == "tester":
                    fn = ud.get("filename") or f"Tester-{ud.get('batch', batch_id())}.txt"
                    if not fn.endswith(".txt"):
                        fn += ".txt"
                    content = build_output_file(cards, is_tester=True)
                    bio = io.BytesIO(content.encode())
                    bio.name = fn
                    await context.bot.send_document(uid, document=InputFile(bio), caption=f"Tester ({ud.get('tester_type')})")
                    st = user_stats(uid)
                    st["testers_given"] += len(cards)
                    put_user_stats(uid, st)
                elif mode == "sale":
                    target = int(ud.get("target") or 0)
                    live = cards
                    sold_n = min(len(live), target) if target else len(live)
                    primary = live[:sold_n]
                    extras = live[sold_n:]
                    cust = re.sub(r"[^\w\-]+", "_", str(ud.get("customer", "Customer")))
                    fn = f"{cust}-{len(primary)}-{ud.get('batch', batch_id())}.txt"
                    content = build_output_file(primary)
                    bio = io.BytesIO(content.encode())
                    bio.name = fn
                    await context.bot.send_document(uid, document=InputFile(bio), caption="Sale pack")
                    if extras:
                        fn2 = f"Extras-{len(extras)}-{ud.get('batch', batch_id())}.txt"
                        bio2 = io.BytesIO(build_output_file(extras).encode())
                        bio2.name = fn2
                        await context.bot.send_document(uid, document=InputFile(bio2), caption="Extras")
                    # accounting
                    st = user_stats(uid)
                    revenue = sold_n * float(conf["sale_price"])
                    profit = sold_n * (float(conf["sale_price"]) - float(conf["card_cost"]))
                    st["cards_sold"] += sold_n
                    st["total_sales"] += 1
                    st["revenue"] += revenue
                    st["total_profit"] += profit
                    put_user_stats(uid, st)
                    stock_decrement_for_cards(primary)
                elif mode == "replace":
                    target = int(ud.get("target") or 0)
                    live = cards
                    primary = live[:target] if target else live
                    extras = live[len(primary):]
                    cust = re.sub(r"[^\w\-]+", "_", str(ud.get("customer", "Customer")))
                    fn = f"{cust}-{len(primary)}-{ud.get('batch', batch_id())}.txt"
                    bio = io.BytesIO(build_output_file(primary).encode())
                    bio.name = fn
                    await context.bot.send_document(uid, document=InputFile(bio), caption="Replacement pack")
                    if extras:
                        fn2 = f"Extras-{len(extras)}-{ud.get('batch', batch_id())}.txt"
                        bio2 = io.BytesIO(build_output_file(extras).encode())
                        bio2.name = fn2
                        await context.bot.send_document(uid, document=InputFile(bio2), caption="Extras")
                    st = user_stats(uid)
                    st["replacements_given"] += len(primary)
                    # subtract card cost from revenue/profit
                    cost = len(primary) * float(conf["card_cost"])
                    st["revenue"] -= cost
                    st["total_profit"] -= cost
                    put_user_stats(uid, st)
                    stock_decrement_for_cards(primary)
                ud["await"] = None
                await context.bot.send_message(uid, "Done. /cancel for Admin panel", reply_markup=main_menu_kb())
                return

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await deny(update)
    ud = context.user_data
    text = (update.message.text or "").strip() if update.message else ""

    # file drop
    cards_from_file = []
    if update.message.document:
        f = await update.message.document.get_file()
        raw = await f.download_as_bytearray()
        try:
            payload = raw.decode("utf-8", errors="ignore")
        except Exception:
            payload = ""
        cards_from_file = parse_cards(payload)
        text = payload

    awaiting = ud.get("await")
    mode = ud.get("mode")

    if mode == "settings" and awaiting is None and ud.get("settings_field"):
        field = ud.get("settings_field")
        conf = settings()
        if field in ("sale_price", "card_cost"):
            try:
                conf[field] = float(text)
                save_settings(conf)
                ud["settings_field"] = None
                return await update.message.reply_text(f"Updated {field}={conf[field]}", reply_markup=main_menu_kb())
            except ValueError:
                return await update.message.reply_text("Number only.")
        if field == "add_admin":
            try:
                new_id = int(text)
                ADMIN_IDS.add(new_id)
                ud["settings_field"] = None
                return await update.message.reply_text(f"Admin {new_id} added for this runtime. Also add to Railway ADMIN_IDS for persistence.", reply_markup=main_menu_kb())
            except ValueError:
                return await update.message.reply_text("Numeric user id only.")

    if mode == "stock":
        if awaiting == "stock_fn":
            ud["stock_fn"] = text if text.endswith(".txt") else text + ".txt"
            ud["await"] = None
            return await update.message.reply_text(f"Stock filename set: {ud['stock_fn']}", reply_markup=main_menu_kb())
        if awaiting == "stock_search":
            b = re.sub(r"\D", "", text)[:6]
            st = stock()
            qty = int(st.get(b, 0))
            info = bins().get(b, {})
            msg = (
                f"BIN STOCK CHECK (forwardable)\n"
                f"BIN: {b}\n"
                f"Qty: {qty}\n"
                f"Bank: {info.get('bank','N/A')}\n"
                f"Country: {info.get('country','N/A')}\n"
                f"Brand: {info.get('brand','N/A')}"
            )
            ud["await"] = None
            return await update.message.reply_text(msg)
        if awaiting == "stock_bin":
            b = re.sub(r"\D", "", text)[:6]
            ud["stock_bin"] = b
            ud["await"] = "stock_qty"
            return await update.message.reply_text(f"BIN {b} selected. Send amount (integer).")
        if awaiting == "stock_qty":
            try:
                qty = int(text)
            except ValueError:
                return await update.message.reply_text("Integer amount only.")
            st = stock()
            b = ud.get("stock_bin")
            cur = int(st.get(b, 0))
            if ud.get("stock_op") == "add":
                st[b] = cur + qty
            else:
                st[b] = max(0, cur - qty)
            save_stock(st)
            # ensure bin exists in bins_db skeleton
            bdb = bins()
            if b not in bdb:
                bdb[b] = {"brand":"UNKNOWN","type":"","level":"","bank":"UNKNOWN","country":"UNKNOWN","cc":"XX","rating":"10/10","vr":10,"balance_rating":10,"suggestion":"General","forced_vr":None}
                save_bins(bdb)
            ud["await"] = None
            return await update.message.reply_text(f"Stock {b} => {st[b]}", reply_markup=main_menu_kb())

    if mode == "rate" and awaiting == "bin":
        b = re.sub(r"\D", "", text)[:6]
        bdb = bins()
        if b not in bdb:
            bdb[b] = {"brand":"UNKNOWN","type":"","level":"","bank":"UNKNOWN","country":"UNKNOWN","cc":"XX","rating":"10/10","vr":10,"balance_rating":10,"suggestion":"General","forced_vr":None}
            save_bins(bdb)
        ud["rate_bin"] = b
        info = bdb[b]
        action = ud.get("rate_action")
        ud["await"] = "rate_value"
        return await update.message.reply_text(
            f"You Have Selected Bin {b}\nBank:{info.get('bank')}\nCountry:{info.get('country')}\nBrand:{info.get('brand')}\n"
            f"Current VR:{info.get('vr')} Rating:{info.get('rating')} Bal:{info.get('balance_rating')} Sug:{info.get('suggestion')} Force:{info.get('forced_vr')}\n"
            + {
                "set_vr": "What Do You Want To Set The Vr Rating As (0-10)",
                "rate_bin": "Rate Bin itself (0-10 or text like 10/10)",
                "set_bal": "Set Bin Balance Rating (0-10)",
                "suggest": "Send suggestion places to use bin",
                "force_vr": "Set Forced Vr Rating, Say Reset To Disable",
            }.get(action, "Send value")
        )

    if mode == "rate" and awaiting == "rate_value":
        b = ud.get("rate_bin")
        bdb = bins()
        info = bdb.get(b, {})
        action = ud.get("rate_action")
        if action == "set_vr":
            try:
                v = int(re.sub(r"[^0-9]", "", text) or "0")
                info["vr"] = max(0, min(10, v))
                info["rating"] = f"{info['vr']}/10"
            except Exception:
                return await update.message.reply_text("0-10 only")
        elif action == "rate_bin":
            info["rating"] = text
        elif action == "set_bal":
            try:
                v = int(re.sub(r"[^0-9]", "", text) or "0")
                info["balance_rating"] = max(0, min(10, v))
            except Exception:
                return await update.message.reply_text("0-10 only")
        elif action == "suggest":
            info["suggestion"] = text
        elif action == "force_vr":
            if text.strip().lower() == "reset":
                info["forced_vr"] = None
            else:
                try:
                    info["forced_vr"] = int(re.sub(r"[^0-9]", "", text) or "0")
                except Exception:
                    return await update.message.reply_text("Number or Reset")
        bdb[b] = info
        save_bins(bdb)
        ud["await"] = None
        return await update.message.reply_text(f"Updated BIN {b}: {info}", reply_markup=main_menu_kb())

    if mode == "sale" and awaiting == "customer":
        ud["customer"] = text
        ud["await"] = "target"
        return await update.message.reply_text(f'How Many Cards Is "{text}" Purchasing (number only)')

    if mode == "replace" and awaiting == "customer":
        ud["customer"] = text
        ud["await"] = "target"
        return await update.message.reply_text("How Many Cards Are Being Replaced (number only)")

    if mode in ("sale", "replace") and awaiting == "target":
        if not text.isdigit():
            return await update.message.reply_text("Number only.")
        ud["target"] = int(text)
        ud["await"] = "cards"
        if mode == "sale":
            await update.message.reply_text("Target Set")
            # sale still needs cards
            return await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
        else:
            await update.message.reply_text("Target Submitted")
            return await update.message.reply_text("Send Cards Or Drop .txt File To Continue")

    if mode == "tester" and awaiting == "tester_type":
        t = text.lower()
        if t not in ("drop", "gift"):
            return await update.message.reply_text("Reply Drop or Gift")
        ud["tester_type"] = t.title()
        ud["await"] = "cards"
        return await update.message.reply_text("Send Cards Or Drop .txt File To Continue")

    if awaiting == "filename":
        ud["filename"] = text if text.endswith(".txt") else text
        ud["await"] = None
        return await send_pre(update, context)

    if awaiting == "remove":
        lasts = [x.strip()[-4:] for x in text.split(",") if x.strip()]
        before = len(session_cards(ud))
        ud["cards"] = [c for c in session_cards(ud) if c["cc"][-4:] not in lasts]
        await update.message.reply_text(f"Removed {before - len(ud['cards'])} cards.")
        ud["await"] = None
        return await send_pre(update, context)

    if awaiting == "cards" or cards_from_file:
        new_cards = cards_from_file or parse_cards(text)
        if not new_cards:
            return await update.message.reply_text("No cards detected. Use pipe format or .txt drop.")
        session_cards(ud).extend(new_cards)
        ud["batch"] = batch_id()  # new batch id on each add; send still dumps full session
        ud["await"] = None
        # ask USA/Foreign then presummary
        await update.message.reply_text(
            f"Added {len(new_cards)}. Total now {len(session_cards(ud))}. Choose bucket:",
            reply_markup=usa_foreign_kb(ud.get("mode") or "format"),
        )
        return

    # default
    if text.startswith("/"):
        return
    await update.message.reply_text("Use panel buttons or /cancel", reply_markup=main_menu_kb())

def main():
    # no range(28) unpack — that was your crash
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("format", lambda u,c: on_callback_equiv(u,c,"menu:format")))
    app.add_handler(CommandHandler("sale", lambda u,c: on_callback_equiv(u,c,"menu:sale")))
    app.add_handler(CommandHandler("replace", lambda u,c: on_callback_equiv(u,c,"menu:replace")))
    app.add_handler(CommandHandler("tester", lambda u,c: on_callback_equiv(u,c,"menu:tester")))
    app.add_handler(CommandHandler("rate", lambda u,c: on_callback_equiv(u,c,"menu:rate")))
    app.add_handler(CommandHandler("list", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.TEXT, on_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

async def on_callback_equiv(update, context, data):
    # synthesize menu route for slash commands
    if not is_admin(update.effective_user.id):
        return await deny(update)
    class Q:
        pass
    # simplest: reuse flows
    ud = context.user_data
    if data == "menu:format":
        ud.clear(); ud.update({"mode":"format","batch":batch_id(),"cards":[],"await":"cards"})
        await update.message.reply_text("Send Cards Or Drop .txt File To Continue")
    elif data == "menu:sale":
        ud.clear(); ud.update({"mode":"sale","batch":batch_id(),"cards":[],"await":"customer"})
        await update.message.reply_text("Please Respond With The Customer Name")
    elif data == "menu:replace":
        ud.clear(); ud.update({"mode":"replace","batch":batch_id(),"cards":[],"await":"customer"})
        await update.message.reply_text("Who Is Being Replaced")
    elif data == "menu:tester":
        ud.clear(); ud.update({"mode":"tester","batch":batch_id(),"cards":[],"await":"tester_type"})
        await update.message.reply_text("Is This Tester A Drop Or Gift?")
    elif data == "menu:rate":
        await update.message.reply_text("Use Rate button panel or /start")

if __name__ == "__main__":
    main()
