# أولاً: استيراد المكتبات التي سنحتاجها
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from fplapi import fplAPI  # هذه المكتبة تسهل التعامل مع بيانات اللعبة

# تفعيل نظام تسجيل الأخطاء لمتابعة البوت
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- 1. تهيئة الاتصال بـ API الفانتاسي ---
# سنقوم بإنشاء كائن (object) من المكتبة للتواصل مع السيرفر
fpl_client = fplAPI()

# --- 2. تحميل البيانات الأساسية (مرة واحدة عند تشغيل البوت) ---
# هذه البيانات تحتوي على كل اللاعبين، الأندية، والأسعار
print("جاري تحميل بيانات اللعبة من السيرفر...")
bootstrap_data = fpl_client.get_fpl_data()  # هذا يجلب كل البيانات
players_data = bootstrap_data["elements"]   # هذا مصفوفة تحتوي على كل اللاعبين
print("تم تحميل البيانات بنجاح!")

# --- 3. دالة مساعدة للبحث عن لاعب بالاسم ---
def search_player_by_name(name):
    """
    هذه الدالة تبحث عن لاعب باستخدام اسمه (أو جزء من الاسم)
    وتُرجع أول لاعب تطابق
    """
    name = name.lower()  # تحويل الاسم إلى حروف صغيرة لتسهيل المقارنة
    for player in players_data:
        # الاسم الكامل للاعب موجود في first_name و second_name
        full_name = f"{player['first_name']} {player['second_name']}".lower()
        if name in full_name:
            return player
    return None  # إذا لم يتم العثور على لاعب

# --- 4. أوامر البوت ---

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك في بوت مساعد الفانتاسي! ⚽\n\n"
        "الأوامر المتاحة:\n"
        "/player (اسم اللاعب) - للحصول على معلومات لاعب\n"
        "/myteam - لعرض لاعبي فريقي\n"
        "/help - للمساعدة"
    )

# أمر /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "كيفية الاستخدام:\n"
        "اكتب /player محمد صلاح\n"
        "اكتب /myteam لعرض فريقك"
    )

# أمر /myteam (فريق افتراضي)
async def myteam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # هذه قائمة بأسماء اللاعبين في فريقك، يمكنك تعديلها بأسماء فريقك الحقيقي
    my_players_names = ["Mohamed Salah", "Erling Haaland", "Bukayo Saka"]
    
    reply_message = "🧑‍🤝‍🧑 **لاعبو فريقي:**\n\n"
    
    for player_name in my_players_names:
        player = search_player_by_name(player_name)
        if player:
            # استخراج المعلومات المهمة
            name = f"{player['first_name']} {player['second_name']}"
            points = player['total_points']  # النقاط الكلية
            form = player['form']  # الفورم (الآخر 30 يوم)
            now_cost = player['now_cost'] / 10  # السعر بالملايين
            # إضافة المعلومات للرسالة
            reply_message += f"• *{name}*: {points} نقطة | السعر: {now_cost}M | الفورم: {form}\n"
        else:
            reply_message += f"• *{player_name}*: لم يتم العثور عليه\n"
            
    await update.message.reply_text(reply_message, parse_mode='Markdown')

# أمر /player للبحث عن لاعب
async def player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # context.args تحتوي على الكلمات التي كتبها المستخدم بعد الأمر
    if not context.args:
        await update.message.reply_text("الرجاء كتابة اسم اللاعب. مثال: /player محمد صلاح")
        return
    
    # دمج الكلمات لتكوين الاسم الكامل
    search_term = " ".join(context.args)
    player = search_player_by_name(search_term)
    
    if player:
        name = f"{player['first_name']} {player['second_name']}"
        points = player['total_points']
        form = player['form']
        now_cost = player['now_cost'] / 10
        selected_by = player['selected_by_percent']  # نسبة ملاك اللاعب
        # تجهيز الرسالة
        response = (
            f"⚽ *{name}*\n\n"
            f"📊 النقاط الكلية: {points}\n"
            f"📈 الفورم (الشكل): {form}\n"
            f"💰 السعر: {now_cost} مليون\n"
            f"👥 نسبة الملاك: {selected_by}%"
        )
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"لم أجد لاعباً بالاسم '{search_term}'. تأكد من كتابة الاسم بشكل صحيح.")

# --- 5. تشغيل البوت ---
def main():
    # ⚠️ مهم جداً: ضع التوكن الذي أعطاك إياه BotFather هنا
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    # إنشاء التطبيق
    application = Application.builder().token(TOKEN).build()
    
    # ربط الأوامر بالدوال التي كتبناها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myteam", myteam))
    application.add_handler(CommandHandler("player", player))
    
    # بدء تشغيل البوت (الاستماع للرسائل)
    print("البوت يعمل الآن...")
    application.run_polling()

if __name__ == '__main__':
    main()