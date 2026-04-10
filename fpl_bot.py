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

# ==================================================
# دوال جلب البيانات من API
# ==================================================

def safe_api_request(url):
    """تنفيذ طلب API بأمان مع إعادة المحاولة"""
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
        except Exception as e:
            logging.warning(f"محاولة {attempt+1} فشلت: {e}")
    return None

def get_manager_info(manager_id):
    """جلب المعلومات الأساسية لمدرب"""
    url = f"{BASE_URL}/entry/{manager_id}/"
    return safe_api_request(url)

def get_manager_history(manager_id):
    """جلب تاريخ المدرب"""
    url = f"{BASE_URL}/entry/{manager_id}/history/"
    return safe_api_request(url)

def get_manager_picks(manager_id, gameweek):
    """جلب تشكيلة المدرب في أسبوع معين"""
    url = f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/"
    return safe_api_request(url)

def get_manager_leagues(manager_id):
    """جلب الدوريات التي يشارك فيها المدرب"""
    info = get_manager_info(manager_id)
    if info and "leagues" in info:
        classic_leagues = info["leagues"].get("classic", [])
        return classic_leagues[:5]
    return []

def get_players_data():
    """جلب بيانات جميع اللاعبين"""
    url = f"{BASE_URL}/bootstrap-static/"
    data = safe_api_request(url)
    if data and "elements" in data:
        players_dict = {}
        for player in data["elements"]:
            players_dict[player["id"]] = f"{player['first_name']} {player['second_name']}"
        return players_dict
    return {}

def get_current_gameweek():
    """الحصول على رقم الأسبوع الحالي"""
    url = f"{BASE_URL}/bootstrap-static/"
    data = safe_api_request(url)
    if data and "events" in data:
        # البحث عن الجولة الحالية أو آخر جولة لعبت
        for event in data["events"]:
            if event.get("is_current"):
                return event["id"]
        # إذا لم تكن هناك جولة حالية، نأخذ آخر جولة انتهت
        for event in reversed(data["events"]):
            if event.get("finished"):
                return event["id"]
    return 1

def get_last_played_gameweek():
    """الحصول على آخر جولة لعبت (منتهية)"""
    url = f"{BASE_URL}/bootstrap-static/"
    data = safe_api_request(url)
    if data and "events" in data:
        for event in reversed(data["events"]):
            if event.get("finished"):
                return event["id"]
    return 1

# تحميل بيانات اللاعبين مرة واحدة
players_dict = get_players_data()
last_gameweek = get_last_played_gameweek()
print(f"📅 آخر جولة لعبت: {last_gameweek}")
print(f"👥 تم تحميل بيانات {len(players_dict)} لاعب")

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

# ==================================================
# دوال عرض المعلومات حسب الجولة
# ==================================================

def format_simple_display(manager_id, info, gameweek, picks_data):
    """تنسيق العرض البسيط لجولة محددة"""
    name = safe_str(info.get("name"))
    total_points = safe_int(info.get("summary_overall_points"))
    
    # نقاط الجولة المحددة من بيانات picks
    event_points = 0
    captain_points = 0
    
    if picks_data and "picks" in picks_data:
        event_points = safe_int(picks_data.get("entry_history", {}).get("points", 0))
        for pick in picks_data["picks"]:
            if pick.get("is_captain"):
                captain_points = safe_int(pick.get("points", 0))
                break
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 المعرف: `{manager_id}`\n\n"
        f"📊 **العرض البسيط - الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة {gameweek}: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"👑 نقاط الكابتن: *{captain_points}*\n"
    )
    return response

