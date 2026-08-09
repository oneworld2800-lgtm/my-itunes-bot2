import telebot
import sqlite3
import threading
import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

TOKEN = '8781704084:AAF82RxWrCRkzOlLFKdi891FmhPMuqRPbcI'
bot = telebot.TeleBot(TOKEN)
ADMIN_ID = 1229224919

conn = sqlite3.connect('itunes_store_v5.db', check_same_thread=False)
db_lock = threading.Lock()

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
        with db_lock:
            c = conn.cursor()
            c.execute('UPDATE allowed_users SET name = ? WHERE user_id = ?', (message.from_user.first_name, user_id))
            conn.commit()
        bot.reply_to(message, "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس.\nتکایە لە دوگمەکانی خوارەوە هەڵبژێرە:", reply_markup=get_main_menu(user_id))
    else:
        bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە و تەنها بۆ کەسانی ڕێگەپێدراوە.\n\nئایدی تۆ: `{user_id}`\nئەم ئایدییە بنێرە بۆ خاوەنی بۆتەکە.", parse_mode='Markdown')

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
            if duration_unit == 'h':
                ban_until = now + datetime.timedelta(hours=duration_val)
            elif duration_unit == 'd':
                ban_until = now + datetime.timedelta(days=duration_val)
            else:
                raise ValueError

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


# ---------------- بەشی نوێ: سفرکردنەوەی قەرزەکان بە لیستی زیرەک ---------------- #
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

        text = "تکایە ئەو کەسە هەڵبژێرە کە دەتەوێت قەرزەکەی سفر بکەیتەوە:"
        if message_id:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        else:
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        text = "هیچ کەسێک قەرزدار نییە لە ئێستادا. 🌸"
        if message_id:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
        else:
            bot.send_message(chat_id, text)

@bot.message_handler(commands=['clear'])
def clear_debt(message):
    if message.chat.id == ADMIN_ID:
        args = message.text.split()[1:]
        # ئەگەر تەنها نووسی /clear بێ هیچ شتێک، لیستەکە دەکرێتەوە
        if not args:
            show_clear_debt_menu(message.chat.id)
            return

        # ئەگەر ئایدی یان وشەی all ی نووسی (بۆ شێوازی کۆن)
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
                        try:
                            bot.send_message(target_id, "🎉 پیرۆزە! خاوەن فرۆشگا هەموو قەرزەکانی لەسەرت سفر کردەوە.")
                        except:
                            pass
                    except ValueError:
                        pass
                conn.commit()
                bot.reply_to(message, f"✅ قەرزی **{cleared_count}** بەکارهێنەر بە سەرکەوتوویی سفر کرایەوە.", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('cd_'))
def handle_clear_debt_callback(call):
    if call.from_user.id != ADMIN_ID:
        return

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
        try:
            bot.send_message(target_id, "🎉 پیرۆزە! خاوەن فرۆشگا هەموو قەرزەکانی لەسەرت سفر کردەوە.")
        except:
            pass
        # دوای سفرکردنەوەی کەسەکە، لیستەکە نوێ دەکەینەوە
        show_clear_debt_menu(call.message.chat.id, call.message.message_id)
# -------------------------------------------------------------------------------- #


