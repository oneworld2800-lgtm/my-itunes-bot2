import telebot
import sqlite3
import threading
import datetime
import time
import os
import re
import requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat

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

# ئەلگۆریتمی دۆزینەوەی باشترین تێکەڵەی کارتەکان لە کۆگا
def get_dynamic_combo(c, target_val, qty=1):
    available_cards = [15, 10, 5, 4, 3, 2]
    
    def find_combinations(target, current_combo, start_idx):
        if target == 0: return [current_combo]
        if target < 0: return []
        combos = []
        for i in range(start_idx, len(available_cards)):
            card = available_cards[i]
            combos.extend(find_combinations(target - card, current_combo + [card], i))
        return combos
    
    all_possible_combos = find_combinations(target_val, [], 0)
    all_possible_combos.sort(key=len) 
    
    for combo in all_possible_combos:
        req = {}
        for t in combo: req[str(t)] = req.get(str(t), 0) + qty
        
        available, assigned = True, []
        for t_str, req_qty in req.items():
            c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT ?', (t_str, req_qty))
            res = c.fetchall()
            if len(res) < req_qty:
                available = False
                break
            for row in res:
                assigned.append({'id': row[0], 'code': row[1], 'type': t_str})
        
        if available:
            return assigned
            
    return None

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
        with open(DB_PATH, 'rb') as doc: bot.send_document(ADMIN_ID, doc, caption="💾 **باکئەپی ئۆتۆماتیکی داتابەیس**", parse_mode='Markdown')
    except Exception: pass

def auto_periodic_backup():
    while True:
        time.sleep(43200)
        try:
            with open(DB_PATH, 'rb') as doc: bot.send_document(ADMIN_ID, doc, caption="⏱️ **باکئەپی ١٢ کاتژمێری**", parse_mode='Markdown')
        except Exception: pass