def format_detailed_display(manager_id, info, gameweek, picks_data, history, leagues):
    """تنسيق العرض المفصل لجولة محددة"""
    name = safe_str(info.get("name"))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "" or joined == "None":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))
    
    # نقاط الجولة المحددة
    event_points = 0
    event_rank = 0
    total_transfers = safe_int(info.get("total_transfers"))
    
    if picks_data and "picks" in picks_data:
        entry_history = picks_data.get("entry_history", {})
        event_points = safe_int(entry_history.get("points", 0))
        event_rank = safe_int(entry_history.get("rank", 0))
    
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 المعرف: `{manager_id}`\n"
        f"📅 انضم: {joined}\n\n"
        f"📊 **العرض المفصل - الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة {gameweek}: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*\n"
        f"🔄 الانتقالات: *{total_transfers}*\n\n"
    )
    
    # إضافة معلومات اللاعبين في هذه الجولة
    if picks_data and "picks" in picks_data and players_dict:
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
            rank_display = f"{league_rank}" if league_rank > 0 else "غير معروف"
            response += f"• {league_name}: {rank_display}/{league_total}\n"
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

def get_buttons(manager_id, gameweek, current_view, min_gameweek=1):
    """إنشاء أزرار التنقل حسب الجولة الحالية"""
    keyboard = []
    
    # صف الأزرار العلوية (عرض بسيط / عرض مفصل)
    row1 = [
        InlineKeyboardButton("📋 عرض بسيط", callback_data=f"simple_{manager_id}_{gameweek}"),
        InlineKeyboardButton("📊 عرض مفصل", callback_data=f"detail_{manager_id}_{gameweek}")
    ]
    keyboard.append(row1)
    
    # صف أزرار التنقل بين الجولات
    row2 = []
    if gameweek > min_gameweek:
        row2.append(InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{gameweek-1}"))
    # عرض رقم الجولة الحالية
    row2.append(InlineKeyboardButton(f"📅 جولة {gameweek}", callback_data="ignore"))
    keyboard.append(row2)
    
    return InlineKeyboardMarkup(keyboard)

async def send_or_update_message(update, context, manager_id, gameweek, view_type, message_id=None):
    """إرسال أو تحديث رسالة حسب الحالة"""
    
    # جلب البيانات الأساسية
    info = get_manager_info(manager_id)
    
    if not info:
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
    
    # جلب تشكيلة المدرب في الجولة المحددة
    picks_data = get_manager_picks(manager_id, gameweek)
    
    # إذا كانت الجولة لم تُلعب بعد أو لا توجد بيانات
    if not picks_data:
        no_data_text = f"⚠️ لا توجد بيانات متاحة للجولة {gameweek}.\nقد تكون هذه الجولة لم تُلعب بعد أو أن المدرب لم يشارك فيها."
        if message_id:
            await context.bot.edit_message_text(
                text=no_data_text,
                chat_id=update.effective_chat.id,
                message_id=message_id,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(no_data_text, parse_mode='Markdown')
        return False
    
    # جلب البيانات الإضافية حسب الحاجة
    if view_type == "detail":
        history = get_manager_history(manager_id)
        leagues = get_manager_leagues(manager_id)
    else:
        history = None
        leagues = None
    
    if view_type == "simple":
        text = format_simple_display(manager_id, info, gameweek, picks_data)
    else:
        text = format_detailed_display(manager_id, info, gameweek, picks_data, history, leagues)
    
    reply_markup = get_buttons(manager_id, gameweek, view_type)
    
    if message_id:
        await context.bot.edit_message_text(
            text=text,
            chat_id=update.effective_chat.id,
            message_id=message_id,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
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
            "2️⃣ سيظهر لك بيانات **آخر جولة لعبت** تلقائياً\n"
            "3️⃣ استخدم الأزرار للتبديل بين:\n"
            "   • 📋 عرض بسيط\n"
            "   • 📊 عرض مفصل\n"
            "   • ⬅️ الجولة السابقة (للتنقل بين الجولات)\n\n"
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
    
    # التحقق من وجود المدرب
    await update.message.reply_text(f"🔄 جاري التحقق من المعرف {manager_id}...")
    
    info = get_manager_info(manager_id)
    
    if not info:
        await update.message.reply_text(
            f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.\n\n"
            "تأكد من صحة المعرف.\n"
            "يمكنك تجربة: `2794801`",
            parse_mode='Markdown'
        )
        return
    
    # إذا وجد المدرب، اعرض بيانات آخر جولة لعبت
    name = safe_str(info.get("name"))
    start_gameweek = last_gameweek
    
    await update.message.reply_text(
        f"✅ تم العثور على المدرب **{name}**!\n"
        f"📅 سيتم عرض بيانات **الجولة {start_gameweek}** (آخر جولة لعبت)\n\n"
        f"🔄 جاري تحميل البيانات...",
        parse_mode='Markdown'
    )
    
    # عرض البيانات أولاً (عرض بسيط افتراضي)
    picks_data = get_manager_picks(manager_id, start_gameweek)
    
    if not picks_data:
        await update.message.reply_text(
            f"⚠️ لا توجد بيانات متاحة للجولة {start_gameweek}.",
            parse_mode='Markdown'
        )
        return
    
    text = format_simple_display(manager_id, info, start_gameweek, picks_data)
    reply_markup = get_buttons(manager_id, start_gameweek, "simple")
    
    await update.message.reply_text(
        text=text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    message_id = query.message.message_id
    
    # تجاهل أزرار "ignore"
    if data == "ignore":
        return
    
    parts = data.split("_")
    
    # معالجة أزرار التنقل (nav)
    if parts[0] == "nav":
        if len(parts) != 3:
            return
        manager_id = parts[1]
        gameweek = int(parts[2])
        
        # نبقى في نفس نوع العرض الحالي (نحاول استنتاج من النص)
        current_text = query.message.text
        if "العرض البسيط" in current_text:
            view_type = "simple"
        else:
            view_type = "detail"
        
        # إظهار مؤقت
        await query.edit_message_text(
            text=f"🔄 جاري تحميل بيانات الجولة {gameweek}...",
            reply_markup=None
        )
        
        # جلب البيانات
        info = get_manager_info(manager_id)
        if not info:
            await query.edit_message_text(
                text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                parse_mode='Markdown'
            )
            return
        
        picks_data = get_manager_picks(manager_id, gameweek)
        if not picks_data:
            await query.edit_message_text(
                text=f"⚠️ لا توجد بيانات متاحة للجولة {gameweek}.",
                parse_mode='Markdown'
            )
            return
        
        if view_type == "simple":
            text = format_simple_display(manager_id, info, gameweek, picks_data)
        else:
            history = get_manager_history(manager_id)
            leagues = get_manager_leagues(manager_id)
            text = format_detailed_display(manager_id, info, gameweek, picks_data, history, leagues)
        
        reply_markup = get_buttons(manager_id, gameweek, view_type)
        
        await query.edit_message_text(
            text=text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # معالجة أزرار العرض (simple/detail)
    if len(parts) >= 3 and parts[0] in ["simple", "detail"]:
        view_type = parts[0]
        manager_id = parts[1]
        gameweek = int(parts[2])
        
        # إظهار مؤقت
        await query.edit_message_text(
            text=f"🔄 جاري تحميل { 'العرض البسيط' if view_type == 'simple' else 'العرض المفصل' } للجولة {gameweek}...",
            reply_markup=None
        )
        
        info = get_manager_info(manager_id)
        if not info:
            await query.edit_message_text(
                text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                parse_mode='Markdown'
            )
            return
        
        picks_data = get_manager_picks(manager_id, gameweek)
        if not picks_data:
            await query.edit_message_text(
                text=f"⚠️ لا توجد بيانات متاحة للجولة {gameweek}.",
                parse_mode='Markdown'
            )
            return
        
        if view_type == "simple":
            text = format_simple_display(manager_id, info, gameweek, picks_data)
        else:
            history = get_manager_history(manager_id)
            leagues = get_manager_leagues(manager_id)
            text = format_detailed_display(manager_id, info, gameweek, picks_data, history, leagues)
        
        reply_markup = get_buttons(manager_id, gameweek, view_type)
        
        await query.edit_message_text(
            text=text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return

# ==================================================
# تشغيل البوت
# ==================================================

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("=" * 50)
    print("🤖 البوت التفاعلي (مع التنقل بين الجولات) يعمل الآن...")
    print(f"📅 آخر جولة لعبت: {last_gameweek}")
    print("📡 أرسل معرف مدرب للبدء")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
