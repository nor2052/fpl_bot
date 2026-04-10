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
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
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

def get_last_played_gameweek():
    """الحصول على آخر جولة لعبت (منتهية)"""
    url = f"{BASE_URL}/bootstrap-static/"
    data = safe_api_request(url)
    if data and "events" in data:
        for event in reversed(data["events"]):
            if event.get("finished"):
                return event["id"]
    return 1

def get_next_gameweek(current_gw):
    """الحصول على رقم الجولة التالية (دائري 1-38)"""
    next_gw = current_gw + 1
    if next_gw > 38:
        next_gw = 1
    return next_gw

def get_previous_gameweek(current_gw):
    """الحصول على رقم الجولة السابقة (دائري 1-38)"""
    prev_gw = current_gw - 1
    if prev_gw < 1:
        prev_gw = 38
    return prev_gw

def get_team_name(team_id):
    """جلب اسم الفريق من معرف الفريق"""
    teams = {
        1: "Arsenal", 2: "Aston Villa", 3: "Bournemouth", 4: "Brentford",
        5: "Brighton", 6: "Chelsea", 7: "Crystal Palace", 8: "Everton",
        9: "Fulham", 10: "Liverpool", 11: "Luton", 12: "Man City",
        13: "Man Utd", 14: "Newcastle", 15: "Nott'm Forest", 16: "Sheffield Utd",
        17: "Spurs", 18: "West Ham", 19: "Wolves", 20: "Burnley"
    }
    return teams.get(team_id, f"فريق {team_id}")

# تحميل البيانات الأساسية
players_dict = get_players_data()
last_gameweek = get_last_played_gameweek()
print(f"📅 آخر جولة لعبت: {last_gameweek}")
print(f"👥 تم تحميل بيانات {len(players_dict)} لاعب")

# تحميل بيانات bootstrap-static للحصول على معلومات الجولات
bootstrap_data = safe_api_request(f"{BASE_URL}/bootstrap-static/")
gameweeks_info = {}
if bootstrap_data and "events" in bootstrap_data:
    for event in bootstrap_data["events"]:
        gameweeks_info[event["id"]] = {
            "name": event.get("name", f"GW{event['id']}"),
            "finished": event.get("finished", False),
            "deadline_time": event.get("deadline_time", "")
        }

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
    """تنسيق العرض البسيط"""
    name = safe_str(info.get("name"))
    total_points = safe_int(info.get("summary_overall_points"))
    
    # نقاط الجولة
    event_points = 0
    if picks_data and "entry_history" in picks_data:
        event_points = safe_int(picks_data["entry_history"].get("points", 0))
    
    # نقاط الكابتن - البحث في التشكيلة
    captain_points = 0
    captain_name = ""
    if picks_data and "picks" in picks_data:
        for pick in picks_data["picks"]:
            if pick.get("is_captain"):
                captain_points = safe_int(pick.get("points", 0))
                player_id = pick.get("element", 0)
                captain_name = players_dict.get(player_id, f"لاعب {player_id}")
                break
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 المعرف: `{manager_id}`\n\n"
        f"📊 **العرض البسيط - الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
    )
    
    if captain_name:
        response += f"👑 الكابتن ({captain_name}): *{captain_points}* نقطة\n"
    else:
        response += f"👑 نقاط الكابتن: *{captain_points}*\n"
    
    # إضافة ملاحظة إذا كانت الجولة لم تلعب بعد
    if gameweek in gameweeks_info and not gameweeks_info[gameweek]["finished"]:
        response += f"\n⚠️ ملاحظة: الجولة {gameweek} لم تنته بعد، البيانات الحالية مؤقتة."
    
    return response

def format_detailed_display(manager_id, info, gameweek, picks_data, history):
    """تنسيق العرض المفصل"""
    name = safe_str(info.get("name"))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "" or joined == "None":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))
    
    # نقاط الجولة
    event_points = 0
    event_rank = 0
    total_transfers = safe_int(info.get("total_transfers"))
    
    if picks_data and "entry_history" in picks_data:
        entry_history = picks_data["entry_history"]
        event_points = safe_int(entry_history.get("points", 0))
        event_rank = safe_int(entry_history.get("rank", 0))
        total_transfers = safe_int(entry_history.get("event_transfers", total_transfers))
    
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 المعرف: `{manager_id}`\n"
        f"📅 انضم: {joined}\n\n"
        f"📊 **العرض المفصل - الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*\n"
        f"🔄 انتقالات الجولة: *{total_transfers}*\n"
        f"📊 ترتيب الجولة: *{event_rank_str}*\n\n"
    )
    
    # ==========================================
    # عرض لاعبي الفريق مع نقاط كل لاعب
    # ==========================================
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
    
    # ==========================================
    # عرض المجموعات (الدوريات)
    # ==========================================
    leagues = info.get("leagues", {})
    classic_leagues = leagues.get("classic", [])
    
    if classic_leagues:
        response += "🏅 **المجموعات (الدوريات):**\n"
        for idx, league in enumerate(classic_leagues[:5], 1):
            league_name = safe_str(league.get("name", "غير معروف"))
            league_rank = safe_int(league.get("rank", 0))
            league_total = safe_int(league.get("total_teams", 0))
            rank_display = f"{league_rank}" if league_rank > 0 else "غير معروف"
            response += f"{idx}. {league_name}: {rank_display}/{league_total}\n"
        response += "\n"
    
    # ==========================================
    # عرض تاريخ المواسم السابقة
    # ==========================================
    if history and "past" in history and history["past"]:
        response += "📜 **آخر 3 مواسم:**\n"
        for season in history["past"][-3:]:
            season_name = safe_str(season.get("season_name"))
            season_points = safe_int(season.get("total_points"))
            season_rank = safe_int(season.get("rank"))
            season_rank_str = f"{season_rank:,}" if season_rank > 0 else "غير مصنف"
            response += f"• {season_name}: {season_points} نقطة (ترتيب {season_rank_str})\n"
    
    # إضافة ملاحظة إذا كانت الجولة لم تلعب بعد
    if gameweek in gameweeks_info and not gameweeks_info[gameweek]["finished"]:
        response += f"\n⚠️ ملاحظة: الجولة {gameweek} لم تنته بعد، البيانات الحالية مؤقتة."
    
    return response

