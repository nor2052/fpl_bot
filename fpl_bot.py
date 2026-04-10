import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# تفعيل تسجيل الأخطاء بمستوى DEBUG لرؤية كل التفاصيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ==================================================
# اقرأ التوكن من متغيرات البيئة
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    exit(1)

BASE_URL = "https://fantasy.premierleague.com/api"

# قاموس لتخزين بيانات الدوريات مؤقتاً
league_rank_cache = {}

# ==================================================
# دوال جلب البيانات مع سجلات التصحيح
# ==================================================

def safe_api_request(url, debug_name="API Request"):
    """تنفيذ طلب API بأمان مع إعادة المحاولة وسجلات التصحيح"""
    logger.debug(f"📡 [{debug_name}] بدء طلب إلى: {url}")
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            logger.debug(f"📡 [{debug_name}] محاولة {attempt+1}: استجابة {response.status_code}")
            if response.status_code == 200:
                logger.debug(f"✅ [{debug_name}] نجح الطلب")
                return response.json()
            elif response.status_code == 404:
                logger.warning(f"⚠️ [{debug_name}] 404 - غير موجود: {url}")
                return None
        except Exception as e:
            logger.warning(f"⚠️ [{debug_name}] محاولة {attempt+1} فشلت: {e}")
    logger.error(f"❌ [{debug_name}] فشل الطلب بعد 3 محاولات")
    return None

def get_manager_info(manager_id):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/", "get_manager_info")

def get_manager_history(manager_id):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/history/", "get_manager_history")

def get_manager_picks(manager_id, gameweek):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/", "get_manager_picks")

def get_live_points(gameweek):
    url = f"{BASE_URL}/event/{gameweek}/live/"
    data = safe_api_request(url, "get_live_points")
    live_points = {}
    if data and "elements" in data:
        for element in data["elements"]:
            points = element.get("stats", {}).get("total_points", 0)
            live_points[element["id"]] = points
    logger.debug(f"📊 get_live_points: تم جلب {len(live_points)} لاعب")
    return live_points

def get_league_standings(league_id, manager_id):
    """
    جلب ترتيب المدرب في دوري معين.
    هذه هي الدالة الأهم - سنضيف لها سجلات تفصيلية.
    """
    cache_key = f"{league_id}_{manager_id}"
    
    # التحقق من الكاش
    if cache_key in league_rank_cache:
        logger.debug(f"🗂️ get_league_standings: تم استرداد {cache_key} من الكاش = {league_rank_cache[cache_key]}")
        return league_rank_cache[cache_key]
    
    logger.debug(f"🔍 get_league_standings: جلب ترتيب الدوري {league_id} للمدرب {manager_id}")
    
    url = f"{BASE_URL}/leagues-classic/{league_id}/standings/"
    data = safe_api_request(url, f"get_league_standings_{league_id}")
    
    if not data:
        logger.warning(f"⚠️ get_league_standings: لا توجد بيانات للدوري {league_id}")
        return (None, None)
    
    logger.debug(f"📄 get_league_standings: البيانات المستلمة تحتوي على مفاتيح: {data.keys()}")
    
    if "standings" in data and "results" in data["standings"]:
        logger.debug(f"📋 get_league_standings: عدد النتائج في الترتيب: {len(data['standings']['results'])}")
        
        for entry in data["standings"]["results"]:
            entry_id = entry.get("entry")
            logger.debug(f"  - مقارنة معرف المدرب: {entry_id} == {manager_id}?")
            if str(entry_id) == str(manager_id):
                rank = entry.get("rank")
                total_teams = data["standings"].get("total_teams")
                logger.info(f"🎉 تم العثور على المدرب! الترتيب: {rank}/{total_teams}")
                result = (rank, total_teams)
                league_rank_cache[cache_key] = result
                return result
        
        logger.warning(f"⚠️ لم يتم العثور على المدرب {manager_id} في ترتيب الدوري {league_id}")
    else:
        logger.warning(f"⚠️ get_league_standings: هيكل البيانات غير متوقع للدوري {league_id}")
        logger.debug(f"   محتوى data: {str(data)[:500]}...")
    
    return (None, None)

def get_players_dict():
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_players_dict")
    players = {}
    if data and "elements" in data:
        for player in data["elements"]:
            players[player["id"]] = f"{player['first_name']} {player['second_name']}"
    logger.info(f"👥 تم تحميل {len(players)} لاعب")
    return players

