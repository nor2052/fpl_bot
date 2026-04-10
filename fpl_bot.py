import os  # أضف هذا السطر في البداية
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# تفعيل تسجيل الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================================================
# ✨ اقرأ التوكن من متغيرات البيئة ✨
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # سيأخذ التوكن من Railway Variables

if not BOT_TOKEN:
    print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    exit(1)
# ==================================================

# باقي الكود كما هو...
BASE_URL = "https://fantasy.premierleague.com/api"

# دالة لجلب بيانات مدرب معين
def get_manager_info(manager_id):
    """جلب المعلومات الأساسية لمدرب باستخدام معرفه"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"خطأ في جلب بيانات المدرب: {e}")
        return None

def get_manager_history(manager_id):
    """جلب تاريخ المدرب في المواسم السابقة"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/history/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"خطأ في جلب تاريخ المدرب: {e}")
        return None

def get_manager_picks(manager_id, gameweek):
    """جلب تشكيلة المدرب في أسبوع معين"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"خطأ في جلب تشكيلة المدرب: {e}")
        return None

# دالة لجلب أسماء اللاعبين (لتحويل الـ ID إلى اسم)
def get_players_data():
    """جلب بيانات جميع اللاعبين لتحويل الأرقام إلى أسماء"""
    try:
        url = f"{BASE_URL}/bootstrap-static/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            # إنشاء قاموس يربط ID اللاعب باسمه
            players_dict = {}
            for player in data["elements"]:
                players_dict[player["id"]] = f"{player['first_name']} {player['second_name']}"
            return players_dict
        else:
            return {}
    except Exception as e:
        print(f"خطأ في جلب بيانات اللاعبين: {e}")
        return {}

# تحميل بيانات اللاعبين عند تشغيل البوت
print("جاري تحميل بيانات اللاعبين...")
players_dict = get_players_data()
print(f"تم تحميل بيانات {len(players_dict)} لاعب بنجاح!")

# ==================== أوامر البوت ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 مرحباً بك في بوت مساعد الفانتاسي!\n\n"
        "هذا البوت يعرض معلومات عن **المدربين** (اللاعبين الحقيقيين في اللعبة)\n\n"
        "📋 **الأوامر المتاحة:**\n"
        "/manager [المعرف] - معلومات عن مدرب\n"
        "/history [المعرف] - تاريخ المدرب في المواسم السابقة\n"
        "/picks [المعرف] [الأسبوع] - تشكيلة المدرب في أسبوع معين\n"
        "/search [اسم المدرب] - البحث عن مدرب بالاسم\n\n"
        "🔑 **كيف تحصل على معرف مدرب؟**\n"
        "افتح موقع FPL، اذهب إلى صفحة 'Points'، المعرف يظهر في الرابط.\n"
        "مثال: https://fantasy.premierleague.com/entry/1234567/\n"
        "الرقم 1234567 هو معرف المدرب."
    )

async def manager_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض معلومات أساسية عن مدرب"""
    if not context.args:
        await update.message.reply_text(
            "❌ الرجاء إدخال معرف المدرب.\n"
            "مثال: `/manager 1234567`"
        )
        return
    
    manager_id = context.args[0]
    await update.message.reply_text(f"🔄 جاري جلب معلومات المدرب {manager_id}...")
    
    data = get_manager_info(manager_id)
    
    if data:
        name = data.get("name", "غير معروف")
        joined = data.get("joined_time", "غير معروف")[:10]  # التاريخ فقط
        total_points = data.get("summary_overall_points", 0)
        rank = data.get("summary_overall_rank", 0)
        event_points = data.get("summary_event_points", 0)
        event_rank = data.get("summary_event_rank", 0)
        last_rank = data.get("last_deadline_rank", 0)
        total_transfers = data.get("total_transfers", 0)
        
        response = (
            f"🎮 **معلومات المدرب**\n\n"
            f"👤 **الاسم:** {name}\n"
            f"🆔 **المعرف:** {manager_id}\n"
            f"📅 **تاريخ الانضمام:** {joined}\n\n"
            f"📊 **الإحصائيات الكلية:**\n"
            f"⭐ النقاط الإجمالية: *{total_points}*\n"
            f"🏆 الترتيب العالمي: *{rank}*\n"
            f"🔄 إجمالي الانتقالات: *{total_transfers}*\n\n"
            f"📈 **آخر أسبوع:**\n"
            f"⭐ نقاط الأسبوع: *{event_points}*\n"
            f"🏆 ترتيب الأسبوع: *{event_rank}*\n"
            f"📉 ترتيب ما قبل الموعد: *{last_rank}*"
        )
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ لم أتمكن من العثور على مدرب بالمعرف {manager_id}. تأكد من صحة المعرف.")

