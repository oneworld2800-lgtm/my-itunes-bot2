import sqlite3
import telebot

# تۆکنی بۆتەکەی خۆت لێرە دابنە
TOKEN = 'تۆکنەکەی_بۆتەکەت_لێرە_دابنە'
bot = telebot.TeleBot(TOKEN)

# سڕینەوەی هەر وێبهووکێکی کۆن بۆ ئەوەی ڕێگری لە کێشە بگرێت
bot.remove_webhook()

# بەستنەوەی داتابەیسەکەی فرۆشگاکەت (چونکە لە هەمان فۆڵدەرە، تەنها ناوی فایلەکە دەنووسین)
# نموونە:
# conn = sqlite3.connect('itunes_store_v5.db')
# cursor = conn.cursor()

# --- لێرەدا کۆدەکان و هاندلەرەکانی بۆتەکەی خۆت دادەنێیت (بۆ نموونە /start و دوگمەکان و کڕین) ---


@bot.message_handler(commands=['start'])
def send_welcome(message):
  bot.reply_to(message, 'سڵاو! فرۆشگاکە بە سەرکەوتوویی کەوتە کار.')


# کۆتا دێڕ کە دەبێت لە کۆتایی فایلەکەدا هەبێت بۆ ئەوەی ٢٤ کاتژمێر کار بکات:
print('Bot is running successfully...')
bot.infinity_polling()
