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
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("autoclose", "")')
        conn.commit()

init_db()

prices = {'2': 3000, '3': 4500, '4': 6000, '5': 7000, '10': 14000, '15': 22000}

# ================== یارمەتیدەرەکان ==================
def get_users_markup(prefix):
    markup = InlineKeyboardMarkup(row_width=2)
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id, name FROM allowed_users')
        users = c.fetchall()
    
    buttons = [InlineKeyboardButton(name, callback_data=f"{prefix}_{uid}") for uid, name in users]
    for i in range(0, len(buttons), 2):
        if i+1 < len(buttons): markup.add(buttons[i], buttons[i+1])
        else: markup.add(buttons[i])
        
    if prefix == 'clrD':
        markup.add(InlineKeyboardButton("🗑 سفرکردنەوەی هەمووی", callback_data=f"{prefix}_all"))
    return markup

def is_allowed(user_id):
    if user_id == ADMIN_ID: return True
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id FROM bans WHERE user_id = ?', (user_id,))
        if c.fetchone(): return False
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
    markup.add(KeyboardButton("💰 قەرزەکانم"), KeyboardButton("📜 مێژووی کڕینەکان"))
    markup.add(KeyboardButton("📦 ئاماری کۆگا"), KeyboardButton("✅ قەرزەکەم داوەتەوە"))
    return markup

# ================== فەرمانەکانی ئەدمین (بەپێی لیستەکەت) ==================

@bot.message_handler(commands=['viewcodes'])
def view_codes_cmd(message):
    if message.chat.id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=3)
        btns = [InlineKeyboardButton(f"{ct}$", callback_data=f"viewC_{ct}") for ct in ['2','3','4','5','10','15']]
        for i in range(0, len(btns), 3): markup.add(*btns[i:i+3])
        bot.reply_to(message, "📦 **بینینی کۆدەکان**\nجۆری کارت هەڵبژێرە:", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['userdebt'])
def userdebt_cmd(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "🆔 قەرزی کام کڕیار دەبینیت؟", reply_markup=get_users_markup('uDebt'))

@bot.message_handler(commands=['userhistory'])
def userhistory_cmd(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "📜 مێژووی کام کڕیار دەبینیت؟", reply_markup=get_users_markup('uHist'))

@bot.message_handler(commands=['about'])
def about_store(message):
    if is_allowed(message.from_user.id): bot.reply_to(message, "🍏 **دەربارەی فرۆشگای ئایتونس**\nئەم فرۆشگایە لەلایەن هیلال بەڕێوە دەبرێت.", parse_mode='Markdown')

@bot.message_handler(commands=['contact'])
def contact_admin(message):
    if is_allowed(message.from_user.id):
        msg = bot.reply_to(message, "تکایە نامەکەت بنووسە، ڕاستەوخۆ دەگاتە هیلال:")
        bot.register_next_step_handler(msg, lambda m: [bot.send_message(ADMIN_ID, f"📩 نامە لە `{m.from_user.id}`:\n{m.text}"), bot.reply_to(m, "نامەکەت نێردرا. ✅")])

@bot.message_handler(commands=['allow'])
def allow_user(message):
    if message.chat.id == ADMIN_ID:
        try:
            parts = message.text.split(maxsplit=2)
            new_uid, name = int(parts[1]), parts[2] if len(parts)>2 else "نەناسراو"
            with db_lock:
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO allowed_users (user_id, name) VALUES (?, ?)', (new_uid, name))
                c.execute('INSERT OR IGNORE INTO debts (user_id, usd, iqd, credit_limit) VALUES (?, 0, 0, 25)', (new_uid,))
                conn.commit()
            bot.reply_to(message, f"✅ کڕیار {name} ڕێگەی پێدرا.")
        except: bot.reply_to(message, "❌ شێواز هەڵەیە: /allow 123 ناو")

@bot.message_handler(commands=['remove'])
def remove_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "❌ کامیان لادەبەیت؟", reply_markup=get_users_markup('remU'))

@bot.message_handler(commands=['setname'])
def setname_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "✏️ ناوی کام کڕیار دەگۆڕیت؟", reply_markup=get_users_markup('setNm'))

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "🚫 کام کڕیار بلۆک دەکەیت؟", reply_markup=get_users_markup('banU'))

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT b.user_id, a.name FROM bans b LEFT JOIN allowed_users a ON b.user_id = a.user_id')
            banned = c.fetchall()
        if banned:
            markup = InlineKeyboardMarkup(row_width=2)
            for uid, name in banned: markup.add(InlineKeyboardButton(str(name), callback_data=f"unbU_{uid}"))
            bot.reply_to(message, "♻️ سزای کامیان لادەبەیت؟", reply_markup=markup)
        else: bot.reply_to(message, "هیچ کەسێک بلۆک نەکراوە.")

