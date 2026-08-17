import telebot
import sqlite3
import threading
import datetime
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat

TOKEN = '8781704084:AAHCCyZ79ud30w3z0sMF9hxpLme4izV6DMA'
bot = telebot.TeleBot(TOKEN)
ADMIN_ID = 1229224919

bot.remove_webhook()

conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)
db_lock = threading.Lock()

user_carts = {}
pending_refunds = {}

def init_db():
    with db_lock:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_type TEXT NOT NULL,
                code TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id INTEGER PRIMARY KEY,
                name TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS debts (
                user_id INTEGER PRIMARY KEY,
                usd INTEGER DEFAULT 0,
                iqd INTEGER DEFAULT 0,
                credit_limit INTEGER DEFAULT 25
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_type TEXT,
                price INTEGER,
                code TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY,
                ban_until TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("store_status", "open")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("close_reason", "")')
        
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_close_enabled", "0")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_close_start", "00:00")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_close_end", "08:00")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("last_auto_trigger", "")')
        conn.commit()

init_db()

prices = {
    '2': 3000,
    '3': 4500,
    '4': 6000,
    '5': 7000,
    '6': 9000,
    '10': 14000,
    '15': 22000
}

def is_allowed(user_id):
    if user_id == ADMIN_ID:
        return True
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
            ban_until_str = res[0]
            ban_until_dt = datetime.datetime.strptime(ban_until_str, '%Y-%m-%d %H:%M:%S')
            if datetime.datetime.now() < ban_until_dt:
                return ban_until_dt
            else:
                c.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
                conn.commit()
                return None
        return None

def get_store_status():
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key="store_status"')
        status_res = c.fetchone()
        c.execute('SELECT value FROM settings WHERE key="close_reason"')
        reason_res = c.fetchone()
        status = status_res[0] if status_res else "open"
        reason = reason_res[0] if reason_res else "فرۆشگا داخراوە."
        return status, reason

def get_main_menu(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🛒 کڕینی کارت"),
        KeyboardButton("💰 قەرزەکانم")
    )
    markup.add(
        KeyboardButton("📜 مێژووی کڕینەکان"),
        KeyboardButton("📦 ئاماری کۆگا")
    )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = (
            "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\n"
            "ئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت.\n\n"
            "تکایە لە دوگمەکانی خوارەوە هەڵبژێرە:"
        )
        bot.reply_to(message, welcome_text, reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    else:
        bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە و تەنها بۆ کەسانی ڕێگەپێدراوە.\n\nئایدی تۆ: `{user_id}`\nئەم ئایدییە بنێرە بۆ خاوەنی بۆتەکە.", parse_mode='Markdown')

@bot.message_handler(commands=['about'])
def about_store(message):
    if is_allowed(message.from_user.id):
        text = (
            "🍏 **دەربارەی فرۆشگای ئایتونس**\n\n"
            "ئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت بۆ دابینکردنی خێراترین و باوەڕپێکراوترین کارتی ئایتونس.\n\n"
            "بۆ هەر کێشەیەک یان داواکارییەک، دەتوانیت لە ڕێگەی فەرمانی /contact وە نامەمان بۆ بنێریت."
        )
        bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(commands=['contact'])
def contact_admin(message):
    if is_allowed(message.from_user.id):
        msg = bot.reply_to(message, "تکایە نامەکەت یان پرسیارەکەت بنووسە، ڕاستەوخۆ دەگاتە هیلال:")
        bot.register_next_step_handler(msg, forward_to_admin)

def forward_to_admin(message):
    bot.send_message(ADMIN_ID, f"📩 **نامەی نوێ لە کڕیارەوە:**\nناو: {message.from_user.first_name}\nئایدی: `{message.from_user.id}`\n\n{message.text}", parse_mode='Markdown')
    bot.reply_to(message, "نامەکەت بە سەرکەوتوویی نێردرا. سوپاس! ✅")

# ------------- فەرمانەکانی ئەدمین -------------
@bot.message_handler(commands=['autoclose'])
def set_autoclose(message):
    if message.chat.id == ADMIN_ID:
        args = message.text.split()
        if len(args) == 2 and args[1].lower() == "off":
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE settings SET value="0" WHERE key="auto_close_enabled"')
                conn.commit()
            bot.reply_to(message, "✅ سیستەمی داخستنی ئۆتۆماتیکی (تەماتیک) ڕاگیرا.")
        elif len(args) == 3:
            start_t = args[1]
            end_t = args[2]
            if ":" in start_t and ":" in end_t:
                with db_lock:
                    c = conn.cursor()
                    c.execute('UPDATE settings SET value="1" WHERE key="auto_close_enabled"')
                    c.execute('UPDATE settings SET value=? WHERE key="auto_close_start"', (start_t,))
                    c.execute('UPDATE settings SET value=? WHERE key="auto_close_end"', (end_t,))
                    conn.commit()
                bot.reply_to(message, f"✅ سیستەمی ئۆتۆماتیکی چالاککرا.\nفرۆشگا هەموو ڕۆژێک لە کاتژمێر **{start_t}** دادەخرێت و لە کاتژمێر **{end_t}** دەکرێتەوە بە شێوەیەکی تەماتیک.", parse_mode='Markdown')
            else:
                bot.reply_to(message, "شێواز هەڵەیە. تکایە بە فۆڕماتی 24 کاتژمێری بینووسە. نموونە:\n`/autoclose 00:00 08:00`", parse_mode='Markdown')
        else:
            bot.reply_to(message, "بۆ چالاککردنی تەماتیک: `/autoclose 00:00 08:00`\nبۆ ڕاگرتنی تەماتیک: `/autoclose off`", parse_mode='Markdown')

@bot.message_handler(commands=['close'])
def close_store(message):
    if message.chat.id == ADMIN_ID:
        reason = message.text.replace('/close', '').strip()
        if not reason:
            reason = "لە ئێستادا فرۆشگا داخراوە، کاتێکی تر هەوڵ بدەرەوە."
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("closed",))
            c.execute('UPDATE settings SET value=? WHERE key="close_reason"', (reason,))
            c.execute('SELECT user_id FROM allowed_users')
            users = c.fetchall()
            conn.commit()
        count = 0
        for (uid,) in users:
            try:
                bot.send_message(uid, f"📢 **ئاگاداری لە فرۆشگاوە:**\n\n🔒 فرۆشگاکە داخرا.\nکات/هۆکار: {reason}", parse_mode='Markdown')
                count += 1
            except: pass
        bot.reply_to(message, f"🔒 فرۆشگا داخرا و نامەی ئاگاداری بۆ {count} کڕیار نێردرا.")

