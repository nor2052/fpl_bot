import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from fplapi import fplAPI

# تفعيل تسجيل الأخطاء لمتابعة البوت
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================================================
# ✨ غيّر هذين السطرين فقط ✨
# ==================================================
# 1. ضع رابط الوكيل (Proxy URL) الذي حصلت عليه من Cloudflare هنا
# 2. ضع توكن البوت الذي أعطاك إياه BotFather هنا
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
# ==================================================

# تهيئة اتصال API الفانتاسي
print("جاري تحميل بيانات اللعبة من السيرفر...")
fpl_client = fplAPI()
bootstrap_data = fpl_client.get_fpl_data()
players_data = bootstrap_data["elements"]
print("تم تحميل البيانات بنجاح!")

# دالة البحث عن لاعب
def search_player_by_name(name):
    name = name.lower()
    for player in players_data:
        full_name = f"{player['first_name']} {player['second_name']}".lower()
        if name in full_name:
            return player
    return None

# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك في بوت مساعد الفانتاسي! ⚽\n\n"
        "الأوامر المتاحة:\n"
        "/player (اسم اللاعب) - معلومات لاعب\n"
        "/myteam - عرض لاعبي فريقي\n"
        "/help - المساعدة"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "كيفية الاستخدام:\n"
        "اكتب /player محمد صلاح\n"
        "اكتب /myteam لعرض فريقك"
    )

async def myteam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_players_names = ["Mohamed Salah", "Erling Haaland", "Bukayo Saka"]
    reply_message = "🧑‍🤝‍🧑 **لاعبو فريقي:**\n\n"
    for player_name in my_players_names:
        player = search_player_by_name(player_name)
        if player:
            name = f"{player['first_name']} {player['second_name']}"
            points = player['total_points']
            form = player['form']
            now_cost = player['now_cost'] / 10
            reply_message += f"• *{name}*: {points} نقطة | السعر: {now_cost}M | الفورم: {form}\n"
        else:
            reply_message += f"• *{player_name}*: لم يتم العثور عليه\n"
    await update.message.reply_text(reply_message, parse_mode='Markdown')

async def player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الرجاء كتابة اسم اللاعب. مثال: /player محمد صلاح")
        return
    search_term = " ".join(context.args)
    player = search_player_by_name(search_term)
    if player:
        name = f"{player['first_name']} {player['second_name']}"
        points = player['total_points']
        form = player['form']
        now_cost = player['now_cost'] / 10
        selected_by = player['selected_by_percent']
        response = (
            f"⚽ *{name}*\n\n"
            f"📊 النقاط الكلية: {points}\n"
            f"📈 الفورم (الشكل): {form}\n"
            f"💰 السعر: {now_cost} مليون\n"
            f"👥 نسبة الملاك: {selected_by}%"
        )
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"لم أجد لاعباً بالاسم '{search_term}'.")

# تشغيل البوت
def main():
    # هنا نستخدم Proxy URL بدلاً من الـ default
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .base_url(PROXY_URL)  # <-- هذا السطر هو الحل السحري!
        .build()
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myteam", myteam))
    application.add_handler(CommandHandler("player", player))
    
    print("البوت يعمل الآن عبر الـ Proxy...")
    application.run_polling()

if __name__ == '__main__':
    main()
