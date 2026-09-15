import telebot
import sqlite3
import threading
import datetime
import time
import os
import re
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault

TOKEN = '8781704084:AAHCCyZ79ud30w3z0sMF9hxpLme4izV6DMA'
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
        
        # زیادکردنی ستوونی جزدان ئەگەر پێشتر نەبووبێت
        try:
            c.execute('ALTER TABLE debts ADD COLUMN wallet_iqd INTEGER DEFAULT 0')
        except:
            pass
            
        conn.commit()

init_db()

prices = {'2': 3000, '3': 4500, '4': 6000, '5': 7000, '10': 14000, '15': 22000}

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
                available = False; break
            for row in res:
                assigned.append({'id': row[0], 'code': row[1], 'type': t_str})
        if available: return assigned
    return None

def is_allowed(user_id):
    if user_id == ADMIN_ID: return True
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id FROM allowed_users WHERE user_id = ?', (user_id,))
        return c.fetchone() is not None

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
    markup.add(KeyboardButton("💰 قەرزەکانم"), KeyboardButton("👛 جزدانەکەم"))
    markup.add(KeyboardButton("📜 مێژووی کڕینەکان"), KeyboardButton("📦 ئاماری کۆگا"))
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
    kurdish_nums = {'١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9','٠':'0'}
    for k, v in kurdish_nums.items(): text = text.replace(k, v)
    text = text.replace('دوو', '2').replace('یەک', '1').replace('سێ', '3').replace('چوار', '4').replace('پێنج', '5').replace('شەش', '6').replace('حەوت', '7').replace('هەشت', '8').replace('نۆ', '9').replace('دە', '10').replace('پانزە', '15')
    
    numbers = [int(n) for n in re.findall(r'\d+', text)]
    if not numbers: return None, 1, False
    numbers = [n for n in numbers if n <= 25]
    if not numbers: return None, 1, False
    
    target, qty = None, 1
    valid_singles = [2, 3, 4, 5, 10, 15]
    
    if len(numbers) == 1: target = numbers[0]
    elif len(numbers) >= 2:
        n1, n2 = numbers[0], numbers[1]
        if n1 in valid_singles and n2 not in valid_singles: target, qty = n1, n2
        elif n2 in valid_singles and n1 not in valid_singles: target, qty = n2, n1
        else: target, qty = n2, n1

    if not target: return None, 1, False
    if target * qty > 25: return target, qty, "limit_exceeded"
    is_mixed = target not in valid_singles
    return target, qty, is_mixed

