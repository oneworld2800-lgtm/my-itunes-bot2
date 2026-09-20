import telebot
import sqlite3
import threading
import datetime
import time
import os
import re
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat

TOKEN = '8781704084:AAHCCyZ79ud30w3z0sMF9hxpLme4izV6DMA'
ADMIN_ID = 1229224919

bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()

DB_PATH = '/app/data/itunes_store_v5.db'
os.makedirs('/app/data', exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
db_lock = threading.Lock()
pending_refunds = {}

def escape_md(text):
    if not text: return "نەناسراو"
    return str(text).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')

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
    if str(user_id) == str(ADMIN_ID): return True
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
    markup.add(KeyboardButton("🛒 کڕینی کارت"), KeyboardButton("🔀 ئایتونسی جیاواز"))
    markup.add(KeyboardButton("💰 قەرزەکانم"), KeyboardButton("👛 جزدانەکەم"))
    markup.add(KeyboardButton("📜 مێژووی کڕینەکان"), KeyboardButton("📦 ئاماری کۆگا"))
    markup.add(KeyboardButton("✅ قەرزەکەم داوەتەوە")) 
    return markup

def auto_periodic_backup():
    while True:
        time.sleep(43200)
        try:
            with open(DB_PATH, 'rb') as doc: bot.send_document(ADMIN_ID, doc, caption="⏱️ **باکئەپی ١٢ کاتژمێری**", parse_mode='Markdown')
        except Exception: pass

@bot.message_handler(commands=['myid'])
def check_my_id(message):
    bot.reply_to(message, f"ئایدی تۆ بریتییە لە: `{message.from_user.id}`\nئایدی ئەدمین بریتییە لە: `{ADMIN_ID}`", parse_mode='Markdown')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\nئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت.\n\nتکایە لە دوگمەکانی خوارەوە داواکارییەکەت هەڵبژێرە:"
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
    try: bot.send_message(ADMIN_ID, f"📩 **نامەی نوێ:**\nناو: {escape_md(message.from_user.first_name)}\nئایدی: `{message.from_user.id}`\n\n{message.text}", parse_mode='Markdown')
    except: pass
    bot.reply_to(message, "نامەکەت نێردرا. ✅")

@bot.message_handler(commands=['autoclose'])
def set_autoclose(message):
    if str(message.chat.id) == str(ADMIN_ID):
        args = message.text.split()
        if len(args) == 2 and args[1].lower() == "off":
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE settings SET value="0" WHERE key="auto_close_enabled"')
                conn.commit()
            bot.reply_to(message, "✅ سیستەمی داخستنی ئۆتۆماتیکی ڕاگیرا.")
        elif len(args) == 3:
            start_t, end_t = args[1], args[2]
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE settings SET value="1" WHERE key="auto_close_enabled"')
                c.execute('UPDATE settings SET value=? WHERE key="auto_close_start"', (start_t,))
                c.execute('UPDATE settings SET value=? WHERE key="auto_close_end"', (end_t,))
                conn.commit()
            bot.reply_to(message, f"✅ سیستەمی ئۆتۆماتیکی چالاککرا لە {start_t} بۆ {end_t}.")
        else: bot.reply_to(message, "شێواز هەڵەیە: /autoclose 00:00 08:00 یان /autoclose off")

@bot.message_handler(commands=['close'])
def close_store(message):
    if str(message.chat.id) == str(ADMIN_ID):
        reason = message.text.replace('/close', '').strip()
        if not reason: reason = "لە ئێستادا فرۆشگا داخراوە."
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("closed",))
            c.execute('UPDATE settings SET value=? WHERE key="close_reason"', (reason,))
            conn.commit()
        bot.reply_to(message, "🔒 فرۆشگا داخرا.")

@bot.message_handler(commands=['open'])
def open_store(message):
    if str(message.chat.id) == str(ADMIN_ID):
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("open",))
            conn.commit()
        bot.reply_to(message, "🔓 فرۆشگا کرایەوە.")

