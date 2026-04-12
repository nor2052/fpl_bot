import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# تفعيل تسجيل الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================================================
# اقرأ التوكن من متغيرات البيئة
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    exit(1)

BASE_URL = "https://fantasy.premierleague.com/api"

# ==================================================
# دوال جلب البيانات
# ==================================================

def safe_api_request(url, debug_name="API Request"):
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
            logger.warning(f"محاولة {attempt+1} فشلت: {e}")
    return None

def get_manager_info(manager_id):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/", "get_manager_info")

def get_manager_history(manager_id):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/history/", "get_manager_history")

def get_manager_picks(manager_id, gameweek):
    """جلب تشكيلة المدرب في جولة معينة"""
    logger.info(f"📡 جلب تشكيلة المدرب {manager_id} للجولة {gameweek}")
    result = safe_api_request(f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/", "get_manager_picks")
    if result is None:
        logger.warning(f"⚠️ فشل في جلب تشكيلة المدرب {manager_id} للجولة {gameweek}")
    return result
    
def get_live_points(gameweek):
    """جلب النقاط الحية لجميع اللاعبين - لا نزال نحتاجها لنقاط اللاعبين"""
    url = f"{BASE_URL}/event/{gameweek}/live/"
    data = safe_api_request(url, "get_live_points")
    live_points = {}
    if data and "elements" in data:
        for element in data["elements"]:
            points = element.get("stats", {}).get("total_points", 0)
            live_points[element["id"]] = points
    return live_points

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

def get_current_gameweek():
    """الحصول على رقم الجولة الحالية (الجاري لعبها الآن)"""
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_current_gameweek")
    if data and "events" in data:
        for event in data["events"]:
            if event.get("is_current"):
                logger.info(f"📅 الجولة الحالية: {event['id']}")
                return event["id"]
        # إذا لم تكن هناك جولة حالية، نأخذ أقرب جولة مستقبلية
        for event in data["events"]:
            if event.get("is_next"):
                logger.info(f"📅 الجولة القادمة: {event['id']}")
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
current_gameweek = get_current_gameweek()
print(f"📅 آخر جولة لعبت: {current_gameweek}")

# ----------------------------- دوال مساعدة -----------------------------
def safe_int(value):
    return int(value) if value is not None else 0

def safe_str(value):
    return str(value) if value is not None else "غير معروف"

# ----------------------------- دوال عرض المعلومات -----------------------------

def sanitize_markdown(text):
    """إزالة الأحرف التي قد تعطل تنسيق Markdown"""
    if not text:
        return "غير معروف"
    # استبدال الأحرف الخاصة
    dangerous_chars = ['*', '_', '`', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in dangerous_chars:
        text = text.replace(char, f'\\{char}')
    return text

def format_simple_display(manager_id, info, gameweek, picks_data):
    name = sanitize_markdown(safe_str(info.get("name")))
    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))

    live_points_map = get_live_points(gameweek)

    event_points = 0
    event_rank = 0
    captain_points = 0
    captain_name = ""

    if picks_data and "picks" in picks_data:
        for pick in picks_data["picks"][:11]:
            player_id = pick.get("element")
            actual_points = live_points_map.get(player_id, 0)
            multiplier = pick.get("multiplier", 1)
            event_points += actual_points * multiplier

            if pick.get("is_captain"):
                captain_points = actual_points * multiplier
                captain_name = sanitize_markdown(players_dict.get(player_id, f"لاعب {player_id}"))

        if "entry_history" in picks_data:
            event_rank = safe_int(picks_data["entry_history"].get("rank", 0))

    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"

    response = (
        f"🎮 **{name}**\n"
        f"🆔 `{manager_id}`\n"
        f"📊 **الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة: *{event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*\n"
        f"📊 ترتيب الجولة: *{event_rank_str}*\n"
    )

    if captain_name:
        response += f"👑 الكابتن ({captain_name}): *{captain_points}* نقطة\n"
    else:
        response += f"👑 نقاط الكابتن: *{captain_points}*\n"

    return response