def get_last_played_gameweek():
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_last_played_gameweek")
    if data and "events" in data:
        for event in reversed(data["events"]):
            if event.get("finished"):
                logger.info(f"📅 آخر جولة لعبت: {event['id']}")
                return event["id"]
    return 1

def get_next_gameweek(current_gw):
    next_gw = current_gw + 1
    return next_gw if next_gw <= 38 else 1

def get_previous_gameweek(current_gw):
    prev_gw = current_gw - 1
    return prev_gw if prev_gw >= 1 else 38

# ----------------------------- تحميل البيانات الأساسية -----------------------------
players_dict = get_players_dict()
last_gameweek = get_last_played_gameweek()
print(f"📅 آخر جولة لعبت: {last_gameweek}")

# ----------------------------- دوال مساعدة -----------------------------
def safe_int(value):
    return int(value) if value is not None else 0

def safe_str(value):
    return str(value) if value is not None else "غير معروف"

# ----------------------------- دوال عرض المعلومات -----------------------------

def format_simple_display(manager_id, info, gameweek, picks_data):
    name = safe_str(info.get("name"))
    total_points = safe_int(info.get("summary_overall_points"))
    
    event_points = 0
    if picks_data and "entry_history" in picks_data:
        event_points = safe_int(picks_data["entry_history"].get("points", 0))
    
    captain_points = 0
    captain_name = ""
    
    if picks_data and "picks" in picks_data:
        live_points_map = get_live_points(gameweek)
        for pick in picks_data["picks"]:
            if pick.get("is_captain"):
                player_id = pick.get("element")
                player_name = players_dict.get(player_id, f"لاعب {player_id}")
                actual_points = live_points_map.get(player_id, 0)
                multiplier = pick.get("multiplier", 1)
                captain_points = actual_points * multiplier
                captain_name = player_name
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
    
    return response

def format_detailed_display(manager_id, info, gameweek, picks_data, history):
    name = safe_str(info.get("name"))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "" or joined == "None":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))
    
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
    # عرض لاعبي الفريق
    # ==========================================
    if picks_data and "picks" in picks_data:
        live_points_map = get_live_points(gameweek)
        
        response += "🧑‍🤝‍🧑 **لاعبو الفريق (الأساسيون):**\n"
        for idx, pick in enumerate(picks_data["picks"][:11], 1):
            player_id = pick.get("element")
            player_name = players_dict.get(player_id, f"لاعب {player_id}")
            actual_points = live_points_map.get(player_id, 0)
            multiplier = pick.get("multiplier", 1)
            display_points = actual_points * multiplier
            is_captain = " 👑 (C)" if pick.get("is_captain") else ""
            is_vice = " (VC)" if pick.get("is_vice_captain") else ""
            response += f"{idx}. {player_name}{is_captain}{is_vice}: {display_points} نقطة\n"
        response += "\n"
    else:
        response += "⚠️ لا توجد بيانات للاعبين في هذه الجولة.\n\n"
    
    # ==========================================
    # عرض المجموعات مع الترتيب (مع سجلات إضافية)
    # ==========================================
    leagues = info.get("leagues", {})
    classic_leagues = leagues.get("classic", [])
    
    logger.debug(f"🏅 عدد الدوريات الكلاسيكية: {len(classic_leagues)}")
    
    if classic_leagues:
        response += "🏅 **المجموعات (الدوريات):**\n"
        for idx, league in enumerate(classic_leagues[:5], 1):
            league_name = safe_str(league.get("name", "غير معروف"))
            league_id = league.get("id")
            logger.debug(f"🏅 معالجة الدوري {idx}: {league_name} (ID: {league_id})")
            
            if league_id:
                # محاولة جلب الترتيب
                league_rank, league_total = get_league_standings(league_id, manager_id)
                logger.debug(f"   النتيجة: rank={league_rank}, total={league_total}")
                
                if league_rank is not None and league_total is not None:
                    response += f"{idx}. {league_name}: {league_rank}/{league_total}\n"
                elif league_rank is not None:
                    response += f"{idx}. {league_name}: الترتيب {league_rank}\n"
                else:
                    response += f"{idx}. {league_name}\n"
                    logger.warning(f"⚠️ لم يتم العثور على ترتيب للمدرب في الدوري {league_name}")
            else:
                response += f"{idx}. {league_name}\n"
                logger.warning(f"⚠️ الدوري {league_name} ليس له معرف (league_id)")
        response += "\n"
    else:
        response += "🏅 **المجموعات:** لا يشارك في مجموعات حالياً\n\n"
    
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
    
    return response