@bot.message_handler(commands=['allow'])
def allow_user(message):
    if str(message.chat.id) == str(ADMIN_ID):
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
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            tid = int(message.text.replace('/remove ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM allowed_users WHERE user_id = ?', (tid,))
                conn.commit()
            bot.reply_to(message, f"کڕیار {tid} لادرا.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /remove 123")

@bot.message_handler(commands=['setname'])
def set_user_name(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            parts = message.text.split(maxsplit=2)
            target_id, new_name = int(parts[1]), parts[2]
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE allowed_users SET name = ? WHERE user_id = ?', (new_name, target_id))
                conn.commit()
            bot.reply_to(message, f"✅ ناوی {target_id} گۆڕدرا بۆ: **{escape_md(new_name)}**", parse_mode='Markdown')
        except: bot.reply_to(message, "شێواز هەڵەیە: /setname 123 ناو")

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            parts = message.text.split()
            target_id, duration_str = int(parts[1]), parts[2]
            duration_val, duration_unit = int(duration_str[:-1]), duration_str[-1].lower()
            now = datetime.datetime.now()
            if duration_unit == 'h': ban_until = now + datetime.timedelta(hours=duration_val)
            elif duration_unit == 'd': ban_until = now + datetime.timedelta(days=duration_val)
            else: raise ValueError
            with db_lock:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO bans (user_id, ban_until) VALUES (?, ?)', (target_id, ban_until.strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
            bot.reply_to(message, f"کڕیار {target_id} سزادرا.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /ban 123 5h")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            target_id = int(message.text.replace('/unban ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM bans WHERE user_id = ?', (target_id,))
                conn.commit()
            bot.reply_to(message, f"سزای {target_id} لابرا.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /unban 123")

@bot.message_handler(commands=['users'])
def list_users(message):
    if str(message.chat.id) == str(ADMIN_ID):
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT user_id, name FROM allowed_users')
            users = c.fetchall()
        if users:
            msg = "👥 **لیستی کڕیاران:**\n\n"
            for uid, name in users: 
                msg += f"👤 ناوی کڕیار: **{escape_md(name)}**\n🆔 ئایدی: `{uid}`\n───────────────\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "بەکارهێنەر نییە.")

@bot.message_handler(commands=['add'])
def add_codes(message):
    if str(message.chat.id) == str(ADMIN_ID):
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

@bot.message_handler(commands=['viewcodes'])
def view_codes_cmd(message):
    if str(message.chat.id) == str(ADMIN_ID): send_viewcodes_panel(message.chat.id)

def send_viewcodes_panel(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
        results = c.fetchall()
    markup = InlineKeyboardMarkup(row_width=2)
    if results:
        for ctype, count in results: markup.add(InlineKeyboardButton(f"{ctype}$ ({count} دانە)", callback_data=f"vc_show_{ctype}"))
    markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
    text = "📦 **پانێڵی بینینی کۆدەکان:**"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('vc_'))
def vc_callback_handler(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    action = call.data.split('_')[1]
    if action == 'main': send_viewcodes_panel(call.message.chat.id, call.message.message_id)
    elif action == 'show':
        ctype = call.data.split('_')[2]
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT code FROM codes WHERE card_type = ?', (ctype,))
            codes = c.fetchall()
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="vc_main"))
        if codes:
            text = f"🔑 **کۆدەکانی {ctype}$:**\n\n"
            for i, (code,) in enumerate(codes[:60], 1): text += f"{i}. `{code}`\n"
        else: text = f"⚠️ کۆدی {ctype}$ نەماوە."
        try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

@bot.message_handler(commands=['delcode'])
def manage_codes(message):
    if str(message.chat.id) == str(ADMIN_ID):
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            markup = InlineKeyboardMarkup(row_width=1)
            for ctype, count in results: markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە)", callback_data=f"viewc_{ctype}"))
            markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
            bot.reply_to(message, "تکایە جۆرێک هەڵبژێرە بۆ سڕینەوە:", reply_markup=markup)
        else: bot.reply_to(message, "کۆگاکە بەتاڵە.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('viewc_') or call.data.startswith('rmc_') or call.data == 'delcode_back')
def handle_delcode_callbacks(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    if call.data == 'delcode_back':
        manage_codes(call.message)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        return
    if call.data.startswith('rmc_'):
        parts = call.data.split('_')
        code_id, card_type = parts[1], parts[2]
        with db_lock:
            c = conn.cursor()
            c.execute('DELETE FROM codes WHERE id = ?', (code_id,))
            conn.commit()
        call.data = f"viewc_{card_type}"
    if call.data.startswith('viewc_'):
        ctype = call.data.split('_')[1]
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT 80', (ctype,))
            codes = c.fetchall()
        if codes:
            markup = InlineKeyboardMarkup(row_width=1)
            for cid, code in codes: markup.add(InlineKeyboardButton(f"❌ سڕینەوە: {code}", callback_data=f"rmc_{cid}_{ctype}"))
            markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="delcode_back"))
            try: bot.edit_message_text(f"لیستی کۆدەکانی {ctype}$ بۆ سڕینەوە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
            except: pass

@bot.message_handler(commands=['clearcodes'])
def clear_codes(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            target = message.text.replace('/clearcodes ', '').strip()
            with db_lock:
                c = conn.cursor()
                if target.lower() == 'all': c.execute('DELETE FROM codes')
                else: c.execute('DELETE FROM codes WHERE card_type = ?', (target,))
                conn.commit()
            bot.reply_to(message, f"🗑️ کۆدەکانی {target} سڕانەوە.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /clearcodes 2 یان /clearcodes all")

@bot.message_handler(commands=['setlimit'])
def set_limit(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            parts = message.text.split()
            tid, nlimit = int(parts[1]), int(parts[2])
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE debts SET credit_limit = ? WHERE user_id = ?', (nlimit, tid))
                conn.commit()
            bot.reply_to(message, f"سنووری {tid} کرا بە {nlimit}$.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /setlimit ID AMOUNT")

@bot.message_handler(commands=['stock'])
def check_stock(message):
    if str(message.chat.id) == str(ADMIN_ID):
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
    if str(message.chat.id) == str(ADMIN_ID):
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT d.user_id, d.usd, d.iqd, d.credit_limit, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0')
            results = c.fetchall()
        if results:
            msg = "📒 **دەفتەری قەرزەکان:**\n\n"
            tot_usd, tot_iqd = 0, 0
            for uid, usd, iqd, limit, name in results:
                msg += f"👤 {escape_md(name)} | 🆔 `{uid}`\n💸 قەرز: **{usd}$ / {limit}$** ({iqd:,} د)\n───────────────\n"
                tot_usd += usd; tot_iqd += iqd
            msg += f"\n💰 **کۆی گشتی قەرزەکانی دەرەوە:** {tot_usd}$ ({tot_iqd:,} دینار)"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "هیچ قەرزێک لە دەرەوە نییە.")

@bot.message_handler(commands=['wallets'])
def check_all_wallets(message):
    if str(message.chat.id) == str(ADMIN_ID):
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT d.user_id, d.wallet_iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.wallet_iqd > 0')
            results = c.fetchall()
        if results:
            msg = "👛 **لیستی جزدانە پڕەکان:**\n\n"
            tot_wallet = 0
            for uid, wallet, name in results:
                msg += f"👤 {escape_md(name)} | 🆔 `{uid}`\n💳 باڵانس: **{wallet:,} دینار**\n───────────────\n"
                tot_wallet += wallet
            msg += f"\n💰 **کۆی گشتی ناو جزدانەکان:** {tot_wallet:,} دینار"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "هیچ کەسێک پارە لە جزدانەکەیدا نییە.")

def show_wallet_users_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id, name FROM allowed_users')
        users = c.fetchall()
    markup = InlineKeyboardMarkup(row_width=1)
    for uid, name in users: markup.add(InlineKeyboardButton(f"👤 {name}", callback_data=f"mwal_u_{uid}"))
    markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
    text = "👛 **دەسکاری کردنی جزدانەکان:**"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['editwallet'])
def editwallet_command(message):
    if str(message.chat.id) == str(ADMIN_ID): show_wallet_users_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mwal_u_'))
def mwal_user_selected(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.wallet_iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        res = c.fetchone()
    if res:
        wallet, name = res
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("➕ زیادکردن", callback_data=f"mwal_act_{uid}_add"), InlineKeyboardButton("➖ کەمکردنەوە", callback_data=f"mwal_act_{uid}_sub"))
        markup.add(InlineKeyboardButton("🗑 سفرکردنەوەی جزدان", callback_data=f"mwal_clear_{uid}"))
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="mwal_back"))
        text = f"👤 **کڕیار:** {escape_md(name)}\n👛 **پارەی جزدان:** {wallet:,} دینار"
        try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'mwal_back')
