import telebot
import sqlite3
import threading
import datetime
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat

# تۆکنە نوێیەکەت بە جێگیری لێرەدا دانراوە
TOKEN = '8781704084:AAHCCyZ79ud30w3z0sMF9hxpLme4izV6DMA'
bot = telebot.TeleBot(TOKEN)
ADMIN_ID = 1229224919

bot.remove_webhook()

conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)
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
    markup.add(KeyboardButton("🛒 کڕینی کارت"), KeyboardButton("🔀 کارتی هەمەجۆر"))
    markup.add(KeyboardButton("💰 قەرزەکانم"), KeyboardButton("📜 مێژووی کڕینەکان"))
    markup.add(KeyboardButton("📦 ئاماری کۆگا"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\nئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت.\n\nتکایە لە دوگمەکانی خوارەوە هەڵبژێرە:"
        bot.reply_to(message, welcome_text, reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    else:
        bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە.\nئایدی تۆ: `{user_id}`\nئەم ئایدییە بنێرە بۆ خاوەنی بۆتەکە.", parse_mode='Markdown')

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

# ================== 🎛 پانێڵی ئەدمین ==================
@bot.message_handler(commands=['admin'])
def admin_panel_cmd(message):
    if message.chat.id == ADMIN_ID: send_admin_panel(message.chat.id)

def send_admin_panel(chat_id, message_id=None):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("📦 کۆگا و کۆدەکان", callback_data="ap_stock"), InlineKeyboardButton("💰 بەڕێوەبردنی قەرز", callback_data="ap_debts"))
    markup.add(InlineKeyboardButton("❌ داخستنی پانێڵ", callback_data="ap_close"))
    text = "🎛 **پانێڵی کۆنترۆڵی ناوەندی (هیلال)**\n\nتکایە بەشێک هەڵبژێرە:"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('ap_'))
def ap_callback_handler(call):
    if call.from_user.id != ADMIN_ID: return
    action = call.data.split('_')[1]
    if action == 'close':
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
    elif action == 'main': send_admin_panel(call.message.chat.id, call.message.message_id)
    elif action == 'debts': show_debt_users_menu(call.message.chat.id, call.message.message_id)
    elif action == 'stock':
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        markup = InlineKeyboardMarkup(row_width=2)
        if results:
            for ctype, count in results: markup.add(InlineKeyboardButton(f"{ctype}$ ({count} دانە)", callback_data=f"ap_vc_{ctype}"))
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="ap_main"))
        try: bot.edit_message_text("📦 **بەشی کۆگا:**\n\nبۆ بینینی کۆدەکان کرتە لە جۆرەکەی بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    elif action == 'vc':
        ctype = call.data.split('_')[2]
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT code FROM codes WHERE card_type = ?', (ctype,))
            codes = c.fetchall()
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە بۆ کۆگا", callback_data="ap_stock"))
        if codes:
            text = f"🔑 **لیستی کۆدەکانی {ctype}$ لە ناو کۆگادا:**\n\n"
            for i, (code,) in enumerate(codes[:60], 1): text += f"{i}. `{code}`\n"
            if len(codes) > 60: text += f"\n... و {len(codes) - 60} کۆدی تریش ماون."
        else: text = f"⚠️ هیچ کۆدێکی جۆری {ctype}$ لە کۆگادا نەماوە."
        try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

# ================== فەرمانەکانی ئەدمین ==================
@bot.message_handler(commands=['autoclose'])
def set_autoclose(message):
    if message.chat.id == ADMIN_ID:
        args = message.text.split()
        if len(args) == 2 and args[1].lower() == "off":
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE settings SET value="0" WHERE key="auto_close_enabled"')
                conn.commit()
            bot.reply_to(message, "✅ سیستەمی داخستنی ڕاگیرا.")
        elif len(args) == 3:
            start_t, end_t = args[1], args[2]
            if ":" in start_t and ":" in end_t:
                with db_lock:
                    c = conn.cursor()
                    c.execute('UPDATE settings SET value="1" WHERE key="auto_close_enabled"')
                    c.execute('UPDATE settings SET value=? WHERE key="auto_close_start"', (start_t,))
                    c.execute('UPDATE settings SET value=? WHERE key="auto_close_end"', (end_t,))
                    conn.commit()
                bot.reply_to(message, f"✅ سیستەمی ئۆتۆماتیکی چالاککرا لە {start_t} بۆ {end_t}.")
            else: bot.reply_to(message, "شێواز هەڵەیە: /autoclose 00:00 08:00")

@bot.message_handler(commands=['close'])
def close_store(message):
    if message.chat.id == ADMIN_ID:
        reason = message.text.replace('/close', '').strip()
        if not reason: reason = "لە ئێستادا فرۆشگا داخراوە."
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("closed",))
            c.execute('UPDATE settings SET value=? WHERE key="close_reason"', (reason,))
            c.execute('SELECT user_id FROM allowed_users')
            users = c.fetchall()
            conn.commit()
        count = 0
        for (uid,) in users:
            try: bot.send_message(uid, f"📢 **ئاگاداری:**\n🔒 فرۆشگا داخرا.\n{reason}", parse_mode='Markdown'); count += 1
            except: pass
        bot.reply_to(message, f"🔒 فرۆشگا داخرا و نامە بۆ {count} کڕیار نێردرا.")