async def manager_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تاريخ المدرب في المواسم السابقة"""
    if not context.args:
        await update.message.reply_text(
            "❌ الرجاء إدخال معرف المدرب.\n"
            "مثال: `/history 1234567`"
        )
        return
    
    manager_id = context.args[0]
    await update.message.reply_text(f"🔄 جاري جلب تاريخ المدرب {manager_id}...")
    
    data = get_manager_history(manager_id)
    
    if data and "past" in data:
        past_seasons = data["past"]
        
        if not past_seasons:
            await update.message.reply_text(f"📭 لا توجد مواسم سابقة للمدرب {manager_id}.")
            return
        
        response = "📜 **تاريخ المواسم السابقة:**\n\n"
        for season in past_seasons:
            season_name = season.get("season_name", "غير معروف")
            total_points = season.get("total_points", 0)
            rank = season.get("rank", 0)
            response += f"📅 **{season_name}:** {total_points} نقطة | الترتيب: {rank}\n"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ لم أتمكن من جلب تاريخ المدرب {manager_id}.")

async def manager_picks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تشكيلة المدرب في أسبوع معين"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ الرجاء إدخال معرف المدرب ورقم الأسبوع.\n"
            "مثال: `/picks 1234567 5`\n"
            "(هذا يعرض تشكيلة المدرب في الأسبوع الخامس)"
        )
        return
    
    manager_id = context.args[0]
    gameweek = context.args[1]
    
    await update.message.reply_text(f"🔄 جاري جلب تشكيلة المدرب {manager_id} في الأسبوع {gameweek}...")
    
    data = get_manager_picks(manager_id, gameweek)
    
    if data and "picks" in data:
        picks = data["picks"]
        active_chip = data.get("active_chip", "لا يوجد")
        
        response = f"🧑‍🤝‍🧑 **تشكيلة المدرب {manager_id} في الأسبوع {gameweek}**\n\n"
        response += f"💡 **الشيب النشط:** {active_chip}\n\n"
        response += "**اللاعبون:**\n"
        
        for idx, pick in enumerate(picks[:11], 1):  # أول 11 لاعب هم التشكيلة الأساسية
            player_id = pick.get("element", 0)
            player_name = players_dict.get(player_id, f"لاعب {player_id}")
            is_captain = " (C)" if pick.get("is_captain") else ""
            is_vice = " (VC)" if pick.get("is_vice_captain") else ""
            multiplier = pick.get("multiplier", 1)
            
            response += f"{idx}. {player_name}{is_captain}{is_vice} - مضاعف: {multiplier}x\n"
        
        # إضافة البدلاء
        if len(picks) > 11:
            response += "\n**البدلاء:**\n"
            for idx, pick in enumerate(picks[11:], 1):
                player_id = pick.get("element", 0)
                player_name = players_dict.get(player_id, f"لاعب {player_id}")
                response += f"{idx}. {player_name}\n"
        
        await update.message.reply_text(response, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ لم أتمكن من جلب تشكيلة المدرب {manager_id} في الأسبوع {gameweek}.")

async def search_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """البحث عن مدرب بالاسم (باستخدام bootstrap-static)"""
    if not context.args:
        await update.message.reply_text(
            "❌ الرجاء إدخال اسم المدرب.\n"
            "مثال: `/search محمد`"
        )
        return
    
    search_term = " ".join(context.args).lower()
    await update.message.reply_text(f"🔄 جاري البحث عن '{search_term}'...")
    
    # جلب البيانات الأساسية التي تحتوي على معلومات عن الفرق
    try:
        url = f"{BASE_URL}/bootstrap-static/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            # البحث في معلومات المدربين (غير موجود مباشرة في bootstrap-static)
            # سنبحث في معلومات الفرق
            teams = data.get("teams", [])
            
            # ملاحظة: الـ API لا يوفر بحثاً مباشراً عن المدربين بالاسم
            # هذه وظيفة توضيحية
            await update.message.reply_text(
                "⚠️ **ملاحظة:** الـ API الرسمي لا يدعم البحث عن المدربين بالاسم مباشرة.\n\n"
                "للحصول على معلومات مدرب، ستحتاج إلى معرفه (manager_id).\n\n"
                "**كيف تحصل على معرف مدرب؟**\n"
                "1. افتح موقع FPL\n"
                "2. اذهب إلى صفحة 'Points' لأي مدرب\n"
                "3. الرقم في الرابط هو المعرف\n\n"
                "مثال: `/manager 1234567`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ فشل الاتصال بخوادم اللعبة.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

# ==================== تشغيل البوت ====================

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # إضافة الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("manager", manager_info))
    application.add_handler(CommandHandler("history", manager_history))
    application.add_handler(CommandHandler("picks", manager_picks))
    application.add_handler(CommandHandler("search", search_manager))
    
    print("=" * 50)
    print("🤖 بوت المدربين يعمل الآن...")
    print("📡 الأوامر المتاحة: /manager, /history, /picks, /search")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