@bot.message_handler(commands=['add'])
def add_codes(message):
    if message.chat.id == ADMIN_ID:
        try:
            lines = message.text.split('\n')
            first_line_parts = lines[0].split()
            card_type = first_line_parts[1]

            codes_to_add = []
            if len(first_line_parts) > 2:
                codes_to_add.append(" ".join(first_line_parts[2:]))

            for line in lines[1:]:
                clean_line = line.strip()
                if clean_line:
                    codes_to_add.append(clean_line)

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
            for ctype, count in results:
                markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە ماوە)", callback_data=f"viewc_{ctype}"))
            bot.reply_to(message, "تکایە ئەو جۆرە هەڵبژێرە کە دەتەوێت کۆدەکانی ببینی و لایانبەری:", reply_markup=markup)
        else:
            bot.reply_to(message, "کۆگاکە بەتاڵە، هیچ کۆدێکی تێدا نییە بۆ سڕینەوە.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('viewc_') or call.data.startswith('rmc_') or call.data == 'delcode_back')
def handle_delcode_callbacks(call):
    if call.from_user.id != ADMIN_ID:
        return

    if call.data == 'delcode_back':
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            markup = InlineKeyboardMarkup(row_width=1)
            for ctype, count in results:
                markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە ماوە)", callback_data=f"viewc_{ctype}"))
            bot.edit_message_text("تکایە ئەو جۆرە هەڵبژێرە کە دەتەوێت کۆدەکانی ببینی و لایانبەری:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        else:
            bot.edit_message_text("کۆگاکە بەتاڵە، هیچ کۆدێکی تێدا نییە.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        return

    if call.data.startswith('rmc_'):
        parts = call.data.split('_')
        code_id = parts[1]
        card_type = parts[2]
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
            for cid, code in codes:
                markup.add(InlineKeyboardButton(f"❌ سڕینەوە: {code}", callback_data=f"rmc_{cid}_{ctype}"))
            markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="delcode_back"))

            bot.edit_message_text(f"لیستی کۆدەکانی {ctype}$:\n(بۆ سڕینەوەی هەر دانەیەک تەنها کرتە لە دوگمەکەی بکە)", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        else:
            bot.answer_callback_query(call.id, f"هیچ کۆدێکی {ctype}$ نەماوە.", show_alert=True)
            with db_lock:
                c = conn.cursor()
                c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
                results = c.fetchall()
            if results:
                markup = InlineKeyboardMarkup(row_width=1)
                for ctype, count in results:
                    markup.add(InlineKeyboardButton(f"جۆری {ctype}$ ({count} دانە ماوە)", callback_data=f"viewc_{ctype}"))
                bot.edit_message_text("تکایە ئەو جۆرە هەڵبژێرە کە دەتەوێت کۆدەکانی ببینی و لایانبەری:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
            else:
                bot.edit_message_text("کۆگاکە بەتاڵە.", chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.message_handler(commands=['clearcodes'])
def clear_codes(message):
    if message.chat.id == ADMIN_ID:
        try:
            target = message.text.replace('/clearcodes ', '').strip()
            if not target:
                raise ValueError

            with db_lock:
                c = conn.cursor()
                if target.lower() == 'all':
                    c.execute('DELETE FROM codes')
                    msg = "🗑️ **هەموو کۆدەکانی کۆگا بەتەواوی سڕانەوە.** کۆگاکە ئێستا خاڵییە."
                else:
                    c.execute('DELETE FROM codes WHERE card_type = ?', (target,))
                    msg = f"🗑️ هەموو کۆدەکانی جۆری **{target}$** سڕانەوە."
                conn.commit()
                bot.reply_to(message, msg, parse_mode='Markdown')
        except:
            bot.reply_to(message, "شێواز هەڵەیە.\nبۆ سڕینەوەی جۆرێک: /clearcodes 2\nبۆ سڕینەوەی هەمووی: /clearcodes all")

@bot.message_handler(commands=['setlimit'])
def set_limit(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split()
            target_id = int(parts[1])
            new_limit = int(parts[2])
            with db_lock:
                c = conn.cursor()
                c.execute('UPDATE debts SET credit_limit = ? WHERE user_id = ?', (new_limit, target_id))
                conn.commit()
            bot.reply_to(message, f"سنووری قەرزی بەکارهێنەر {target_id} کرا بە {new_limit} دۆلار.")
            bot.send_message(target_id, f"ئاگاداری: سنووری قەرزەکەت لەلایەن خاوەن فرۆشگاوە نوێکرایەوە بۆ {new_limit} دۆلار.")
        except:
            bot.reply_to(message, "شێواز هەڵەیە: /setlimit ID AMOUNT")

@bot.message_handler(commands=['stock'])
def check_stock(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()

        if results:
            msg = "📊 **ئاماری کۆگا:**\n\n"
            for card_type, count in results:
                msg += f"کارتی {card_type}$ : **{count}** دانە\n"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else:
            bot.reply_to(message, "کۆگا بەتاڵە.")

@bot.message_handler(commands=['debts'])
def check_all_debts(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('''
                SELECT d.user_id, d.usd, d.iqd, d.credit_limit, a.name
                FROM debts d
                LEFT JOIN allowed_users a ON d.user_id = a.user_id
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
        else:
            bot.reply_to(message, "هیچ قەرزێک نییە.")

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
                except:
                    pass
            bot.reply_to(message, f"نامەکە بۆ {count} بەکارهێنەر نێردرا.")
        else:
            bot.reply_to(message, "تکایە دەقەکەی لەپێش بنووسە: /broadcast پەیامەکەت لێرە")

def send_buy_menu(message):
    if is_allowed(message.from_user.id):
        markup = InlineKeyboardMarkup(row_width=1)
        for ctype, price in prices.items():
            markup.add(InlineKeyboardButton(f"{ctype} دۆلاری - {price:,} دینار", callback_data=f"buy_{ctype}"))
        bot.reply_to(message, "تکایە جۆری کارت هەڵبژێرە:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["🛒 کڕینی کارت", "💰 قەرزەکانم", "📜 مێژووی کڕینەکان", "📦 ئاماری کۆگا"])
def handle_text_buttons(message):
    uid = message.from_user.id
    if not is_allowed(uid): return

    if message.text == "🛒 کڕینی کارت":
        ban_time = get_ban_status(uid)
        if ban_time:
            bot.reply_to(message, f"⚠️ تۆ سزادراویت و ناتوانیت کڕین بکەیت تا بەرواری:\n`{ban_time.strftime('%Y-%m-%d %H:%M:%S')}`", parse_mode='Markdown')
            return
        send_buy_menu(message)

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
                msg += f"💳 کارتی {ctype}$ | {prc:,} د\nکۆد: `{cd}`\nبەروار: {dt}\n------------------\n"
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy(call):
    uid = call.from_user.id
    if not is_allowed(uid):
        bot.answer_callback_query(call.id, "ڕێگەپێدراو نیت.", show_alert=True)
        return

    ban_time = get_ban_status(uid)
    if ban_time:
        bot.answer_callback_query(call.id, f"تۆ سزادراویت! ناتوانیت کڕین بکەیت تا: {ban_time.strftime('%Y-%m-%d %H:%M')}", show_alert=True)
        return

    user_name = call.from_user.first_name
    ctype = call.data.split('_')[1]

    with db_lock:
        c = conn.cursor()
        c.execute('UPDATE allowed_users SET name = ? WHERE user_id = ?', (user_name, uid))
        c.execute('SELECT usd, credit_limit FROM debts WHERE user_id = ?', (uid,))
        d_res = c.fetchone()

    current_debt = d_res[0] if d_res else 0
    limit = d_res[1] if d_res else 25

    requested_usd = int(ctype)
    if current_debt + requested_usd > limit:
        bot.answer_callback_query(call.id, f"ناتوانیت! گەیشتووی بە سنووری قەرز ({limit}$).", show_alert=True)
        bot.send_message(uid, f"⚠️ داواکاری کڕینت ڕەتکرایەوە چونکە قەرزەکەت دەگاتە سەروو سنووری ڕێگەپێدراو ({limit}$).")
        return

    with db_lock:
        c = conn.cursor()
        c.execute('SELECT id, code FROM codes WHERE card_type = ? LIMIT 1', (ctype,))
        res = c.fetchone()

        if res:
            cid, code = res
            c.execute('DELETE FROM codes WHERE id = ?', (cid,))

            prc = prices.get(ctype, 0)
            c.execute('INSERT OR IGNORE INTO debts (user_id, usd, iqd, credit_limit) VALUES (?, 0, 0, 25)', (uid,))
            c.execute('UPDATE debts SET usd = usd + ?, iqd = iqd + ? WHERE user_id = ?', (requested_usd, prc, uid))
            c.execute('INSERT INTO history (user_id, card_type, price, code) VALUES (?, ?, ?, ?)', (uid, ctype, prc, code))
            conn.commit()

    if res:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"سوپاس! بڕی {prc:,} دینار چووە سەر قەرزەکەت.\n\nکۆدەکەت:\n`{code}`", parse_mode='Markdown')

        username = f"@{call.from_user.username}" if call.from_user.username else "بوونی نییە"
        admin_msg = f"کەسێک کارتی {ctype}$ی کڕی:\nناو: {user_name}\nیوزەرنەیم: {username}\nئایدی: `{uid}`\n(بڕی {prc:,} دینار / {requested_usd}$ چووە سەر قەرزەکانی)"
        bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, f"کارتی {ctype}$ لە کۆگادا نەماوە.", show_alert=True)

print("بۆتەکە ئێستا کار دەکات...")
bot.polling(none_stop=True)