@bot.message_handler(commands=['open'])
def open_store(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("open",))
            c.execute('SELECT user_id FROM allowed_users')
            users = c.fetchall()
            conn.commit()
        count = 0
        for (uid,) in users:
            try:
                bot.send_message(uid, f"📢 **ئاگاداری لە فرۆشگاوە:**\n\n🔓 فرۆشگاکە ئێستا کرایەوە! 🍏\nدەتوانن کڕینەکانتان ئەنجام بدەن.", parse_mode='Markdown')
                count += 1
            except: pass
        bot.reply_to(message, f"🔓 فرۆشگا کرایەوە و نامەی ئاگاداری بۆ {count} کڕیار نێردرا.")

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
            bot.reply_to(message, f"کڕیار بە ئایدی {new_user_id} ڕێگەی پێدرا.")
        except:
            bot.reply_to(message, "شێواز هەڵەیە. نموونە:\n/allow 987654321 ناوەکە")

@bot.message_handler(commands=['remove'])
def remove_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            target_id = int(message.text.replace('/remove ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM allowed_users WHERE user_id = ?', (target_id,))
                conn.commit()
            bot.reply_to(message, f"کڕیار بە ئایدی {target_id} لە فرۆشگاکە لادرا.")
        except:
            bot.reply_to(message, "شێواز هەڵەیە: /remove 987654321")

@bot.message_handler(commands=['setname'])
def set_user_name(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split(maxsplit=2)
            target_id = int(parts[1])
            new_name = parts[2]
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE allowed_users SET name = ? WHERE user_id = ?', (new_name, target_id))
                conn.commit()
            bot.reply_to(message, f"✅ ناوی کڕیار بە ئایدی {target_id} گۆڕدرا بۆ: **{new_name}**", parse_mode='Markdown')
        except:
            bot.reply_to(message, "شێواز هەڵەیە. نموونە:\n`/setname 123456789 هێمن`", parse_mode='Markdown')

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            target_id = int(parts[1])
            duration_str = parts[2]
            duration_val = int(duration_str[:-1])
            duration_unit = duration_str[-1].lower()
            now = datetime.datetime.now()
            if duration_unit == 'h': ban_until = now + datetime.timedelta(hours=duration_val)
            elif duration_unit == 'd': ban_until = now + datetime.timedelta(days=duration_val)
            else: raise ValueError
            ban_until_str = ban_until.strftime('%Y-%m-%d %H:%M:%S')
            with db_lock:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO bans (user_id, ban_until) VALUES (?, ?)', (target_id, ban_until_str))
                conn.commit()
            bot.reply_to(message, f"کڕیار `{target_id}` سزادرا تا بەرواری {ban_until_str}", parse_mode='Markdown')
            bot.send_message(target_id, f"⚠️ **ئاگاداری:**\nتۆ سزادراویت و ناتوانیت هیچ کڕینێک بکەیت تا بەرواری:\n`{ban_until_str}`", parse_mode='Markdown')
        except:
            bot.reply_to(message, "شێواز هەڵەیە!\nبۆ کاتژمێر: /ban 12345 5h\nبۆ ڕۆژ: /ban 12345 2d")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            target_id = int(message.text.replace('/unban ', '').strip())
            with db_lock:
                c = conn.cursor()
                c.execute('DELETE FROM bans WHERE user_id = ?', (target_id,))
                conn.commit()
            bot.reply_to(message, f"سزای کڕیار `{target_id}` بە سەرکەوتوویی لابرا.", parse_mode='Markdown')
            bot.send_message(target_id, "✅ **ئاگاداری:**\nسزاکەت لەلایەن خاوەن فرۆشگاوە لابرا، ئێستا دەتوانیت کڕینەکانت ئەنجام بدەیت.", parse_mode='Markdown')
        except:
            bot.reply_to(message, "شێواز هەڵەیە: /unban 987654321")

@bot.message_handler(commands=['users'])
def list_users(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT user_id, name FROM allowed_users')
            users = c.fetchall()
        if users:
            msg = "👥 **لیستی بەکارهێنەرە ڕێگەپێدراوەکان:**\n\n"
            for uid, name5 in users:
                disp_name = name5 if name5 and name5 != "نەناسراو" else "نەناسراو"
                msg += f"👤 **ناو:** {disp_name}\n🆔 **ئایدی:** `{uid}`\n------------------\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else:
            bot.reply_to(message, "هیچ بەکارهێنەرێکی ڕێگەپێدراو نییە.")


# ================== سیستەمی گەڕانەوەی قەرز بە یەک کلیک (گەڕایەوە) ==================

def show_clear_debt_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('''
            SELECT d.user_id, d.usd, a.name
            FROM debts d
            LEFT JOIN allowed_users a ON d.user_id = a.user_id
            WHERE d.usd > 0
        ''')
        results = c.fetchall()
    if results:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("🗑️ سفرکردنەوەی هەموو قەرزەکان", callback_data="cd_all"))
        for uid, usd, name in results:
            disp_name = name if name and name != "نەناسراو" else "نەناسراو"
            markup.add(InlineKeyboardButton(f"❌ سفرکردنەوە: {disp_name} ({usd}$)", callback_data=f"cd_{uid}"))
        text = "تکایە ئەو کەسە هەڵبژێرە کە دەتەوێت قەرزەکەی بە یەک کلیک سفر بکەیتەوە:"
        if message_id: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        else: bot.send_message(chat_id, text, reply_markup=markup)
    else:
        text = "هیچ کەسێک قەرزدار نییە لە ئێستادا. 🌸"
        if message_id: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
        else: bot.send_message(chat_id, text)

@bot.message_handler(commands=['clear'])
def clear_debt(message):
    if message.chat.id == ADMIN_ID:
        args = message.text.split()[1:]
        if not args:
            show_clear_debt_menu(message.chat.id)
            return
        with db_lock:
            c = conn.cursor()
            if args[0].lower() == 'all':
                c.execute('UPDATE debts SET usd = 0, iqd = 0')
                conn.commit()
                bot.reply_to(message, "✅ **هەموو قەرزەکانی ناو دەفتەرەکە بەتەواوی سفر کرانەوە.**", parse_mode='Markdown')
            else:
                cleared_count = 0
                for target_id_str in args:
                    try:
                        target_id = int(target_id_str)
                        c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (target_id,))
                        cleared_count += 1
                        try: bot.send_message(target_id, "🎉 پیرۆزە! هیلال هەموو قەرزەکانی لەسەرت سفر کردەوە.")
                        except: pass
                    except ValueError: pass
                conn.commit()
                bot.reply_to(message, f"✅ قەرزی **{cleared_count}** بەکارهێنەر بە سەرکەوتوویی سفر کرایەوە.", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('cd_'))
def handle_clear_debt_callback(call):
    if call.from_user.id != ADMIN_ID: return
    action = call.data.split('_')[1]
    if action == 'all':
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE debts SET usd = 0, iqd = 0')
            conn.commit()
        bot.answer_callback_query(call.id, "هەموو قەرزەکان بە سەرکەوتوویی سفر کرانەوە! ✅", show_alert=True)
        show_clear_debt_menu(call.message.chat.id, call.message.message_id)
    else:
        target_id = int(action)
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (target_id,))
            conn.commit()
        bot.answer_callback_query(call.id, "قەرزی کڕیارەکە سفر کرایەوە! ✅")
        try: bot.send_message(target_id, "🎉 پیرۆزە! هیلال هەموو قەرزەکانی لەسەرت سفر کردەوە.")
        except: pass
        show_clear_debt_menu(call.message.chat.id, call.message.message_id)