@bot.message_handler(commands=['open'])
def open_store(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("open",))
            c.execute('SELECT user_id FROM allowed_users')
            users = c.fetchall()
            conn.commit()
        for (uid,) in users:
            try: bot.send_message(uid, f"📢 **ئاگاداری:**\n🔓 فرۆشگاکە ئێستا کرایەوە! 🍏", parse_mode='Markdown')
            except: pass
        bot.reply_to(message, f"🔓 فرۆشگا کرایەوە.")

@bot.message_handler(commands=['allow'])
def allow_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            new_user_id = int(parts[1])
            name = parts[2] if len(parts) > 2 else "نەناسراو"
            with db_lock:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO allowed_users (user_id, name) VALUES (?, ?)', (new_user_id, name))
                c.execute('INSERT OR IGNORE INTO debts (user_id, usd, iqd, credit_limit) VALUES (?, 0, 0, 25)', (new_user_id,))
                conn.commit()
            bot.reply_to(message, f"کڕیار {new_user_id} ڕێگەی پێدرا.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /allow 123 ناو")
        
@bot.message_handler(commands=['remove'])
def remove_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            target_id = int(message.text.replace('/remove ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM allowed_users WHERE user_id = ?', (target_id,))
                conn.commit()
            bot.reply_to(message, f"کڕیار {target_id} لادرا.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /remove 123")

@bot.message_handler(commands=['setname'])
def set_user_name(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split(maxsplit=2)
            target_id, new_name = int(parts[1]), parts[2]
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE allowed_users SET name = ? WHERE user_id = ?', (new_name, target_id))
                conn.commit()
            bot.reply_to(message, f"✅ ناوی {target_id} گۆڕدرا بۆ: **{new_name}**", parse_mode='Markdown')
        except: bot.reply_to(message, "شێواز هەڵەیە: /setname 123 ناو")

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            target_id, duration_str = int(parts[1]), parts[2]
            duration_val, duration_unit = int(duration_str[:-1]), duration_str[-1].lower()
            now = datetime.datetime.now()
            if duration_unit == 'h': ban_until = now + datetime.timedelta(hours=duration_val)
            elif duration_unit == 'd': ban_until = now + datetime.timedelta(days=duration_val)
            else: raise ValueError
            ban_until_str = ban_until.strftime('%Y-%m-%d %H:%M:%S')
            with db_lock:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO bans (user_id, ban_until) VALUES (?, ?)', (target_id, ban_until_str))
                conn.commit()
            bot.reply_to(message, f"کڕیار `{target_id}` سزادرا تا {ban_until_str}", parse_mode='Markdown')
        except: bot.reply_to(message, "شێواز هەڵەیە: /ban 123 5h")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            target_id = int(message.text.replace('/unban ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM bans WHERE user_id = ?', (target_id,))
                conn.commit()
            bot.reply_to(message, f"سزای `{target_id}` لابرا.", parse_mode='Markdown')
        except: bot.reply_to(message, "شێواز هەڵەیە: /unban 123")

@bot.message_handler(commands=['users'])
def list_users(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT user_id, name FROM allowed_users')
            users = c.fetchall()
        if users:
            msg = "👥 **لیستی بەکارهێنەرەکان:**\n\n"
            for uid, name in users:
                disp_name = name if name and name != "نەناسراو" else "نەناسراو"
                msg += f"👤 **ناو:** {disp_name}\n🆔 **ئایدی:** `{uid}`\n------------------\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "بەکارهێنەر نییە.")

@bot.message_handler(commands=['add'])
def add_codes(message):
    if message.chat.id == ADMIN_ID:
        try:
            lines = message.text.split('\n')
            first_line_parts = lines[0].split()
            card_type = first_line_parts[1]
            codes_to_add = []
            if len(first_line_parts) > 2: codes_to_add.append(" ".join(first_line_parts[2:]))
            for line in lines[1:]:
                clean_line = line.strip()
                if clean_line: codes_to_add.append(clean_line)
            added_count = 0
            with db_lock:
                c = conn.cursor()
                for code in codes_to_add:
                    c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (card_type, code))
                    added_count += 1
                conn.commit()
            bot.reply_to(message, f"بڕی {added_count} کۆدی {card_type}$ زیادکرا.")
        except Exception as e: bot.reply_to(message, "شێواز هەڵەیە: /add 2 XXXXX")

@bot.message_handler(commands=['delcode'])
def manage_codes(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            markup = InlineKeyboardMarkup(row_width=1)
            for ctype, count in results: markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە)", callback_data=f"viewc_{ctype}"))
            bot.reply_to(message, "تکایە جۆرێک هەڵبژێرە بۆ سڕینەوە:", reply_markup=markup)
        else: bot.reply_to(message, "کۆگاکە بەتاڵە.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('viewc_') or call.data.startswith('rmc_') or call.data == 'delcode_back')
def handle_delcode_callbacks(call):
    if call.from_user.id != ADMIN_ID: return
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
        bot.answer_callback_query(call.id, "کۆدەکە سڕایەوە! ✅")
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
    if message.chat.id == ADMIN_ID:
        try:
            target = message.text.replace('/clearcodes ', '').strip()
            if not target: raise ValueError
            with db_lock:
                c = conn.cursor()
                if target.lower() == 'all':
                    c.execute('DELETE FROM codes')
                    msg = "🗑️ **هەموو کۆدەکانی کۆگا سڕانەوە.**"
                else:
                    c.execute('DELETE FROM codes WHERE card_type = ?', (target,))
                    msg = f"🗑️ هەموو کۆدەکانی **{target}$** سڕانەوە."
                conn.commit()
                bot.reply_to(message, msg, parse_mode='Markdown')
        except: bot.reply_to(message, "شێواز هەڵەیە: /clearcodes 2 یان all")


@bot.message_handler(commands=['setlimit'])
def set_limit(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            target_id, new_limit = int(parts[1]), int(parts[2])
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE debts SET credit_limit = ? WHERE user_id = ?', (new_limit, target_id))
                conn.commit()
            bot.reply_to(message, f"سنووری قەرزی {target_id} کرا بە {new_limit}$.")
        except: bot.reply_to(message, "شێواز هەڵەیە: /setlimit ID AMOUNT")

@bot.message_handler(commands=['stock'])
def check_stock(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            msg = "📊 **ئاماری کۆگا:**\n\n"
            for card_type, count in results: msg += f"کارتی {card_type}$ : **{count}** دانە\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "کۆگا بەتاڵە.")

@bot.message_handler(commands=['debts'])
def check_all_debts(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT d.user_id, d.usd, d.iqd, d.credit_limit, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0')
            results = c.fetchall()
        if results:
            msg = "📒 **دەفتەری قەرزەکان:**\n\n"
            tot_usd, tot_iqd = 0, 0
            for uid, usd, iqd, limit, name in results:
                disp_name = name if name and name != "نەناسراو" else "نەناسراو"
                msg += f"👤 **{disp_name}** | ئایدی: `{uid}`\n💸 قەرز: {usd}$ ({iqd:,} د) | سنور: {usd}$/{limit}$\n\n"
                tot_usd += usd; tot_iqd += iqd
            msg += f"💰 **کۆی گشتی قەرز:** {tot_usd}$ ({tot_iqd:,} دینار)"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "هیچ قەرزێک نییە.")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.chat.id == ADMIN_ID:
        text = message.text.replace('/broadcast', '').strip()
        if text:
            with db_lock:
                c = conn.cursor()
                c.execute('SELECT user_id FROM allowed_users')
                users = c.fetchall()
            count = 0
            for (uid,) in users:
                try: bot.send_message(uid, f"📢 **ئاگاداری لە فرۆشگا:**\n\n{text}", parse_mode='Markdown'); count += 1
                except: pass
            bot.reply_to(message, f"نامەکە بۆ {count} بەکارهێنەر نێردرا.")
        else: bot.reply_to(message, "تکایە دەق بنووسە: /broadcast پەیامەکەت لێرە")

@bot.message_handler(commands=['update'])
def announce_update(message):
    if message.chat.id == ADMIN_ID:
        text = message.text.replace('/update', '').strip()
        if text:
            with db_lock:
                c = conn.cursor()
                c.execute('SELECT user_id FROM allowed_users')
                users = c.fetchall()
            count = 0
            for (uid,) in users:
                try:
                    update_msg = f"✨ **نوێکاری لە فرۆشگا!** ✨\n\n{text}"
                    bot.send_message(uid, update_msg, parse_mode='Markdown', reply_markup=get_main_menu(uid))
                    count += 1
                except: pass
            bot.reply_to(message, f"✅ نامەی نوێکاری و دوگمە نوێیەکان بە سەرکەوتوویی بۆ {count} کڕیار نێردرا.")
        else: bot.reply_to(message, "تکایە دەق بنووسە. نموونە:\n`/update سەبەتەی کڕین بۆ فرۆشگاکەمان زیاد کرا!`", parse_mode='Markdown')

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if message.chat.id == ADMIN_ID:
        try:
            with open('itunes_store_v5.db', 'rb') as doc:
                bot.send_document(message.chat.id, doc, caption="💾 **باکئەپی داتابەیس.**", parse_mode='Markdown')
        except Exception as e: bot.reply_to(message, f"کێشە: {e}")

@bot.message_handler(commands=['restore'])
def restore_instructions(message):
    if message.chat.id == ADMIN_ID: bot.reply_to(message, "تەنها فایلی `itunes_store_v5.db` بنێرە بۆ ئێرە بۆ گەڕاندنەوە.")

@bot.message_handler(content_types=['document'])
def handle_database_restore(message):
    global conn
    if message.chat.id == ADMIN_ID and message.document.file_name.endswith('.db'):
        try:
            bot.reply_to(message, "⏳ خەریکی خوێندنەوەی فایلەکەم...")
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with db_lock:
                conn.close()
                with open('itunes_store_v5.db', 'wb') as new_file: new_file.write(downloaded_file)
                conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)
            bot.reply_to(message, "✅ داتابەیس گەڕێندرایەوە.")
        except Exception as e:
            bot.reply_to(message, f"❌ کێشە ڕوویدا: {e}")
            conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)

@bot.message_handler(commands=['paydebt'])
def manual_pay_debt(message):
    if message.chat.id != ADMIN_ID: return
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
                disp_name = res[2] if res[2] and res[2] != "نەناسراو" else "نەناسراو"
                bot.reply_to(message, f"✅ پارەکە وەرگیرا!\n\nکڕیار: {disp_name}\nقەرزی ماوە: {new_usd}$ ({new_iqd:,} دینار)")
                try: bot.send_message(uid, f"✅ بڕی {usd_amt}$ ({iqd_amt:,} دینار) لە قەرزەکەت درا.\nقەرزی ماوەت بوو بە: {new_usd}$")
                except: pass
            else: bot.reply_to(message, "کڕیار نەدۆزرایەوە.")
    except: bot.reply_to(message, "شێواز هەڵەیە: /paydebt ID USD IQD")

def show_clear_debt_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.user_id, d.usd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0')
        results = c.fetchall()
    if results:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🗑️ سفرکردنەوەی هەموو قەرزەکان", callback_data="cd_all"))
        for uid, usd, name in results:
            disp_name = name if name and name != "نەناسراو" else "نەناسراو"
            markup.add(InlineKeyboardButton(f"❌ سفرکردنەوە: {disp_name} ({usd}$)", callback_data=f"cd_{uid}"))
        text = "تکایە ئەو کەسە هەڵبژێرە بۆ سفرکردنەوە:"
        if message_id: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        else: bot.send_message(chat_id, text, reply_markup=markup)
    else:
        text = "هیچ قەرزێک نییە."
        if message_id: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
        else: bot.send_message(chat_id, text)

@bot.message_handler(commands=['clear'])
def clear_debt(message):
    if message.chat.id == ADMIN_ID: show_clear_debt_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cd_'))
def handle_clear_debt_callback(call):
    if call.from_user.id != ADMIN_ID: return
    action = call.data.split('_')[1]
    if action == 'all':
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE debts SET usd = 0, iqd = 0')
            conn.commit()
        bot.answer_callback_query(call.id, "هەموو قەرزەکان سفر کرانەوە!", show_alert=True)
    else:
        target_id = int(action)
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (target_id,))
            conn.commit()
        bot.answer_callback_query(call.id, "قەرزی کڕیارەکە سفر کرایەوە!", show_alert=True)
        try: bot.send_message(target_id, "🎉 پیرۆزە! هەموو قەرزەکانی لەسەرت سفر کردەوە.")
        except: pass
    show_clear_debt_menu(call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['editdebt'])
def editdebt_command(message):
    if message.chat.id == ADMIN_ID: show_debt_users_menu(message.chat.id)

def show_debt_users_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id, name FROM allowed_users')
        users = c.fetchall()
    markup = InlineKeyboardMarkup(row_width=1)
    for uid, name in users:
        disp_name = name if name and name != "نەناسراو" else "نەناسراو"
        markup.add(InlineKeyboardButton(f"👤 {disp_name}", callback_data=f"mdebt_u_{uid}"))
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە بۆ پانێڵی ئەدمین", callback_data="ap_main"))
    text = "🛠 **بەڕێوەبردنی قەرزەکان:**\n\nتکایە کڕیارێک هەڵبژێرە:"
    if message_id:
        try: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass
    else: bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_u_'))
def mdebt_user_selected(call):
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.usd, d.iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        res = c.fetchone()
    if res:
        usd, iqd, name = res
        disp_name = name if name and name != "نەناسراو" else "نەناسراو"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("➕ زیادکردنی قەرز", callback_data=f"mdebt_act_{uid}_add"), InlineKeyboardButton("➖ وەرگرتنی قەرز", callback_data=f"mdebt_act_{uid}_pay"))
        markup.add(InlineKeyboardButton("🗑 سفرکردنەوەی قەرز (یەک کلیک)", callback_data=f"mdebt_clear_{uid}"))
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="mdebt_back"))
        text = f"👤 **کڕیار:** {disp_name}\n📊 **قەرز:** {usd}$ ({iqd:,} دینار)"
        try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_clear_'))
