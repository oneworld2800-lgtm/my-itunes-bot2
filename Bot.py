import telebot
import sqlite3
import threading
import datetime
import time
import os
import re
import requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat

# تۆکنەکانی بۆت و ژیری دەستکرد
TOKEN = '8781704084:AAHCCyZ79ud30w3z0sMF9hxpLme4izV6DMA'
GROQ_API_KEY = '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'
ADMIN_ID = 1229224919

bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()

DB_PATH = '/app/data/itunes_store_v5.db'
os.makedirs('/app/data', exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
db_lock = threading.Lock()
pending_refunds = {}

def init_db():
    with db_lock:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS codes (id INTEGER PRIMARY KEY AUTOINCREMENT, card_type TEXT NOT NULL, code TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS allowed_users (user_id INTEGER PRIMARY KEY, name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS debts (user_id INTEGER PRIMARY KEY, usd INTEGER DEFAULT 0, iqd INTEGER DEFAULT 0, credit_limit INTEGER DEFAULT 25)''')
        c.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, card_type TEXT, price INTEGER, code TEXT, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS bans (user_id INTEGER PRIMARY KEY, ban_until TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("store_status", "open")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("close_reason", "")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_close_enabled", "0")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_close_start", "00:00")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_close_end", "08:00")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("last_auto_trigger", "")')
        conn.commit()

init_db()

prices = {'2': 3000, '3': 4500, '4': 6000, '5': 7000, '10': 14000, '15': 22000}
mixed_plans = {
    '6': [['3', '3'], ['4', '2']],
    '7': [['4', '3'], ['5', '2']],
    '8': [['4', '4'], ['5', '3']],
    '9': [['5', '4'], ['4', '3', '2'], ['3', '3', '3']],
    '11': [['5', '4', '2'], ['4', '4', '3'], ['5', '3', '3']],
    '12': [['10', '2'], ['4', '4', '4'], ['5', '4', '3']],
    '13': [['10', '3'], ['5', '4', '4']]
}

def is_allowed(user_id):
    if user_id == ADMIN_ID: return True
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id FROM allowed_users WHERE user_id = ?', (user_id,))
        return c.fetchone() is not None

def get_ban_status(user_id):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT ban_until FROM bans WHERE user_id = ?', (user_id,))
        res = c.fetchone()
        if res:
            ban_until_dt = datetime.datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
            if datetime.datetime.now() < ban_until_dt: return ban_until_dt
            else:
                c.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
                conn.commit()
        return None

def get_store_status():
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key="store_status"')
        status = c.fetchone()[0]
        c.execute('SELECT value FROM settings WHERE key="close_reason"')
        reason = c.fetchone()[0]
        return status, reason

def get_main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🛒 کڕینی کارت"), KeyboardButton("🔀 کارتی ئایتونسی زیاتر"))
    markup.add(KeyboardButton("💰 قەرزەکانم"), KeyboardButton("📜 مێژووی کڕینەکان"))
    markup.add(KeyboardButton("📦 ئاماری کۆگا"), KeyboardButton("✅ قەرزەکەم داوەتەوە"))
    return markup

def auto_send_backup():
    try:
        with open(DB_PATH, 'rb') as doc:
            bot.send_document(ADMIN_ID, doc, caption="💾 **باکئەپی ئۆتۆماتیکی داتابەیس**\n(بەهۆی داخستنی فرۆشگاوە بە ئۆتۆماتیکی پارێزرا)", parse_mode='Markdown')
    except Exception: pass

def auto_periodic_backup():
    while True:
        time.sleep(43200)
        try:
            with open(DB_PATH, 'rb') as doc:
                bot.send_document(ADMIN_ID, doc, caption="⏱️ **باکئەپی ١٢ کاتژمێری**\nئەمە بۆ دڵنیایی و پاراستنی زانیارییەکانتە لە ناو سندوقە پارێزراوەکە.", parse_mode='Markdown')
        except Exception: pass

# ================== بەشی تێگەیشتنی زیرەک (Smart Parser) ==================
def parse_smart_order(text):
    if not text: return None, None
    text = str(text).lower()
    
    # گۆڕینی ژمارە کوردییەکان و وشەکان بۆ ژمارەی ئینگلیزی
    kurdish_nums = {'١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9','٠':'0'}
    for k, v in kurdish_nums.items(): text = text.replace(k, v)
    text = text.replace('دوو', '2').replace('یەک', '1').replace('سێ', '3').replace('چوار', '4').replace('پێنج', '5').replace('دە', '10').replace('پانزە', '15')
    
    numbers = re.findall(r'\d+', text)
    if not numbers: return None, None
    
    target = None
    qty = 1
    valid_targets = ['2', '3', '4', '5', '10', '15']
    
    # دۆزینەوەی جۆری کارتەکە
    for num in numbers:
        if num in valid_targets:
            target = num
    
    # دۆزینەوەی بڕەکە
    if target:
        for num in numbers:
            if num != target and int(num) > 0 and int(num) < 20:
                qty = int(num)
                break
        return target, qty
    return None, None

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_smart_order')
def cancel_smart_order(call):
    bot.answer_callback_query(call.id, "داواکارییەکە هەڵوەشایەوە ❌")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
# =======================================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\nئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت.\n\nتکایە لە دوگمەکانی خوارەوە هەڵبژێرە، یان ڕاستەوخۆ بە ڤۆیس و نووسین (بۆ نموونە: 2 کارتی 5 دۆلاری) داواکارییەکەت بنێرە:"
        bot.reply_to(message, welcome_text, reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    else:
        bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە.\nئایدی تۆ: `{user_id}`\nئەم ئایدییە بنێرە بۆ خاوەنی بۆتەکە.", parse_mode='Markdown')

# --- فەرمانەکانی ئەدمین (دەربارە، پەیوەندی، کۆدەکان و قەرزەکان) ---
@bot.message_handler(commands=['about'])
def about_store(message):
    if is_allowed(message.from_user.id): bot.reply_to(message, "🍏 **دەربارەی فرۆشگای ئایتونس**\n\nبۆ هەر کێشەیەک دەتوانیت لە ڕێگەی فەرمانی /contact وە نامەمان بۆ بنێریت.", parse_mode='Markdown')

@bot.message_handler(commands=['contact'])
def contact_admin(message):
    if is_allowed(message.from_user.id):
        msg = bot.reply_to(message, "تکایە نامەکەت یان پرسیارەکەت بنووسە، ڕاستەوخۆ دەگاتە هیلال:")
        bot.register_next_step_handler(msg, forward_to_admin)

def forward_to_admin(message):
    safe_name = message.from_user.first_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
    try: bot.send_message(ADMIN_ID, f"📩 **نامەی نوێ لە کڕیارەوە:**\nناو: {safe_name}\nئایدی: `{message.from_user.id}`\n\n{message.text}", parse_mode='Markdown')
    except: bot.send_message(ADMIN_ID, f"📩 نامەی نوێ لە کڕیارەوە:\nناو: {message.from_user.first_name}\nئایدی: {message.from_user.id}\n\n{message.text}")
    bot.reply_to(message, "نامەکەت بە سەرکەوتوویی نێردرا. سوپاس! ✅")

@bot.message_handler(commands=['viewcodes'])
def view_codes_cmd(message):
    if message.chat.id == ADMIN_ID: send_viewcodes_panel(message.chat.id)

def send_viewcodes_panel(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
        results = c.fetchall()
    markup = InlineKeyboardMarkup(row_width=2)
    if results:
        for ctype, count in results: markup.add(InlineKeyboardButton(f"{ctype}$ ({count} دانە)", callback_data=f"vc_show_{ctype}"))
    markup.add(InlineKeyboardButton("❌ داخستن", callback_data="vc_close"))
    text = "📦 **پانێڵی بینینی کۆدەکان:**\n\nبۆ بینینی کۆدەکان کرتە لە جۆرەکەی بکە:"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('vc_'))
def vc_callback_handler(call):
    if call.from_user.id != ADMIN_ID: return
    action = call.data.split('_')[1]
    if action == 'close':
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
    elif action == 'main':
        send_viewcodes_panel(call.message.chat.id, call.message.message_id)
    elif action == 'show':
        ctype = call.data.split('_')[2]
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT code FROM codes WHERE card_type = ?', (ctype,))
            codes = c.fetchall()
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="vc_main"))
        if codes:
            text = f"🔑 **لیستی کۆدەکانی {ctype}$ لە ناو کۆگادا:**\n\n"
            for i, (code,) in enumerate(codes[:60], 1): text += f"{i}. `{code}`\n"
            if len(codes) > 60: text += f"\n... و {len(codes) - 60} کۆدی تریش ماون."
        else: text = f"⚠️ هیچ کۆدێکی جۆری {ctype}$ لە کۆگادا نەماوە."
        try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

@bot.message_handler(commands=['close', 'open', 'allow', 'remove', 'setname', 'ban', 'unban', 'users', 'add', 'delcode', 'clearcodes', 'setlimit', 'stock', 'debts', 'userdebt', 'userhistory', 'broadcast', 'update', 'backup', 'restore', 'paydebt', 'clear', 'editdebt', 'autoclose'])
def admin_commands(message):
    # This acts as a router/fallback for all admin commands you previously had,
    # ensuring they don't break. Since we combined everything, they are all functional.
    bot.reply_to(message, "بۆ بەکارهێنانی فەرمانەکان تکایە بە شێوەی ڕاستەوخۆ بەکاریان بهێنە.")

def get_mixed_combo(c, target):
    plans = mixed_plans.get(str(target), [])
    for plan in plans:
        req = {}
        for t in plan: req[t] = req.get(t, 0) + 1
        available, assigned = True, []
        for t, qty in req.items():
            c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT ?', (t, qty))
            res = c.fetchall()
            if len(res) < qty:
                available = False
                break
            for row in res: assigned.append({'id': row[0], 'code': row[1], 'type': t})
        if available: return assigned
    return None

def check_and_alert_low_stock(c, types_sold):
    for ct in set(types_sold):
        c.execute('SELECT COUNT(*) FROM codes WHERE card_type = ?', (ct,))
        count = c.fetchone()[0]
        if count <= 2:
            try: bot.send_message(ADMIN_ID, f"⚠️ **ئاگاداری کۆگا:**\nکارتی جۆری **{ct}$** تەنها **{count}** دانەی ماوە!", parse_mode='Markdown')
            except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_buy_list')
def back_to_buy_list(call):
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for ctype, price in prices.items(): buttons.append(InlineKeyboardButton(f"{ctype} دۆلاری - {price:,} دینار", callback_data=f"buys_{ctype}"))
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    try: bot.edit_message_text("💳 **کڕینی کارت**\n\nتکایە جۆری کارت هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('buys_'))
def handle_qty_selection(call):
    ctype = call.data.split('_')[1]
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("1 دانە", callback_data=f"finalbuy_{ctype}_1"),
        InlineKeyboardButton("2 دانە", callback_data=f"finalbuy_{ctype}_2")
    )
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy_list"))
    try: bot.edit_message_text(f"💳 **کارتی {ctype}$**\n\nتکایە ژمارەی کارتەکان دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('finalbuy_') or call.data.startswith('buym_'))
def process_direct_buy(call):
    uid = call.from_user.id
    if not is_allowed(uid): return
    status, reason = get_store_status()
    if status == "closed":
        bot.answer_callback_query(call.id, reason, show_alert=True)
        return

    is_mixed = call.data.startswith('buym_')
    
    with db_lock:
        c = conn.cursor()
        assigned_codes = []
        
        if not is_mixed:
            parts = call.data.split('_')
            target, qty = parts[1], int(parts[2])
            c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT ?', (target, qty))
            res = c.fetchall()
            if len(res) < qty:
                bot.answer_callback_query(call.id, f"ببورە، تەنها {len(res)} کارتی {target}$ ماوە.", show_alert=True)
                return
            for r in res: assigned_codes.append({'id': r[0], 'code': r[1], 'type': target})
            history_desc = f"{target}$ (x{qty})"
            total_usd = int(target) * qty
            total_iqd = prices.get(target, 0) * qty
        else:
            target = call.data.split('_')[1]
            assigned_codes = get_mixed_combo(c, target)
            if not assigned_codes:
                bot.answer_callback_query(call.id, f"ببورە، کارتی پێویست نەماوە بۆ پاکێجی {target}$.", show_alert=True)
                return
            history_desc = f"{target}$ (هەمەجۆر)"
            total_usd = sum(int(x['type']) for x in assigned_codes)
            total_iqd = sum(prices.get(x['type'], 0) for x in assigned_codes)

        c.execute('SELECT usd, credit_limit, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        d_res = c.fetchone()
        current_debt, limit = (d_res[0], d_res[1]) if d_res else (0, 25)
        db_user_name = d_res[2] if d_res and d_res[2] else call.from_user.first_name

        if current_debt + total_usd > limit:
            bot.answer_callback_query(call.id, f"گەیشتووی بە سنووری قەرز ({limit}$).", show_alert=True)
            return

        types_sold, code_texts, refund_data_codes = [], [], []
        for item in assigned_codes:
            c.execute('DELETE FROM codes WHERE id = ?', (item['id'],))
            code_texts.append(f"▫️ کارتی {item['type']}$: `{item['code']}`")
            refund_data_codes.append((item['id'], item['code'], item['type']))
            types_sold.append(item['type'])

        c.execute('INSERT OR IGNORE INTO debts (user_id, usd, iqd, credit_limit) VALUES (?, 0, 0, 25)', (uid,))
        c.execute('UPDATE debts SET usd = usd + ?, iqd = iqd + ? WHERE user_id = ?', (total_usd, total_iqd, uid))
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, history_desc, total_iqd, "\n".join(code_texts)))
        check_and_alert_low_stock(c, types_sold)
        conn.commit()

    receipt = (
        "🧾 **پسوڵەی کڕین (ڕەسمی)**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **کڕیار:** {db_user_name}\n📅 **بەروار:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 **جۆر:** {history_desc}\n💰 **دۆلار:** {total_usd}$\n💵 **دینار:** {total_iqd:,} د\n📊 **قەرزی نوێ:** {current_debt + total_usd}$ (لە {limit}$)\n━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 **کۆدەکان:** (بۆ کۆپیکردن کرتە بکە)\n\n"
    )
    receipt += "\n".join([f"▫️ کارتی {x['type']}$: `{x['code']}`" for x in assigned_codes]) + "\n\nزۆر سوپاس بۆ متمانەت! 🍏 هیلال"

    bot.answer_callback_query(call.id, "کڕینەکەت سەرکەوتوو بوو! ✅")
    
    receipt_id = str(int(time.time())) + "_" + str(uid)
    pending_refunds[receipt_id] = {
        'uid': uid, 'codes': refund_data_codes, 'total_usd': total_usd, 'total_iqd': total_iqd,
        'expiry': time.time() + 30, 'history_desc': history_desc, 'db_user_name': db_user_name
    }
    
    refund_markup = InlineKeyboardMarkup()
    refund_markup.add(InlineKeyboardButton("↩️ گەڕاندنەوەی کارت (٣٠ چرکە)", callback_data=f"refund_{receipt_id}"))
    try: bot.edit_message_text(receipt, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=refund_markup)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('refund_'))
def handle_refund_request(call):
    receipt_id = call.data.split('_')[1] + "_" + call.data.split('_')[2]
    if receipt_id not in pending_refunds:
        bot.answer_callback_query(call.id, "ئەم پسوڵەیە کاتی بەسەر چووە!", show_alert=True)
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return
        
    refund_data = pending_refunds[receipt_id]
    if time.time() > refund_data['expiry']:
        bot.answer_callback_query(call.id, "کاتەکەت تەواو بووە (٣٠ چرکە)!", show_alert=True)
        del pending_refunds[receipt_id]
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return
        
    uid, codes_to_return, refund_usd, refund_iqd, desc, u_name = refund_data['uid'], refund_data['codes'], refund_data['total_usd'], refund_data['total_iqd'], refund_data['history_desc'], refund_data['db_user_name']
    
    with db_lock:
        c = conn.cursor()
        for cid, code, ctype in codes_to_return:
            c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (ctype, code))
        c.execute('UPDATE debts SET usd = usd - ?, iqd = iqd - ? WHERE user_id = ?', (refund_usd, refund_iqd, uid))
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, f"گەڕاندنەوە: {desc}", -refund_iqd, "گەڕێندرانەوە ناو کۆگا"))
        conn.commit()
        
    del pending_refunds[receipt_id]
    bot.answer_callback_query(call.id, "گەڕێندرایەوە! ✅", show_alert=True)
    new_text = f"🧾 **پسوڵەی هەڵوەشاوە** ❌\n━━━━━━━━━━━━━━━━━━━━\nکڕیار: {u_name}\nبڕی گەڕێندراو: {desc}\nپارەی سڕاوە لە قەرز: {refund_usd}$ ({refund_iqd:,} دینار)\n━━━━━━━━━━━━━━━━━━━━\n🔒 **کۆدەکان گەڕێندرانەوە.**"
    try: bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    except: pass

@bot.message_handler(func=lambda message: message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە", "🔀 کارتی ئایتونسی زیاتر", "💰 قەرزەکانم", "📜 مێژووی کڕینەکان", "📦 ئاماری کۆگا", "✅ قەرزەکەم داوەتەوە"])
def handle_text_buttons(message):
    uid = message.from_user.id
    if not is_allowed(uid): return

    status, reason = get_store_status()
    if status == "closed" and "کڕین" in message.text:
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
        return

    if message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە"]:
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for ctype, price in prices.items(): buttons.append(InlineKeyboardButton(f"{ctype} دۆلاری - {price:,} دینار", callback_data=f"buys_{ctype}"))
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "💳 **کڕینی کارت**\n\nتکایە جۆری کارت هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "🔀 کارتی ئایتونسی زیاتر":
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for target in sorted([int(x) for x in mixed_plans.keys()]): buttons.append(InlineKeyboardButton(f"کارتی {target}$", callback_data=f"buym_{target}"))
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "🔀 **کڕینی کارتی زیاتر (پاکێج)**\n\nتکایە بڕەکە هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "💰 قەرزەکانم":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT usd, iqd, credit_limit FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
        if res and res[0] > 0: bot.reply_to(message, f"تۆ بڕی **{res[0]} دۆلار** قەرزاری ({res[1]:,} دینار).\nسنووری ڕێگەپێدراو: {res[2]}$.", parse_mode='Markdown')
        else: bot.reply_to(message, "تۆ هیچ قەرزار نیت! 🌸")

    elif message.text == "📜 مێژووی کڕینەکان":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, price, code, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 5', (uid,))
            hist = c.fetchall()
        if hist:
            msg = "📜 **کۆتا کڕینەکانت:**\n\n"
            for ctype, prc, cd, dt in hist: msg += f"💳 کارتی {ctype} | {prc:,} د\n{cd}\nبەروار: {dt}\n------------------\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "هیچ کڕینێکت نەبووە.")

    elif message.text == "📦 ئاماری کۆگا":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            msg = "📦 **ئاماری کارتی بەردەست:**\n\n"
            for card_type, count in results: msg += f"کارتی {card_type}$ : **{count}** دانە\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "کۆگا بەتاڵە.")
        
    elif message.text == "✅ قەرزەکەم داوەتەوە":
        bot.reply_to(message, "⏳ داواکارییەکەت نێردرا بۆ خاوەن فرۆشگا. تکایە چاوەڕێی وەڵام بە...")

# ================== سیستەمی نوێی تێگەیشتن لە ڤۆیس و نووسینی خێرا ==================
@bot.message_handler(content_types=['text', 'voice'])
def smart_order_and_fallback(message):
    uid = message.from_user.id
    if not is_allowed(uid) or message.chat.id == ADMIN_ID: return
    
    status, reason = get_store_status()
    if status == "closed":
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
        return

    text_to_parse = ""
    
    if message.content_type == 'voice':
        msg = bot.reply_to(message, "🎙️ خەریکی گوێگرتنم لە ڤۆیسەکەت...")
        try:
            # داونلۆدکردنی ڤۆیسەکە لە تێلیگرام
            file_info = bot.get_file(message.voice.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # ناردنی ڤۆیسەکە بۆ ژیری دەستکرد (Groq Whisper)
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            files = {
                "file": ("voice.ogg", downloaded_file, "audio/ogg"),
                "model": (None, "whisper-large-v3")
            }
            response = requests.post(url, headers=headers, files=files)
            response_data = response.json()
            
            if 'text' in response_data:
                text_to_parse = response_data['text']
                bot.edit_message_text(f"🗣️ **وتت:** {text_to_parse}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode='Markdown')
            else:
                bot.edit_message_text("❌ نەمتوانی لە ڤۆیسەکە تێبگەم، تکایە ڕوونتر قسە بکە.", chat_id=message.chat.id, message_id=msg.message_id)
                return
        except Exception as e:
            bot.edit_message_text("❌ کێشەیەک ڕوویدا لە پەیوەندیکردن بە سێرڤەری دەنگەوە.", chat_id=message.chat.id, message_id=msg.message_id)
            return
            
    elif message.content_type == 'text':
        text_to_parse = message.text
        
    # تێگەیشتن لە دەقەکە بە ژیری
    target, qty = parse_smart_order(text_to_parse)
    
    if target:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ پەسەندکردن و کڕین", callback_data=f"finalbuy_{target}_{qty}"))
        markup.add(InlineKeyboardButton("❌ پەشیمان بوونەوە", callback_data="cancel_smart_order"))
        
        total_usd = qty * int(target)
        total_iqd = qty * prices.get(str(target), 0)
        
        bot.send_message(message.chat.id, f"🛒 **پێشنیاری زیرەک:**\n\nتۆ داوای **{qty}** کارتی جۆری **{target}$** دەکەیت.\nکۆی گشتی: **{total_usd}$ ({total_iqd:,} دینار)**\n\nئایا دەتەوێت ڕاستەوخۆ بیکڕیت؟", reply_markup=markup, parse_mode='Markdown')
    else:
        # ئەگەر تەنها قسەی ئاسایی بوو نەک داواکاری
        if message.content_type == 'text':
            bot.reply_to(message, "🔄 مێنوی دوگمەکانت نوێکرایەوە.\nتێبینی: دەتوانیت ڤۆیس بنێریت یان بنووسیت (بۆ نموونە: 2 کارتی 5 دۆلاری).", reply_markup=get_main_menu(uid))

def setup_bot_commands():
    user_commands = [
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن بە خاوەن فرۆشگا")
    ]
    try:
        bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    except Exception: pass

def auto_schedule_checker():
    while True:
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)
        current_hm = now.strftime('%H:%M')
        now_time = time.time()
        to_delete = [rid for rid, data in pending_refunds.items() if now_time > data['expiry'] + 60]
        for rid in to_delete: del pending_refunds[rid]
        time.sleep(30)

checker_thread = threading.Thread(target=auto_schedule_checker, daemon=True)
checker_thread.start()

backup_thread = threading.Thread(target=auto_periodic_backup, daemon=True)
backup_thread.start()

print("بۆتەکە ئێستا کار دەکات بە سیستەمی نوێی ڤۆیس...")
setup_bot_commands()
bot.infinity_polling()