# ================== سیستەمی نوێی بەڕێوەبردنی قەرزەکان بە دوگمە (/editdebt) ==================

@bot.message_handler(commands=['editdebt'])
def editdebt_command(message):
    if message.chat.id == ADMIN_ID:
        show_debt_users_menu(message.chat.id)

def show_debt_users_menu(chat_id, message_id=None):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id, name FROM allowed_users')
        users = c.fetchall()

    markup = InlineKeyboardMarkup(row_width=1)
    for uid, name in users:
        disp_name = name if name and name != "نەناسراو" else "نەناسراو"
        markup.add(InlineKeyboardButton(f"👤 {disp_name}", callback_data=f"mdebt_u_{uid}"))

    text = "🛠 **بەڕێوەبردنی قەرزەکان:**\n\nتکایە کڕیارێک هەڵبژێرە بۆ دەستکاریکردنی قەرزەکەی:"
    if message_id:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

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
        markup.add(
            InlineKeyboardButton("➕ زیادکردنی قەرز", callback_data=f"mdebt_act_{uid}_add"),
            InlineKeyboardButton("➖ وەرگرتنی قەرز", callback_data=f"mdebt_act_{uid}_pay")
        )
        markup.add(InlineKeyboardButton("🗑 سفرکردنەوەی قەرز (یەک کلیک)", callback_data=f"mdebt_clear_{uid}"))
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="mdebt_back"))

        text = f"👤 **کڕیار:** {disp_name}\n\n📊 **قەرزی ئێستا:**\nدۆلار: {usd}$\nدینار: {iqd:,} دینار\n\nدەتەوێت چی بکەیت؟"
        
        # گۆڕانکاری بۆ ڕێگریکردن لە هەڵەی "Message is not modified"
        try:
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            pass
    else:
        bot.answer_callback_query(call.id, "کڕیار نەدۆزرایەوە!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_clear_'))
def mdebt_clear_action(call):
    if call.from_user.id != ADMIN_ID: return
    uid = int(call.data.split('_')[2])
    
    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (uid,))
        conn.commit()
        
    bot.answer_callback_query(call.id, "قەرزەکە بەتەواوی سفر کرایەوە! ✅", show_alert=True)
    try: bot.send_message(uid, "🎉 پیرۆزە! هیلال هەموو قەرزەکانی لەسەرت سفر کردەوە.")
    except: pass
    
    # نوێکردنەوەی شاشەکە بۆ بینینی قەرزی نوێ کە بووەتە سفر
    mdebt_user_selected(call)

