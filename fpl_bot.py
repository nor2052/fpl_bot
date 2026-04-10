import os
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# تفعيل تسجيل الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================================================
# اقرأ التوكن من متغيرات البيئة
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    exit(1)

# عنوان API الفانتاسي الرسمي
BASE_URL = "https://fantasy.premierleague.com/api"

# ==================================================
# دوال جلب البيانات من API
# ==================================================

def get_manager_info(manager_id):
    """جلب المعلومات الأساسية لمدرب"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"خطأ في جلب معلومات المدرب: {e}")
        return None

def get_manager_history(manager_id):
    """جلب تاريخ المدرب"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/history/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"خطأ في جلب تاريخ المدرب: {e}")
        return None

# ==================================================
# دالة مساعدة لتحويل القيم الفارغة إلى 0
# ==================================================

def safe_int(value):
    """تحويل القيمة إلى int بشكل آمن"""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

def safe_str(value):
    """تحويل القيمة إلى string بشكل آمن"""
    if value is None:
        return "غير معروف"
    return str(value)

# ==================================================
# دالة معالجة الرسائل (القلب الرئيسي للبوت)
# ==================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هذه الدالة تتعامل مع أي رسالة يرسلها المستخدم"""
    message_text = update.message.text.strip()
    
    # إذا كان المستخدم أرسل أمر /start أو /help
    if message_text.startswith('/start') or message_text.startswith('/help'):
        await update.message.reply_text(
            "🎮 **بوت مساعد الفانتاسي**\n\n"
            "✨ **كيف يعمل البوت؟**\n"
            "فقط أرسل **رقم معرف المدرب** وسأعطيك معلوماته الكاملة!\n\n"
            "📝 **مثال:**\n"
            "أرسل الرقم `1234567`\n\n"
            "🔑 **كيف تحصل على معرف مدرب؟**\n"
            "افتح موقع FPL، اذهب إلى صفحة أي مدرب، الرقم في الرابط:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📊 **المعلومات التي سأعرضها:**\n"
            "• الاسم والتاريخ\n"
            "• النقاط والترتيب\n"
            "• تاريخ المواسم السابقة\n"
            "• إحصائيات الأسبوع الحالي",
            parse_mode='Markdown'
        )
        return
    
    # محاولة تحويل الرسالة إلى رقم (معرف المدرب)
    try:
        manager_id = int(message_text)
    except ValueError:
        await update.message.reply_text(
            "❌ لم أفهم! يرجى إرسال **رقم معرف المدرب** فقط.\n\n"
            "مثال: `1234567`\n"
            "أو أرسل /help للمساعدة",
            parse_mode='Markdown'
        )
        return
    
    # جلب معلومات المدرب
    await update.message.reply_text(f"🔄 جاري جلب معلومات المدرب {manager_id}...")
    
    info = get_manager_info(manager_id)
    history = get_manager_history(manager_id)
    
    if not info:
        await update.message.reply_text(
            f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.\n\n"
            "تأكد من صحة المعرف.\n"
            "مثال: `1234567`",
            parse_mode='Markdown'
        )
        return
    
    # استخراج البيانات مع التعامل مع القيم الفارغة
    name = safe_str(info.get("name"))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))
    event_points = safe_int(info.get("summary_event_points"))
    event_rank = safe_int(info.get("summary_event_rank"))
    total_transfers = safe_int(info.get("total_transfers"))
    
    # تنسيق الأرقام الكبيرة (إضافة فواصل)
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"
    
    # بناء الرسالة
    response = (
        f"🎮 **{name}**\n"
        f"🆔 المعرف: `{manager_id}`\n"
        f"📅 انضم: {joined}\n\n"
        f"📊 **الإحصائيات الكلية**\n"
        f"⭐ النقاط: *{total_points}*\n"
        f"🏆 الترتيب العالمي: *{rank_str}*\n"
        f"🔄 الانتقالات: *{total_transfers}*\n\n"
        f"📈 **آخر أسبوع**\n"
        f"⭐ نقاط: *{event_points}*\n"
        f"🏆 ترتيب الأسبوع: *{event_rank_str}*\n"
    )
    
    # إضافة تاريخ المواسم السابقة إذا وجد
    if history and "past" in history and history["past"]:
        response += "\n📜 **المواسم السابقة**\n"
        for season in history["past"][-3:]:  # آخر 3 مواسم فقط
            season_name = safe_str(season.get("season_name"))
            season_points = safe_int(season.get("total_points"))
            season_rank = safe_int(season.get("rank"))
            season_rank_str = f"{season_rank:,}" if season_rank > 0 else "غير مصنف"
            response += f"• {season_name}: {season_points} نقطة (الترتيب {season_rank_str})\n"
    
    # إضافة معلومات إضافية إذا وجدت
    if info.get("kit"):
        kit = safe_str(info.get("kit"))
        response += f"\n👕 القميص: {kit}\n"
    
    await update.message.reply_text(response, parse_mode='Markdown')

# ==================================================
# تشغيل البوت
# ==================================================

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # معالج الأوامر (/start, /help)
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    
    # معالج الرسائل النصية (هذا هو الأهم - يلتقط أي رقم يرسله المستخدم)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 50)
    print("🤖 البوت يعمل الآن...")
    print("📡 أرسل أي رقم معرف مدرب وسأعرض معلوماته")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