def format_detailed_display(manager_id, info, gameweek, picks_data, history):
    """عرض مفصل يتضمن معلومات أساسية + اللاعبين الأساسيين + اللاعبين البدلاء + القيمة المالية"""
    name = sanitize_markdown(safe_str(info.get("name")))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "" or joined == "None":
        joined = "غير معروف"

    total_points = safe_int(info.get("summary_overall_points"))
    rank = safe_int(info.get("summary_overall_rank"))
    
    # ========== القسم المصحح: استخراج القيمة المالية ==========
    team_value = 0.0
    bank_value = 0.0
    total_value_display = 0.0
    
    if picks_data and "entry_history" in picks_data:
        history_info = picks_data["entry_history"]
        raw_total_value = safe_int(history_info.get("value", 0))  # القيمة الكلية (تشكيلة + بنك)
        raw_bank = safe_int(history_info.get("bank", 0))          # البنك فقط
        
        bank_value = raw_bank / 10
        team_value = (raw_total_value - raw_bank) / 10
        total_value_display = raw_total_value / 10
    # =====================================================

    live_points_map = get_live_points(gameweek)

    calculated_event_points = 0
    total_transfers = safe_int(info.get("total_transfers"))
    event_rank = 0

    if picks_data and "picks" in picks_data:
        for pick in picks_data["picks"][:11]:
            player_id = pick.get("element")
            actual_points = live_points_map.get(player_id, 0)
            multiplier = pick.get("multiplier", 1)
            calculated_event_points += actual_points * multiplier

        if "entry_history" in picks_data:
            event_rank = safe_int(picks_data["entry_history"].get("rank", 0))
            total_transfers = safe_int(picks_data["entry_history"].get("event_transfers", total_transfers))

    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"

    response = (
        f"🎮 **{name}**\n"
        f"🆔 `{manager_id}`\n"
        f"📅 انضم: {joined}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة: *{calculated_event_points}*\n"
        f"🏆 النقاط الكلية: *{total_points}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*\n"
        f"🔄 انتقالات الجولة: *{total_transfers}*\n"
        f"📊 ترتيب الجولة: *{event_rank_str}*\n\n"
    )
    
    # ========== عرض القيمة المالية ==========
    if team_value > 0 or bank_value > 0:
        response += (
            f"💰 **المالية:**\n"
            f"• قيمة التشكيلة: *£{team_value:.1f}m*\n"
            f"• البنك: *£{bank_value:.1f}m*\n"
            f"• الإجمالي: *£{total_value_display:.1f}m*\n\n"
        )
    # ======================================
    
    # الحصول على بيانات اللاعبين الكاملة لمعرفة مراكزهم
    players_full_data = {}
    bootstrap_data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_players_full_data")
    if bootstrap_data and "elements" in bootstrap_data:
        for player in bootstrap_data["elements"]:
            players_full_data[player["id"]] = {
                "element_type": player.get("element_type"),  # 1=GK, 2=DEF, 3=MID, 4=FWD
                "name": f"{player['first_name']} {player['second_name']}"
            }

    # قاموس ترجمة المراكز
    position_names = {1: "🧤 الحراسة", 2: "🛡️ الدفاع", 3: "⚡ الوسط", 4: "🎯 الهجوم"}
    
    # عرض لاعبي الفريق الأساسيين
    if picks_data and "picks" in picks_data:
        response += "🧑‍🤝‍🧑 **اللاعبون الأساسيون:**\n\n"
        
        # تجميع اللاعبين حسب المركز
        players_by_position = {1: [], 2: [], 3: [], 4: []}
        
        for pick in picks_data["picks"][:11]:
            player_id = pick.get("element")
            player_info = players_full_data.get(player_id, {})
            position = player_info.get("element_type", 0)
            player_name = sanitize_markdown(players_dict.get(player_id, f"لاعب {player_id}"))
            actual_points = live_points_map.get(player_id, 0)
            multiplier = pick.get("multiplier", 1)
            display_points = actual_points * multiplier
            is_captain = " 👑" if pick.get("is_captain") else ""
            is_vice = " (VC)" if pick.get("is_vice_captain") else ""
            
            player_text = f"{player_name}{is_captain}{is_vice}: {display_points} نقطة"
            
            if position in players_by_position:
                players_by_position[position].append(player_text)
            else:
                players_by_position[0].append(player_text)  # في حال عدم معرفة المركز
        
        # عرض اللاعبين حسب المركز مع ترقيم متسلسل
        counter = 1
        for pos in [1, 2, 3, 4]:
            if players_by_position[pos]:
                response += f"{position_names[pos]}:\n"
                for player_text in players_by_position[pos]:
                    response += f"{counter}. {player_text}\n"
                    counter += 1
        
        # عرض اللاعبين البدلاء (الاحتياط)
        if len(picks_data["picks"]) > 11:
            response += "\n🔄 **اللاعبون البدلاء:**\n\n"
            
            # تجميع البدلاء حسب المركز
            subs_by_position = {1: [], 2: [], 3: [], 4: []}
            
            for pick in picks_data["picks"][11:]:
                player_id = pick.get("element")
                player_info = players_full_data.get(player_id, {})
                position = player_info.get("element_type", 0)
                player_name = sanitize_markdown(players_dict.get(player_id, f"لاعب {player_id}"))
                actual_points = live_points_map.get(player_id, 0)
                
                player_text = f"{player_name}: {actual_points} نقطة"
                
                if position in subs_by_position:
                    subs_by_position[position].append(player_text)
                else:
                    subs_by_position[0].append(player_text)
            
            # عرض البدلاء حسب المركز مع ترقيم متسلسل
            counter = 1
            for pos in [1, 2, 3, 4]:
                if subs_by_position[pos]:
                    response += f"{position_names[pos]}:\n"
                    for player_text in subs_by_position[pos]:
                        response += f"{counter}. {player_text}\n"
                        counter += 1
        response += "\n"
    else:
        response += "⚠️ لا توجد بيانات للاعبين في هذه الجولة.\n\n"

    return response