@bot.callback_query_handler(func=lambda call: call.data == 'mdebt_back')
def mdebt_back_call(call):
    show_debt_users_menu(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_act_'))
def mdebt_action_selected(call):
    parts = call.data.split('_')
    uid = parts[2]
    action = parts[3] 

    action_text = "زیاد بکەیت (بیخەیتە سەری)" if action == 'add' else "کەمی بکەیتەوە (وەری بگریت)"

    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for ctype, price in prices.items():
        buttons.append(InlineKeyboardButton(f"{ctype}$ ({price:,} د)", callback_data=f"mdebt_do_{uid}_{action}_{ctype}"))

    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons):
            markup.add(buttons[i], buttons[i+1])
        else:
            markup.add(buttons[i])

    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data=f"mdebt_u_{uid}"))

    text = f"تکایە ئەو بڕە هەڵبژێرە کە دەتەوێت {action_text}:"
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mdebt_do_'))
def mdebt_do_action(call):
    if call.from_user.id != ADMIN_ID: return
    parts = call.data.split('_')
    uid = int(parts[2])
    action = parts[3]
    ctype = parts[4]

    amount_usd = int(ctype)
    amount_iqd = prices.get(ctype, 0)

    with db_lock:
        c = conn.cursor()
        c.execute('SELECT d.usd, d.iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.user_id = ?', (uid,))
        res = c.fetchone()

        if res:
            current_usd, current_iqd, name = res
            disp_name = name if name and name != "نەناسراو" else "نەناسراو"

            if action == 'add':
                new_usd = current_usd + amount_usd
                new_iqd = current_iqd + amount_iqd
                msg_admin = f"✅ قەرز بە سەرکەوتوویی زیاد کرا!\n\n👤 کڕیار: **{disp_name}**\n➕ زیادکرا: {amount_usd}$ ({amount_iqd:,} د)\n📊 قەرزی نوێ: {new_usd}$"
                msg_user = f"⚠️ **ئاگاداری:**\nبڕی **{amount_usd}$** ({amount_iqd:,} دینار) خرایە سەر قەرزەکانت لەلایەن فرۆشگاوە.\n📊 کۆی گشتی قەرزت ئێستا بوو بە: **{new_usd}$**"
            else: 
                new_usd = current_usd - amount_usd
                if new_usd < 0: new_usd = 0
                new_iqd = current_iqd - amount_iqd
                if new_iqd < 0: new_iqd = 0
                msg_admin = f"✅ پارەکە وەرگیرا!\n\n👤 کڕیار: **{disp_name}**\n➖ کەمکرایەوە: {amount_usd}$ ({amount_iqd:,} د)\n📊 قەرزی ماوە: {new_usd}$"
                msg_user = f"✅ بڕی **{amount_usd}$** ({amount_iqd:,} دینار) لە قەرزەکەت درا بە فرۆشگا.\n📊 قەرزی ماوەت بوو بە: **{new_usd}$**"

            c.execute('UPDATE debts SET usd = ?, iqd = ? WHERE user_id = ?', (new_usd, new_iqd, uid))
            conn.commit()

            bot.answer_callback_query(call.id, "سەرکەوتوو بوو! ✅", show_alert=True)
            try: bot.send_message(uid, msg_user, parse_mode='Markdown')
            except: pass

            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("➕ زیادکردنی قەرز", callback_data=f"mdebt_act_{uid}_add"),
                InlineKeyboardButton("➖ کەمکردنەوە (وەرگرتن)", callback_data=f"mdebt_act_{uid}_pay")
            )
            markup.add(InlineKeyboardButton("🗑 سفرکردنەوەی قەرز (یەک کلیک)", callback_data=f"mdebt_clear_{uid}"))
            markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="mdebt_back"))

            bot.edit_message_text(msg_admin + "\n\nدەتەوێت کارێکی تر بکەیت؟", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

# =========================================================================

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
            bot.reply_to(message, f"بڕی {added_count} کۆدی جۆری {card_type} دۆلاری بە سەرکەوتوویی زیادکرا.")
        except Exception as e:
            bot.reply_to(message, "شێوازی زیادکردن هەڵەیە. نموونە:\n/add 2 XXXXX-XXXXX")

@bot.message_handler(commands=['delcode'])
def manage_codes(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            markup = InlineKeyboardMarkup(row_width=1)
            for ctype, count in results: markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە ماوە)", callback_data=f"viewc_{ctype}"))
            bot.reply_to(message, "تکایە ئەو جۆرە هەڵبژێرە کە دەتەوێت کۆدەکانی ببینی و لایانبەری:", reply_markup=markup)
        else: bot.reply_to(message, "کۆگاکە بەتاڵە، هیچ کۆدێکی تێدا نییە بۆ سڕینەوە.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('viewc_') or call.data.startswith('rmc_') or call.data == 'delcode_back')
def handle_delcode_callbacks(call):
    if call.from_user.id != ADMIN_ID: return
    if call.data == 'delcode_back':
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            markup = InlineKeyboardMarkup(row_width=1)
            for ctype, count in results: markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە ماوە)", callback_data=f"viewc_{ctype}"))
            bot.edit_message_text("تکایە ئەو جۆرە هەڵبژێرە کە دەتەوێت کۆدەکانی ببینی و لایانبەری:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        else: bot.edit_message_text("کۆگاکە بەتاڵە، هیچ کۆدێکی تێدا نییە.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        return
    if call.data.startswith('rmc_'):
        parts = call.data.split('_')
        code_id, card_type = parts[1], parts[2]
        with db_lock:
            c = conn.cursor()
            c.execute('DELETE FROM codes WHERE id = ?', (code_id,))
            conn.commit()
        bot.answer_callback_query(call.id, "کۆدەکە بە سەرکەوتوویی سڕایەوە! ✅")
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
            bot.edit_message_text(f"لیستی کۆدەکانی {ctype}$:\n(بۆ سڕینەوەی هەر دانەیەک تەنها کرتە لە دوگمەکەی بکە)", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        else: bot.answer_callback_query(call.id, f"هیچ کۆدێکی {ctype}$ نەماوە.", show_alert=True)

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
                    msg = "🗑️ **هەموو کۆدەکانی کۆگا بەتەواوی سڕانەوە.**"
                else:
                    c.execute('DELETE FROM codes WHERE card_type = ?', (target,))
                    msg = f"🗑️ هەموو کۆدەکانی جۆری **{target}$** سڕانەوە."
                conn.commit()
                bot.reply_to(message, msg, parse_mode='Markdown')
        except: bot.reply_to(message, "شێواز هەڵەیە.\nبۆ سڕینەوەی جۆرێک: /clearcodes 2\nبۆ سڕینەوەی هەمووی: /clearcodes all")

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
            bot.reply_to(message, f"سنووری قەرزی بەکارهێنەر {target_id} کرا بە {new_limit} دۆلار.")
            bot.send_message(target_id, f"ئاگاداری: سنووری قەرزەکەت لەلایەن هیلال نوێکرایەوە بۆ {new_limit} دۆلار.")
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
            c.execute('''
                SELECT d.user_id, d.usd, d.iqd, d.credit_limit, a.name
                FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id
                WHERE d.usd > 0
            ''')
            results = c.fetchall()
        if results:
            msg = "📒 **دەفتەری قەرزەکان:**\n\n"
            tot_usd, tot_iqd = 0, 0
            for uid, usd, iqd, limit, name in results:
                disp_name = name if name and name != "نەناسراو" else "نەناسراو"
                msg += f"👤 **{disp_name}** | ئایدی: `{uid}`\n💸 قەرز: {usd}$ ({iqd:,} د) | سنور: {usd}$/{limit}$\n\n"
                tot_usd += usd
                tot_iqd += iqd
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
                try:
                    bot.send_message(uid, f"📢 **ئاگاداری لە فرۆشگا:**\n\n{text}", parse_mode='Markdown')
                    count += 1
                except: pass
            bot.reply_to(message, f"نامەکە بۆ {count} بەکارهێنەر نێردرا.")
        else: bot.reply_to(message, "تکایە دەقەکەی لەپێش بنووسە: /broadcast پەیامەکەت لێرە")

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
                    bot.send_message(uid, update_msg, parse_mode='Markdown')
                    count += 1
                except: pass
            bot.reply_to(message, f"✅ نامەی نوێکاری بە سەرکەوتوویی بۆ {count} کڕیار نێردرا.")
        else: bot.reply_to(message, "تکایە دەقەکەی لەپێش بنووسە. نموونە:\n`/update سەبەتەی کڕین بۆ فرۆشگاکەمان زیاد کرا!`", parse_mode='Markdown')

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if message.chat.id == ADMIN_ID:
        try:
            with open('itunes_store_v5.db', 'rb') as doc:
                bot.send_document(message.chat.id, doc, caption="💾 **ئەمە فایلی داتابەیسەکەتە (باکئەپ).**\n\nتەواوی کۆدەکان، قەرزەکان، و کڕیارەکانی تێدایە. دەتوانیت ئەم فایلە لای خۆت بپارێزیت.", parse_mode='Markdown')
        except Exception as e: bot.reply_to(message, f"کێشەیەک هەیە لە ناردنی فایلەکە: {e}")

@bot.message_handler(commands=['restore'])
def restore_instructions(message):
    if message.chat.id == ADMIN_ID: bot.reply_to(message, "بۆ گەڕاندنەوەی زانیارییەکان (Restore)، تکایە تەنها ئەو فایلە باکئەپەی کە پێشتر وەرتگرتووە (`itunes_store_v5.db`) ڕاستەوخۆ بنێرە بۆ ئێرە و بۆتەکە خۆی دەیخوێنێتەوە.")

@bot.message_handler(content_types=['document'])
def handle_database_restore(message):
    global conn
    if message.chat.id == ADMIN_ID:
        if message.document.file_name.endswith('.db'):
            try:
                bot.reply_to(message, "⏳ خەریکی خوێندنەوەی فایلەکەم...")
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                with db_lock:
                    conn.close()
                    with open('itunes_store_v5.db', 'wb') as new_file: new_file.write(downloaded_file)
                    conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)
                bot.reply_to(message, "✅ داتابەیسەکە بە سەرکەوتوویی گەڕێندرایەوە (Restore). هەموو کۆدەکان، قەرزەکان و کڕیارەکان گەڕانەوە شوێنی خۆیان!")
            except Exception as e:
                bot.reply_to(message, f"❌ کێشەیەک ڕوویدا لە کاتی گەڕاندنەوەدا: {e}")
                conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)
        else: bot.reply_to(message, "ئەمە فایلی داتابەیس نییە. تکایە تەنها فایلی `.db` بنێرە.")

def send_buy_menu(chat_id, message_id=None):
    markup = InlineKeyboardMarkup(row_width=1)
    for ctype, price in prices.items():
        markup.add(InlineKeyboardButton(f"{ctype} دۆلاری - {price:,} دینار", callback_data=f"buy_{ctype}"))
    
    cart = user_carts.get(chat_id, {})
    if cart:
        total_items = sum(cart.values())
        markup.add(
            InlineKeyboardButton(f"🛒 بینینی سەبەتەکەم ({total_items} کاڵا)", callback_data="viewcart"),
            InlineKeyboardButton("🗑 بەتاڵکردنەوەی سەبەتە", callback_data="emptycart")
        )
        
    text = "تکایە جۆری کارت هەڵبژێرە:"
    if message_id:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["🛒 کڕینی کارت", "💰 قەرزەکانم", "📜 مێژووی کڕینەکان", "📦 ئاماری کۆگا"])
