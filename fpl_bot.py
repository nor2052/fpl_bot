import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

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

# قاموس مؤقت لتخزين بيانات المدربين (لتجنب جلبها كل مرة)
cache = {}

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

def get_manager_picks(manager_id, gameweek):
    """جلب تشكيلة المدرب في أسبوع معين"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"خطأ في جلب تشكيلة المدرب: {e}")
        return None

def get_players_data():
    """جلب بيانات جميع اللاعبين لتحويل الأرقام إلى أسماء"""
    try:
        url = f"{BASE_URL}/bootstrap-static/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            players_dict = {}
            for player in data["elements"]:
                players_dict[player["id"]] = f"{player['first_name']} {player['second_name']}"
            return players_dict
        return {}
    except Exception as e:
        print(f"خطأ في جلب بيانات اللاعبين: {e}")
        return {}

def get_current_gameweek():
    """الحصول على رقم الأسبوع الحالي"""
    try:
        url = f"{BASE_URL}/bootstrap-static/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            for event in data["events"]:
                if event["is_current"]:
                    return event["id"]
        return 1
    except Exception:
        return 1

def get_manager_leagues(manager_id):
    """جلب الدوريات التي يشارك فيها المدرب"""
    try:
        url = f"{BASE_URL}/entry/{manager_id}/"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            leagues = data.get("leagues", {})
            classic_leagues = leagues.get("classic", [])
            # جلب أول 3 دوريات فقط
            return classic_leagues[:3]
        return []
    except Exception:
        return []

# ==================================================
# دوال مساعدة
# ==================================================

def safe_int(value):
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

def safe_str(value):
    if value is None:
        return "غير معروف"
    return str(value)

# تحميل بيانات اللاعبين مرتين واحدة
players_dict = get_players_data()
current_gameweek = get_current_gameweek()

# ==================================================
# دوال عرض المعلومات
# ==================================================

def format_simple_display(manager_id, info):
    """تنسيق العرض البسيط"""
    name = safe_str(info.get("name"))
    total_points = safe_int(info.get("summary_overall_points"))
    event_points = safe_int(info.get("summary_event_points"))
    
    # معرفة نقاط الكابتن - نحتاج لجلب التشكيلة
    captain_points = 0
    picks_data = get_manager_picks(manager_id, current_gameweek)
    if picks_data and "picks" in picks_data:
        for pick in picks_data["picks"]:
            if pick.get("is_captain"):
                captain_points = safe_int(pick.get("points", 0))
                break
    
    response = (
        f"🎮 **{name}**\n\n"
        f"📊 **العرض البسيط**\n"
        f"⭐ نقاط الجولة الحالية: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"👑 نقاط الكابتن: *{captain_points}*\n"
    )
    return response

def format_detailed_display(manager_id, info, history, leagues, picks_data):
    """تنسيق العرض المفصل"""
    name = safe_str(info.get("name"))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))
    event_points = safe_int(info.get("summary_event_points"))
    event_rank = safe_int(info.get("summary_event_rank"))
    total_transfers = safe_int(info.get("total_transfers"))
    
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 المعرف: `{manager_id}`\n"
        f"📅 انضم: {joined}\n\n"
        f"📊 **الإحصائيات الكلية**\n"
        f"⭐ النقاط الجولة: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*\n"
        f"🔄 الانتقالات: *{total_transfers}*\n\n"
    )
    
    # إضافة معلومات اللاعبين إذا وجدت
    if picks_data and "picks" in picks_data:
        response += "🧑‍🤝‍🧑 **لاعبو الفريق (الأساسيون):**\n"
        for idx, pick in enumerate(picks_data["picks"][:11], 1):
            player_id = pick.get("element", 0)
            player_name = players_dict.get(player_id, f"لاعب {player_id}")
            points = safe_int(pick.get("points", 0))
            is_captain = " 👑 (C)" if pick.get("is_captain") else ""
            is_vice = " (VC)" if pick.get("is_vice_captain") else ""
            response += f"{idx}. {player_name}{is_captain}{is_vice}: {points} نقطة\n"
        response += "\n"
    
    # إضافة ترتيب الدوريات
    if leagues:
        response += "🏅 **الدوريات:**\n"
        for league in leagues[:3]:
            league_name = safe_str(league.get("name"))
            league_rank = safe_int(league.get("rank"))
            league_total = safe_int(league.get("total_teams"))
            response += f"• {league_name}: {league_rank}/{league_total}\n"
        response += "\n"
    
    # إضافة تاريخ المواسم السابقة
    if history and "past" in history and history["past"]:
        response += "📜 **آخر 3 مواسم:**\n"
        for season in history["past"][-3:]:
            season_name = safe_str(season.get("season_name"))
            season_points = safe_int(season.get("total_points"))
            season_rank = safe_int(season.get("rank"))
            season_rank_str = f"{season_rank:,}" if season_rank > 0 else "غير مصنف"
            response += f"• {season_name}: {season_points} نقطة (ترتيب {season_rank_str})\n"
    
    return response

# ==================================================
# دوال إنشاء الأزرار
# ==================================================

def get_buttons(manager_id, current_view):
    """إنشاء أزرار التنقل"""
    keyboard = []
    
    if current_view == "simple":
        keyboard.append([InlineKeyboardButton("📊 عرض مفصل", callback_data=f"detail_{manager_id}")])
    else:
        keyboard.append([InlineKeyboardButton("📋 عرض بسيط", callback_data=f"simple_{manager_id}")])
    
    return InlineKeyboardMarkup(keyboard)

async def send_or_update_message(update, context, manager_id, view_type, message_id=None):
    """إرسال أو تحديث رسالة حسب الحالة"""
    # جلب البيانات من الكاش أو من الـ API
    if manager_id not in cache:
        cache[manager_id] = {
            "info": get_manager_info(manager_id),
            "history": get_manager_history(manager_id),
            "leagues": get_manager_leagues(manager_id),
            "picks": get_manager_picks(manager_id, current_gameweek)
        }
    
    data = cache[manager_id]
    
    if not data["info"]:
        error_text = f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`."
        if message_id:
            await context.bot.edit_message_text(
                text=error_text,
                chat_id=update.effective_chat.id,
                message_id=message_id,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(error_text, parse_mode='Markdown')
        return False
    
    if view_type == "simple":
        text = format_simple_display(manager_id, data["info"])
    else:
        text = format_detailed_display(manager_id, data["info"], data["history"], data["leagues"], data["picks"])
    
    reply_markup = get_buttons(manager_id, view_type)
    
    if message_id:
        # تحديث رسالة موجودة
        await context.bot.edit_message_text(
            text=text,
            chat_id=update.effective_chat.id,
            message_id=message_id,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        # إرسال رسالة جديدة
        await update.message.reply_text(
            text=text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    return True

# ==================================================
# معالجات البوت
# ==================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل النصية (الأرقام)"""
    message_text = update.message.text.strip()
    
    # أوامر المساعدة
    if message_text.startswith('/start') or message_text.startswith('/help'):
        await update.message.reply_text(
            "🎮 **بوت مساعد الفانتاسي التفاعلي**\n\n"
            "✨ **كيف يعمل؟**\n"
            "1️⃣ أرسل **رقم معرف المدرب**\n"
            "2️⃣ اختر **العرض البسيط** أو **العرض المفصل**\n"
            "3️⃣ يمكنك التبديل بين العرضين بأزرار التفاعل\n\n"
            "🔑 **كيف تحصل على معرف مدرب؟**\n"
            "افتح موقع FPL، الرقم في الرابط:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📝 **مثال:** أرسل `2794801`",
            parse_mode='Markdown'
        )
        return
    
    # محاولة تحويل إلى رقم
    try:
        manager_id = int(message_text)
    except ValueError:
        await update.message.reply_text(
            "❌ يرجى إرسال **رقم معرف المدرب** فقط.\n"
            "مثال: `1234567`\n"
            "أو أرسل /help للمساعدة",
            parse_mode='Markdown'
        )
        return
    
    # إرسال رسالة أولى مع خيارين
    await update.message.reply_text(
        f"✅ تم العثور على المدرب! اختر نوع العرض:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 عرض بسيط", callback_data=f"simple_{manager_id}"),
                InlineKeyboardButton("📊 عرض مفصل", callback_data=f"detail_{manager_id}")
            ]
        ])
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار"""
    query = update.callback_query
    await query.answer()  # إعلام Telegram أننا استلمنا الضغطة
    
    data = query.data
    message_id = query.message.message_id
    
    # تحليل البيانات (تنسيق: simple_1234567 أو detail_1234567)
    parts = data.split("_")
    if len(parts) != 2:
        return
    
    view_type = parts[0]  # "simple" أو "detail"
    manager_id = parts[1]
    
    # تحديث الرسالة الحالية
    await send_or_update_message(update, context, manager_id, view_type, message_id)

# ==================================================
# تشغيل البوت
# ==================================================

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # معالج الأوامر
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    
    # معالج الرسائل النصية (الأرقام)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # معالج الضغط على الأزرار
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("=" * 50)
    print("🤖 البوت التفاعلي يعمل الآن...")
    print("📡 أرسل معرف مدرب واختر العرض")
    print("🔄 يمكنك التبديل بين العروض بالأزرار")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