def mwal_back_call(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    show_wallet_users_menu(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mwal_clear_'))
def mwal_clear_action(call):
    try: bot.answer_callback_query(call.id, "جزدان سفر کرایەوە ✅", show_alert=True)
    except: pass
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET wallet_iqd = 0 WHERE user_id = ?', (uid,))
        conn.commit()
    mwal_user_selected(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mwal_act_'))
def mwal_action_selected(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    parts = call.data.split('_')
    uid, action = parts[2], parts[3] 
    markup = InlineKeyboardMarkup(row_width=2)
    amounts = [1000, 3000, 5000, 10000, 14000, 25000]
    buttons = [InlineKeyboardButton(f"{amt:,} د", callback_data=f"mwal_do_{uid}_{action}_{amt}") for amt in amounts]
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data=f"mwal_u_{uid}"))
    try: bot.edit_message_text("تکایە بڕەکە هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('mwal_do_'))
def mwal_do_action(call):
    try: bot.answer_callback_query(call.id, "سەرکەوتوو بوو ✅", show_alert=True)
    except: pass
    parts = call.data.split('_')
    uid, action, amt = int(parts[2]), parts[3], int(parts[4])
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT wallet_iqd FROM debts WHERE user_id = ?', (uid,))
        res = c.fetchone()
        if res:
            current_wallet = res[0]
            if action == 'add': new_wallet = current_wallet + amt
            else: new_wallet = max(0, current_wallet - amt)
            c.execute('UPDATE debts SET wallet_iqd = ? WHERE user_id = ?', (new_wallet, uid))
            conn.commit()
            mwal_user_selected(call)

def show_clear_debt_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.user_id, d.usd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0')
        results = c.fetchall()
    if results:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🗑️ سفرکردنەوەی هەموو قەرزەکان", callback_data="cd_all"))
        for uid, usd, name in results: markup.add(InlineKeyboardButton(f"❌ سفرکردنەوە: {name} ({usd}$)", callback_data=f"cd_{uid}"))
        markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
        text = "تکایە ئەو کەسە هەڵبژێرە بۆ سفرکردنەوەی قەرزەکەی:"
        if message_id:
            try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
            except: pass
        else: bot.send_message(chat_id, text, reply_markup=markup)
    else: bot.send_message(chat_id, "هیچ قەرزێک نییە.")

@bot.message_handler(commands=['clear'])
def clear_debt(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            tid = message.text.replace('/clear', '').strip()
            if tid:
                with db_lock:
                    c = conn.cursor()
                    if tid.lower() == 'all': c.execute('UPDATE debts SET usd = 0, iqd = 0')
                    else: c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (int(tid),))
                    conn.commit()
                bot.reply_to(message, "✅ قەرزەکان سفر کرانەوە.")
            else: show_clear_debt_menu(message.chat.id)
        except: bot.reply_to(message, "شێواز: /clear ID یان /clear all")

@bot.callback_query_handler(func=lambda call: call.data.startswith('cd_'))
def handle_clear_debt_callback(call):
    try: bot.answer_callback_query(call.id, "قەرزەکان سفر کرانەوە! ✅", show_alert=True)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    action = call.data.split('_')[1]
    if action == 'all':
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE debts SET usd = 0, iqd = 0')
            conn.commit()
    else:
        target_id = int(action)
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (target_id,))
            conn.commit()
        try: bot.send_message(target_id, "🎉 پیرۆزە! هەموو قەرزەکانی لەسەرت سفر کردەوە.")
        except: pass
    show_clear_debt_menu(call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['paydebt'])
def manual_pay_debt(message):
    if str(message.chat.id) != str(ADMIN_ID): return
    try:
        parts = message.text.split()
        uid, usd_amt, iqd_amt = int(parts[1]), int(parts[2]), int(parts[3])
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT usd, iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
            res = c.fetchone()
            if res:
                new_usd, new_iqd = max(0, res[0] - usd_amt), max(0, res[1] - iqd_amt)
                c.execute('UPDATE debts SET usd = ?, iqd = ? WHERE user_id = ?', (new_usd, new_iqd, uid))
                conn.commit()
                bot.reply_to(message, f"✅ پارەکە وەرگیرا!\nقەرزی ماوە: {new_usd}$")
            else: bot.reply_to(message, "کڕیار نەدۆزرایەوە.")
    except: bot.reply_to(message, "شێواز هەڵەیە: /paydebt ID USD IQD")

def show_debt_users_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id, name FROM allowed_users')
        users = c.fetchall()
    markup = InlineKeyboardMarkup(row_width=1)
    for uid, name in users: markup.add(InlineKeyboardButton(f"👤 {name}", callback_data=f"mdebt_u_{uid}"))
    markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
    text = "🛠 **بەڕێوەبردنی قەرزەکان:**"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['editdebt'])
def editdebt_command(message):
    if str(message.chat.id) == str(ADMIN_ID): show_debt_users_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'delete_msg')