def mdebt_clear_action(call):
    if call.from_user.id != ADMIN_ID: return
    uid = int(call.data.split('_')[2])
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (uid,))
        conn.commit()
    bot.answer_callback_query(call.id, "قەرز سفر کرایەوە! ✅", show_alert=True)
    mdebt_user_selected(call)

@bot.callback_query_handler(func=lambda call: call.data == 'mdebt_back')
def mdebt_back_call(call): show_debt_users_menu(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_act_'))
def mdebt_action_selected(call):
    parts = call.data.split('_')
    uid, action = parts[2], parts[3] 
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for ctype, price in prices.items(): buttons.append(InlineKeyboardButton(f"{ctype}$ ({price:,} د)", callback_data=f"mdebt_do_{uid}_{action}_{ctype}"))
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data=f"mdebt_u_{uid}"))
    try: bot.edit_message_text("تکایە بڕەکە هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_do_'))
def mdebt_do_action(call):
    if call.from_user.id != ADMIN_ID: return
    parts = call.data.split('_')
    uid, action, ctype = int(parts[2]), parts[3], parts[4]
    amount_usd, amount_iqd = int(ctype), prices.get(ctype, 0)
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.usd, d.iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        res = c.fetchone()
        if res:
            current_usd, current_iqd, name = res
            disp_name = name if name and name != "نەناسراو" else "نەناسراو"
            if action == 'add': new_usd, new_iqd = current_usd + amount_usd, current_iqd + amount_iqd
            else: new_usd, new_iqd = max(0, current_usd - amount_usd), max(0, current_iqd - amount_iqd)
            c.execute('UPDATE debts SET usd = ?, iqd = ? WHERE user_id = ?', (new_usd, new_iqd, uid))
            conn.commit()
            bot.answer_callback_query(call.id, "سەرکەوتوو بوو! ✅", show_alert=True)
            mdebt_user_selected(call)

# ================== سیستەمی نوێی کڕینەکان و وەڵامەکان ==================

def check_and_alert_low_stock(c, types_sold):
    for ct in set(types_sold):
        c.execute('SELECT COUNT(*) FROM codes WHERE card_type = ?', (ct,))
        count = c.fetchone()[0]
        if count <= 2:
            try: bot.send_message(ADMIN_ID, f"⚠️ **ئاگاداری کۆگا:**\nکارتی جۆری **{ct}$** تەنها **{count}** دانەی ماوە! تکایە کۆدی نوێ زیاد بکە.", parse_mode='Markdown')
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
            history_desc = f"{target}$ (هەمەجۆر: " + " + ".join([x['type']+"$" for x in assigned_codes]) + ")"
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
    receipt += "\n".join([f" `{x['code']}`" for x in assigned_codes]) + "\n\nزۆر سوپاس بۆ متمانەت! 🍏 هیلال"

    bot.answer_callback_query(call.id, "کڕینەکەت سەرکەوتوو بوو! ✅")
    
    receipt_id = str(int(time.time())) + "_" + str(uid)
    pending_refunds[receipt_id] = {
        'uid': uid, 'codes': refund_data_codes, 'total_usd': total_usd, 'total_iqd': total_iqd,
        'expiry': time.time() + 30, 'history_desc': history_desc, 'db_user_name': db_user_name
    }
    
    refund_markup = InlineKeyboardMarkup()
    refund_markup.add(InlineKeyboardButton("↩️ گەڕاندنەوەی کارت (لەماوەی ٣٠ چرکەدا)", callback_data=f"refund_{receipt_id}"))
    try: bot.edit_message_text(receipt, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=refund_markup)
    except: pass

    safe_uname = call.from_user.username.replace('_', '\\_') if call.from_user.username else "بوونی نییە"
    safe_dbname = db_user_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
    admin_msg = f"🛒 **کڕینێکی نوێ!**\nناو: {safe_dbname}\nئایدی: `{uid}`\nکڕیارەکە ئەمەی کڕی: {history_desc}\n\n{receipt}"
    try: bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')
    except: bot.send_message(ADMIN_ID, admin_msg)

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
        code_texts_for_admin = []
        for cid, code, ctype in codes_to_return:
            c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (ctype, code))
            code_texts_for_admin.append(f"▫️ {ctype}$: `{code}`")
        c.execute('UPDATE debts SET usd = usd - ?, iqd = iqd - ? WHERE user_id = ?', (refund_usd, refund_iqd, uid))
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, f"گەڕاندنەوە: {desc}", -refund_iqd, "گەڕێندرانەوە ناو کۆگا"))
        conn.commit()
        
    del pending_refunds[receipt_id]
    bot.answer_callback_query(call.id, "گەڕێندرایەوە! ✅", show_alert=True)
    
    new_text = f"🧾 **پسوڵەی هەڵوەشاوە** ❌\n━━━━━━━━━━━━━━━━━━━━\nکڕیار: {u_name}\nبڕی گەڕێندراو: {desc}\nپارەی سڕاوە لە قەرز: {refund_usd}$ ({refund_iqd:,} دینار)\n━━━━━━━━━━━━━━━━━━━━\n🔒 **کۆدەکان گەڕێندرانەوە.**"
    try: bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    except: pass
    
    safe_u_name = u_name.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
    admin_msg = f"⚠️ **گەڕاندنەوەی کارت!**\n👤 کڕیار: {safe_u_name}\n🆔 ئایدی: `{uid}`\nبڕی گەڕێندراو: {desc}\n\n**ئەم کۆدانە گەڕانەوە:**\n" + "\n".join(code_texts_for_admin)
    try: bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')
    except: bot.send_message(ADMIN_ID, admin_msg)