def handle_text_buttons(message):
    uid = message.from_user.id
    if not is_allowed(uid): return

    if message.text == "🛒 کڕینی کارت":
        status, reason = get_store_status()
        if status == "closed":
            bot.reply_to(message, f"🚫 **فرۆشگا داخراوە**\n\n{reason}", parse_mode='Markdown')
            return
        ban_time = get_ban_status(uid)
        if ban_time:
            bot.reply_to(message, f"⚠️ تۆ سزادراویت و ناتوانیت کڕین بکەیت تا بەرواری:\n`{ban_time.strftime('%Y-%m-%d %H:%M:%S')}`", parse_mode='Markdown')
            return
        send_buy_menu(message.chat.id)

    elif message.text == "💰 قەرزەکانم":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT usd, iqd, credit_limit FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
        if res and res[0] > 0:
            usd, iqd, limit = res
            bot.reply_to(message, f"تۆ بڕی **{usd} دۆلار** قەرزاری ({iqd:,} دینار).\nسنووری قەرزی ڕێگەپێدراوت: **{limit} دۆلار**.", parse_mode='Markdown')
        else:
            bot.reply_to(message, "تۆ هیچ قەرزار نیت! 🌸")

    elif message.text == "📜 مێژووی کڕینەکان":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, price, code, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 5', (uid,))
            hist = c.fetchall()
        if hist:
            msg = "📜 **کۆتا کڕینەکانت:**\n\n"
            for ctype, prc, cd, dt in hist:
                msg += f"💳 کارتی {ctype} | {prc:,} د\n{cd}\nبەروار: {dt}\n------------------\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else:
            bot.reply_to(message, "تۆ هیچ کڕینێکت نەبووە.")

    elif message.text == "📦 ئاماری کۆگا":
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            msg = "📦 **ئاماری کارتی بەردەست لە کۆگادا:**\n\n"
            for card_type, count in results:
                msg += f"کارتی {card_type}$ : **{count}** دانە ماوە\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else:
            bot.reply_to(message, "لە ئێستادا کۆگا بەتاڵە، چاوەڕێی نوێکردنەوە بن. 🌸")

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_buy')
def back_to_buy_callback(call):
    if not is_allowed(call.from_user.id): return
    send_buy_menu(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy_mode_selection(call):
    uid = call.from_user.id
    if not is_allowed(uid): return

    status, reason = get_store_status()
    if status == "closed":
        bot.answer_callback_query(call.id, reason, show_alert=True)
        return

    ctype = call.data.split('_')[1]
    cart = user_carts.get(uid, {})
    
    if cart:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("1 دانە", callback_data=f"addcart_{ctype}_1"),
            InlineKeyboardButton("2 دانە", callback_data=f"addcart_{ctype}_2")
        )
        markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy"))
        bot.edit_message_text(f"🛒 **زیادکردن بۆ سەبەتە (کارتی {ctype}$)**\n\nتکایە ژمارەی کارتەکان دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("⚡ کڕینی خێرا", callback_data=f"mode_quick_{ctype}"),
            InlineKeyboardButton("🛒 خستنە سەبەتە", callback_data=f"mode_cart_{ctype}"),
            InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy")
        )
        bot.edit_message_text(f"💳 **کارتی {ctype} دۆلاری**\n\nتکایە شێوازی کڕین هەڵبژێرە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('mode_quick_'))
def handle_mode_quick(call):
    ctype = call.data.split('_')[2]
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("1 دانە", callback_data=f"quickbuy_{ctype}_1"),
        InlineKeyboardButton("2 دانە", callback_data=f"quickbuy_{ctype}_2")
    )
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data=f"buy_{ctype}"))
    bot.edit_message_text(f"⚡ **کڕینی خێرا (کارتی {ctype}$)**\n\nتکایە ژمارەی کارتەکان دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('mode_cart_'))
def handle_mode_cart(call):
    ctype = call.data.split('_')[2]
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("1 دانە", callback_data=f"addcart_{ctype}_1"),
        InlineKeyboardButton("2 دانە", callback_data=f"addcart_{ctype}_2")
    )
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data=f"buy_{ctype}"))
    bot.edit_message_text(f"🛒 **خستنە سەبەتە (کارتی {ctype}$)**\n\nتکایە ژمارەی کارتەکان دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('addcart_'))
def handle_add_cart(call):
    uid = call.from_user.id
    if not is_allowed(uid): return

    parts = call.data.split('_')
    ctype = parts[1]
    qty = int(parts[2])

    if uid not in user_carts:
        user_carts[uid] = {}
    
    current_in_cart = user_carts[uid].get(ctype, 0)
    
    if current_in_cart + qty > 2:
        bot.answer_callback_query(call.id, "⚠️ ناتوانیت لە ٢ دانە زیاتر لە یەک جۆری کارت بخەیتە سەبەتەوە!", show_alert=True)
        return
        
    user_carts[uid][ctype] = current_in_cart + qty
    bot.answer_callback_query(call.id, f"✅ {qty} کارتی {ctype}$ خرایە سەبەتەکەتەوە!")
    
    call.data = 'viewcart'
    handle_view_cart(call)

@bot.callback_query_handler(func=lambda call: call.data == 'emptycart')
def handle_empty_cart(call):
    uid = call.from_user.id
    user_carts.pop(uid, None)
    bot.answer_callback_query(call.id, "سەبەتەکەت بەتاڵ کرایەوە! 🗑", show_alert=True)
    send_buy_menu(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == 'viewcart')
def handle_view_cart(call):
    uid = call.from_user.id
    cart = user_carts.get(uid, {})
    
    if not cart:
        bot.answer_callback_query(call.id, "سەبەتەکەت بەتاڵە!", show_alert=True)
        send_buy_menu(call.message.chat.id, call.message.message_id)
        return

    text = "🛒 **ناوەڕۆکی سەبەتەکەت:**\n\n"
    total_usd = 0
    total_iqd = 0
    
    for ctype, qty in cart.items():
        price = prices.get(ctype, 0) * qty
        usd = int(ctype) * qty
        total_usd += usd
        total_iqd += price
        text += f"▫️ {qty} دانە کارتی {ctype}$ = {price:,} دینار\n"
        
    text += f"\n💰 **کۆی گشتی:** {total_usd}$ ({total_iqd:,} دینار)"
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("✅ پشتڕاستکردنەوە و کڕینی سەبەتە", callback_data="checkout"))
    markup.add(InlineKeyboardButton("➕ زیادکردنی کارتی تر بۆ سەبەتە", callback_data="back_to_buy"))
    markup.add(InlineKeyboardButton("🗑 بەتاڵکردنەوە", callback_data="emptycart"))
    
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