def delete_message_handler(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_u_'))
def mdebt_user_selected(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.usd, d.iqd, d.credit_limit, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        res = c.fetchone()
    if res:
        usd, iqd, limit, name = res
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("➕ زیادکردنی قەرز", callback_data=f"mdebt_act_{uid}_add"), InlineKeyboardButton("➖ وەرگرتنی قەرز", callback_data=f"mdebt_act_{uid}_pay"))
        markup.add(InlineKeyboardButton("🗑 سفرکردنەوەی قەرز", callback_data=f"mdebt_clear_{uid}"))
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="mdebt_back"))
        text = f"👤 **کڕیار:** {escape_md(name)}\n📊 **قەرز:** {usd}$ / {limit}$ ({iqd:,} دینار)"
        try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_clear_'))
def mdebt_clear_action(call):
    try: bot.answer_callback_query(call.id, "قەرز سفر کرایەوە! ✅", show_alert=True)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (uid,))
        conn.commit()
    mdebt_user_selected(call)

@bot.callback_query_handler(func=lambda call: call.data == 'mdebt_back')
def mdebt_back_call(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    show_debt_users_menu(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_act_'))
def mdebt_action_selected(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    parts = call.data.split('_')
    uid, action = parts[2], parts[3] 
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(f"{ctype}$ ({price:,} د)", callback_data=f"mdebt_do_{uid}_{action}_{ctype}") for ctype, price in prices.items()]
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data=f"mdebt_u_{uid}"))
    try: bot.edit_message_text("تکایە بڕەکە هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_do_'))
def mdebt_do_action(call):
    try: bot.answer_callback_query(call.id, "سەرکەوتوو بوو! ✅", show_alert=True)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    parts = call.data.split('_')
    uid, action, ctype = int(parts[2]), parts[3], parts[4]
    amount_usd, amount_iqd = int(ctype), prices.get(ctype, 0)
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.usd, d.iqd FROM debts d WHERE d.user_id = ?', (uid,))
        res = c.fetchone()
        if res:
            current_usd, current_iqd = res
            if action == 'add': new_usd, new_iqd = current_usd + amount_usd, current_iqd + amount_iqd
            else: new_usd, new_iqd = max(0, current_usd - amount_usd), max(0, current_iqd - amount_iqd)
            c.execute('UPDATE debts SET usd = ?, iqd = ? WHERE user_id = ?', (new_usd, new_iqd, uid))
            conn.commit()
            mdebt_user_selected(call)

def show_userdebt_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.user_id, a.name, d.usd FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0')
        users = c.fetchall()
    if not users:
        text = "هیچ قەرزارێک نییە لە ئێستادا. 🌸"
        if message_id:
            try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
            except: pass
        else: bot.send_message(chat_id, text)
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for uid, name in users: markup.add(InlineKeyboardButton(f"👤 {name} ({usd}$)", callback_data=f"udebt_u_{uid}"))
    markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
    text = "🆔 **سەیرکردنی قەرزی یەک کەس:**"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['userdebt'])
def check_specific_debt_menu(message):
    if str(message.chat.id) == str(ADMIN_ID): show_userdebt_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('udebt_u_'))
def udebt_user_selected(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.usd, d.iqd, d.credit_limit, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        res = c.fetchone()
    if res:
        usd, iqd, limit, name = res
        msg = f"👤 **ناوی کڕیار:** {escape_md(name)}\n🆔 **ئایدی:** `{uid}`\n💸 **قەرزی ئێستا:** {usd}$ / {limit}$  ({iqd:,} دینار)"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="udebt_back"))
        try: bot.edit_message_text(msg, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'udebt_back')
def udebt_back_call(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    show_userdebt_menu(call.message.chat.id, call.message.message_id)

def show_userhistory_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT DISTINCT h.user_id, a.name FROM history h LEFT JOIN allowed_users a ON h.user_id = a.user_id')
        users = c.fetchall()
    if not users:
        text = "هیچ مێژوویەکی کڕین بوونی نییە هێشتا."
        if message_id:
            try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
            except: pass
        else: bot.send_message(chat_id, text)
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for uid, name in users: markup.add(InlineKeyboardButton(f"👤 {name}", callback_data=f"uhist_u_{uid}"))
    markup.add(InlineKeyboardButton("❌ داخستن", callback_data="delete_msg"))
    text = "📜 **سەیرکردنی مێژووی کڕینەکان:**"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['userhistory'])
def check_user_history_menu(message):
    if str(message.chat.id) == str(ADMIN_ID): show_userhistory_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('uhist_u_'))
def uhist_user_selected(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT name FROM allowed_users WHERE user_id = ?', (uid,))
        u_res = c.fetchone()
        name = u_res[0] if u_res else "نەناسراو"
        c.execute('SELECT card_type, price, code, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10', (uid,))
        hist = c.fetchall()
    if hist:
        msg = f"📜 **مێژووی کڕینەکانی:** {escape_md(name)}\n\n"
        for ctype, prc, cd, dt in hist: msg += f"💳 **{ctype}** | {prc:,} د\n🔑 `{cd}`\n📅 {dt}\n------------------\n"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="uhist_back"))
        try: bot.edit_message_text(msg, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: 
        try: bot.answer_callback_query(call.id, "هیچ کڕینێکی نەکردووە.", show_alert=True)
        except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'uhist_back')