# ئامادەکردنی دوگمەکانی کڕین بەپێی باڵانسی جزدان
def get_purchase_markup(uid, target, qty, total_iqd, is_mixed=False):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT wallet_iqd FROM debts WHERE user_id = ?', (uid,))
        res = c.fetchone()
        wallet_bal = res[0] if res else 0

    markup = InlineKeyboardMarkup(row_width=1)
    prefix = "smartmix" if is_mixed else "finalbuy"
    w_prefix = "wbuy_mix" if is_mixed else "wbuy_std"
    
    if wallet_bal > 0:
        if wallet_bal >= total_iqd:
            markup.add(InlineKeyboardButton(f"👛 کڕین بە جزدان (لێبڕینی {total_iqd:,} د)", callback_data=f"{w_prefix}_{target}_{qty}"))
        else:
            remaining_debt = total_iqd - wallet_bal
            markup.add(InlineKeyboardButton(f"👛 بەکارهێنانی جزدان ({wallet_bal:,} د) + قەرز ({remaining_debt:,} د)", callback_data=f"{w_prefix}_{target}_{qty}"))
            
        markup.add(InlineKeyboardButton(f"📒 نەخێر، هەمووی بخەرە سەر قەرز", callback_data=f"{prefix}_{target}_{qty}"))
    else:
        markup.add(InlineKeyboardButton("✅ پەسەندکردن و کڕین (بە قەرز)", callback_data=f"{prefix}_{target}_{qty}"))
        
    markup.add(InlineKeyboardButton("❌ پەشیمان بوونەوە", callback_data="cancel_smart_order"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_smart_order')
def cancel_smart_order(call):
    bot.answer_callback_query(call.id, "داواکارییەکە هەڵوەشایەوە ❌")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\nئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت.\n\nتکایە لە دوگمەکانی خوارەوە هەڵبژێرە، یان ڕاستەوخۆ بە نووسین (بۆ نموونە: 2 کارتی 5 یان 13) داواکارییەکەت بنێرە:"
        bot.reply_to(message, welcome_text, reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    else: bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە.\nئایدی تۆ: `{user_id}`")

# ================== فەرمانەکانی ئەدمین ==================
@bot.message_handler(commands=['about'])
def about_store(message):
    if is_allowed(message.from_user.id): bot.reply_to(message, "🍏 **دەربارەی فرۆشگای ئایتونس**", parse_mode='Markdown')

@bot.message_handler(commands=['contact'])
def contact_admin(message):
    if is_allowed(message.from_user.id):
        msg = bot.reply_to(message, "تکایە نامەکەت بنووسە، ڕاستەوخۆ دەگاتە هیلال:")
        bot.register_next_step_handler(msg, forward_to_admin)

def forward_to_admin(message):
    try: bot.send_message(ADMIN_ID, f"📩 **نامەی نوێ:**\nناو: {message.from_user.first_name}\nئایدی: `{message.from_user.id}`\n\n{message.text}", parse_mode='Markdown')
    except: pass
    bot.reply_to(message, "نامەکەت نێردرا. ✅")

@bot.message_handler(commands=['close'])
def close_store(message):
    if message.chat.id == ADMIN_ID:
        reason = message.text.replace('/close', '').strip()
        if not reason: reason = "لە ئێستادا فرۆشگا داخراوە."
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("closed",))
            c.execute('UPDATE settings SET value=? WHERE key="close_reason"', (reason,))
            conn.commit()
        bot.reply_to(message, "🔒 فرۆشگا داخرا.")
        auto_send_backup()

@bot.message_handler(commands=['open'])
def open_store(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("open",))
            conn.commit()
        bot.reply_to(message, "🔓 فرۆشگا کرایەوە.")

@bot.message_handler(commands=['allow'])
def allow_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            new_uid = int(parts[1])
            name = parts[2] if len(parts) > 2 else "نەناسراو"
            with db_lock:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO allowed_users (user_id, name) VALUES (?, ?)', (new_uid, name))
                c.execute('INSERT OR IGNORE INTO debts (user_id, usd, iqd, credit_limit, wallet_iqd) VALUES (?, 0, 0, 25, 0)', (new_uid,))
                conn.commit()
            bot.reply_to(message, f"کڕیار {new_uid} ڕێگەی پێدرا.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /allow 123 ناو")
        
@bot.message_handler(commands=['remove'])
def remove_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            tid = int(message.text.replace('/remove ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM allowed_users WHERE user_id = ?', (tid,))
                conn.commit()
            bot.reply_to(message, f"کڕیار {tid} لادرا.")
        except: pass

@bot.message_handler(commands=['users'])
def list_users(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT user_id, name FROM allowed_users')
            users = c.fetchall()
        if users:
            msg = "👥 **لیستی کڕیاران:**\n\n"
            for uid, name in users: msg += f"👤 {name} | `{uid}`\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "بەکارهێنەر نییە.")

@bot.message_handler(commands=['add'])
def add_codes(message):
    if message.chat.id == ADMIN_ID:
        try:
            lines = message.text.split('\n')
            ctype = lines[0].split()[1]
            codes = [lines[0].split(' ', 2)[2]] if len(lines[0].split()) > 2 else []
            codes += [l.strip() for l in lines[1:] if l.strip()]
            with db_lock:
                c = conn.cursor()
                for cd in codes: c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (ctype, cd))
                conn.commit()
            bot.reply_to(message, f"بڕی {len(codes)} کۆدی {ctype}$ زیادکرا.")
        except: bot.reply_to(message, "شێواز: /add 2 XXXXX")

@bot.message_handler(commands=['clearcodes'])
def clear_codes(message):
    if message.chat.id == ADMIN_ID:
        try:
            target = message.text.replace('/clearcodes ', '').strip()
            with db_lock:
                c = conn.cursor()
                if target.lower() == 'all': c.execute('DELETE FROM codes')
                else: c.execute('DELETE FROM codes WHERE card_type = ?', (target,))
                conn.commit()
            bot.reply_to(message, f"🗑️ کۆدەکانی {target} سڕانەوە.")
        except: pass

@bot.message_handler(commands=['setlimit'])
def set_limit(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            tid, nlimit = int(parts[1]), int(parts[2])
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE debts SET credit_limit = ? WHERE user_id = ?', (nlimit, tid))
                conn.commit()
            bot.reply_to(message, f"سنووری {tid} کرا بە {nlimit}$.")
        except: pass

@bot.message_handler(commands=['stock'])
def check_stock(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            msg = "📊 **ئاماری کۆگا:**\n\n"
            for ctype, count in results: msg += f"کارتی {ctype}$ : **{count}** دانە\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "کۆگا بەتاڵە.")

@bot.message_handler(commands=['debts'])
def check_all_debts(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT d.user_id, d.usd, d.iqd, d.wallet_iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0 OR d.wallet_iqd > 0')
            results = c.fetchall()
        if results:
            msg = "📒 **دەفتەری قەرز و جزدانەکان:**\n\n"
            tot_usd, tot_iqd = 0, 0
            for uid, usd, iqd, wallet, name in results:
                wallet_txt = f"\n👛 جزدان: {wallet:,} د" if wallet > 0 else ""
                debt_txt = f"\n💸 قەرز: {usd}$ ({iqd:,} د)" if usd > 0 else ""
                msg += f"👤 **{name}** | `{uid}`{debt_txt}{wallet_txt}\n\n"
                tot_usd += usd; tot_iqd += iqd
            msg += f"💰 **کۆی گشتی قەرزەکانی دەرەوە:** {tot_usd}$ ({tot_iqd:,} دینار)"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "هیچ قەرزێک یان جزدانێکی پڕ نییە.")

@bot.message_handler(commands=['clear'])
def clear_debt(message):
    if message.chat.id == ADMIN_ID:
        try:
            tid = message.text.replace('/clear', '').strip()
            with db_lock:
                c = conn.cursor()
                if tid.lower() == 'all': c.execute('UPDATE debts SET usd = 0, iqd = 0')
                else: c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (int(tid),))
                conn.commit()
            bot.reply_to(message, "✅ قەرزەکان سفر کرانەوە (پارەی جزدانەکان پارێزراوە).")
        except: bot.reply_to(message, "شێواز: /clear ID یان /clear all")

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if message.chat.id == ADMIN_ID:
        try:
            with open(DB_PATH, 'rb') as doc: bot.send_document(message.chat.id, doc, caption="💾 داتابەیس")
        except Exception as e: bot.reply_to(message, f"کێشە: {e}")

@bot.message_handler(commands=['restore'])
def restore_instructions(message):
    if message.chat.id == ADMIN_ID: bot.reply_to(message, "تەنها فایلی `itunes_store_v5.db` بنێرە بۆ گەڕاندنەوە.")

@bot.message_handler(content_types=['document'])
def handle_database_restore(message):
    global conn
    if message.chat.id == ADMIN_ID and message.document.file_name.endswith('.db'):
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with db_lock:
                conn.close()
                with open(DB_PATH, 'wb') as new_file: new_file.write(downloaded_file)
                conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            bot.reply_to(message, "✅ داتابەیس گەڕێندرایەوە.")
        except: bot.reply_to(message, "❌ کێشە ڕوویدا.")

# ================== بەشی جزدان (Wallet) ==================
@bot.callback_query_handler(func=lambda call: call.data == 'add_wallet_req')
def add_wallet_req(call):
    msg = bot.send_message(call.message.chat.id, "💳 **پڕکردنەوەی جزدان**\n\nتکایە ئەو بڕە پارەیە بنووسە کە دەتەوێت بیخەیتە جزدانەکەتەوە (تەنها ژمارە بنووسە، بۆ نموونە: 3000):")
    bot.register_next_step_handler(msg, process_wallet_req)

def process_wallet_req(message):
    try:
        amount = int(message.text.strip())
        if amount <= 0: raise ValueError
    except:
        bot.reply_to(message, "❌ بڕەکە نادروستە، تکایە تەنها ژمارە بنووسە.")
        return
        
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ وەرگرە (پەسەندکردن)", callback_data=f"approve_w_{message.from_user.id}_{amount}"),
        InlineKeyboardButton("❌ وەر مەگرە", callback_data=f"reject_w_{message.from_user.id}")
    )
    
    bot.send_message(ADMIN_ID, f"📥 **داواکاری پڕکردنەوەی جزدان:**\n\nکڕیار: {message.from_user.first_name} (`{message.from_user.id}`)\nبڕی داواکراو: **{amount:,} دینار**", reply_markup=markup, parse_mode='Markdown')
    bot.reply_to(message, f"⏳ داواکارییەکەت بۆ بڕی **{amount:,} دینار** نێردرا بۆ ئەدمین. چاوەڕێی پەسەندکردن بە.", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_w_'))
def approve_wallet(call):
    if call.from_user.id != ADMIN_ID: return
    target_uid = int(call.data.split('_')[2])
    amount = int(call.data.split('_')[3])
    
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET wallet_iqd = wallet_iqd + ? WHERE user_id = ?', (amount, target_uid))
        conn.commit()
        
    bot.edit_message_text(f"{call.message.text}\n\n✅ **پەسەند کرا و خرایە جزدانییەوە.**", chat_id=call.message.chat.id, message_id=call.message.message_id)
    try: bot.send_message(target_uid, f"🎉 پیرۆزە! بڕی **{amount:,} دینار** بە سەرکەوتوویی خرایە ناو جزدانەکەتەوە.", parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_w_'))
def reject_wallet(call):
    if call.from_user.id != ADMIN_ID: return
    target_uid = int(call.data.split('_')[2])
    bot.edit_message_text(f"{call.message.text}\n\n❌ **ڕەتکرایەوە.**", chat_id=call.message.chat.id, message_id=call.message.message_id)
    try: bot.send_message(target_uid, "❌ داواکاری پڕکردنەوەی جزدانەکەت ڕەتکرایەوە لەلایەن خاوەن فرۆشگاوە.")
    except: pass

# ================== بەشی کڕین و سەبەتە ==================
def check_and_alert_low_stock(c, types_sold):
    for ct in set(types_sold):
        c.execute('SELECT COUNT(*) FROM codes WHERE card_type = ?', (ct,))
        if c.fetchone()[0] <= 2:
            try: bot.send_message(ADMIN_ID, f"⚠️ کارتی **{ct}$** زۆر کەمە لە کۆگا!", parse_mode='Markdown')
            except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_buy_list')
def back_to_buy_list(call):
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(f"{ctype}$ - {price:,} د", callback_data=f"buys_{ctype}") for ctype, price in prices.items()]
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    try: bot.edit_message_text("💳 **کڕینی کارت:**", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('buys_'))
def handle_qty_selection(call):
    ctype = call.data.split('_')[1]
    markup = InlineKeyboardMarkup(row_width=2)
    # دوگمەکان دەگۆڕین بۆ ئەوەی ڕاستەوخۆ بچێتە سیستەمی لێکدانەوەی جزدان پێش کڕین
    markup.add(InlineKeyboardButton("1 دانە", callback_data=f"paymethod_std_{ctype}_1"), InlineKeyboardButton("2 دانە", callback_data=f"paymethod_std_{ctype}_2"))
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy_list"))
    try: bot.edit_message_text(f"💳 **کارتی {ctype}$**\nژمارە دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('paymethod_'))
def handle_payment_method(call):
    parts = call.data.split('_')
    is_mixed = parts[1] == 'mix'
    target = int(parts[2]) if is_mixed else parts[2]
    qty = int(parts[3])
    
    total_iqd = 0
    if is_mixed:
        with db_lock:
            assigned = get_dynamic_combo(conn.cursor(), target, qty)
            if not assigned:
                bot.answer_callback_query(call.id, "ببورە، کارتی پێویست لە کۆگا نەماوە.", show_alert=True)
                return
            total_iqd = sum(prices.get(x['type'], 0) for x in assigned)
    else:
        total_iqd = qty * prices.get(str(target), 0)
        
    markup = get_purchase_markup(call.from_user.id, target, qty, total_iqd, is_mixed)
    try: bot.edit_message_text(f"🛒 **دووپاتکردنەوەی کڕین:**\n\nکۆی نرخەکە: **{total_iqd:,} دینار**.\nتکایە شێوازی پارەدان هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('finalbuy_') or call.data.startswith('buym_') or call.data.startswith('smartmix_') or call.data.startswith('wbuy_'))
def process_direct_buy(call):
    uid = call.from_user.id
    if not is_allowed(uid): return
    status, reason = get_store_status()
    if status == "closed":
        bot.answer_callback_query(call.id, reason, show_alert=True)
        return

    is_mixed = 'mix' in call.data or 'buym_' in call.data
    use_wallet = call.data.startswith('wbuy_')
    
    with db_lock:
        c = conn.cursor()
        assigned_codes = []
        
        # گرتنی داواکارییە هەمەجۆرەکان (وەک کارتی ١٣) کە یەکسەر لە مێنووەوە دێن
        if call.data.startswith('buym_'):
            target = int(call.data.split('_')[1])
            qty = 1
            assigned_codes = get_dynamic_combo(c, target, qty)
            if not assigned_codes:
                bot.answer_callback_query(call.id, "ببورە، کارتی پێویست نەماوە.", show_alert=True)
                return
            # ڕەوانەکردنی بۆ بەشی هەڵبژاردنی پارەدان لەبری ئەوەی یەکسەر بیکڕێت
            total_iqd = sum(prices.get(x['type'], 0) for x in assigned_codes)
            markup = get_purchase_markup(uid, target, qty, total_iqd, is_mixed=True)
            try: bot.edit_message_text(f"🛒 **دووپاتکردنەوەی کڕین:**\n\nکۆی نرخەکە: **{total_iqd:,} دینار**.\nتکایە شێوازی پارەدان هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
            except: pass
            return

        if is_mixed:
            parts = call.data.split('_')
            target, qty = int(parts[2]), int(parts[3])
            assigned_codes = get_dynamic_combo(c, target, qty)
            if not assigned_codes:
                bot.answer_callback_query(call.id, f"ببورە، کارتی پێویست لە کۆگا نەماوە.", show_alert=True)
                return
            history_desc = f"{target}$ (هەمەجۆر) x{qty}"
            total_usd = target * qty
            total_iqd = sum(prices.get(x['type'], 0) for x in assigned_codes)
        else:
            parts = call.data.split('_')
            target, qty = parts[2], int(parts[3])
            c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT ?', (target, qty))
            res = c.fetchall()
            if len(res) < qty:
                bot.answer_callback_query(call.id, f"ببورە، تەنها {len(res)} ماوە.", show_alert=True)
                return
            for r in res: assigned_codes.append({'id': r[0], 'code': r[1], 'type': target})
            history_desc = f"{target}$ (x{qty})"
            total_usd = int(target) * qty
            total_iqd = prices.get(target, 0) * qty

        c.execute('SELECT usd, iqd, credit_limit, wallet_iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        d_res = c.fetchone()
        current_debt_usd, current_debt_iqd, limit, wallet_iqd, db_user_name = d_res if d_res else (0, 0, 25, 0, call.from_user.first_name)

        usd_to_add = total_usd
        iqd_to_add = total_iqd
        wallet_deducted = 0

        # لێکدانەوەی پارەی جزدان
        if use_wallet and wallet_iqd > 0:
            if wallet_iqd >= total_iqd:
                wallet_deducted = total_iqd
                iqd_to_add = 0
                usd_to_add = 0
                c.execute('UPDATE debts SET wallet_iqd = wallet_iqd - ? WHERE user_id = ?', (total_iqd, uid))
            else:
                wallet_deducted = wallet_iqd
                iqd_to_add = total_iqd - wallet_iqd
                # خەمڵاندنی دۆلارەکە بۆ ئەوەی بەشێکی لەسەر قەرز بمێنێت
                usd_to_add = round(total_usd * (iqd_to_add / total_iqd))
                c.execute('UPDATE debts SET wallet_iqd = 0 WHERE user_id = ?', (uid,))

        if current_debt_usd + usd_to_add > limit:
            bot.answer_callback_query(call.id, f"گەیشتووی بە سنووری قەرز ({limit}$).", show_alert=True)
            return

        types_sold, code_texts, refund_data_codes = [], [], []
        for item in assigned_codes:
            c.execute('DELETE FROM codes WHERE id = ?', (item['id'],))
            code_texts.append(f"▫️ کارتی {item['type']}$: `{item['code']}`")
            refund_data_codes.append((item['id'], item['code'], item['type']))
            types_sold.append(item['type'])

        c.execute('UPDATE debts SET usd = usd + ?, iqd = iqd + ? WHERE user_id = ?', (usd_to_add, iqd_to_add, uid))
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, history_desc, total_iqd, "\n".join(code_texts)))
        check_and_alert_low_stock(c, types_sold)
        conn.commit()

    wallet_receipt_text = f"\n👛 **لە جزدان بڕدرا:** {wallet_deducted:,} دینار" if wallet_deducted > 0 else ""
    debt_receipt_text = f"\n💸 **چووە سەر قەرز:** {usd_to_add}$ ({iqd_to_add:,} د)" if iqd_to_add > 0 else "\n💸 **چووە سەر قەرز:** 0 (بە جزدان درا)"

    receipt = (
        "🧾 **پسوڵەی کڕین (ڕەسمی)**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **کڕیار:** {db_user_name}\n📅 **بەروار:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 **جۆر:** {history_desc}\n💰 **نرخی گشتی:** {total_usd}$ ({total_iqd:,} د){wallet_receipt_text}{debt_receipt_text}\n📊 **قەرزی نوێ:** {current_debt_usd + usd_to_add}$ (لە {limit}$)\n━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 **کۆدەکان:**\n\n"
    )
    receipt += "\n".join([f"▫️ کارتی {x['type']}$: `{x['code']}`" for x in assigned_codes]) + "\n\nزۆر سوپاس بۆ متمانەت! 🍏 هیلال"

    bot.answer_callback_query(call.id, "کڕینەکەت سەرکەوتوو بوو! ✅")
    
    receipt_id = str(int(time.time())) + "_" + str(uid)
    pending_refunds[receipt_id] = {
        'uid': uid, 'codes': refund_data_codes, 'usd_added': usd_to_add, 'iqd_added': iqd_to_add, 'wallet_deducted': wallet_deducted,
        'expiry': time.time() + 30, 'history_desc': history_desc, 'db_user_name': db_user_name
    }
    
    refund_markup = InlineKeyboardMarkup()
    refund_markup.add(InlineKeyboardButton("↩️ گەڕاندنەوەی کارت (٣٠ چرکە)", callback_data=f"refund_{receipt_id}"))
    try: bot.edit_message_text(receipt, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=refund_markup)
    except: pass

    if uid != ADMIN_ID:
        try: bot.send_message(ADMIN_ID, f"🔔 **فرۆشتنی نوێ:**\n\n{receipt}", parse_mode='Markdown')
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
        
    uid, codes_to_return, usd_added, iqd_added, wallet_deducted, desc, u_name = refund_data['uid'], refund_data['codes'], refund_data['usd_added'], refund_data['iqd_added'], refund_data['wallet_deducted'], refund_data['history_desc'], refund_data['db_user_name']
    
    with db_lock:
        c = conn.cursor()
        for cid, code, ctype in codes_to_return:
            c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (ctype, code))
        # لێرەدا هەم قەرزەکان کەمدەکەینەوە هەم پارەکەی جزدانی بۆ دەگەڕێنینەوە!
        c.execute('UPDATE debts SET usd = usd - ?, iqd = iqd - ?, wallet_iqd = wallet_iqd + ? WHERE user_id = ?', (usd_added, iqd_added, wallet_deducted, uid))
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, f"گەڕاندنەوە: {desc}", -(iqd_added + wallet_deducted), "گەڕێندرانەوە ناو کۆگا"))
        conn.commit()
        
    del pending_refunds[receipt_id]
    bot.answer_callback_query(call.id, "گەڕێندرایەوە! ✅", show_alert=True)
    new_text = f"🧾 **پسوڵەی هەڵوەشاوە** ❌\n━━━━━━━━━━━━━━━━━━━━\nکڕیار: {u_name}\nبڕی گەڕێندراو: {desc}\nپارەی سڕاوە لە قەرز: {usd_added}$ ({iqd_added:,} دینار)\nپارەی گەڕێندراو بۆ جزدان: {wallet_deducted:,} دینار\n━━━━━━━━━━━━━━━━━━━━\n🔒 **کۆدەکان گەڕێندرانەوە.**"
    try: bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    except: pass

    if uid != ADMIN_ID:
        try: bot.send_message(ADMIN_ID, f"↩️ **گەڕاندنەوەی کارت:**\n\nکڕیار ({u_name}) پەشیمان بووەوە و کارتی {desc} ی گەڕاندەوە ناو کۆگا.", parse_mode='Markdown')
        except: pass

@bot.message_handler(func=lambda message: message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە", "🔀 کارتی ئایتونسی زیاتر", "💰 قەرزەکانم", "📜 مێژووی کڕینەکان", "📦 ئاماری کۆگا", "✅ قەرزەکەم داوەتەوە", "👛 جزدانەکەم"])
def handle_text_buttons(message):
    uid = message.from_user.id
    if not is_allowed(uid): return

    status, reason = get_store_status()
    if status == "closed" and "کڕین" in message.text:
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
        return

    if message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە"]:
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = [InlineKeyboardButton(f"{ctype}$ - {price:,} د", callback_data=f"buys_{ctype}") for ctype, price in prices.items()]
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "💳 **کڕینی کارت**\nتکایە جۆری کارت هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "🔀 کارتی ئایتونسی زیاتر":
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = [InlineKeyboardButton(f"کارتی {target}$", callback_data=f"buym_{target}") for target in [6, 7, 8, 9, 11, 12, 13]]
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "🔀 **کڕینی کارتی زیاتر (پاکێج)**\nتکایە بڕەکە هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "👛 جزدانەکەم":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT wallet_iqd FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
            wallet_bal = res[0] if res else 0
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➕ پڕکردنەوەی جزدان", callback_data="add_wallet_req"))
        bot.reply_to(message, f"👛 **جزدانەکەی تۆ:**\n\nبڕی بەردەست: **{wallet_bal:,} دينار**\n\nدەتوانیت پارە حەواڵە بکەیت و بیخەیتە ناو جزدانەکەتەوە بۆ ئەوەی کڕینەکانت خێراتر بێت و نەچێتە سەر قەرزەکانت.", reply_markup=markup, parse_mode='Markdown')

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
            for ctype, prc, cd, dt in hist: msg += f"💳 کارتی {ctype} | {abs(prc):,} د\n{cd}\nبەروار: {dt}\n------------------\n"
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
        bot.reply_to(message, "⏳ داواکارییەکەت نێردرا بۆ خاوەن فرۆشگا.")

@bot.message_handler(content_types=['text', 'voice'])
def smart_order_and_fallback(message):
    uid = message.from_user.id
    if not is_allowed(uid): return
    
    status, reason = get_store_status()
    if status == "closed":
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
        return

    if message.content_type == 'voice':
        bot.reply_to(message, "🎙️ ببورە، تایبەتمەندی ڤۆیس لە ئێستادا ڕاگیراوە. تکایە بە نووسین داواکارییەکەت بنێرە (بۆ نموونە بنووسە: 13 یان 2 دانە 5).")
        return

    if message.text.startswith('/'): return
    text_to_parse = message.text
        
    target, qty, is_mixed = parse_smart_order(text_to_parse)
    
    if is_mixed == "limit_exceeded":
        bot.send_message(message.chat.id, f"⚠️ ببورە، داواکارییەکەت دەبێتە **{qty * target}$** کە ئەمەش لە سنووری ڕێگەپێدراوی سەبەتە (25$) زیاترە.", parse_mode='Markdown')
        return
        
    if target:
        total_iqd = 0
        if is_mixed:
            with db_lock:
                assigned = get_dynamic_combo(conn.cursor(), target, qty)
                if not assigned:
                    bot.send_message(message.chat.id, "ببورە، کارتی پێویست لە کۆگا نەماوە.")
                    return
                total_iqd = sum(prices.get(x['type'], 0) for x in assigned)
        else:
            total_iqd = qty * prices.get(str(target), 0)
            
        markup = get_purchase_markup(uid, target, qty, total_iqd, is_mixed)
        bot.send_message(message.chat.id, f"🛒 **پێشنیاری زیرەک:**\n\nتۆ داوای **{qty}** داواکاری جۆری **{target}$** دەکەیت.\nکۆی گشتی: **{total_iqd:,} دینار**\n\nتکایە شێوازی پارەدان هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')
    else:
        bot.reply_to(message, "🔄 مێنوی دوگمەکانت نوێکرایەوە.\nتێبینی: دەتوانیت ڕاستەوخۆ ژمارە بنووسیت (وەک: 13 یان 5 2).", reply_markup=get_main_menu(uid))

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

print("بۆتەکە ئێستا بەتەواوی کار دەکات و سیستەمی جزدانی تێدایە...")
setup_bot_commands()
bot.infinity_polling()