# ----------------------------- دوال الأزرار ومعالجات البوت -----------------------------

def get_buttons(manager_id, gameweek, current_view):
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    
    if message_text.startswith('/start') or message_text.startswith('/help'):
        await update.message.reply_text(
            "🎮 **بوت مساعد الفانتاسي التفاعلي - مع سجلات التصحيح**\n\n"
            "✨ **كيف يعمل؟**\n"
            "1️⃣ أرسل **رقم معرف المدرب**\n"
            "2️⃣ سيظهر لك بيانات **آخر جولة لعبت** تلقائياً\n\n"
            "🔍 **ملاحظة:** هذا الإصدار يحتوي على سجلات تصحيح (Debug Logs)\n"
            "يمكنك مراجعة سجل Railway لمعرفة سبب عدم ظهور ترتيب الدوريات\n\n"
            "📝 **مثال:** أرسل `2794801`",
            parse_mode='Markdown'
        )
        return
    
    try:
        manager_id = int(message_text)
    except ValueError:
        await update.message.reply_text(
            "❌ يرجى إرسال **رقم معرف المدرب** فقط.\nمثال: `1234567`\nأو أرسل /help للمساعدة",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(f"🔄 جاري التحقق من المعرف {manager_id}...")
    
    info = get_manager_info(manager_id)
    if not info:
        await update.message.reply_text(
            f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
            parse_mode='Markdown'
        )
        return
    
    name = safe_str(info.get("name"))
    start_gameweek = last_gameweek
    
    await update.message.reply_text(
        f"✅ تم العثور على المدرب **{name}**!\n📅 سيتم عرض بيانات **الجولة {start_gameweek}**\n\n🔄 جاري تحميل البيانات...",
        parse_mode='Markdown'
    )
    
    picks_data = get_manager_picks(manager_id, start_gameweek)
    text = format_simple_display(manager_id, info, start_gameweek, picks_data)
    reply_markup = get_buttons(manager_id, start_gameweek, "simple")
    
    await update.message.reply_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    message_id = query.message.message_id
    parts = data.split("_")
    
    if len(parts) < 3:
        return
    
    if parts[0] == "nav":
        manager_id = parts[1]
        gameweek = int(parts[2])
        
        current_text = query.message.text
        view_type = "simple" if "العرض البسيط" in current_text else "detail"
        
        await query.edit_message_text(text=f"🔄 جاري تحميل بيانات الجولة {gameweek}...", reply_markup=None)
        
        info = get_manager_info(manager_id)
        if not info:
            await query.edit_message_text(text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.", parse_mode='Markdown')
            return
        
        picks_data = get_manager_picks(manager_id, gameweek)
        if view_type == "simple":
            text = format_simple_display(manager_id, info, gameweek, picks_data)
        else:
            text = format_detailed_display(manager_id, info, gameweek, picks_data, get_manager_history(manager_id))
        
        reply_markup = get_buttons(manager_id, gameweek, view_type)
        
        await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)
        return
    
    if parts[0] in ["simple", "detail"]:
        view_type = parts[0]
        manager_id = parts[1]
        gameweek = int(parts[2])
        
        await query.edit_message_text(text=f"🔄 جاري تحميل { 'العرض البسيط' if view_type == 'simple' else 'العرض المفصل' } للجولة {gameweek}...", reply_markup=None)
        
        info = get_manager_info(manager_id)
        if not info:
            await query.edit_message_text(text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.", parse_mode='Markdown')
            return
        
        picks_data = get_manager_picks(manager_id, gameweek)
        if view_type == "simple":
            text = format_simple_display(manager_id, info, gameweek, picks_data)
        else:
            text = format_detailed_display(manager_id, info, gameweek, picks_data, get_manager_history(manager_id))
        
        reply_markup = get_buttons(manager_id, gameweek, view_type)
        
        await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)
        return

# ----------------------------- تشغيل البوت -----------------------------

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("=" * 50)
    print("🤖 البوت يعمل الآن مع سجلات التصحيح (Debug Mode)")
    print(f"📅 آخر جولة لعبت: {last_gameweek}")
    print("📡 أرسل معرف مدرب للبدء")
    print("🔍 تأكد من مراجعة سجل Railway (Logs) لرؤية تفاصيل الطلبات")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