# ==================================================
# دوال إنشاء الأزرار
# ==================================================

def get_buttons(manager_id, gameweek, current_view):
    """إنشاء أزرار التنقل"""
    next_gw = get_next_gameweek(gameweek)
    prev_gw = get_previous_gameweek(gameweek)
    
    keyboard = [
        [
            InlineKeyboardButton("📋 عرض بسيط", callback_data=f"simple_{manager_id}_{gameweek}"),
            InlineKeyboardButton("📊 عرض مفصل", callback_data=f"detail_{manager_id}_{gameweek}")
        ],
        [
            InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{prev_gw}"),
            InlineKeyboardButton("➡️ الجولة القادمة", callback_data=f"nav_{manager_id}_{next_gw}")
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)

# ==================================================
# معالجات البوت
# ==================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل النصية (الأرقام)"""
    message_text = update.message.text.strip()
    
    if message_text.startswith('/start') or message_text.startswith('/help'):
        await update.message.reply_text(
            "🎮 **بوت مساعد الفانتاسي التفاعلي**\n\n"
            "✨ **كيف يعمل؟**\n"
            "1️⃣ أرسل **رقم معرف المدرب**\n"
            "2️⃣ سيظهر لك بيانات **آخر جولة لعبت** تلقائياً\n"
            "3️⃣ استخدم الأزرار للتبديل بين:\n"
            "   • 📋 عرض بسيط - الاسم، النقاط، الكابتن\n"
            "   • 📊 عرض مفصل - كل المعلومات (اللاعبين، المجموعات، التاريخ)\n"
            "   • ⬅️ الجولة السابقة - للانتقال للجولة السابقة\n"
            "   • ➡️ الجولة القادمة - للانتقال للجولة التالية\n\n"
            "🔄 **التنقل الدائري:**\n"
            "• بعد الجولة 38 → يعود للجولة 1\n"
            "• قبل الجولة 1 → يذهب للجولة 38\n\n"
            "🔑 **كيف تحصل على معرف مدرب؟**\n"
            "افتح موقع FPL، الرقم في الرابط:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📝 **مثال:** أرسل `2794801`",
            parse_mode='Markdown'
        )
        return
    
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
    
    name = safe_str(info.get("name"))
    start_gameweek = last_gameweek
    
    await update.message.reply_text(
        f"✅ تم العثور على المدرب **{name}**!\n"
        f"📅 سيتم عرض بيانات **الجولة {start_gameweek}** (آخر جولة لعبت)\n\n"
        f"🔄 جاري تحميل البيانات...",
        parse_mode='Markdown'
    )
    
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
    
    parts = data.split("_")
    
    if len(parts) < 3:
        return
    
    # معالجة أزرار التنقل (nav)
    if parts[0] == "nav":
        manager_id = parts[1]
        gameweek = int(parts[2])
        
        # تحديد نوع العرض الحالي
        current_text = query.message.text
        if "العرض البسيط" in current_text:
            view_type = "simple"
        else:
            view_type = "detail"
        
        await query.edit_message_text(
            text=f"🔄 جاري تحميل بيانات الجولة {gameweek}...",
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
        
        if view_type == "simple":
            text = format_simple_display(manager_id, info, gameweek, picks_data)
        else:
            history = get_manager_history(manager_id)
            text = format_detailed_display(manager_id, info, gameweek, picks_data, history)
        
        reply_markup = get_buttons(manager_id, gameweek, view_type)
        
        await query.edit_message_text(
            text=text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    # معالجة أزرار العرض (simple/detail)
    if parts[0] in ["simple", "detail"]:
        view_type = parts[0]
        manager_id = parts[1]
        gameweek = int(parts[2])
        
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
        
        if view_type == "simple":
            text = format_simple_display(manager_id, info, gameweek, picks_data)
        else:
            history = get_manager_history(manager_id)
            text = format_detailed_display(manager_id, info, gameweek, picks_data, history)
        
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
    print("🤖 البوت التفاعلي يعمل الآن...")
    print(f"📅 آخر جولة لعبت: {last_gameweek}")
    print("🔄 نظام التنقل الدائري (1 ←→ 38)")
    print("📡 أرسل معرف مدرب للبدء")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