def get_codes_for_purchase(c, ctype, qty, used_ids):
    def get_avail(target_type, needed):
        if not used_ids:
            c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT ?', (target_type, needed))
        else:
            placeholders = ','.join(['?'] * len(used_ids))
            query = f'SELECT id, code FROM codes WHERE card_type = ? AND id NOT IN ({placeholders}) LIMIT ?'
            params = [target_type] + list(used_ids) + [needed]
            c.execute(query, params)
        return c.fetchall()

    if ctype != '6':
        res = get_avail(ctype, qty)
        if len(res) == qty:
            return res
        return None
    else:
        res3 = get_avail('3', qty * 2)
        if len(res3) == qty * 2:
            return res3
        res4 = get_avail('4', qty)
        res2 = get_avail('2', qty)
        if len(res4) == qty and len(res2) == qty:
            return res4 + res2
        return None

def process_checkout(call, uid, cart_dict, is_quickbuy=False):
    status, reason = get_store_status()
    if status == "closed":
        bot.answer_callback_query(call.id, reason, show_alert=True)
        return

    ban_time = get_ban_status(uid)
    if ban_time:
        bot.answer_callback_query(call.id, f"تۆ سزادراویت! تا: {ban_time.strftime('%Y-%m-%d %H:%M')}", show_alert=True)
        return

    total_usd = 0
    total_iqd = 0
    for ctype, qty in cart_dict.items():
        total_usd += int(ctype) * qty
        total_iqd += prices.get(ctype, 0) * qty

    user_tg_name = call.from_user.first_name

    with db_lock:
        c = conn.cursor()
        c.execute('SELECT name FROM allowed_users WHERE user_id = ?', (uid,))
        n_res = c.fetchone()
        db_user_name = n_res[0] if n_res and n_res[0] else user_tg_name
        
        c.execute('SELECT usd, credit_limit FROM debts WHERE user_id = ?', (uid,))
        d_res = c.fetchone()

    current_debt = d_res[0] if d_res else 0
    limit = d_res[1] if d_res else 25

    if current_debt + total_usd > limit:
        bot.answer_callback_query(call.id, f"ناتوانیت! گەیشتووی بە سنووری قەرز ({limit}$).", show_alert=True)
        bot.send_message(uid, f"⚠️ داواکاری کڕینت ڕەتکرایەوە چونکە قەرزەکەت دەگاتە سەروو سنووری ڕێگەپێدراو ({limit}$).")
        return

    with db_lock:
        c = conn.cursor()
        all_assigned_codes = []
        used_ids = set()
        can_fulfill = True
        
        for ctype, qty in cart_dict.items():
            res = get_codes_for_purchase(c, ctype, qty, used_ids)
            if not res:
                can_fulfill = False
                break
            for cid, code in res:
                all_assigned_codes.append((cid, code, ctype))
                used_ids.add(cid)

        if not can_fulfill:
            bot.answer_callback_query(call.id, "ببورە، کارتی پێویست لە کۆگادا نەماوە بۆ داواکارییەکەت.", show_alert=True)
            return

        code_texts = []
        for cid, code, ctype in all_assigned_codes:
            c.execute('DELETE FROM codes WHERE id = ?', (cid,))
            code_texts.append(f"▫️ کارتی {ctype}$: `{code}`")

        c.execute('INSERT OR IGNORE INTO debts (user_id, usd, iqd, credit_limit) VALUES (?, 0, 0, 25)', (uid,))
        c.execute('UPDATE debts SET usd = usd + ?, iqd = iqd + ? WHERE user_id = ?', (total_usd, total_iqd, uid))
        
        history_desc = ", ".join([f"{ct}$ (x{q})" for ct, q in cart_dict.items()])
        history_codes = "\n".join(code_texts)
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, history_desc, total_iqd, history_codes))
        conn.commit()

    receipt = (
        "🧾 **پسوڵەی کڕین (ڕەسمی)**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **کڕیار:** {db_user_name}\n"
        f"📅 **بەروار:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛒 **کاڵاکان:**\n"
    )
    for ct, q in cart_dict.items():
        receipt += f"▫️ {q}x کارتی {ct}$ = {prices.get(ct,0)*q:,} دینار\n"
    
    receipt += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **کۆی گشتی دۆلار:** {total_usd}$\n"
        f"💵 **کۆی گشتی دینار:** {total_iqd:,} دینار\n"
        f"📊 **کۆی قەرزی نوێ:** {current_debt + total_usd}$ (لە {limit}$)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 **کۆدەکان:** (بۆ کۆپیکردن کرتە لە کۆدەکە بکە)\n\n"
    )
    
    for cid, code, ct in all_assigned_codes:
         receipt += f" `{code}`\n"
    
    receipt += "\nزۆر سوپاس بۆ متمانەت! 🍏 هیلال"

    if not is_quickbuy:
        user_carts.pop(uid, None)
    
    bot.answer_callback_query(call.id, "کڕینەکەت سەرکەوتوو بوو! ✅")
    
    receipt_id = str(int(time.time())) + "_" + str(uid)
    pending_refunds[receipt_id] = {
        'uid': uid,
        'codes': all_assigned_codes,
        'total_usd': total_usd,
        'total_iqd': total_iqd,
        'expiry': time.time() + 30,
        'history_desc': history_desc,
        'db_user_name': db_user_name
    }
    
    refund_markup = InlineKeyboardMarkup()
    refund_markup.add(InlineKeyboardButton("↩️ گەڕاندنەوەی کارت (لەماوەی ٣٠ چرکەدا)", callback_data=f"refund_{receipt_id}"))
    
    bot.edit_message_text(receipt, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=refund_markup)

    username = f"@{call.from_user.username}" if call.from_user.username else "بوونی نییە"
    admin_msg = f"🛒 **کڕینێکی نوێ ئەنجامدرا!**\n\nناو: {db_user_name}\nیوزەرنەیم: {username}\nئایدی: `{uid}`\nکڕیارەکە ئەمەی کڕی: {history_desc}\n\n{receipt}"
    bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('quickbuy_'))