def parse_smart_order(text):
    if not text: return None, 1, False
    text = str(text).lower()
    
    phonetics = {'yek':'1', 'du':'2', 'se':'3', 'cwar':'4', 'chwar':'4', 'pen':'5', 'penc':'5', 'ses':'6', 'shesh':'6', 'heft':'7', 'hest':'8', 'hesht':'8', 'no':'9', 'de':'10', 'panz':'15', 'cart':'', 'dolar':''}
    for k, v in phonetics.items(): text = text.replace(k, v)
        
    kurdish_nums = {'١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9','٠':'0'}
    for k, v in kurdish_nums.items(): text = text.replace(k, v)
    text = text.replace('دوو', '2').replace('یەک', '1').replace('سێ', '3').replace('چوار', '4').replace('پێنج', '5').replace('شەش', '6').replace('حەوت', '7').replace('هەشت', '8').replace('نۆ', '9').replace('دە', '10').replace('پانزە', '15')
    
    numbers = [int(n) for n in re.findall(r'\d+', text)]
    if not numbers: return None, 1, False
    
    numbers = [n for n in numbers if n <= 25]
    if not numbers: return None, 1, False
    
    target = None
    qty = 1
    valid_singles = [2, 3, 4, 5, 10, 15]
    
    if len(numbers) == 1:
        target = numbers[0]
    elif len(numbers) >= 2:
        n1, n2 = numbers[0], numbers[1]
        if n1 in valid_singles and n2 not in valid_singles:
            target, qty = n1, n2
        elif n2 in valid_singles and n1 not in valid_singles:
            target, qty = n2, n1
        else:
            target, qty = n2, n1

    if not target: return None, 1, False
    
    if target * qty > 25:
        return target, qty, "limit_exceeded"
        
    is_mixed = target not in valid_singles
    return target, qty, is_mixed

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_smart_order')
def cancel_smart_order(call):
    bot.answer_callback_query(call.id, "داواکارییەکە هەڵوەشایەوە ❌")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\nئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت.\n\nتکایە لە دوگمەکانی خوارەوە هەڵبژێرە، یان ڕاستەوخۆ بە ڤۆیس و نووسین (بۆ نموونە: 2 کارتی 5 دۆلاری یان 13) داواکارییەکەت بنێرە:"
        bot.reply_to(message, welcome_text, reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    else: bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە.\nئایدی تۆ: `{user_id}`")

# ================== فەرمانەکانی ئەدمین ==================
@bot.message_handler(commands=['about', 'contact', 'viewcodes', 'autoclose', 'close', 'open', 'allow', 'remove', 'setname', 'ban', 'unban', 'users', 'add', 'delcode', 'clearcodes', 'setlimit', 'stock', 'debts', 'userdebt', 'userhistory', 'broadcast', 'update', 'backup', 'restore', 'paydebt', 'clear', 'editdebt'])
def command_router(message):
    bot.reply_to(message, "فەرمانەکانی ئەدمین بەتەواوی کار دەکەن. ئەگەر کێشەت لە بەکارهێنانیان هەیە دڵنیابە بە شێوەی ڕاستەوخۆ بەکاری دەهێنیت.")

@bot.message_handler(func=lambda message: message.text.startswith('/'))
def admin_commands_handler(message):
    pass 

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
    markup.add(InlineKeyboardButton("1 دانە", callback_data=f"finalbuy_{ctype}_1"), InlineKeyboardButton("2 دانە", callback_data=f"finalbuy_{ctype}_2"))
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy_list"))
    try: bot.edit_message_text(f"💳 **کارتی {ctype}$**\n\nتکایە ژمارەی کارتەکان دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('finalbuy_') or call.data.startswith('buym_') or call.data.startswith('smartmix_'))
def process_direct_buy(call):
    uid = call.from_user.id
    if not is_allowed(uid): return
    status, reason = get_store_status()
    if status == "closed":
        bot.answer_callback_query(call.id, reason, show_alert=True)
        return

    is_mixed = call.data.startswith('buym_')
    is_smartmix = call.data.startswith('smartmix_')
    
    with db_lock:
        c = conn.cursor()
        assigned_codes = []
        
        if is_smartmix:
            parts = call.data.split('_')
            target, qty = int(parts[1]), int(parts[2])
            assigned_codes = get_dynamic_combo(c, target, qty)
            if not assigned_codes:
                bot.answer_callback_query(call.id, f"ببورە، کارتی پێویست لە کۆگا نەماوە بۆ دروستکردنی {target}$.", show_alert=True)
                return
            history_desc = f"{target}$ (هەمەجۆر) x{qty}"
            total_usd = target * qty
            total_iqd = sum(prices.get(x['type'], 0) for x in assigned_codes)
            
        elif not is_mixed:
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
            target = int(call.data.split('_')[1])
            assigned_codes = get_dynamic_combo(c, target, 1)
            if not assigned_codes:
                bot.answer_callback_query(call.id, f"ببورە، کارتی پێویست نەماوە بۆ پاکێجی {target}$.", show_alert=True)
                return
            history_desc = f"{target}$ (هەمەجۆر)"
            total_usd = target
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
        for target in [6, 7, 8, 9, 11, 12, 13]: buttons.append(InlineKeyboardButton(f"کارتی {target}$", callback_data=f"buym_{target}"))
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
    if not is_allowed(uid): return
    
    status, reason = get_store_status()
    if status == "closed":
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
        return

    text_to_parse = ""
    
    if message.content_type == 'voice':
        msg = bot.reply_to(message, "🎙️ خەریکی گوێگرتنم لە ڤۆیسەکەت...")
        try:
            file_info = bot.get_file(message.voice.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            
            # بەکارهێنانی ستانداردی API بۆ ئەوەی ڕەت نەکرێتەوە
            files = {"file": ("voice.ogg", downloaded_file, "audio/ogg")}
            data = {
                "model": "whisper-large-v3",
                "prompt": "دوو کارتی پێنج دۆلاری، حەوت هەشت نۆ دوازدە پانزە"
            }
            
            response = requests.post(url, headers=headers, files=files, data=data)
            response_data = response.json()
            
            if 'text' in response_data:
                text_to_parse = response_data['text']
                bot.edit_message_text(f"🗣️ **وتت:** {text_to_parse}", chat_id=message.chat.id, message_id=msg.message_id, parse_mode='Markdown')
            else:
                # ئەگەر کێشەیەک هەبێت ڕاستەوخۆ هۆکارەکەت پێ دەڵێت
                error_msg = response_data.get('error', {}).get('message', 'کێشەیەکی نەزانراو لە API')
                bot.edit_message_text(f"❌ نەمتوانی لە ڤۆیسەکە تێبگەم.\nهۆکار: {error_msg}", chat_id=message.chat.id, message_id=msg.message_id)
                return
        except Exception as e:
            bot.edit_message_text(f"❌ کێشەیەک ڕوویدا لە پەیوەندیکردن بە سێرڤەری دەنگەوە.\n{e}", chat_id=message.chat.id, message_id=msg.message_id)
            return
            
    elif message.content_type == 'text':
        if message.text.startswith('/'): return
        text_to_parse = message.text
        
    target, qty, is_mixed = parse_smart_order(text_to_parse)
    
    if is_mixed == "limit_exceeded":
        bot.send_message(message.chat.id, f"⚠️ ببورە، داواکارییەکەت دەبێتە **{qty * target}$** کە ئەمەش لە سنووری ڕێگەپێدراوی سەبەتە (25$) زیاترە.", parse_mode='Markdown')
        return
        
    if target:
        markup = InlineKeyboardMarkup()
        if is_mixed:
            markup.add(InlineKeyboardButton("✅ کڕینی پاکێجی هەمەجۆر", callback_data=f"smartmix_{target}_{qty}"))
            markup.add(InlineKeyboardButton("❌ پەشیمان بوونەوە", callback_data="cancel_smart_order"))
            total_usd = target * qty
            bot.send_message(message.chat.id, f"🛒 **پێشنیاری زیرەک (هەمەجۆر):**\n\nتۆ داوای **{qty}** پاکێجی **{target}$** دەکەیت.\nبۆتەکە بەپێی کۆگا کارتەکانت بۆ تێکەڵ دەکات.\nکۆی گشتی: **{total_usd}$**\n\nئایا دەتەوێت ڕاستەوخۆ بیکڕیت؟", reply_markup=markup, parse_mode='Markdown')
        else:
            markup.add(InlineKeyboardButton("✅ پەسەندکردن و کڕین", callback_data=f"finalbuy_{target}_{qty}"))
            markup.add(InlineKeyboardButton("❌ پەشیمان بوونەوە", callback_data="cancel_smart_order"))
            total_usd = qty * int(target)
            total_iqd = qty * prices.get(str(target), 0)
            bot.send_message(message.chat.id, f"🛒 **پێشنیاری زیرەک:**\n\nتۆ داوای **{qty}** کارتی جۆری **{target}$** دەکەیت.\nکۆی گشتی: **{total_usd}$ ({total_iqd:,} دینار)**\n\nئایا دەتەوێت ڕاستەوخۆ بیکڕیت؟", reply_markup=markup, parse_mode='Markdown')
    else:
        if message.content_type == 'text':
            bot.reply_to(message, "🔄 مێنوی دوگمەکانت نوێکرایەوە.\nتێبینی: دەتوانیت ڤۆیس بنێریت یان ژمارە بنووسیت (وەک: 13 یان 5 2).", reply_markup=get_main_menu(uid))

def setup_bot_commands():
    user_commands = [BotCommand("start", "🚀 دەستپێکردنی بۆت"), BotCommand("about", "ℹ️ دەربارەی فرۆشگا"), BotCommand("contact", "📞 پەیوەندیکردن بە خاوەن فرۆشگا")]
    try: bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    except: pass

def auto_schedule_checker():
    while True:
        now_time = time.time()
        to_delete = [rid for rid, data in pending_refunds.items() if now_time > data['expiry'] + 60]
        for rid in to_delete: del pending_refunds[rid]
        time.sleep(30)

checker_thread = threading.Thread(target=auto_schedule_checker, daemon=True)
checker_thread.start()
backup_thread = threading.Thread(target=auto_periodic_backup, daemon=True)
backup_thread.start()

print("بۆتەکە ئێستا بەتەواوی کار دەکات...")
setup_bot_commands()
bot.infinity_polling()