@bot.message_handler(commands=['users'])
def list_users(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT user_id, name FROM allowed_users')
            users = c.fetchall()
        if users:
            msg = "👥 **لیستی کڕیاران:**\n\n" + "".join([f"👤 {n} | `{u}`\n" for u, n in users])
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "بەکارهێنەر نییە.")

@bot.message_handler(commands=['editdebt'])
def editdebt_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "🛠 قەرزی کام کڕیار دەستکاری دەکەیت؟", reply_markup=get_users_markup('edDebt'))

@bot.message_handler(commands=['paydebt'])
def paydebt_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "💵 کام کڕیار قەرزەکەی دەداتەوە؟", reply_markup=get_users_markup('payD'))

@bot.message_handler(commands=['clear'])
def clear_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "💸 قەرزی کام کڕیار سفر دەکەیتەوە؟", reply_markup=get_users_markup('clrD'))

@bot.message_handler(commands=['open'])
def open_store(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            conn.execute('UPDATE settings SET value="open" WHERE key="store_status"')
            conn.commit()
        bot.reply_to(message, "🔓 فرۆشگا کرایەوە.")

@bot.message_handler(commands=['close'])
def close_store(message):
    if message.chat.id == ADMIN_ID:
        reason = message.text.replace('/close', '').strip() or "لە ئێستادا فرۆشگا داخراوە."
        with db_lock:
            conn.execute('UPDATE settings SET value="closed" WHERE key="store_status"')
            conn.execute('UPDATE settings SET value=? WHERE key="close_reason"', (reason,))
            conn.commit()
        bot.reply_to(message, "🔒 فرۆشگا داخرا.")

@bot.message_handler(commands=['autoclose'])
def autoclose_store(message):
    if message.chat.id == ADMIN_ID:
        times = message.text.replace('/autoclose', '').strip()
        with db_lock:
            conn.execute('UPDATE settings SET value=? WHERE key="autoclose"', (times,))
            conn.commit()
        if times: bot.reply_to(message, f"⏰ سیستەمی داخستنی ئۆتۆماتیکی چالاک کرا بۆ کاتی: {times}\n*(بۆ کوژاندنەوەی تەنها بنووسە /autoclose)*")
        else: bot.reply_to(message, "⏰ سیستەمی ئۆتۆماتیکی کوژایەوە.")

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
            bot.reply_to(message, f"✅ بڕی {len(codes)} کۆدی {ctype}$ زیادکرا.")
        except: bot.reply_to(message, "❌ شێواز: /add 2 XXXXX")

@bot.message_handler(commands=['delcode'])
def delcode_cmd(message):
    if message.chat.id == ADMIN_ID:
        msg = bot.reply_to(message, "🗑 ئەو کۆدە بنووسە کە دەتەوێت بیسڕیتەوە:")
        bot.register_next_step_handler(msg, lambda m: [conn.execute('DELETE FROM codes WHERE code=?', (m.text.strip(),)), conn.commit(), bot.reply_to(m, "کۆدەکە سڕایەوە.")])

@bot.message_handler(commands=['clearcodes'])
def clearcodes_cmd(message):
    if message.chat.id == ADMIN_ID:
        markup = InlineKeyboardMarkup(row_width=3)
        btns = [InlineKeyboardButton(f"{ct}$", callback_data=f"clrC_{ct}") for ct in ['2','3','4','5','10','15', 'all']]
        for i in range(0, len(btns)-1, 3): markup.add(*btns[i:i+3])
        markup.add(btns[-1])
        bot.reply_to(message, "⚠️ کام کۆدانە خاوێن دەکەیتەوە؟", reply_markup=markup)

@bot.message_handler(commands=['stock'])
def check_stock(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, COUNT(*) FROM codes GROUP BY card_type')
            results = c.fetchall()
        if results:
            msg = "📊 **ئاماری کۆگا:**\n\n" + "".join([f"کارتی {ct}$ : **{count}** دانە\n" for ct, count in results])
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "کۆگا بەتاڵە.")

@bot.message_handler(commands=['debts'])
def check_all_debts(message):
    if message.chat.id == ADMIN_ID:
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT d.user_id, d.usd, d.iqd, a.name FROM debts d LEFT JOIN allowed_users a ON d.user_id = a.user_id WHERE d.usd > 0')
            results = c.fetchall()
        if results:
            tot_usd, tot_iqd, msg = 0, 0, "📒 **دەفتەری قەرزەکان:**\n\n"
            for uid, usd, iqd, name in results:
                msg += f"👤 **{name}** | `{uid}`\n💸 {usd}$ ({iqd:,} د)\n\n"
                tot_usd += usd; tot_iqd += iqd
            msg += f"💰 **کۆی گشتی:** {tot_usd}$ ({tot_iqd:,} دینار)"
            bot.reply_to(message, msg, parse_mode='Markdown')
        else: bot.reply_to(message, "هیچ قەرزێک نییە.")

@bot.message_handler(commands=['setlimit'])
def setlimit_user(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "🚧 سنووری قەرزی کام کڕیار دەگۆڕیت؟", reply_markup=get_users_markup('setLim'))

@bot.message_handler(commands=['broadcast', 'update'])
def broadcast_cmd(message):
    if message.chat.id == ADMIN_ID:
        prefix = "✨ **نوێکاری:**\n\n" if message.text.startswith('/update') else "📢 **ئاگاداری:**\n\n"
        msg = bot.reply_to(message, "دەقەکە بنووسە بۆ ناردنی بۆ هەمووان:")
        bot.register_next_step_handler(msg, lambda m: send_to_all(m.text, prefix, m.chat.id))

def send_to_all(text, prefix, admin_chat):
    with db_lock:
        c = conn.cursor()
        c.execute('SELECT user_id FROM allowed_users')
        users = c.fetchall()
    succ = 0
    for (uid,) in users:
        try:
            bot.send_message(uid, prefix + text, parse_mode='Markdown')
            succ += 1
        except: pass
    bot.send_message(admin_chat, f"✅ نێردرا بۆ {succ} کڕیار.")

@bot.message_handler(commands=['backup'])
def send_backup(message):
    if message.chat.id == ADMIN_ID:
        try:
            with open(DB_PATH, 'rb') as doc: bot.send_document(message.chat.id, doc, caption="💾 داتابەیس")
        except: pass

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

# ================== بەڕێوەبردنی دوگمەکانی ئەدمین ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith(('remU_', 'setNm_', 'banU_', 'unbU_', 'uDebt_', 'uHist_', 'edDebt_', 'payD_', 'clrD_', 'setLim_', 'viewC_', 'clrC_')))
def admin_callbacks(call):
    if call.from_user.id != ADMIN_ID: return
    action, uid = call.data.split('_')
    
    if action == 'viewC':
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT code FROM codes WHERE card_type = ?', (uid,))
            res = c.fetchall()
        if res:
            text = f"کۆدەکانی {uid}$:\n" + "\n".join([r[0] for r in res])
            if len(text) > 4000:
                with open("temp_codes.txt", "w") as f: f.write(text)
                with open("temp_codes.txt", "rb") as f: bot.send_document(call.message.chat.id, f)
            else: bot.send_message(call.message.chat.id, text)
        else: bot.answer_callback_query(call.id, "هیچ کۆدێک نییە!", show_alert=True)
        return

    if action == 'clrC':
        with db_lock:
            c = conn.cursor()
            if uid == 'all': c.execute('DELETE FROM codes')
            else: c.execute('DELETE FROM codes WHERE card_type = ?', (uid,))
            conn.commit()
        bot.answer_callback_query(call.id, "خاوێنکرایەوە! ✅", show_alert=True)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        return
        
    if uid != 'all': uid = int(uid)
    
    if action == 'remU':
        with db_lock:
            conn.execute('DELETE FROM allowed_users WHERE user_id = ?', (uid,))
            conn.commit()
        bot.answer_callback_query(call.id, "کڕیار سڕایەوە ✅", show_alert=True)
    elif action == 'banU':
        with db_lock:
            conn.execute('INSERT OR REPLACE INTO bans (user_id, ban_until) VALUES (?, NULL)', (uid,))
            conn.commit()
        bot.answer_callback_query(call.id, "کڕیار سزادرا ✅", show_alert=True)
    elif action == 'unbU':
        with db_lock:
            conn.execute('DELETE FROM bans WHERE user_id = ?', (uid,))
            conn.commit()
        bot.answer_callback_query(call.id, "سزا لابرا ✅", show_alert=True)
    elif action == 'clrD':
        with db_lock:
            if uid == 'all': conn.execute('UPDATE debts SET usd = 0, iqd = 0')
            else: conn.execute('UPDATE debts SET usd = 0, iqd = 0 WHERE user_id = ?', (uid,))
            conn.commit()
        bot.answer_callback_query(call.id, "قەرز سفرکرایەوە ✅", show_alert=True)
    elif action == 'uDebt':
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT usd, iqd, credit_limit FROM debts WHERE user_id = ?', (uid,))
            res = c.fetchone()
        if res: bot.send_message(call.message.chat.id, f"👤 قەرزی کڕیار:\n💸 {res[0]}$\n💵 {res[1]:,} دینار\n🚧 سنور: {res[2]}$")
    elif action == 'uHist':
        with db_lock:
            c = conn.cursor()
            c.execute('SELECT card_type, price, date FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10', (uid,))
            hist = c.fetchall()
        if hist:
            msg = "📜 مێژووی کڕیار:\n" + "".join([f"💳 {ctype} | {prc:,} د | {dt[:16]}\n" for ctype, prc, dt in hist])
            bot.send_message(call.message.chat.id, msg)
        else: bot.answer_callback_query(call.id, "هیچ کڕینێکی نییە.", show_alert=True)
    
    # فەرمانەکانی پێویستیان بە نووسینە دوای کرتە
    elif action == 'setNm':
        msg = bot.send_message(call.message.chat.id, "✏️ ناوی نوێ بنووسە:")
        bot.register_next_step_handler(msg, lambda m: [conn.execute('UPDATE allowed_users SET name=? WHERE user_id=?', (m.text, uid)), conn.commit(), bot.reply_to(m, "ناو گۆڕدرا ✅")])
    elif action == 'edDebt':
        msg = bot.send_message(call.message.chat.id, "🛠 بڕی نوێی قەرز بنووسە (بە دۆلار):")
        bot.register_next_step_handler(msg, lambda m: [conn.execute('UPDATE debts SET usd=?, iqd=? WHERE user_id=?', (int(m.text), int(m.text)*1500, uid)), conn.commit(), bot.reply_to(m, "قەرز دەستکاری کرا ✅")])
    elif action == 'payD':
        msg = bot.send_message(call.message.chat.id, "💵 چەند دۆلار دەداتەوە؟")
        bot.register_next_step_handler(msg, lambda m: [conn.execute('UPDATE debts SET usd = usd - ?, iqd = iqd - ? WHERE user_id = ?', (int(m.text), int(m.text)*1500, uid)), conn.commit(), bot.reply_to(m, "قەرز درایەوە ✅")])
    elif action == 'setLim':
        msg = bot.send_message(call.message.chat.id, "🚧 سنوری نوێ بنووسە (دۆلار):")
        bot.register_next_step_handler(msg, lambda m: [conn.execute('UPDATE debts SET credit_limit=? WHERE user_id=?', (int(m.text), uid)), conn.commit(), bot.reply_to(m, "سنور گۆڕدرا ✅")])

    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

# ================== لۆژیکی کڕین و بەشی خوارەوە ==================

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

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_smart_order')
def cancel_smart_order(call):
    bot.answer_callback_query(call.id, "داواکارییەکە هەڵوەشایەوە ❌")
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_allowed(user_id):
        welcome_text = "سڵاو! بەخێربێیت بۆ فرۆشگای تایبەتی ئایتونس. 🍏\n\nئەم فرۆشگایە لەلایەن **هیلال** بەڕێوە دەبرێت."
        bot.reply_to(message, welcome_text, reply_markup=get_main_menu(user_id), parse_mode='Markdown')
    else: bot.reply_to(message, f"ببورە، ئەم بۆتە تایبەتە.\nئایدی تۆ: `{user_id}`")

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
    markup.add(InlineKeyboardButton("1 دانە", callback_data=f"finalbuy_{ctype}_1"), InlineKeyboardButton("2 دانە", callback_data=f"finalbuy_{ctype}_2"))
    markup.add(InlineKeyboardButton("🔙 گەڕانەوە", callback_data="back_to_buy_list"))
    try: bot.edit_message_text(f"💳 **کارتی {ctype}$**\nژمارە دیاری بکە:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')
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
                bot.answer_callback_query(call.id, f"ببورە، کارتی پێویست لە کۆگا نەماوە.", show_alert=True)
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
                bot.answer_callback_query(call.id, f"ببورە، تەنها {len(res)} ماوە.", show_alert=True)
                return
            for r in res: assigned_codes.append({'id': r[0], 'code': r[1], 'type': target})
            history_desc = f"{target}$ (x{qty})"
            total_usd = int(target) * qty
            total_iqd = prices.get(target, 0) * qty
            
        else:
            target = int(call.data.split('_')[1])
            assigned_codes = get_dynamic_combo(c, target, 1)
            if not assigned_codes:
                bot.answer_callback_query(call.id, "ببورە، کارتی پێویست نەماوە.", show_alert=True)
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
        "🎁 **کۆدەکان:**\n\n"
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
        bot.reply_to(message, "🎙️ ببورە، تایبەتمەندی ڤۆیس ڕاگیراوە. بە نووسین بینێرە.")
        return

    if message.text.startswith('/'): return
    target, qty, is_mixed = parse_smart_order(message.text)
    
    if is_mixed == "limit_exceeded":
        bot.send_message(message.chat.id, f"⚠️ ببورە، داواکارییەکەت لە سنووری ڕێگەپێدراو (25$) زیاترە.", parse_mode='Markdown')
        return
        
    if target:
        markup = InlineKeyboardMarkup()
        if is_mixed:
            markup.add(InlineKeyboardButton("✅ کڕین", callback_data=f"smartmix_{target}_{qty}"))
            markup.add(InlineKeyboardButton("❌ پەشیمان بوونەوە", callback_data="cancel_smart_order"))
            bot.send_message(message.chat.id, f"🛒 **پێشنیاری زیرەک:** {qty} پاکێجی {target}$ دەکڕیت؟", reply_markup=markup, parse_mode='Markdown')
        else:
            markup.add(InlineKeyboardButton("✅ پەسەندکردن و کڕین", callback_data=f"finalbuy_{target}_{qty}"))
            markup.add(InlineKeyboardButton("❌ پەشیمان بوونەوە", callback_data="cancel_smart_order"))
            bot.send_message(message.chat.id, f"🛒 **پێشنیاری زیرەک:** {qty} کارتی جۆری {target}$ دەکڕیت؟", reply_markup=markup, parse_mode='Markdown')

def auto_schedule_checker():
    while True:
        now_time = time.time()
        to_delete = [rid for rid, data in pending_refunds.items() if now_time > data['expiry'] + 60]
        for rid in to_delete: del pending_refunds[rid]
        
        try:
            with db_lock:
                c = conn.cursor()
                c.execute('SELECT value FROM settings WHERE key="autoclose"')
                ac = c.fetchone()
                
            if ac and ac[0]:
                now_str = datetime.datetime.now().strftime("%H:%M")
                times = ac[0].split('-')
                if len(times) == 2:
                    st, en = times[0].strip(), times[1].strip()
                    should_be_closed = False
                    if st < en: should_be_closed = (st <= now_str <= en)
                    else: should_be_closed = (now_str >= st or now_str <= en)
                    
                    with db_lock:
                        c.execute('SELECT value FROM settings WHERE key="store_status"')
                        curr_status = c.fetchone()[0]
                    
                    if should_be_closed and curr_status == 'open':
                        with db_lock:
                            conn.execute('UPDATE settings SET value="closed" WHERE key="store_status"')
                            conn.execute('UPDATE settings SET value="بە هۆی کاتی دیاریکراوەوە داخراوە." WHERE key="close_reason"')
                            conn.commit()
                    elif not should_be_closed and curr_status == 'closed':
                        with db_lock:
                            conn.execute('UPDATE settings SET value="open" WHERE key="store_status"')
                            conn.commit()
        except: pass
        time.sleep(30)

def auto_periodic_backup():
    while True:
        time.sleep(43200)
        try:
            with open(DB_PATH, 'rb') as doc: bot.send_document(ADMIN_ID, doc, caption="⏱️ باکئەپی ئۆتۆماتیکی")
        except: pass

def setup_bot_commands():
    # بە مەبەست فەرمانەکانی نەکردووەتە ناو مێنیوی ئۆتۆماتیکی تێلیگرام بۆ ئەوەی لیستی ناو وێنەکانت تێک نەچێت
    pass

checker_thread = threading.Thread(target=auto_schedule_checker, daemon=True)
checker_thread.start()
backup_thread = threading.Thread(target=auto_periodic_backup, daemon=True)
backup_thread.start()

print("بۆتەکە ئێستا بەتەواوی کار دەکات، هەموو دوگمەکانیش ئامادەن...")
setup_bot_commands()
bot.infinity_polling()