def handle_quickbuy(call):
    uid = call.from_user.id
    if not is_allowed(uid): return
    parts = call.data.split('_')
    ctype = parts[1]
    qty = int(parts[2])
    cart_dict = {ctype: qty}
    process_checkout(call, uid, cart_dict, is_quickbuy=True)

@bot.callback_query_handler(func=lambda call: call.data == 'checkout')
def handle_checkout_cart(call):
    uid = call.from_user.id
    if not is_allowed(uid): return
    cart_dict = user_carts.get(uid, {})
    if not cart_dict:
        bot.answer_callback_query(call.id, "سەبەتەکەت بەتاڵە!", show_alert=True)
        return
    process_checkout(call, uid, cart_dict, is_quickbuy=False)

@bot.callback_query_handler(func=lambda call: call.data.startswith('refund_'))
def handle_refund_request(call):
    receipt_id = call.data.split('_')[1] + "_" + call.data.split('_')[2]
    
    if receipt_id not in pending_refunds:
        bot.answer_callback_query(call.id, "ئەم پسوڵەیە کاتی گەڕاندنەوەی بەسەر چووە یان پێشتر گەڕێندراوەتەوە!", show_alert=True)
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return
        
    refund_data = pending_refunds[receipt_id]
    
    if time.time() > refund_data['expiry']:
        bot.answer_callback_query(call.id, "کاتەکەت تەواو بووە (٣٠ چرکە تێپەڕیوە)، ناتوانیت بیگەڕێنیتەوە!", show_alert=True)
        del pending_refunds[receipt_id]
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        return
        
    uid = refund_data['uid']
    codes_to_return = refund_data['codes']
    refund_usd = refund_data['total_usd']
    refund_iqd = refund_data['total_iqd']
    desc = refund_data['history_desc']
    u_name = refund_data['db_user_name']
    
    with db_lock:
        c = conn.cursor()
        code_texts_for_admin = []
        
        for cid, code, ctype in codes_to_return:
            c.execute('INSERT INTO codes (card_type, code) VALUES (?, ?)', (ctype, code))
            code_texts_for_admin.append(f"▫️ کارتی {ctype}$: `{code}`")
            
        c.execute('UPDATE debts SET usd = usd - ?, iqd = iqd - ? WHERE user_id = ?', (refund_usd, refund_iqd, uid))
        
        c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, f"گەڕاندنەوە: {desc}", -refund_iqd, "کۆدەکان گەڕێندرانەوە ناو کۆگا"))
        conn.commit()
        
    del pending_refunds[receipt_id]
    
    bot.answer_callback_query(call.id, "کڕینەکە هەڵوەشایەوە و کۆدەکان گەڕێندرانەوە! ✅", show_alert=True)
    
    new_text = (
        "🧾 **پسوڵەی هەڵوەشاوە** ❌\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"ئەم کڕینە بە سەرکەوتوویی هەڵوەشایەوە.\n\n"
        f"کڕیار: {u_name}\n"
        f"بڕی گەڕێندراو: {desc}\n"
        f"پارەی سڕاوە لە قەرز: {refund_usd}$ ({refund_iqd:,} دینار)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 **کۆدەکان شاردرانەوە و گەڕێندرانەوە بۆ ناو کۆگا.**\n"
        "هیچ بڕە پارەیەک بۆ ئەم پسوڵەیە نەچووەتە سەر قەرزەکانت."
    )
    bot.edit_message_text(new_text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
    
    codes_str = "\n".join(code_texts_for_admin)
    admin_msg = (
        "⚠️ **ئاگاداری: گەڕاندنەوەی کارت!**\n\n"
        f"👤 کڕیار: {u_name}\n"
        f"🆔 ئایدی: `{uid}`\n"
        f"بڕی گەڕێندراو: {desc}\n"
        f"پاشەکەوتی قەرز: گەڕێندرایەوە ({refund_usd}$ لە قەرزەکەی سڕایەوە)\n\n"
        "**ئەم کۆدانەی خوارەوە سەلامەتن و گەڕانەوە ناو کۆگا:**\n"
        f"{codes_str}"
    )
    bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')

def setup_bot_commands():
    user_commands = [
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن بە خاوەن فرۆشگا")
    ]
    
    admin_commands = [
        BotCommand("start", "🚀 دەستپێکردنی بۆت"),
        BotCommand("about", "ℹ️ دەربارەی فرۆشگا"),
        BotCommand("contact", "📞 پەیوەندیکردن"),
        BotCommand("allow", "✅ ڕێگەپێدان بە کڕیار"),
        BotCommand("remove", "❌ سڕینەوەی کڕیار"),
        BotCommand("setname", "✏️ گۆڕینی ناوی کڕیار"),
        BotCommand("ban", "🚫 سزادانی کڕیار"),
        BotCommand("unban", "♻️ لابردنی سزا"),
        BotCommand("users", "👥 لیستی کڕیارەکان"),
        BotCommand("editdebt", "🛠 دەستکاریکردنی قەرز (بە دوگمە)"),
        BotCommand("clear", "💸 سفرکردنەوەی قەرز (بە دوگمە)"),
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
        BotCommand("backup", "💾 وەرگرتنی باکئەپ (فایل)"),
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
        for rid in to_delete:
            del pending_refunds[rid]
        
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
                    start_t = res_start[0]
                    end_t = res_end[0]
                    
                    c.execute('SELECT value FROM settings WHERE key="last_auto_trigger"')
                    last_trigger = c.fetchone()
                    last_t = last_trigger[0] if last_trigger else ""
                    trigger_key = f"{now.strftime('%Y-%m-%d')}_{current_hm}"
                    
                    if current_hm == start_t and last_t != trigger_key:
                        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("last_auto_trigger", ?)', (trigger_key,))
                        c.execute('SELECT value FROM settings WHERE key="store_status"')
                        curr_st = c.fetchone()[0]
                        
                        if curr_st != "closed":
                            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("closed",))
                            c.execute('UPDATE settings SET value=? WHERE key="close_reason"', (f"فرۆشگا بەشێوەی ئۆتۆماتیکی داخرا لە کاتژمێر {start_t} تا {end_t}.",))
                            c.execute('SELECT user_id FROM allowed_users')
                            users = c.fetchall()
                            conn.commit()
                            for (uid,) in users:
                                try: bot.send_message(uid, f"📢 **ئاگاداری لە فرۆشگاوە:**\n\n🔒 فرۆشگا داخرا.\nئەمە سیستەمی داخستنی ئۆتۆماتیکییە تا کاتژمێر {end_t}.", parse_mode='Markdown')
                                except: pass
                        else:
                            conn.commit()
                            
                    elif current_hm == end_t and last_t != trigger_key:
                        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("last_auto_trigger", ?)', (trigger_key,))
                        c.execute('SELECT value FROM settings WHERE key="store_status"')
                        curr_st = c.fetchone()[0]
                        
                        if curr_st != "open":
                            c.execute('UPDATE settings SET value=? WHERE key="store_status"', ("open",))
                            c.execute('SELECT user_id FROM allowed_users')
                            users = c.fetchall()
                            conn.commit()
                            for (uid,) in users:
                                try: bot.send_message(uid, f"📢 **ئاگاداری لە فرۆشگاوە:**\n\n🔓 فرۆشگاکە ئێستا کرایەوە! 🍏\nدەتوانن کڕینەکانتان ئەنجام بدەن.", parse_mode='Markdown')
                                except: pass
                        else:
                            conn.commit()
        time.sleep(30)

checker_thread = threading.Thread(target=auto_schedule_checker, daemon=True)
checker_thread.start()

print("بۆتەکە ئێستا کار دەکات و فەرمانەکان جیاکرانەوە...")
setup_bot_commands()
bot.infinity_polling()