def uhist_back_call(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    show_userhistory_menu(call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if str(message.chat.id) == str(ADMIN_ID):
        text = message.text.replace('/broadcast', '').strip()
        if text:
            with db_lock:
                c = conn.cursor()
                c.execute('SELECT user_id FROM allowed_users')
                users = c.fetchall()
            count = 0
            for (uid,) in users:
                try: bot.send_message(uid, f"📢 **ئاگاداری:**\n\n{text}", parse_mode='Markdown'); count += 1
                except: pass
            bot.reply_to(message, f"نامەکە بۆ {count} بەکارهێنەر نێردرا.")
        else: bot.reply_to(message, "تکایە دەق بنووسە: /broadcast پەیامەکەت لێرە")

@bot.message_handler(commands=['update'])
def announce_update(message):
    if str(message.chat.id) == str(ADMIN_ID):
        text = message.text.replace('/update', '').strip()
        if text:
            with db_lock:
                c = conn.cursor()
                c.execute('SELECT user_id FROM allowed_users')
                users = c.fetchall()
            count = 0
            for (uid,) in users:
                try:
                    bot.send_message(uid, f"✨ **نوێکاری لە فرۆشگا!** ✨\n\n{text}", parse_mode='Markdown', reply_markup=get_main_menu(uid))
                    count += 1
                except: pass
            bot.reply_to(message, f"✅ نامەی نوێکاری و مێنووی نوێ بۆ {count} کڕیار نێردرا.")
        else: bot.reply_to(message, "تکایە دەق بنووسە: /update پەیامەکەت")

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            with open(DB_PATH, 'rb') as doc: bot.send_document(message.chat.id, doc, caption="💾 داتابەیس")
        except Exception as e: bot.reply_to(message, f"کێشە: {e}")

@bot.message_handler(commands=['restore'])
def restore_instructions(message):
    if str(message.chat.id) == str(ADMIN_ID): bot.reply_to(message, "تەنها فایلی `itunes_store_v5.db` بنێرە بۆ گەڕاندنەوە.")

@bot.message_handler(content_types=['document'])
def handle_database_restore(message):
    global conn
    if str(message.chat.id) == str(ADMIN_ID) and message.document.file_name.endswith('.db'):
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with db_lock:
                conn.close()
                with open(DB_PATH, 'wb') as new_file: new_file.write(downloaded_file)
                conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            bot.reply_to(message, "✅ داتابەیس گەڕێندرایەوە.")
        except: bot.reply_to(message, "❌ کێشە ڕوویدا.")

# ================== بەشی جزدان و قەرزدانەوە ==================
@bot.callback_query_handler(func=lambda call: call.data == 'add_wallet_req')
def add_wallet_req(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    msg = bot.send_message(call.message.chat.id, "💳 **پڕکردنەوەی جزدان**\n\nتکایە ئەو بڕە پارەیە بنووسە کە دەتەوێت بیخەیتە جزدانەکەتەوە (تەنها ژمارە بنووسە، بۆ نموونە: 3000):")
    bot.register_next_step_handler(msg, process_wallet_req)

def process_wallet_req(message):
    try:
        amount = int(message.text.strip())
        if amount <= 0: raise ValueError
    except:
        bot.reply_to(message, "❌ بڕەکە نادروستە، تکایە تەنها ژمارە بنووسە.", reply_markup=get_main_menu(message.from_user.id))
        return
        
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ وەرگرە (پەسەندکردن)", callback_data=f"approve_w_{message.from_user.id}_{amount}"),
        InlineKeyboardButton("❌ وەر مەگرە", callback_data=f"reject_w_{message.from_user.id}")
    )
    
    bot.send_message(ADMIN_ID, f"📥 **داواکاری پڕکردنەوەی جزدان:**\n\nکڕیار: {escape_md(message.from_user.first_name)} (`{message.from_user.id}`)\nبڕی داواکراو: **{amount:,} دینار**", reply_markup=markup, parse_mode='Markdown')
    bot.reply_to(message, f"⏳ داواکارییەکەت بۆ بڕی **{amount:,} دینار** نێردرا بۆ ئەدمین. چاوەڕێی پەسەندکردن بە.", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_w_'))
def approve_wallet(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    target_uid = int(call.data.split('_')[2])
    amount = int(call.data.split('_')[3])
    
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET wallet_iqd = wallet_iqd + ? WHERE user_id = ?', (amount, target_uid))
        conn.commit()
        
    try: bot.edit_message_text(f"{call.message.text}\n\n✅ **پەسەند کرا و خرایە جزدانییەوە.**", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except: pass
    try: bot.send_message(target_uid, f"🎉 پیرۆزە! بڕی **{amount:,} دینار** بە سەرکەوتوویی خرایە ناو جزدانەکەتەوە.", parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_w_'))
def reject_wallet(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    target_uid = int(call.data.split('_')[2])
    try: bot.edit_message_text(f"{call.message.text}\n\n❌ **ڕەتکرایەوە.**", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except: pass
    try: bot.send_message(target_uid, "❌ داواکاری پڕکردنەوەی جزدانەکەت ڕەتکرایەوە لەلایەن خاوەن فرۆشگاوە.")
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_pay_'))
def confirm_debt_payment(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    target_uid = int(call.data.split('_')[2])
    
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (target_uid,))
        conn.commit()
        
    try: bot.edit_message_text(f"{call.message.text}\n\n✅ **پەسەند کرا و قەرزەکەی سفر کرایەوە.**", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except: pass
    try: bot.send_message(target_uid, "🎉 پیرۆزە! خاوەن فرۆشگا پشتڕاستی کردەوە کە قەرزەکەت داوەتەوە و ئێستا قەرزەکانت سفر کرانەوە.")
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('reject_pay_'))
def reject_debt_payment(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    if str(call.from_user.id) != str(ADMIN_ID): return
    target_uid = int(call.data.split('_')[2])
    try: bot.edit_message_text(f"{call.message.text}\n\n❌ **ڕەتکرایەوە.**", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except: pass
    try: bot.send_message(target_uid, "❌ خاوەن فرۆشگا داواکاری سفرکردنەوەی قەرزەکەی ڕەتکردەوە.")
    except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'reqstock_cancel')
def reqstock_cancel(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('reqstock_alert_'))
def handle_out_of_stock_alert(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    target = call.data.split('_')[2]
    try:
        bot.send_message(ADMIN_ID, f"🔔 **کارتی نەماو:**\nکڕیار `{escape_md(call.from_user.first_name)}` پێویستی بە کارتی **{target}$** هەیە بەڵام لە کۆگا نەماوە! تکایە کۆگا پڕ بکەرەوە.", parse_mode='Markdown')
        bot.edit_message_text("✅ هیلال ئاگادار کرایەوە. بە زوترین کات کارتی نوێ دەخرێتە کۆگاوە.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_buy_list')
def back_to_buy_list(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(f"{ctype}$ - {price:,} د", callback_data=f"buys_{ctype}") for ctype, price in prices.items()]
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    try: bot.edit_message_text("💳 **کڕینی کارت:**\nتکایە جۆری کارت هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('buys_'))
def handle_qty_selection(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    try:
        ctype = call.data.split('_')[1]
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("1 دانە", callback_data=f"directbuy_std_{ctype}_1"), InlineKeyboardButton("2 دانە", callback_data=f"directbuy_std_{ctype}_2"))
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy_list"))
        
        text = f"💳 **کارتی {ctype}$**\nتکایە ژمارەی داواکراو دیاری بکە (بە پەنجەنان ڕاستەوخۆ دەبێتە وەسڵ):"
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        try: bot.send_message(ADMIN_ID, f"⚠️ Error in buys_: {e}")
        except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('directbuy_'))
def process_direct_quick_buy(call):
    try: bot.answer_callback_query(call.id, "لە جێبەجێکردندایە ⏳")
    except: pass
    
    try:
        uid = call.from_user.id
        if not is_allowed(uid): return
        status, reason = get_store_status()
        if status == "closed":
            try: bot.answer_callback_query(call.id, reason, show_alert=True)
            except: pass
            return

        parts = call.data.split('_')
        is_mixed = parts[1] == 'mix'
        target_val = parts[2]
        qty = int(parts[3])
        
        with db_lock:
            c = conn.cursor()
            assigned_codes = []
            
            if is_mixed:
                target = int(target_val)
                assigned_codes = get_dynamic_combo(c, target, qty)
                if not assigned_codes:
                    markup = InlineKeyboardMarkup()
                    markup.add(InlineKeyboardButton("✅ بەڵێ (ئاگادارکردنەوەی هیلال)", callback_data=f"reqstock_alert_{target}"))
                    markup.add(InlineKeyboardButton("❌ نەخێر", callback_data="reqstock_cancel"))
                    try: bot.edit_message_text(f"⚠️ ببورە، کارتی **{target}$** لە کۆگا نەماوە یان بەشی داواکارییەکەت ناکات.\n\nدەتەوێت هیلال ئاگادار بکەیتەوە بۆ ئەوەی کۆگا پڕ بکاتەوە؟", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
                    except: pass
                    try: bot.send_message(ADMIN_ID, f"⚠️ **کۆگا بەتاڵە:** کڕیارێک ویستی کارتی {target}$ بکڕێت بەڵام نەماوە!", parse_mode='Markdown')
                    except: pass
                    return
                history_desc = f"{target}$ (هەمەجۆر) x{qty}"
                total_usd = target * qty
                total_iqd = sum(prices.get(x['type'], 0) for x in assigned_codes)
            else:
                target = target_val
                c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT ?', (target, qty))
                res = c.fetchall()
                if len(res) < qty:
                    markup = InlineKeyboardMarkup()
                    markup.add(InlineKeyboardButton("✅ بەڵێ (ئاگادارکردنەوەی هیلال)", callback_data=f"reqstock_alert_{target}"))
                    markup.add(InlineKeyboardButton("❌ نەخێر", callback_data="reqstock_cancel"))
                    try: bot.edit_message_text(f"⚠️ ببورە، کارتی **{target}$** لە کۆگا نەماوە یان بەشی داواکارییەکەت ناکات.\n\nدەتەوێت هیلال ئاگادار بکەیتەوە بۆ ئەوەی کۆگا پڕ بکاتەوە؟", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
                    except: pass
                    try: bot.send_message(ADMIN_ID, f"⚠️ **کۆگا بەتاڵە:** کڕیارێک ویستی کارتی {target}$ بکڕێت بەڵام نەماوە!", parse_mode='Markdown')
                    except: pass
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

            if wallet_iqd > 0:
                if wallet_iqd >= total_iqd:
                    wallet_deducted = total_iqd
                    iqd_to_add = 0
                    usd_to_add = 0
                    c.execute('UPDATE debts SET wallet_iqd = wallet_iqd - ? WHERE user_id = ?', (total_iqd, uid))
                else:
                    wallet_deducted = wallet_iqd
                    iqd_to_add = total_iqd - wallet_iqd
                    usd_to_add = round(total_usd * (iqd_to_add / total_iqd))
                    c.execute('UPDATE debts SET wallet_iqd = 0 WHERE user_id = ?', (uid,))

            if current_debt_usd + usd_to_add > limit:
                try: bot.answer_callback_query(call.id, f"گەیشتووی بە سنووری قەرز ({limit}$). ناتوانیت کڕین بکەیت.", show_alert=True)
                except: pass
                return

            code_texts, refund_data_codes = [], []
            for item in assigned_codes:
                c.execute('DELETE FROM codes WHERE id = ?', (item['id'],))
                code_texts.append(f"▫️ کارتی {item['type']}$: `{item['code']}`")
                refund_data_codes.append((item['id'], item['code'], item['type']))

            c.execute('UPDATE debts SET usd = usd + ?, iqd = iqd + ? WHERE user_id = ?', (usd_to_add, iqd_to_add, uid))
            c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, history_desc, total_iqd, "\n".join(code_texts)))
            check_and_alert_low_stock(c, [item['type'] for item in assigned_codes])
            conn.commit()

        wallet_receipt_text = f"\n👛 **لە جزدان بڕدرا:** {wallet_deducted:,} دینار" if wallet_deducted > 0 else ""
        debt_receipt_text = f"\n💸 **چووە سەر قەرز:** {usd_to_add}$ ({iqd_to_add:,} د)" if iqd_to_add > 0 else "\n💸 **چووە سەر قەرز:** 0 (بە جزدان درا)"

        safe_name = escape_md(db_user_name)
        receipt = (
            "🧾 **پسوڵەی کڕین (ڕەسمی)**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **کڕیار:** {safe_name}\n📅 **بەروار:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🛒 **جۆر:** {history_desc}\n💰 **نرخی گشتی:** {total_usd}$ ({total_iqd:,} د){wallet_receipt_text}{debt_receipt_text}\n📊 **قەرزی نوێ:** {current_debt_usd + usd_to_add}$/ {limit}$\n━━━━━━━━━━━━━━━━━━━━\n"
            "🎁 **کۆدەکان:**\n\n"
        )
        receipt += "\n".join([f"▫️ کارتی {x['type']}$: `{x['code']}`" for x in assigned_codes]) + "\n\nزۆر سوپاس بۆ متمانەت! 🍏 هیلال"
        
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

    except Exception as e:
        try: bot.send_message(ADMIN_ID, f"⚠️ کێشەیەک ڕوویدا لە کڕیندا:\n{str(e)}")
        except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('refund_'))
def handle_refund_request(call):
    try: bot.answer_callback_query(call.id)
    except: pass
    receipt_id = call.data.split('_')[1] + "_" + call.data.split('_')[2]
    if receipt_id not in pending_refunds:
        try: bot.answer_callback_query(call.id, "ئەم پسوڵەیە کاتی بەسەر چووە!", show_alert=True)
        except: pass
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return
        
    refund_data = pending_refunds[receipt_id]
    if time.time() > refund_data['expiry']:
        try: bot.answer_callback_query(call.id, "کاتەکەت تەواو بووە (٣٠ چرکە)!", show_alert=True)
        except: pass
        del pending_refunds[receipt_id]
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return
        
    uid, codes_to_return, usd_added, iqd_added, wallet_deducted, desc, u_name = refund_data['uid'], refund_data['codes'], refund_data['usd_added'], refund_data['iqd_added'], refund_data['wallet_deducted'], refund_data['history_desc'], refund_data['db_user_name']
    
    with db_lock:
        c = conn.cursor()
        for cid, code, ctype in codes_to_return:
            c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (ctype, code))
        c.execute('UPDATE debts SET usd = usd - ?, iqd = iqd - ?, wallet_iqd = wallet_iqd + ? WHERE user_id = ?', (usd_added, iqd_added, wallet_deducted, uid))
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, f"گەڕاندنەوە: {desc}", -(iqd_added + wallet_deducted), "گەڕێندرانەوە ناو کۆگا"))
        conn.commit()
        
    del pending_refunds[receipt_id]
    try: bot.answer_callback_query(call.id, "گەڕێندرایەوە! ✅", show_alert=True)
    except: pass
    new_text = f"🧾 **پسوڵەی هەڵوەشاوە** ❌\n━━━━━━━━━━━━━━━━━━━━\nکڕیار: {escape_md(u_name)}\nبڕی گەڕێندراو: {desc}\nپارەی سڕاوە لە قەرز: {usd_added}$ ({iqd_added:,} دینار)\nپارەی گەڕێندراو بۆ جزدان: {wallet_deducted:,} دینار\n━━━━━━━━━━━━━━━━━━━━\n🔒 **کۆدەکان گەڕێندرانەوە.**"
    try: bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    except: pass

    if uid != ADMIN_ID:
        try: bot.send_message(ADMIN_ID, f"↩️ **گەڕاندنەوەی کارت:**\n\nکڕیار ({escape_md(u_name)}) پەشیمان بووەوە و کارتی {desc} ی گەڕاندەوە ناو کۆگا.", parse_mode='Markdown')
        except: pass

@bot.message_handler(func=lambda message: True)
def handle_all_texts(message):
    uid = message.from_user.id
    if not is_allowed(uid): return

    current_markup = get_main_menu(uid)
    status, reason = get_store_status()
    if status == "closed" and "کڕین" in message.text:
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown', reply_markup=current_markup)
        return

    if message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە"]:
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = [InlineKeyboardButton(f"{ctype}$ - {price:,} د", callback_data=f"buys_{ctype}") for ctype, price in prices.items()]
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "💳 **کڕینی کارت**\nتکایە جۆری کارت هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "🔀 ئایتونسی جیاواز":
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = [InlineKeyboardButton(f"کارتی {target}$", callback_data=f"directbuy_mix_{target}_1") for target in [6, 7, 8, 9, 11, 12, 13]]
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "🔀 **کڕینی ئایتونسی جیاواز**\nتکایە بڕەکە هەڵبژێرە (ڕاستەوخۆ دەبێتە وەسڵ):", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "👛 جزدانەکەم":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT wallet_iqd FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
            wallet_bal = res[0] if res else 0
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➕ پڕکردنەوەی جزدان", callback_data="add_wallet_req"))
        bot.reply_to(message, f"👛 **جزدانەکەی تۆ:**\n\nبڕی بەردەست: **{wallet_bal:,} دينار**\n\nدەتوانیت پارە حەواڵە بکەیت و بیخەیتە ناو جزدانەکەتەوە بۆ ئەوەی کڕینەکانت خێراتر بێت.", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "💰 قەرزەکانم":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT usd, iqd, credit_limit FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
        if res and res[0] > 0: 
            bot.reply_to(message, f"تۆ بڕی **{res[0]}$** قەرزاری لە کۆی سنووری ڕێگەپێدراوی **{res[2]}$**.\nبڕی قەرز بە دینار: **{res[1]:,} دینار**.", parse_mode='Markdown', reply_markup=current_markup)
        else: bot.reply_to(message, "تۆ هیچ قەرزار نیت! 🌸", reply_markup=current_markup)

    elif message.text == "📜 مێژووی کڕینەکان":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, price, code, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 5', (uid,))
            hist = c.fetchall()
        if hist:
            msg = "📜 **کۆتا کڕینەکانت:**\n\n"
            for ctype, prc, cd, dt in hist: msg += f"💳 کارتی {ctype} | {abs(prc):,} د\n{cd}\nبەروار: {dt}\n------------------\n"
            bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=current_markup)
        else: bot.reply_to(message, "هیچ کڕینێکت نەبووە.", reply_markup=current_markup)

    elif message.text == "📦 ئاماری کۆگا":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            msg = "📦 **ئاماری کارتی بەردەست:**\n\n"
            for card_type, count in results: msg += f"کارتی {card_type}$ : **{count}** دانە\n"
            bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=current_markup)
        else: bot.reply_to(message, "کۆگا بەتاڵە.", reply_markup=current_markup)
        
    elif message.text == "✅ قەرزەکەم داوەتەوە":
        bot.reply_to(message, "⏳ داواکارییەکەت نێردرا بۆ خاوەن فرۆشگا.", reply_markup=current_markup)
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ بەڵێ (سفرکردنەوە)", callback_data=f"confirm_pay_{uid}"),
            InlineKeyboardButton("❌ نەخێر", callback_data=f"reject_pay_{uid}")
        )
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT usd, iqd FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
            debt_info = f"{res[0]}$ ({res[1]:,} دینار)" if res else "0$"
        try: bot.send_message(ADMIN_ID, f"🔔 **ئاگاداری دانەوەی قەرز:**\n\nکڕیار: {escape_md(message.from_user.first_name)} (`{uid}`)\nقەرزی لەسەرە: **{debt_info}**\n\nئایا ئەم کڕیارە قەرزەکەی داوەتەوە؟", parse_mode='Markdown', reply_markup=markup)
        except: pass

    else:
        if message.text.startswith('/'): return
        bot.reply_to(message, "تکایە تەنها لە ڕێگەی دوگمەکانی خوارەوە داواکارییەکەت هەڵبژێرە.", reply_markup=current_markup)

def auto_schedule_checker():
    while True:
        now_time = time.time()
        to_delete = [rid for rid, data in pending_refunds.items() if now_time > data['expiry'] + 60]
        for rid in to_delete: del pending_refunds[rid]
        time.sleep(30)

def setup_bot_commands():
    user_commands = [
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن بە خاوەن فرۆشگا")
    ]
    try: bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    except: pass

    admin_commands = [
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن بە خاوەن فرۆشگا"),
        BotCommand("allow", "✅ ڕێگەپێدان بە کڕیار"),
        BotCommand("remove", "❌ سڕینەوەی کڕیار"),
        BotCommand("setname", "✏️ گۆڕینی ناوی کڕیار"),
        BotCommand("ban", "🚫 سزادانی کڕیار"),
        BotCommand("unban", "♻️ لابردنی سزا"),
        BotCommand("users", "👥 لیستی کڕیارەکان"),
        BotCommand("debts", "📒 لیستی قەرزەکان"),
        BotCommand("editdebt", "🛠 دەستکاریکردنی قەرز"),
        BotCommand("paydebt", "💵 دانەوەی قەرز بە دەستی"),
        BotCommand("clear", "💸 سفرکردنەوەی قەرز"),
        BotCommand("wallets", "💳 لیستی جزدانەکان"),
        BotCommand("editwallet", "👛 دەستکاریکردنی جزدان"),
        BotCommand("userdebt", "🆔 بینینی قەرزی یەک کەس"),
        BotCommand("userhistory", "📜 مێژووی کڕینی یەک کەس"),
        BotCommand("add", "➕ زیادکردنی کارت"),
        BotCommand("stock", "📦 ئاماری کۆگا"),
        BotCommand("viewcodes", "👀 بینینی کۆدەکان"),
        BotCommand("delcode", "🗑 سڕینەوەی کۆدی هەڵە"),
        BotCommand("clearcodes", "🧹 خاوێنکردنەوەی جۆرێک"),
        BotCommand("setlimit", "🚧 دانانی سنووری قەرز"),
        BotCommand("broadcast", "📢 ناردنی نامەی گشتی"),
        BotCommand("update", "✨ ناردنی نامەی نوێکاری"),
        BotCommand("open", "🔓 کردنەوەی فرۆشگا"),
        BotCommand("close", "🔒 داخستنی فرۆشگا"),
        BotCommand("autoclose", "⏰ سیستەمی داخستنی ئۆتۆماتیک"),
        BotCommand("backup", "💾 وەرگرتنی باکئەپ"),
        BotCommand("restore", "🔄 گەڕاندنەوەی باکئەپ"),
    ]
    try: bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(ADMIN_ID))
    except: pass

checker_thread = threading.Thread(target=auto_schedule_checker, daemon=True)
checker_thread.start()
backup_thread = threading.Thread(target=auto_periodic_backup, daemon=True)
backup_thread.start()

print("✅ بۆتەکە بەتەواوی کار دەکات. فەرمانەکان گەڕێندرانەوە و کێشەی وەستانەکە چارەسەر کرا.")
setup_bot_commands()
bot.infinity_polling()