# انتهت دالة العرض المفصل والتالية هي دالة عرض الدوريات

def format_leagues_display(manager_id, info, gameweek, history):
    """عرض منفصل للمجموعات والدوريات والمواسم السابقة"""
    name = sanitize_markdown(safe_str(info.get("name")))
    
    response = (
        f"🏆 **الدوريات والمواسم**\n"
        f"🎮 {name}\n"
        f"🆔 `{manager_id}`\n"
        f"📊 **الجولة {gameweek}**\n"
    )
    
        # عرض المجموعات
    leagues = info.get("leagues", {})
    classic_leagues = leagues.get("classic", [])

    if classic_leagues:
        response += "🏅 **المجموعات (الدوريات):**\n\n"
        for idx, league in enumerate(classic_leagues[:20], 1):
            league_name = sanitize_markdown(safe_str(league.get("name", "غير معروف")))
            league_rank = league.get('entry_rank')
            if not league_rank:
                league_rank = league.get('rank')
            league_total = league.get('rank_count')

            if league_rank is not None and league_total is not None:
                league_rank_str = f"{league_rank:,}"
                league_total_str = f"{league_total:,}"
                response += f"{idx}. {league_name}: {league_rank_str} / {league_total_str}\n\n"
            elif league_rank is not None:
                response += f"{idx}. {league_name}: الترتيب {league_rank}\n\n"
            else:
                response += f"{idx}. {league_name}\n\n"
    else:
        response += "🏅 **المجموعات:** لا يشارك في مجموعات حالياً\n\n"

    # عرض تاريخ المواسم السابقة
    if history and "past" in history and history["past"]:
        response += "📜 **المواسم السابقة:**\n"
        for season in history["past"][-5:]:  # آخر 5 مواسم
            season_name = sanitize_markdown(safe_str(season.get("season_name")))
            season_points = safe_int(season.get("total_points"))
            season_rank = safe_int(season.get("rank"))
            season_rank_str = f"{season_rank:,}" if season_rank > 0 else "غير مصنف"
            response += f"• {season_name}: {season_points} نقطة (ترتيب {season_rank_str})\n"
    else:
        response += "📜 **المواسم السابقة:** لا يوجد تاريخ للمواسم السابقة\n\n"

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
            InlineKeyboardButton("🏆 الدوريات", callback_data=f"leagues_{manager_id}_{gameweek}")
        ],
        [
            InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{prev_gw}"),
            InlineKeyboardButton("➡️ الجولة التالية", callback_data=f"nav_{manager_id}_{next_gw}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()

    if message_text.startswith('/start') or message_text.startswith('/help'):
        await update.message.reply_text(
        "🎮 **بوت مساعد الفانتاسي**\n"
        "✨ **كيف يعمل؟**\n"
        "• أرسل **رقم معرف المدرب**\n"
        "• سأعرض لك بيانات الجولة الحالية تلقائياً\n\n"
        "📊 **البيانات المتاحة**\n"
        "✓ نقاط الجولة للمدرب\n"
        "✓ النقاط الكلية والترتيب العالمي\n"
        "✓ نقاط كل لاعب في الفريق\n"
        "✓ نقاط الكابتن\n"
        "✓ قيمة الفريق والبنك 💰\n"
        "✓ ترتيب المدرب في كل دوري\n"
        "✓ تاريخ المواسم السابقة\n"    
        "🔑 **كيف تحصل على معرف مدرب؟**\n"
        "افتح موقع FPL، الرقم في الرابط:\n"
        "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
        "📝 **مثال:** أرسل `2794801`",
        parse_mode='Markdown'
)
        return

    try:
        manager_id = int(message_text)
        # حفظ معرف المدرب لهذا المستخدم
        context.user_data['current_manager_id'] = manager_id
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
            f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.\n\nتأكد من صحة المعرف.\nيمكنك تجربة: `2794801`",
            parse_mode='Markdown'
        )
        return

    name = safe_str(info.get("name"))
    start_gameweek = current_gameweek

    await update.message.reply_text(
        f"✅ تم العثور على المدرب **{name}**!\n📅 سيتم عرض بيانات **الجولة {start_gameweek}** (الجولة الحالية)\n\n🔄 جاري تحميل البيانات...",
        parse_mode='Markdown'
    )

    picks_data = get_manager_picks(manager_id, start_gameweek)
    text = format_simple_display(manager_id, info, start_gameweek, picks_data)
    reply_markup = get_buttons(manager_id, start_gameweek, "simple")

    await update.message.reply_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار - دعم متعدد المستخدمين مع معالجة الأخطاء"""
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"فشل في answer callback: {e}")
    
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    parts = data.split("_")
    
    if len(parts) < 3:
        logger.warning(f"تنسيق غير صحيح للبيانات: {data}")
        return
    
    # استخدم manager_id من user_data إذا كان متاحاً، وإلا استخدمه من callback_data
    manager_id = context.user_data.get('current_manager_id')
    if not manager_id:
        # محاولة استخراج manager_id من callback_data كحل احتياطي
        try:
            manager_id = parts[1]
        except IndexError:
            await context.bot.edit_message_text(
                text="❌ حدث خطأ: يرجى إرسال معرف المدرب مرة أخرى باستخدام /start",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
            return
    
    try:
        # معالجة أزرار التنقل (nav)
        if parts[0] == "nav":
            gameweek = int(parts[2])
            
            current_text = query.message.text
            # تحديد نوع العرض الحالي
            if "العرض المفصل" in current_text or "اللاعبون الأساسيون" in current_text:
                view_type = "detail"
            elif "الدوريات" in current_text:
                view_type = "leagues"
            else:
                view_type = "simple"
            
            # إظهار مؤقت التحميل
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل بيانات الجولة {gameweek}...",
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            
            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='Markdown'
                )
                return
            
            picks_data = get_manager_picks(manager_id, gameweek)
            
            if view_type == "simple":
                text = format_simple_display(manager_id, info, gameweek, picks_data)
            elif view_type == "detail":
                text = format_detailed_display(manager_id, info, gameweek, picks_data, get_manager_history(manager_id))
            else:  # leagues
                text = format_leagues_display(manager_id, info, gameweek, get_manager_history(manager_id))
            
            reply_markup = get_buttons(manager_id, gameweek, view_type)
            
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        
        # معالجة أزرار العرض (simple/detail/leagues)
        elif parts[0] in ["simple", "detail", "leagues"]:
            view_type = parts[0]
            gameweek = int(parts[2])
            
            # نصوص التحميل المناسبة
            loading_texts = {
                "simple": "العرض البسيط",
                "detail": "العرض المفصل",
                "leagues": "الدوريات والمواسم"
            }
            
            # إظهار مؤقت التحميل
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل {loading_texts[view_type]} للجولة {gameweek}...",
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
            
            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='Markdown'
                )
                return
            
            picks_data = get_manager_picks(manager_id, gameweek)
            
            if view_type == "simple":
                text = format_simple_display(manager_id, info, gameweek, picks_data)
            elif view_type == "detail":
                text = format_detailed_display(manager_id, info, gameweek, picks_data, get_manager_history(manager_id))
            else:  # leagues
                text = format_leagues_display(manager_id, info, gameweek, get_manager_history(manager_id))
            
            reply_markup = get_buttons(manager_id, gameweek, view_type)
            
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return
        
        else:
            logger.warning(f"نوع أمر غير معروف: {parts[0]}")
            
    except Exception as e:
        logger.error(f"خطأ في معالجة callback: {e}")
        # محاولة إرسال رسالة خطأ للمستخدم
        try:
            await context.bot.edit_message_text(
                text=f"❌ حدث خطأ أثناء تحميل البيانات: {str(e)[:100]}\n\nيرجى المحاولة مرة أخرى بإرسال معرف المدرب.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
        except Exception as edit_error:
            logger.error(f"فشل في إرسال رسالة الخطأ: {edit_error}")

# ----------------------------- تشغيل البوت -----------------------------

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("=" * 50)
    print("🤖 البوت يعمل الآن (الإصدار المحسن)")
    print(f"📅 آخر جولة لعبت: {current_gameweek}")
    print("✅ المميزات الجديدة:")
    print("   • زر منفصل للدوريات والمواسم السابقة")
    print("   • العرض المفصل يشمل اللاعبين الأساسيين والبدلاء")
    print("   • تنقل سلس بين جميع العروض")
    print("📡 أرسل معرف مدرب للبدء")
    print("=" * 50)

    application.run_polling()

if __name__ == '__main__':
    main()