@bot.message_handler(func=lambda message: message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە", "🔀 کارتی هەمەجۆر", "💰 قەرزەکانم", "📜 مێژووی کڕینەکان", "📦 ئاماری کۆگا"])
def handle_text_buttons(message):
    uid = message.from_user.id
    if not is_allowed(uid): return

    status, reason = get_store_status()
    if status == "closed" and "کڕین" in message.text:
        bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
        return
    ban_time = get_ban_status(uid)
    if ban_time and "کڕین" in message.text:
        bot.reply_to(message, f"⚠️ تۆ سزادراویت تا بەرواری:\n`{ban_time.strftime('%Y-%m-%d %H:%M')}`", parse_mode='Markdown')
        return

    if message.text in ["🛒 کڕینی کارت", "🛒 کڕینی کارتی تاقە"]:
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for ctype, price in prices.items(): buttons.append(InlineKeyboardButton(f"{ctype} دۆلاری - {price:,} دینار", callback_data=f"buys_{ctype}"))
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "💳 **کڕینی کارت**\n\nتکایە جۆری کارت هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

    elif message.text == "🔀 کارتی هەمەجۆر":
        markup = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for target in sorted([int(x) for x in mixed_plans.keys()]): buttons.append(InlineKeyboardButton(f"کارتی {target}$", callback_data=f"buym_{target}"))
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
            else: markup.add(buttons[i])
        bot.reply_to(message, "🔀 **کڕینی کارتی هەمەجۆر (پاکێج)**\n\nتکایە بڕەکە هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

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

@bot.message_handler(func=lambda message: True)
def refresh_keyboard_fallback(message):
    uid = message.from_user.id
    if is_allowed(uid) and message.chat.id != ADMIN_ID:
        bot.reply_to(message, "🔄 مێنوی دوگمەکانت نوێکرایەوە. تکایە دوگمە نوێیەکانی خوارەوە بەکاربهێنە:", reply_markup=get_main_menu(uid))

def setup_bot_commands():
    user_commands = [
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن بە خاوەن فرۆشگا")
    ]
    
    admin_commands = [
        BotCommand("admin", "🎛 پانێڵی کۆنترۆڵی ناوەندی"),
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن"),
        BotCommand("allow", "✅ ڕێگەپێدان بە کڕیار"),
        BotCommand("remove", "❌ سڕینەوەی کڕیار"),
        BotCommand("setname", "✏️ گۆڕینی ناوی کڕیار"),
        BotCommand("ban", "🚫 سزادانی کڕیار"),
        BotCommand("unban", "♻️ لابردنی سزا"),
        BotCommand("users", "👥 لیستی کڕیارەکان"),
        BotCommand("editdebt", "🛠 دەستکاریکردنی قەرز"),
        BotCommand("paydebt", "💵 دانەوەی قەرز بە دەستی"),
        BotCommand("clear", "💸 سفرکردنەوەی قەرز"),
        BotCommand("open", "🔓 کردنەوەی فرۆشگا"),
        BotCommand("close", "🔒 داخستنی فرۆشگا"),
        BotCommand("autoclose", "⏰ سیستەمی داخستنی تەماتیک"),
        BotCommand("add", "➕ زیادکردنی کۆد"),
        BotCommand("delcode", "🗑 سڕینەوەی کۆد"),
        BotCommand("clearcodes", "⚠️ خاوێنکردنەوەی کۆگا"),
        BotCommand("stock", "📦 ئاماری کۆگا"),
        BotCommand("debts", "📒 دەفتەری قەرزەکان"),
        BotCommand("setlimit", "🚧 گۆڕینی سنوری قەرز"),
        BotCommand("broadcast", "📢 ناردنی ئاگاداری"),
        BotCommand("update", "✨ ڕاگەیاندنی نوێکاری"),
        BotCommand("backup", "💾 وەرگرتنی باکئەپ"),
        BotCommand("restore", "🔄 گەڕاندنەوەی باکئەپ")
    ]
    
    try:
        bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(ADMIN_ID))
    except Exception as e:
        print("کێشەیەک لە دانانی فەرمانەکان هەبوو:", e)

def auto_schedule_checker():
    while True:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=3) 
        current_hm = now.strftime('%H:%M')
        now_time = time.time()
        to_delete = [rid for rid, data in pending_refunds.items() if now_time > data['expiry'] + 60]
        for rid in to_delete: del pending_refunds[rid]
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT value FROM settings WHERE key="auto_close_enabled"')
            res_en = c.fetchone()
            if res_en and res_en[0] == "1":
                c.execute('SELECT value FROM settings WHERE key="auto_close_start"')
                res_start = c.fetchone()
                c.execute('SELECT value FROM settings WHERE key="auto_close_end"')
                res_end = c.fetchone()
                if res_start and res_end:
                    start_t, end_t = res_start[0], res_end[0]
                    c.execute('SELECT value FROM settings WHERE key="last_auto_trigger"')
                    last_trigger = c.fetchone()
                    last_t = last_trigger[0] if last_trigger else ""
                    trigger_key = f"{now.strftime('%Y-%m-%d')}_{current_hm}"
                    if current_hm == start_t and last_t != trigger_key:
                        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("last_auto_trigger", ?)', (trigger_key,))
                        c.execute('SELECT value FROM settings WHERE key="store_status"')
                        if c.fetchone()[0] != "closed":
                            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("closed",))
                            c.execute('UPDATE settings SET value=? WHERE key="close_reason"', (f"فرۆشگا بەشێوەی ئۆتۆماتیکی داخرا.",))
                            c.execute('SELECT user_id FROM allowed_users')
                            for (uid,) in c.fetchall():
                                try: bot.send_message(uid, f"📢 **ئاگاداری:**\n🔒 فرۆشگا داخرا.", parse_mode='Markdown')
                                except: pass
                            conn.commit()
                    elif current_hm == end_t and last_t != trigger_key:
                        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("last_auto_trigger", ?)', (trigger_key,))
                        c.execute('SELECT value FROM settings WHERE key="store_status"')
                        if c.fetchone()[0] != "open":
                            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("open",))
                            c.execute('SELECT user_id FROM allowed_users')
                            for (uid,) in c.fetchall():
                                try: bot.send_message(uid, f"📢 **ئاگاداری:**\n🔓 فرۆشگاکە کرایەوە!", parse_mode='Markdown')
                                except: pass
                            conn.commit()
        time.sleep(30)

checker_thread = threading.Thread(target=auto_schedule_checker, daemon=True)
checker_thread.start()

print("بۆتەکە ئێستا کار دەکات بێ سەبەتە و بە سیستەمی نوێوە...")
setup_bot_commands()
bot.infinity_polling()
