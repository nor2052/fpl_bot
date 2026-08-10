import os
import logging
import calendar
from datetime import datetime, timezone, timedelta
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# ============================================================
# الإعدادات الأساسية والتكوين
# ============================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    exit(1)

BASE_URL = "https://fantasy.premierleague.com/api"

CHANNELS = [
    {"id": "@Fantasypremierlea", "name": "القناة الأولى"},
    {"id": "@Fantasyargoal", "name": "القناة الثانية"},
]

POSITION_OVERRIDES_26_27 = {}

# ============================================================
# دوال مساعدة عامة
# ============================================================

def safe_int(value):
    return int(value) if value is not None else 0

def safe_str(value):
    return str(value) if value is not None else "غير معروف"

def sanitize_markdown(text):
    if not text:
        return "غير معروف"
    dangerous_chars = ['[', ']', '(', ')', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in dangerous_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    for channel in CHANNELS:
        channel_id = channel["id"]
        try:
            chat_member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if chat_member.status not in ["member", "administrator", "creator"]:
                logger.info(f"المستخدم {user_id} غير مشترك في القناة {channel_id}")
                return False
        except Exception as e:
            logger.error(f"خطأ في التحقق من اشتراك المستخدم {user_id} في القناة {channel_id}: {e}")
            return False  # تم التعديل إلى False لضمان الأمان
    return True
    
def safe_api_request(url, debug_name="API Request"):
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

def format_number_abbreviation(num):
    if num is None or num == 0:
        return "0"
    
    abs_num = abs(num)
    sign = "+" if num > 0 else "-"
    
    if abs_num >= 1_000_000:
        value = abs_num / 1_000_000
        return f"{sign}{value:.1f}M".replace('.0M', 'M')
    elif abs_num >= 1_000:
        value = abs_num / 1_000
        return f"{sign}{value:.0f}K".replace('.0K', 'K')
    else:
        return f"{sign}{abs_num}"

def get_rank_change_display(manager_id, gameweek, history):
    current_rank = 0
    previous_rank = 0
    
    if history and "current" in history:
        for gw_entry in history["current"]:
            if gw_entry.get("event") == gameweek:
                current_rank = safe_int(gw_entry.get("overall_rank"))
            elif gw_entry.get("event") == gameweek - 1:
                previous_rank = safe_int(gw_entry.get("overall_rank"))
    
    if current_rank <= 0 or previous_rank <= 0:
        return ""
    
    if current_rank == previous_rank:
        return ""
    
    diff = previous_rank - current_rank
    
    if diff > 0:
        formatted_diff = format_number_abbreviation(diff)
        return f" 🚀 **(+{formatted_diff[1:]})**" if formatted_diff.startswith('+') else f" 🚀 **({formatted_diff})**"
    else:
        formatted_diff = format_number_abbreviation(diff)
        return f" 🔻 **({formatted_diff})**"

def get_league_change_display(current_rank, previous_rank):
    if previous_rank <= 0 or current_rank <= 0:
        return ""
    
    diff = previous_rank - current_rank
    
    if diff > 0:
        formatted_diff = format_number_abbreviation(diff)
        return f" 🚀 **(+{formatted_diff[1:]})**" if formatted_diff.startswith('+') else f" 🚀 **({formatted_diff})**"
    elif diff < 0:
        formatted_diff = format_number_abbreviation(diff)
        return f" 🔻 **({formatted_diff})**"
    return ""

# ============================================================
# دوال جلب البيانات من API
# ============================================================

def get_manager_info(manager_id):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/", "get_manager_info")

def get_manager_history(manager_id):
    return safe_api_request(f"{BASE_URL}/entry/{manager_id}/history/", "get_manager_history")

def get_manager_picks(manager_id, gameweek):
    logger.info(f"📡 جلب تشكيلة المدرب {manager_id} للجولة {gameweek}")
    result = safe_api_request(f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/", "get_manager_picks")
    if result is None:
        logger.warning(f"⚠️ فشل في جلب تشكيلة المدرب {manager_id} للجولة {gameweek}")
    return result

def get_live_points(gameweek):
    url = f"{BASE_URL}/event/{gameweek}/live/"
    data = safe_api_request(url, "get_live_points")
    live_points = {}
    if data and "elements" in data:
        for element in data["elements"]:
            points = element.get("stats", {}).get("total_points", 0)
            live_points[element["id"]] = points
    return live_points

def get_full_live_data(gameweek):
    url = f"{BASE_URL}/event/{gameweek}/live/"
    data = safe_api_request(url, "get_full_live_data")
    
    players_data = {}
    if data and "elements" in data:
        for element in data["elements"]:
            player_id = element["id"]
            stats = element.get("stats", {})
            
            clearances = stats.get('clearances', 0)
            blocks = stats.get('blocks', 0)
            interceptions = stats.get('interceptions', 0)
            tackles = stats.get('tackles', 0)
            recoveries = stats.get('recoveries', 0)
            cbi = stats.get('clearances_blocks_interceptions', 0)
            
            if cbi > 0:
                cbit_total = cbi + tackles
            else:
                cbit_total = clearances + blocks + interceptions + tackles
            
            cbirt_total = cbit_total + recoveries
            
            players_data[player_id] = {
                "id": player_id,
                "stats": stats,
                "def_metrics": {
                    "cbit": cbit_total,
                    "cbirt": cbirt_total,
                    "clearances": clearances,
                    "blocks": blocks,
                    "interceptions": interceptions,
                    "tackles": tackles,
                    "recoveries": recoveries,
                    "cbi_field": cbi
                }
            }
    return players_data

def get_players_dict():
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_players_dict")
    players = {}
    if data and "elements" in data:
        for player in data["elements"]:
            players[player["id"]] = f"{player['first_name']} {player['second_name']}"
    logger.info(f"👥 تم تحميل {len(players)} لاعب")
    return players

def get_all_players_data(sort_by="points", team_id=None, position_id=None):
    """
    جلب كافة اللاعبين وتنسيق بياناتهم مع التصفية حسب الفريق أو المركز
    """
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_all_players_data")
    players_list = []
    
    if data and "elements" in data:
        for player in data["elements"]:
            p_id = player["id"]
            element_type = player.get("element_type", 0)

            if p_id in POSITION_OVERRIDES_26_27:
                element_type, _ = POSITION_OVERRIDES_26_27[p_id]

            if team_id is not None and player.get("team") != team_id:
                continue

            if position_id is not None and element_type != position_id:
                continue

            try:
                selected_val = float(player.get("selected_by_percent", 0))
            except (ValueError, TypeError):
                selected_val = 0.0

            try:
                form_val = float(player.get("form", 0))
            except (ValueError, TypeError):
                form_val = 0.0

            try:
                ppm_val = float(player.get("points_per_game", 0))
            except (ValueError, TypeError):
                ppm_val = 0.0

            cbi = safe_int(player.get("clearances_blocks_interceptions", 0))
            tackles = safe_int(player.get("tackles", 0))
            recoveries = safe_int(player.get("recoveries", 0))
            def_contrib = cbi + tackles + recoveries

            players_list.append({
                "id": player["id"],
                "name": f"{player['first_name']} {player['second_name']}",
                "position": element_type,
                "price": player.get("now_cost", 0) / 10,
                "total_points": player.get("total_points", 0),
                "team": player.get("team", 0),
                "selected_by": selected_val,
                "form": form_val,
                "ppm": ppm_val,
                "goals": safe_int(player.get("goals_scored", 0)),
                "assists": safe_int(player.get("assists", 0)),
                "clean_sheets": safe_int(player.get("clean_sheets", 0)),
                "saves": safe_int(player.get("saves", 0)),
                "def_contrib": def_contrib
            })
    
    # الفرز بناءً على المسميات الجديدة كلياً
    if sort_by == "price":
        players_list.sort(key=lambda x: (x["price"], x["total_points"]), reverse=True)
    elif sort_by == "selected":
        players_list.sort(key=lambda x: (x["selected_by"], x["total_points"]), reverse=True)
    elif sort_by == "form":
        players_list.sort(key=lambda x: (x["form"], x["total_points"]), reverse=True)
    elif sort_by == "ppm":
        players_list.sort(key=lambda x: (x["ppm"], x["total_points"]), reverse=True)
    elif sort_by == "goals":
        players_list.sort(key=lambda x: (x["goals"], x["total_points"]), reverse=True)
    elif sort_by == "assists":
        players_list.sort(key=lambda x: (x["assists"], x["total_points"]), reverse=True)
    elif sort_by in ["clean_sheets", "cleansheets"]:
        players_list.sort(key=lambda x: (x["clean_sheets"], x["total_points"]), reverse=True)
    elif sort_by == "saves":
        players_list.sort(key=lambda x: (x["saves"], x["total_points"]), reverse=True)
    elif sort_by in ["def_contrib", "defcontrib"]:
        players_list.sort(key=lambda x: (x["def_contrib"], x["total_points"]), reverse=True)
    else:
        players_list.sort(key=lambda x: (x["total_points"], x["price"]), reverse=True)
        
    return players_list
    
def get_fixtures(gameweek=None):
    if gameweek:
        url = f"{BASE_URL}/fixtures/?event={gameweek}"
    else:
        url = f"{BASE_URL}/fixtures/"
    data = safe_api_request(url, "get_fixtures")
    return data if data else []

def get_match_details(fixture_id):
    """جلب تفاصيل المباراة من API"""
    # الرابط الصحيح للمباريات هو /fixtures/ وليس /fixture/
    url = f"{BASE_URL}/fixtures/{fixture_id}/"
    data = safe_api_request(url, "get_match_details")
    
    if not data:
        return None, "error"  # خطأ في جلب البيانات
    
    # التحقق من حالة المباراة
    finished = data.get("finished", False) or data.get("finished_provisional", False)
    started = data.get("started", False)
    
    # إذا كانت المباراة لم تبدأ بعد
    if not started and not finished:
        return data, "not_started"
    
    # إذا كانت المباراة انتهت أو جارية
    return data, "started"
    
def format_match_detail_display(manager_id, info, gameweek, fixture_id):
    """تنسيق تفاصيل المباراة المختارة"""
    match_data, status = get_match_details(fixture_id)
    
    # حالة خطأ في جلب البيانات
    if status == "error" or match_data is None:
        return "❌ حدث خطأ أثناء جلب تفاصيل المباراة. تأكد من اتصال الإنترنت وحاول مرة أخرى.", None
    
    # حالة المباراة لم تبدأ بعد
    if status == "not_started":
        teams_dict = get_teams_dict()
        team_h_id = match_data.get("team_h")
        team_a_id = match_data.get("team_a")
        team_h_info = teams_dict.get(team_h_id, {"name": "فريق", "short_name": "؟", "emoji_only": "⚽"})
        team_a_info = teams_dict.get(team_a_id, {"name": "فريق", "short_name": "؟", "emoji_only": "⚽"})
        
        # تنسيق وقت المباراة
        kickoff_time = match_data.get("kickoff_time")
        match_time = format_match_time(kickoff_time) if kickoff_time else "توقيت غير محدد"
        
        response = (
            f"⏳ **المباراة لم تبدأ بعد**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚽ **{team_h_info['emoji_only']} {team_h_info['name']}**\n"
            f"🆚 **{team_a_info['emoji_only']} {team_a_info['name']}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 وقت المباراة: {match_time}\n"
            f"📅 الجولة: {gameweek}\n\n"
            f"💡 ستظهر التفاصيل بعد بدء المباراة."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 العودة لقائمة المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"simple_{manager_id}_{gameweek}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        return response, reply_markup
    
    # حالة المباراة بدأت أو انتهت
    fixture = match_data
    teams_dict = get_teams_dict()
    
    # تحديد حالة المباراة
    finished = fixture.get("finished", False) or fixture.get("finished_provisional", False)
    started = fixture.get("started", False)
    
    if finished:
        status_text = "🔴 انتهت"
        status_icon = "🔴"
    elif started:
        status_text = "🟢 جارية"
        status_icon = "🟢"
    else:
        status_text = "⏳ لم تبدأ"
        status_icon = "⏳"
    
    # معلومات الفرق
    team_h_id = fixture.get("team_h")
    team_a_id = fixture.get("team_a")
    team_h_info = teams_dict.get(team_h_id, {"name": "فريق", "short_name": "؟", "emoji_only": "⚽"})
    team_a_info = teams_dict.get(team_a_id, {"name": "فريق", "short_name": "؟", "emoji_only": "⚽"})
    
    team_h_score = fixture.get("team_h_score", 0)
    team_a_score = fixture.get("team_a_score", 0)
    
    # وقت المباراة
    kickoff_time = fixture.get("kickoff_time")
    match_time = format_match_time(kickoff_time) if kickoff_time else "توقيت غير محدد"
    
    response = (
        f"{status_icon} **{team_h_info['emoji_only']} {team_h_info['name']}** [ {team_h_score} ]\n"
        f"🆚 **{team_a_info['emoji_only']} {team_a_info['name']}** [ {team_a_score} ]\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **تفاصيل المباراة:**\n"
        f"• الحالة: {status_text}\n"
        f"• الوقت: {match_time}\n"
        f"• الدقائق: {fixture.get('minutes', 0)}'\n"
    )
    
    # إضافة تفاصيل إضافية إذا كانت المباراة انتهت
    if finished:
        response += f"• النتيجة النهائية: {team_h_score} - {team_a_score}\n"
    
    # محاولة جلب إحصائيات إضافية من live data
    try:
        live_data = get_full_live_data(gameweek)
        if live_data:
            response += f"\n📈 **إحصائيات حية:**\n"
            response += f"• عدد اللاعبين المشاركين: {len(live_data)}\n"
    except:
        pass
    
    response += f"\n💡 يمكنك العودة لاستعراض المباريات الأخرى."
    
    keyboard = [
        [InlineKeyboardButton("🔙 العودة لقائمة المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"simple_{manager_id}_{gameweek}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return response, reply_markup    


def get_teams_dict():
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_teams_dict")
    
    team_emojis = {
        "Arsenal": "🔫", "Aston Villa": "🏰", "Bournemouth": "🍒", "Brentford": "🐝",
        "Brighton and Hove Albion": "🐦", "Brighton": "🐦", "Chelsea": "🦁", "Crystal Palace": "🦅",
        "Everton": "🍬", "Fulham": "🏁", "Leicester City": "🦊",
        "Liverpool": "🐦‍🔥", "Manchester City": "💎", "Manchester United": "🔱", "Newcastle United": "🐦‍⬛",
        "Nottingham Forest": "🎋", "Southampton": "⚪", "Tottenham Hotspur": "🐔",
        "Coventry City": "🐘", "Ipswich Town": "🎠", "Hull City": "🐯",
        "Leeds United": "🦚", "Sunderland": "🐈",
        "ARS": "🔫", "AVL": "🏰", "BOU": "🍒", "BRE": "🐝", "BHA": "🐦", "CHE": "🦁",
        "CRY": "🦅", "EVE": "🍬", "FUL": "🏁", "LEI": "🦊", "LIV": "🐦‍🔥",
        "MCI": "💎", "MUN": "🔱", "NEW": "🐦‍⬛", "NFO": "🎋", "SOU": "⚪", "TOT": "🐔",
        "COV": "🐘", "IPS": "🎠", "HUL": "🐯",
        "LEE": "🦚", "SUN": "🐈"
    }
    
    teams = {}
    if data and "teams" in data:
        for team in data["teams"]:
            team_id = team["id"]
            team_name = team["name"]
            team_short_name = team["short_name"]
            emoji = team_emojis.get(team_name) or team_emojis.get(team_short_name, "⚽")
            teams[team_id] = {
                "id": team_id,
                "name": team_name,
                "short_name": team_short_name,
                "emoji": f"{emoji} {team_short_name}",
                "emoji_only": emoji
            }
    return teams

POSITION_NAMES = {
    1: "🥅 حارس",
    2: "🛡️ مدافع",
    3: "⚡ وسط",
    4: "🎯 مهاجم"
}

TEAM_NAMES = {
    1: "ARS", 2: "AVL", 3: "BOU", 4: "BRE", 5: "BHA",
    6: "CHE", 7: "CRY", 8: "EVE", 9: "FUL", 10: "LEI",
    11: "LIV", 12: "MCI", 13: "MUN", 14: "NEW", 15: "NFO",
    16: "SOU", 17: "TOT", 18: "WOL", 19: "IPS", 20: "COV"
}

def get_defensive_contribution_status(player_id, element_type, full_live_data):
    p_entry = full_live_data.get(player_id, {})
    if not p_entry or element_type == 1:
        return False, 0, 0
    
    metrics = p_entry.get("def_metrics", {})
    
    if element_type == 2:
        current = metrics.get("cbit", 0)
        threshold = 10
    else:
        current = metrics.get("cbirt", 0)
        threshold = 12
    
    return current >= threshold, current, threshold

# ============================================================
# دوال الجولات والتواريخ
# ============================================================

def get_current_gameweek():
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_current_gameweek")
    if data and "events" in data:
        for event in data["events"]:
            if event.get("is_current"):
                logger.info(f"📅 الجولة الحالية: {event['id']}")
                return event["id"]
        for event in data["events"]:
            if event.get("is_next"):
                logger.info(f"📅 الجولة القادمة: {event['id']}")
                return event["id"]
    return 1

def get_next_gameweek(current_gw):
    return current_gw + 1 if current_gw < 38 else 1

def get_previous_gameweek(current_gw):
    return current_gw - 1 if current_gw > 1 else 38

def format_match_time(kickoff_time):
    if not kickoff_time:
        return "توقيت غير محدد"
    try:
        if kickoff_time.endswith('Z'):
            kickoff_time = kickoff_time.replace('Z', '+00:00')
        dt_utc = datetime.fromisoformat(kickoff_time)
        dt_mecca = dt_utc + timedelta(hours=3)
        return dt_mecca.strftime("%I:%M %p").lstrip('0').lower()
    except Exception as e:
        logger.warning(f"خطأ في تنسيق الوقت: {e}")
        return kickoff_time[:16] if kickoff_time else "توقيت غير محدد"

def format_match_status(fixture):
    started = fixture.get("started", False)
    finished = fixture.get("finished", False) or fixture.get("finished_provisional", False)
    minutes = fixture.get("minutes", 0)
    
    if finished:
        return "🔴 انتهت"
    elif started:
        if minutes >= 90:
            added_time = minutes - 90
            return f"🟢 الوقت بدل الضائع +{added_time}" if added_time > 0 else "🟢 الدقيقة 90+"
        return f"🟢 الدقيقة {minutes}"
    return "⚪ لم تبدأ"

def get_gameweek_stats(gameweek):
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_gw_stats")
    if data and "events" in data:
        for event in data["events"]:
            if event.get("id") == gameweek:
                return {
                    "average_score": event.get("average_entry_score", 0),
                    "highest_score": event.get("highest_score", 0)
                }
    return {"average_score": 0, "highest_score": 0}

# ============================================================
# دوال عرض المعلومات
# ============================================================

def format_simple_display(manager_id, info, gameweek, picks_data, history):
    name = sanitize_markdown(safe_str(info.get("name")))
    total_points = safe_int(info.get("summary_overall_points"))

    target_gw_rank = 0
    if history and "current" in history:
        for gw_entry in history["current"]:
            if gw_entry.get("event") == gameweek:
                target_gw_rank = safe_int(gw_entry.get("overall_rank"))
                break
    
    rank = target_gw_rank if target_gw_rank > 0 else safe_int(info.get("summary_overall_rank"))
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    
    live_points_map = get_live_points(gameweek)
    active_chip = picks_data.get("active_chip") if picks_data else None
    event_points_before_hits = 0
    event_rank = 0
    captain_points = 0
    captain_name = ""
    transfers_made = 0
    transfers_cost = 0
    
    if picks_data and "picks" in picks_data:
        players_to_count = picks_data["picks"] if active_chip == "bboost" else picks_data["picks"][:11]
        for pick in players_to_count:
            player_id = pick.get("element")
            player_points = live_points_map.get(player_id, 0)
            current_multiplier = pick.get("multiplier", 1)
            if pick.get("is_captain"):
                current_multiplier = 3 if active_chip == "3xc" else 2
                captain_name = sanitize_markdown(players_dict.get(player_id, f"لاعب {player_id}"))
                captain_points = player_points * current_multiplier
            event_points_before_hits += player_points * current_multiplier
        
        if "entry_history" in picks_data:
            history_data = picks_data["entry_history"]
            transfers_made = safe_int(history_data.get("event_transfers", 0))
            transfers_cost = safe_int(history_data.get("event_transfers_cost", 0))
            event_rank = safe_int(history_data.get("rank", 0))
    
    event_points_after_hits = event_points_before_hits - transfers_cost
    transfer_line = f"🔄 الانتقالات: *{transfers_made}*" + (f" (-{transfers_cost})" if transfers_cost > 0 else "")
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"

    rank_change_display = get_rank_change_display(manager_id, gameweek, history)
    
    if transfers_cost > 0:
        points_display = f"**{event_points_after_hits}** ({event_points_before_hits})"
    else:
        points_display = f"**{event_points_before_hits}**"
    
    tc_indicator = " 🔥×3" if active_chip == "3xc" else ""
    bb_indicator = " 💺" if active_chip == "bboost" else ""
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 `{manager_id}` | 📊 **جولة {gameweek}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⭐️ نقاط الجولة: {points_display}\n"
        f"🏆 النقاط الكلية: *{total_points:,}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*{rank_change_display}\n"
        f"📊 ترتيب الجولة: *{event_rank_str}*\n"
        f"{transfer_line}\n"
        f"👑 القائد: {captain_name} (*{captain_points}*){tc_indicator}\n"
    )
    
    if active_chip:
        chip_names = {"3xc": "TC", "bboost": "BB", "freehit": "FH", "wildcard": "WC"}
        response += f"🎭 بطاقة نشطة: **{chip_names.get(active_chip, active_chip)}**{bb_indicator}\n"
    
    return response

def format_detailed_display(manager_id, info, gameweek, picks_data, history):
    name = sanitize_markdown(safe_str(info.get("name")))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "" or joined == "None":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))

    target_gw_rank = 0
    if history and "current" in history:
        for gw_entry in history["current"]:
            if gw_entry.get("event") == gameweek:
                target_gw_rank = safe_int(gw_entry.get("overall_rank"))
                break
    
    rank = target_gw_rank if target_gw_rank > 0 else safe_int(info.get("summary_overall_rank"))
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    
    team_value = bank_value = total_value_display = 0.0
    if picks_data and "entry_history" in picks_data:
        history_data = picks_data["entry_history"]
        raw_total_value = safe_int(history_data.get("value", 0))
        raw_bank = safe_int(history_data.get("bank", 0))
        bank_value = raw_bank / 10
        team_value = (raw_total_value - raw_bank) / 10
        total_value_display = raw_total_value / 10
    
    full_live_data = get_full_live_data(gameweek)
    active_chip = picks_data.get("active_chip") if picks_data else None

    rank_change_display = get_rank_change_display(manager_id, gameweek, history)

    gw_stats = get_gameweek_stats(gameweek)
    avg_points = gw_stats["average_score"]
    
    players_full_data = {}
    bootstrap_data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_players_full_data")
    if bootstrap_data and "elements" in bootstrap_data:
        for player in bootstrap_data["elements"]:
            players_full_data[player["id"]] = {"element_type": player.get("element_type")}
    
    position_names = {1: "🥅 الحراسة", 2: "🪖 الدفاع", 3: "⚡ الوسط", 4: "🎯 الهجوم"}
    
    def get_player_row(p_id, multiplier):
        p_entry = full_live_data.get(p_id, {})
        stats = p_entry.get('stats', {})
        e_type = players_full_data.get(p_id, {}).get("element_type", 0)
        
        def_earned, _, _ = get_defensive_contribution_status(p_id, e_type, full_live_data)
        total_api = stats.get('total_points', 0)
        final_display_pts = total_api * multiplier
        
        events = []
        if stats.get('goals_scored', 0) > 0:
            events.append("⚽" * stats['goals_scored'])
        if stats.get('assists', 0) > 0:
            events.append("🅰️" * stats['assists'])
        if stats.get('clean_sheets', 0) > 0 and e_type in [1, 2, 3]:
            events.append("🛡️")
        if stats.get('saves', 0) >= 3:
            events.append(f"🧤({stats.get('saves', 0)})")
        if stats.get('yellow_cards', 0) > 0:
            events.append("🟨")
        if stats.get('red_cards', 0) > 0:
            events.append("🟥")
        if stats.get('own_goals', 0) > 0:
            events.append("🚫(OG)")
        if stats.get('penalties_missed', 0) > 0:
            events.append("❌(PK)")
        if stats.get('penalties_saved', 0) > 0:
            events.append("🧤(PK)")
        
        def_icon = " 🧱" if def_earned else ""
        return final_display_pts, total_api * multiplier, " ".join(events), def_icon
    
    event_points_before_hits = 0
    total_transfers = safe_int(info.get("total_transfers"))
    event_rank = 0
    transfers_cost = 0
    players_output = ""
    
    if picks_data and "picks" in picks_data:
        for pos_id in [1, 2, 3, 4]:
            pos_players = [p for p in picks_data["picks"][:11] 
                          if players_full_data.get(p['element'], {}).get('element_type') == pos_id]
            if pos_players:
                players_output += f"{position_names[pos_id]}:\n"
                for pick in pos_players:
                    p_id = pick['element']
                    mult = 3 if (pick.get('is_captain') and active_chip == '3xc') else (2 if pick.get('is_captain') else 1)
                    p_name = sanitize_markdown(players_dict.get(p_id, "Unknown"))
                    p_pts_val, p_pts_raw, p_icons, def_icon = get_player_row(p_id, mult)
                    
                    cap_tag = "👑" if pick.get('is_captain') else ""
                    tc_tag = "×3🔥" if (pick.get('is_captain') and active_chip == '3xc') else ""
                    vc_tag = "(VC)" if pick.get('is_vice_captain') and not pick.get('is_captain') else ""
                    captain_display = f"{cap_tag}{tc_tag}" if cap_tag else vc_tag
                    
                    players_output += f"• {p_name} {captain_display} {p_icons}{def_icon}: **{p_pts_val}**\n"
                    event_points_before_hits += p_pts_raw
                players_output += "\n"
        
        if len(picks_data["picks"]) > 11:
            players_output += "🔄 **اللاعبون البدلاء:**\n\n"
            for pick in picks_data["picks"][11:]:
                p_id = pick['element']
                p_name = sanitize_markdown(players_dict.get(p_id, "Unknown"))
                p_pts_val, p_pts_raw, p_icons, def_icon = get_player_row(p_id, 1)
                players_output += f"• {p_name} {p_icons}{def_icon}: **{p_pts_val}**\n"
                if active_chip == "bboost":
                    event_points_before_hits += p_pts_raw
            players_output += "\n"
        
        if "entry_history" in picks_data:
            event_rank = safe_int(picks_data["entry_history"].get("rank", 0))
            transfers_cost = safe_int(picks_data["entry_history"].get("event_transfers_cost", 0))
            total_transfers = safe_int(picks_data["entry_history"].get("event_transfers", total_transfers))
    
    event_points_after_hits = event_points_before_hits - transfers_cost
    
    chips_status = ""
    if history and "chips" in history:
        used_chips = history["chips"]
        chips_info = {
            "3xc": "👑 تثليث القائد (TC)",
            "bboost": "💺 تفعيل الدكة (BB)",
            "freehit": "🃏 ضربة الحظ (FH)",
            "wildcard": "🛠 بطاقة الوحش (WC)"
        }
        chips_status = "🎭 ** البطاقات (Chips):**\n"
        for chip_key, chip_name in chips_info.items():
            all_usages = [c for c in used_chips if c['name'] == chip_key]
            if gameweek <= 19:
                usage = next((c for c in all_usages if c['event'] <= 19), None)
            else:
                usage = next((c for c in all_usages if c['event'] > 19), None)
            
            if active_chip == chip_key:
                chips_status += f"• **{chip_name}: تلعب الآن 🟢**\n"
            elif usage:
                chips_status += f"• ~~{chip_name}~~: الجولة {usage['event']} 🔴\n"
            else:
                chips_status += f"• _{chip_name}_: لم تلعب 🟡\n"
        chips_status += "\n"
    else:
        chips_status = "🎭 **حالة البطاقات (Chips):** لا توجد بيانات متاحة حالياً\n\n"
    
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"
    bb_indicator = " (تشمل البدلاء 💺)" if active_chip == "bboost" else ""
    
    transfers_text = f"🔄 انتقالات الجولة: *{total_transfers}*"
    if transfers_cost > 0:
        transfers_text += f" (-{transfers_cost})"
    
    if transfers_cost > 0:
        points_display = f"*{event_points_after_hits}* ({event_points_before_hits})"
    else:
        points_display = f"*{event_points_before_hits}*"
    
    response = (
        f"🎮 **{name}**\n"
        f"🆔 `{manager_id}`\n"
        f"📅 انضم: {joined}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"⭐ نقاط الجولة: {points_display}{bb_indicator}\n"
        f"🌍 متوسط نقاط الجولة: *{avg_points}*\n"
        f"🏆 النقاط الكلية: *{total_points:,}*\n"
        f"📈 الترتيب العالمي: *{rank_str}*{rank_change_display}\n"
        f"{transfers_text}\n"
        f"📊 ترتيب الجولة: *{event_rank_str}*\n\n"
    )
    
    response += chips_status
    
    if team_value > 0 or bank_value > 0:
        response += (
            f"💰 **المالية:**\n"
            f"• قيمة التشكيلة: *£{team_value:.1f}m*\n"
            f"• البنك: *£{bank_value:.1f}m*\n"
            f"• الإجمالي: *£{total_value_display:.1f}m*\n\n"
        )
    
    response += "🧑‍🤝‍🧑 **اللاعبون:**\n\n"
    response += players_output
    
    return response

def format_leagues_display(manager_id, info, gameweek, history):
    name = sanitize_markdown(safe_str(info.get("name")))
    
    leagues = info.get("leagues", {})
    classic_leagues = leagues.get("classic", [])
    
    response = (
        f"🏆 **الدوريات والمواسم**\n"
        f"🎮 {name}\n"
        f"🆔 `{manager_id}`\n"
        f"📊 **الجولة {gameweek}**\n"
    )
    
    if classic_leagues:
        response += "🏅 **المجموعات (الدوريات):**\n\n"
        for idx, league in enumerate(classic_leagues[:20], 1):
            raw_name = safe_str(league.get("name", "غير معروف"))
            clean_name = raw_name.replace('*', '✦').replace('_', '-').replace('`', "'")
            clean_name = clean_name.replace('[', '(').replace(']', ')')
            league_name = sanitize_markdown(clean_name)
            
            league_rank = league.get('entry_rank') or league.get('rank')
            league_total = league.get('rank_count')
            
            previous_league_rank = league.get('entry_last_rank') or league.get('last_rank', 0)
            
            league_change_display = get_league_change_display(league_rank, previous_league_rank) if league_rank else ""
            
            try:
                if league_rank is not None and league_total is not None:
                    response += f"{idx}. {league_name}: {league_rank:,} / {league_total:,}{league_change_display}\n\n"
                elif league_rank is not None:
                    response += f"{idx}. {league_name}: الترتيب {league_rank}{league_change_display}\n\n"
                else:
                    response += f"{idx}. {league_name}\n\n"
            except Exception as e:
                logger.warning(f"⚠️ فشل تنسيق الدوري {idx} للمدرب {manager_id}: {e}")
                try:
                    response += f"{idx}. {clean_name}\n\n"
                except:
                    response += f"{idx}. (اسم غير قابل للعرض)\n\n"
    else:
        response += "🏅 **المجموعات:** لا يشارك في مجموعات حالياً\n\n"

    if history and "past" in history and history["past"]:
        response += "📜 **المواسم السابقة:**\n"
        for season in history["past"][-5:]:
            try:
                raw_season_name = safe_str(season.get("season_name"))
                clean_season = raw_season_name.replace('*', '✦').replace('_', '-').replace('`', "'")
                season_name = sanitize_markdown(clean_season)
                season_points = safe_int(season.get("total_points"))
                season_rank = safe_int(season.get("rank"))
                season_rank_str = f"{season_rank:,}" if season_rank > 0 else "غير مصنف"
                response += f"• {season_name}: {season_points} نقطة (ترتيب {season_rank_str})\n"
            except Exception as e:
                logger.warning(f"⚠️ فشل تنسيق موسم للمدرب {manager_id}: {e}")
                response += f"• {clean_season}: {season_points} نقطة\n"
    else:
        response += "📜 **المواسم السابقة:** لا يوجد تاريخ للمواسم السابقة\n\n"
    
    return response

def format_fixtures_display(manager_id, info, gameweek, history):
    fixtures = get_fixtures(gameweek)
    teams_dict = get_teams_dict()
    
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")
    
    response = (
        f"⚽ **قائمة مباريات الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (بتوقيت مكة المكرمة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 **اختر المباراة لعرض تفاصيلها:**\n"
    )
    
    if not fixtures:
        response += "🚫 لا توجد مباريات في هذه الجولة\n"
        return response, None
    
    # إنشاء أزرار للمباريات
    keyboard = []
    for idx, fixture in enumerate(fixtures, 1):
        team_h_info = teams_dict.get(fixture.get("team_h"), {"emoji_only": "⚽", "short_name": "?"})
        team_a_info = teams_dict.get(fixture.get("team_a"), {"emoji_only": "⚽", "short_name": "?"})
        
        # اختصار أسماء الفرق
        home_name = team_h_info['short_name']
        away_name = team_a_info['short_name']
        
        # تحديد حالة المباراة والإيموجي المناسب
        finished = fixture.get("finished", False) or fixture.get("finished_provisional", False)
        started = fixture.get("started", False)
        
        if finished:
            status_icon = "🔴"  # انتهت
        elif started:
            status_icon = "🟢"  # جارية
        else:
            status_icon = "⏳"  # لم تبدأ
        
        # إضافة النتيجة إذا كانت المباراة انتهت
        score_display = ""
        if finished and fixture.get("team_h_score") is not None and fixture.get("team_a_score") is not None:
            score_display = f" [{fixture['team_h_score']}-{fixture['team_a_score']}]"
        
        # زر لكل مباراة
        btn_text = f"{status_icon} {home_name} vs {away_name}{score_display}"
        callback_data = f"matchdetail_{manager_id}_{gameweek}_{fixture.get('id')}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"simple_{manager_id}_{gameweek}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    return response, reply_markup
    
def format_deadline_display(manager_id, info, gameweek):
    name = sanitize_markdown(safe_str(info.get("name")))
    
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time_str = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date_str = now_mecca.strftime("%d/%m/%Y")
    
    deadline_display = "غير معروف"
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_deadline")
    if data and "events" in data:
        for event in data["events"]:
            if event.get("id") == gameweek:
                kickoff = event.get("deadline_time")
                if kickoff:
                    deadline_time = format_match_time(kickoff)
                    deadline_date = kickoff[:10] if len(kickoff) >= 10 else "غير معروف"
                    deadline_display = f"{deadline_time} - {deadline_date}"
                break
    
    first_match_display = "غير معروف"
    last_match_display = "غير معروف"
    fixtures = get_fixtures(gameweek)
    if fixtures:
        valid = [f for f in fixtures if f.get("kickoff_time")]
        if valid:
            sorted_fixtures = sorted(valid, key=lambda x: x["kickoff_time"])
            first = sorted_fixtures[0]["kickoff_time"]
            last = sorted_fixtures[-1]["kickoff_time"]
            
            first_time = format_match_time(first)
            first_date = first[:10]
            last_time = format_match_time(last)
            last_date = last[:10]
            
            first_match_display = f"{first_time} - {first_date}"
            last_match_display = f"{last_time} - {last_date}"
    
    response = (
        f"📅 **مواعيد الجولة {gameweek}**\n"
        f"👤 {name}\n"
        f"🕐 آخر تحديث: {update_time_str} - {update_date_str} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 **موعد غلق الانتقالات:** {deadline_display}\n"
        f"⚽ **بداية الجولة (أول مباراة):** {first_match_display}\n"
        f"🏁 **نهاية الجولة (آخر مباراة):** {last_match_display}\n"
        f"\n🕌 جميع الأوقات بتوقيت مكة المكرمة (UTC+3)"
    )
    return response

def format_players_display(manager_id, info, gameweek, sort_by="points", page=0):
    """
    عرض قائمة 20 لاعباً لكل صفحة مصفوفين حسب المعيار المختار
    """
    name = sanitize_markdown(safe_str(info.get("name")))
    players_per_page = 20
    
    all_players = get_all_players_data(sort_by=sort_by)
    total_players = len(all_players)
    total_pages = (total_players + players_per_page - 1) // players_per_page
    
    start_idx = page * players_per_page
    end_idx = min(start_idx + players_per_page, total_players)
    page_players = all_players[start_idx:end_idx]
    
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")
    
    sort_titles = {
        "points": "🏆 الأكثر نقاطاً",
        "price": "💰 الأعلى سعراً",
        "selected": "📊 الأكثر ملكية",
        "form": "🔥 الأفضل فورماً",
        "ppm": "🎯 الأعلى معدل نقاط (PPM)"
    }
    sort_title = sort_titles.get(sort_by, "🏆 الأكثر نقاطاً")
    
    response = (
        f"👥 **قائمة لاعبي الدوري الإنجليزي**\n"
        f"👤 {name}\n"
        f"📌 **نمط الفرز:** {sort_title}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📖 الصفحة {page + 1} من {total_pages}\n"
        f"👥 إجمالي اللاعبين: {total_players}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not page_players:
        response += "🚫 لا يوجد لاعبين للعرض\n"
        return response
    
    for idx, player in enumerate(page_players, start=start_idx + 1):
        player_name = sanitize_markdown(player['name'])
        pos_id = player.get("position", 0)
        pos_name = POSITION_NAMES.get(pos_id, "❓ غير معروف")
        
        price = player.get("price", 0.0)
        points = player.get("total_points", 0)
        team_id = player.get("team", 0)
        team_short = TEAM_NAMES.get(team_id, "???")
        selected = player.get("selected_by", 0.0)
        form = player.get("form", 0.0)
        ppm = player.get("ppm", 0.0)
        
        price_str = f"£{price:.1f}M" if price > 0 else "غير متاح"
        selected_str = f"{selected:.1f}%" if selected > 0 else "0%"
        form_str = f"{form:.1f}" if form > 0 else "-"
        ppm_str = f"{ppm:.1f}" if ppm > 0 else "0.0"
        
        response += (
            f"{idx:3d}. **{player_name}**\n"
            f"   {pos_name} | {team_short} | النقاط: **{points}** | السعر: **{price_str}** | معدل النقاط: **{ppm_str}** | الفورم: {form_str} | الملكية: {selected_str}\n\n"
        )
    
    response += "━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"📊 إجمالي المعروض بالصفحة: {len(page_players)} لاعبين\n"
    response += "🔄 اختَر نوع الفرز أو استخدم أزرار التنقل بالأسفل:"
    
    return response
    
def format_price_changes_display(manager_id, info, gameweek):
    """
    عرض توقعات وتغيرات الأسعار للاعبين بناءً على بيانات الرسمية للفانتاسي
    """
    name = sanitize_markdown(safe_str(info.get("name")))
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_price_changes")
    
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")

    if not data or "elements" not in data:
        return "❌ حدث خطأ أثناء جلب بيانات الأسعار."

    elements = data["elements"]
    
    # تحضير قائمة اللاعبين وحساب مقياس التوقع للارتفاع والانخفاض (بناءً على الانتقالات في الجولة)
    players_list = []
    for p in elements:
        transfers_in = safe_int(p.get("transfers_in_event", 0))
        transfers_out = safe_int(p.get("transfers_out_event", 0))
        net_transfers = transfers_in - transfers_out
        
        p_name = sanitize_markdown(f"{p.get('first_name', '')} {p.get('second_name', '')}".strip())
        price = safe_int(p.get("now_cost", 0)) / 10.0
        ownership = safe_str(p.get("selected_by_percent", "0.0"))
        cost_change = safe_int(p.get("cost_change_event", 0))
        
        players_list.append({
            "name": p_name,
            "price": price,
            "ownership": ownership,
            "net_transfers": net_transfers,
            "cost_change": cost_change,
            "transfers_in": transfers_in,
            "transfers_out": transfers_out
        })

    # 1. التوقعات (أكثر 5 متوقع ارتفاعهم وأكثر 5 متوقع انخفاضهم)
    predicted_rise = sorted(players_list, key=lambda x: x["net_transfers"], reverse=True)[:5]
    predicted_fall = sorted(players_list, key=lambda x: x["net_transfers"])[:5]

    # 2. التغيرات الحقيقية الأخيرة (آخر 5 ارتفعوا وآخر 5 انخفضوا في الجولة الحالية)
    actual_risen = [p for p in elements if p.get("cost_change_event", 0) > 0]
    actual_risen = sorted(actual_risen, key=lambda x: x.get("cost_change_event", 0), reverse=True)[:5]

    actual_fallen = [p for p in elements if p.get("cost_change_event", 0) < 0]
    actual_fallen = sorted(actual_fallen, key=lambda x: x.get("cost_change_event", 0))[:5]

    response = (
        f"📈 **تغيرات وتوقعات أسعار اللاعبين**\n"
        f"👤 {name}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    # 📈 أكثر 5 متوقع ارتفاعهم
    response += "🚀 **أكثر 5 لاعبين متوقع ارتفاعهم:**\n"
    for idx, p in enumerate(predicted_rise, 1):
        # حساب نسبة توقع تقريبية بناءً على زخم الانتقالات
        prediction_pct = min(100.0, max(0.0, (p["net_transfers"] / 50000.0) * 100))
        response += (
            f"{idx}. **{p['name']}**\n"
            f"   💰 السعر: £{p['price']:.1f}m | 📊 الملكية: {p['ownership']}% | 📈 نسبة التوقع: {prediction_pct:.1f}%\n"
        )
    response += "\n"

    # 🔻 أكثر 5 متوقع انخفاضهم
    response += "🔻 **أكثر 5 لاعبين متوقع انخفاضهم:**\n"
    for idx, p in enumerate(predicted_fall, 1):
        prediction_pct = min(100.0, max(0.0, (abs(p["net_transfers"]) / 50000.0) * 100))
        response += (
            f"{idx}. **{p['name']}**\n"
            f"   💰 السعر: £{p['price']:.1f}m | 📊 الملكية: {p['ownership']}% | 📉 نسبة التوقع: {prediction_pct:.1f}%\n"
        )
    response += "\n━━━━━━━━━━━━━━━━━━━━━\n\n"

    # 🟢 آخر 5 لاعبين ارتفع سعرهم بالفعل
    response += "🟢 **آخر 5 لاعبين ارتفع سعرهم:**\n"
    if actual_risen:
        for idx, p in enumerate(actual_risen, 1):
            p_name = sanitize_markdown(f"{p.get('first_name', '')} {p.get('second_name', '')}".strip())
            price = safe_int(p.get("now_cost", 0)) / 10.0
            ownership = safe_str(p.get("selected_by_percent", "0.0"))
            response += f"{idx}. **{p_name}** | 💰 السعر: £{price:.1f}m | 📊 الملكية: {ownership}%\n"
    else:
        response += "لا يوجد ارتفاعات في الأسعار مؤخراً\n"
    response += "\n"

    # 🔴 آخر 5 لاعبين انخفض سعرهم بالفعل
    response += "🔴 **آخر 5 لاعبين انخفض سعرهم:**\n"
    if actual_fallen:
        for idx, p in enumerate(actual_fallen, 1):
            p_name = sanitize_markdown(f"{p.get('first_name', '')} {p.get('second_name', '')}".strip())
            price = safe_int(p.get("now_cost", 0)) / 10.0
            ownership = safe_str(p.get("selected_by_percent", "0.0"))
            response += f"{idx}. **{p_name}** | 💰 السعر: £{price:.1f}m | 📊 الملكية: {ownership}%\n"
    else:
        response += "لا يوجد انخفاضات في الأسعار مؤخراً\n"

    return response
    
# ============================================================
# دوال الأزرار ومعالجات البوت
# ============================================================

def get_buttons(manager_id, gameweek, current_view):
    next_gw = get_next_gameweek(gameweek)
    prev_gw = get_previous_gameweek(gameweek)
    
    keyboard = [
        [InlineKeyboardButton("📋 عرض بسيط", callback_data=f"simple_{manager_id}_{gameweek}"),
         InlineKeyboardButton("📊 عرض مفصل", callback_data=f"detail_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🏆 الدوريات", callback_data=f"leagues_{manager_id}_{gameweek}"),
         InlineKeyboardButton("⚽ المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🚨 بدء الجولة", callback_data=f"deadline_{manager_id}_{gameweek}"),
         InlineKeyboardButton("📈 أسعار اللاعبين", callback_data=f"price_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("👥 جميع اللاعبين", callback_data=f"players_{manager_id}_{gameweek}_0")],
        [InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{prev_gw}"),
         InlineKeyboardButton("➡️ الجولة التالية", callback_data=f"nav_{manager_id}_{next_gw}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_players_buttons(manager_id, gameweek, sort_by, page, total_pages):
    keyboard = []
    
    points_btn_text = "✅ النقاط 🏆" if sort_by == "points" else "النقاط 🏆"
    price_btn_text = "✅ السعر 💰" if sort_by == "price" else "السعر 💰"
    selected_btn_text = "✅ الملكية 📊" if sort_by == "selected" else "الملكية 📊"
    form_btn_text = "✅ الفورم 🔥" if sort_by == "form" else "الفورم 🔥"
    ppm_btn_text = "✅ معدل PPM 🎯" if sort_by == "ppm" else "معدل PPM 🎯"
    
    keyboard.append([
        InlineKeyboardButton(points_btn_text, callback_data=f"players_{manager_id}_{gameweek}_points_0"),
        InlineKeyboardButton(price_btn_text, callback_data=f"players_{manager_id}_{gameweek}_price_0")
    ])
    
    keyboard.append([
        InlineKeyboardButton(selected_btn_text, callback_data=f"players_{manager_id}_{gameweek}_selected_0"),
        InlineKeyboardButton(form_btn_text, callback_data=f"players_{manager_id}_{gameweek}_form_0")
    ])
    
    keyboard.append([
        InlineKeyboardButton(ppm_btn_text, callback_data=f"players_{manager_id}_{gameweek}_ppm_0")
    ])

    # أزرار اختيار الفريق واختيار المركز
    keyboard.append([
        InlineKeyboardButton("🏢 اختيار فريق", callback_data=f"teamslist_{manager_id}_{gameweek}"),
        InlineKeyboardButton("🎯 مركز اللاعب", callback_data=f"poslist_{manager_id}_{gameweek}")
    ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"players_{manager_id}_{gameweek}_{sort_by}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"players_{manager_id}_{gameweek}_{sort_by}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"simple_{manager_id}_{gameweek}")])
    
    return InlineKeyboardMarkup(keyboard)

def get_subscription_button():
    keyboard = []
    # إضافة زر لكل قناة من القنوات المحددة
    for channel in CHANNELS:
        keyboard.append([
            InlineKeyboardButton(f"📢 اشترك في {channel['name']}", url=f"https://t.me/{channel['id'].replace('@', '')}")
        ])
    # إضافة زر التحقق بعد الانضمام
    keyboard.append([
        InlineKeyboardButton("✅ تم الاشتراك - تحقق مرة أخرى", callback_data="check_0")
    ])
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التأكد من وجود رسالة نصية
    if not update.message or not update.message.text:
        return

    message_text = update.message.text.strip()
    user_id = update.effective_user.id

    # 1. فحص الاشتراك أولاً قبل أي شيء لجميع الرسائل
    try:
        is_subscribed = await check_subscription(context, user_id)
    except Exception as e:
        logger.error(f"خطأ أثناء فحص الاشتراك للمستخدم {user_id}: {e}")
        # في حال حدوث خطأ في الفحص، نفترض أنه غير مشترك ونطلب منه الاشتراك
        is_subscribed = False

    # إذا لم يكن مشتركاً (سواء كتب /start أو أرسل آيدي مباشرة)
    if not is_subscribed:
        channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
        await update.message.reply_text(
            f"🔒 **يرجى الاشتراك في جميع القنوات أولاً!**\n\n"
            f"للحصول على إمكانية استخدام البوت، يرجى الانضمام إلى قنواتنا:\n"
            f"{channels_list}\n\n"
            f"✅ **خطوات الاشتراك:**\n"
            f"1️⃣ اضغط على أزرار 'اشترك في القناة' أدناه لكل قناة\n"
            f"2️⃣ انضم إلى جميع القنوات\n"
            f"3️⃣ عد إلى البوت واضغط 'تم الاشتراك - تحقق مرة أخرى'\n\n"
            f"📌 **ملاحظة:** البوت لن يعمل بدون اشتراكك في جميع القنوات.",
            parse_mode='Markdown',
            reply_markup=get_subscription_button()
        )
        return

    # 2. إذا كان مشتركاً وكتب /start أو /help
    if message_text.startswith(('/start', '/help')):
        await update.message.reply_text(
            "🎮 **بوت مساعد الفانتاسي**\n"
            "✨ **كيف يعمل؟**\n"
            "• أرسل **رقم معرف المدرب**\n"
            "• سأعرض لك بيانات الجولة الحالية تلقائياً\n\n"
            "📊 **البيانات المتاحة**\n"
            "✓ نقاط الجولة للمدرب\n"
            "✓ النقاط الكلية والترتيب العالمي\n"
            "✓ نقاط كل لاعب في الفريق\n"
            "✓ نقاط القائد\n"
            "✓ قيمة الفريق والبنك 💰\n"
            "✓ ترتيب المدرب في كل دوري\n"
            "✓ تاريخ المواسم السابقة\n"
            "✓ نتائج المباريات وتفاصيلها ⚽\n"
            "✓ مواعيد الديدلاين وانتهاء وقت الانتقالات \n"
            "🔑 **كيف تحصل على معرف مدرب؟**\n"
            "افتح موقع FPL، الرقم في الرابط:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📝 **مثال:** أرسل `2794801`",
            parse_mode='Markdown'
        )
        return

    # 3. لمعالجة رقم معرف المدرب
    try:
        manager_id = int(message_text)
        context.user_data['current_manager_id'] = manager_id
    except ValueError:
        await update.message.reply_text(
            "❌ يرجى إرسال **رقم معرف المدرب** فقط.\nمثال: `1234567`\nأو أرسل /help للمساعدة",
            parse_mode='Markdown'
        )
        return

    # 4. جلب البيانات وحذف الرسائل المؤقتة
    msg_checking = await update.message.reply_text(f"🔄 جاري التحقق من المعرف {manager_id}...")
    info = get_manager_info(manager_id)

    if not info:
        await msg_checking.delete()
        await update.message.reply_text(
            f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.\n\nتأكد من صحة المعرف.\nيمكنك تجربة: `2794801`",
            parse_mode='Markdown'
        )
        return

    name = safe_str(info.get("name"))
    start_gameweek = current_gameweek

    msg_loading = await update.message.reply_text(
        f"✅ تم العثور على المدرب **{name}**!\n📅 سيتم عرض بيانات **الجولة {start_gameweek}** (الجولة الحالية)\n\n🔄 جاري تحميل البيانات...",
        parse_mode='Markdown'
    )

    picks_data = get_manager_picks(manager_id, start_gameweek)
    history = get_manager_history(manager_id)
    text = format_simple_display(manager_id, info, start_gameweek, picks_data, history)
    reply_markup = get_buttons(manager_id, start_gameweek, "simple")

    try:
        await msg_checking.delete()
        await msg_loading.delete()
    except Exception as e:
        logger.warning(f"فشل حذف الرسائل المؤقتة: {e}")

    await update.message.reply_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)    
def get_teams_keyboard(manager_id, gameweek):
    """
    إنشاء لوحة أزرار تحتوي على قائمة كافة الفرق بالدوري
    """
    teams_dict = get_teams_dict()
    keyboard = []
    row = []
    
    for team_id, t_info in sorted(teams_dict.items()):
        btn_text = f"{t_info['emoji_only']} {t_info['short_name']}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"teamview_{manager_id}_{gameweek}_{team_id}_points"))
        if len(row) == 2:  # صف أزرار من زرين لكل سطر
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة اللاعبين", callback_data=f"players_{manager_id}_{gameweek}_points_0")])
    return InlineKeyboardMarkup(keyboard)

def get_team_players_buttons(manager_id, gameweek, team_id, sort_by):
    """
    أزرار الفرز الخاصة بلاعبي فريق محدد (النقاط، السعر، الملكية)
    """
    pts_txt = "✅ النقاط 🏆" if sort_by == "points" else "النقاط 🏆"
    prc_txt = "✅ السعر 💰" if sort_by == "price" else "السعر 💰"
    sel_txt = "✅ الملكية 📊" if sort_by == "selected" else "الملكية 📊"
    
    keyboard = [
        [
            InlineKeyboardButton(pts_txt, callback_data=f"teamview_{manager_id}_{gameweek}_{team_id}_points"),
            InlineKeyboardButton(prc_txt, callback_data=f"teamview_{manager_id}_{gameweek}_{team_id}_price"),
            InlineKeyboardButton(sel_txt, callback_data=f"teamview_{manager_id}_{gameweek}_{team_id}_selected")
        ],
        [InlineKeyboardButton("🏢 تغيير الفريق", callback_data=f"teamslist_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🔙 العودة لقائمة اللاعبين العامة", callback_data=f"players_{manager_id}_{gameweek}_points_0")]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_team_players_display(manager_id, gameweek, team_id, sort_by="points"):
    """
    تنسيق وعرض لاعبي فريق محدد
    """
    teams_dict = get_teams_dict()
    t_info = teams_dict.get(int(team_id), {"name": "الفريق", "emoji": "⚽"})
    
    team_players = get_all_players_data(sort_by=sort_by, team_id=int(team_id))
    
    sort_titles = {
        "points": "🏆 حسب النقاط",
        "price": "💰 حسب السعر",
        "selected": "📊 حسب الملكية"
    }
    sort_title = sort_titles.get(sort_by, "🏆 حسب النقاط")
    
    response = (
        f"{t_info.get('emoji', '⚽')} **لاعبو فريق {t_info.get('name', '')}**\n"
        f"📌 **الفرز:** {sort_title}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not team_players:
        response += "🚫 لا يوجد لاعبين لهذا الفريق حالياً\n"
        return response
        
    for idx, player in enumerate(team_players, start=1):
        player_name = sanitize_markdown(player['name'])
        pos_id = player.get("position", 0)
        pos_name = POSITION_NAMES.get(pos_id, "❓")
        
        price = player.get("price", 0.0)
        points = player.get("total_points", 0)
        selected = player.get("selected_by", 0.0)
        
        response += (
            f"{idx:2d}. **{player_name}** ({pos_name})\n"
            f"    النقاط: **{points}** | السعر: **£{price:.1f}M** | الملكية: **{selected:.1f}%**\n\n"
        )
        
    response += "━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"👥 إجمالي لاعبي الفريق: {len(team_players)} لاعبين"
    return response

def get_positions_keyboard(manager_id, gameweek):
    """
    قائمة المراكز الأربعة
    """
    keyboard = [
        [
            InlineKeyboardButton("🎯 الهجوم", callback_data=f"posview_{manager_id}_{gameweek}_4_points_0"),
            InlineKeyboardButton("⚡ الوسط", callback_data=f"posview_{manager_id}_{gameweek}_3_points_0")
        ],
        [
            InlineKeyboardButton("🛡️ الدفاع", callback_data=f"posview_{manager_id}_{gameweek}_2_points_0"),
            InlineKeyboardButton("🥅 الحراس", callback_data=f"posview_{manager_id}_{gameweek}_1_points_0")
        ],
        [InlineKeyboardButton("🔙 العودة لقائمة اللاعبين العامة", callback_data=f"players_{manager_id}_{gameweek}_points_0")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_position_players_buttons(manager_id, gameweek, pos_id, sort_by, page, total_pages):
    """
    أزرار الفرز المخصصة لكل مركز (بدون شرطات سفلى في الكالباك لتجنب خطأ split)
    """
    keyboard = []
    
    def btn(label, key):
        icon = "✅ " if sort_by == key else ""
        return InlineKeyboardButton(f"{icon}{label}", callback_data=f"posview_{manager_id}_{gameweek}_{pos_id}_{key}_0")

    # 1. الهجوم (5 أزرار)
    if pos_id == 4:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("الأهداف ⚽", "goals")])
        keyboard.append([btn("الأسيستات 🅰️", "assists")])
        
    # 2. الوسط (6 أزرار)
    elif pos_id == 3:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("الأهداف ⚽", "goals")])
        keyboard.append([btn("الأسيستات 🅰️", "assists"), btn("مساهمات دفاعية 🧱", "defcontrib")])

    # 3. الدفاع (7 أزرار)
    elif pos_id == 2:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("الأهداف ⚽", "goals")])
        keyboard.append([btn("الأسيستات 🅰️", "assists"), btn("كلين شيت 🛡️", "cleansheets")])
        keyboard.append([btn("مساهمات دفاعية 🧱", "defcontrib")])

    # 4. الحراس (5 أزرار)
    elif pos_id == 1:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("كلين شيت 🛡️", "cleansheets")])
        keyboard.append([btn("التصديات 🧤", "saves")])

    # أزرار الصفحات
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"posview_{manager_id}_{gameweek}_{pos_id}_{sort_by}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"posview_{manager_id}_{gameweek}_{pos_id}_{sort_by}_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🎯 تغيير المركز", callback_data=f"poslist_{manager_id}_{gameweek}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة اللاعبين العامة", callback_data=f"players_{manager_id}_{gameweek}_points_0")])

    return InlineKeyboardMarkup(keyboard)
    
def format_position_players_display(manager_id, gameweek, pos_id, sort_by="points", page=0):
    """
    عرض وتنسيق لاعبي مركز محدد
    """
    pos_names = {1: "🥅 حراس المرمى", 2: "🛡️ خط الدفاع", 3: "⚡ خط الوسط", 4: "🎯 خط الهجوم"}
    pos_name = pos_names.get(pos_id, "اللاعبين")
    
    players_per_page = 20
    all_pos_players = get_all_players_data(sort_by=sort_by, position_id=pos_id)
    total_players = len(all_pos_players)
    total_pages = max(1, (total_players + players_per_page - 1) // players_per_page)
    
    start_idx = page * players_per_page
    end_idx = min(start_idx + players_per_page, total_players)
    page_players = all_pos_players[start_idx:end_idx]
    
    sort_labels = {
        "points": "النقاط", "price": "السعر", "selected": "الملكية",
        "goals": "الأهداف", "assists": "الأسيستات",
        "clean_sheets": "الكلين شيت", "cleansheets": "الكلين شيت",
        "saves": "التصديات",
        "def_contrib": "المساهمات الدفاعية", "defcontrib": "المساهمات الدفاعية"
    }
    
    response = (
        f"قائمة **{pos_name}**\n"
        f"📌 **الفرز حسب:** {sort_labels.get(sort_by, 'النقاط')}\n"
        f"📖 الصفحة {page + 1} من {total_pages} (إجمالي: {total_players})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not page_players:
        return response + "🚫 لا يوجد لاعبين للعرض\n"
        
    for idx, player in enumerate(page_players, start=start_idx + 1):
        p_name = sanitize_markdown(player['name'])
        team_short = TEAM_NAMES.get(player['team'], "???")
        
        extra_stat = ""
        if sort_by == "goals":
            extra_stat = f" | الأهداف: **{player['goals']}**"
        elif sort_by == "assists":
            extra_stat = f" | الأسيستات: **{player['assists']}**"
        elif sort_by in ["clean_sheets", "cleansheets"]:
            extra_stat = f" | الكلين شيت: **{player['clean_sheets']}**"
        elif sort_by == "saves":
            extra_stat = f" | التصديات: **{player['saves']}**"
        elif sort_by in ["def_contrib", "defcontrib"]:
            extra_stat = f" | مساهمات دفاعية: **{player['def_contrib']}**"

        response += (
            f"{idx:2d}. **{p_name}** ({team_short})\n"
            f"    النقاط: **{player['total_points']}** | السعر: **£{player['price']:.1f}M** | الملكية: **{player['selected_by']:.1f}%**{extra_stat}\n\n"
        )
        
    response += "━━━━━━━━━━━━━━━━━━━━━\n"
    return response
    
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"فشل في answer callback: {e}")
    
    user_id = update.effective_user.id
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    parts = data.split("_")
    
    logger.info(f"📩 تم استلام callback: {data}")
    
    if len(parts) < 2:
        logger.warning(f"تنسيق غير صحيح للبيانات: {data}")
        return

    # 1. معالجة زر التحقق من الاشتراك الخاص بالقنوات أولاً
    if parts[0] == "check":
        logger.info(f"✅ تم الضغط على زر التحقق للمستخدم {user_id}")
        is_subscribed = await check_subscription(context, user_id)
        
        if is_subscribed:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                logger.error(f"فشل في حذف رسالة الاشتراك: {e}")
            
            welcome_text = (
                "🎮 **بوت مساعد الفانتاسي**\n\n"
                "✨ **كيف يعمل؟**\n"
                "• أرسل **رقم معرف المدرب**\n"
                "• سأعرض لك بيانات الجولة الحالية تلقائياً\n\n"
                "📊 **البيانات المتاحة**\n"
                "✓ نقاط الجولة للمدرب\n"
                "✓ النقاط الكلية والترتيب العالمي\n"
                "✓ نقاط كل لاعب في الفريق\n"
                "✓ نقاط القائد\n"
                "✓ قيمة الفريق والبنك 💰\n"
                "✓ ترتيب المدرب في كل دوري\n"
                "✓ تاريخ المواسم السابقة\n"
                "✓ نتائج المباريات وتفاصيلها ⚽\n"
                "✓ مواعيد الديدلاين وانتهاء وقت الانتقالات \n\n"
                "🔑 **كيف تحصل على معرف مدرب؟**\n"
                "افتح موقع FPL، الرقم في الرابط:\n"
                "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
                "📝 **مثال:** أرسل `2794801`"
            )
            await context.bot.send_message(chat_id=chat_id, text=welcome_text, parse_mode='Markdown')
        else:
            channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
            await context.bot.edit_message_text(
                text=f"❌ **لم يتم العثور على اشتراكك في جميع القنوات بعد.**\n\n"
                     f"يرجى الانضمام إلى جميع القنوات أولاً:\n{channels_list}",
                chat_id=chat_id, message_id=message_id, parse_mode='Markdown',
                reply_markup=get_subscription_button()
            )
        return

    # 2. فحص الاشتراك لباقي الأزرار والتفاعل
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
        await context.bot.edit_message_text(
            text=f"🔒 **يرجى الاشتراك في جميع القنوات أولاً!**\n\n"
                 f"{channels_list}\n\n"
                 f"✅ بعد الاشتراك في الكل، اضغط على زر 'تم الاشتراك - تحقق مرة أخرى'.",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='Markdown',
            reply_markup=get_subscription_button()
        )
        return
    
    manager_id = context.user_data.get('current_manager_id')
    if not manager_id:
        try:
            if len(parts) >= 2:
                manager_id = parts[1]
        except Exception:
            pass
    
    if not manager_id:
        await context.bot.edit_message_text(
            text="❌ حدث خطأ: يرجى إرسال معرف المدرب مرة أخرى باستخدام /start",
            chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
        )
        return
    
    try:
        # 3. قائمة اختيار المراكز
        if parts[0] == "poslist":
            gameweek = int(parts[2])
            await context.bot.edit_message_text(
                text="🎯 **اختر المركز المطلوب لعرض لاعبيه:**",
                chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown',
                reply_markup=get_positions_keyboard(manager_id, gameweek)
            )
            return

        # 4. عرض لاعبي مركز معين
        elif parts[0] == "posview":
            gameweek = int(parts[2])
            pos_id = int(parts[3])
            sort_by = parts[4]
            page = int(parts[5]) if len(parts) > 5 else 0

            await context.bot.edit_message_text(
                text="🔄 جاري تحميل لاعبي المركز...",
                chat_id=chat_id, message_id=message_id
            )

            all_pos_players = get_all_players_data(sort_by=sort_by, position_id=pos_id)
            total_pages = max(1, (len(all_pos_players) + 19) // 20)

            text = format_position_players_display(manager_id, gameweek, pos_id, sort_by, page)
            reply_markup = get_position_players_buttons(manager_id, gameweek, pos_id, sort_by, page, total_pages)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return

        # 5. قائمة اختيار الفرق
        elif parts[0] == "teamslist":
            gameweek = int(parts[2])
            await context.bot.edit_message_text(
                text="🏢 **اختر الفريق لعرض لاعبيه:**",
                chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown',
                reply_markup=get_teams_keyboard(manager_id, gameweek)
            )
            return

        # 6. عرض لاعبي فريق معين
        elif parts[0] == "teamview":
            gameweek = int(parts[2])
            team_id = int(parts[3])
            sort_by = parts[4] if len(parts) > 4 else "points"
            
            await context.bot.edit_message_text(
                text="🔄 جاري تحميل لاعبي الفريق...",
                chat_id=chat_id, message_id=message_id
            )
            
            text = format_team_players_display(manager_id, gameweek, team_id, sort_by)
            reply_markup = get_team_players_buttons(manager_id, gameweek, team_id, sort_by)
            
            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return

        # 7. قائمة جميع اللاعبين العامة
        elif parts[0] == "players":
            gameweek = int(parts[2])
            
            if len(parts) == 5:
                sort_by = parts[3]
                page = int(parts[4])
            elif len(parts) == 4:
                sort_by = "points"
                page = int(parts[3])
            else:
                sort_by = "points"
                page = 0
            
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل قائمة اللاعبين (صفحة {page + 1})...",
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
            
            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
                )
                return
            
            all_players = get_all_players_data(sort_by=sort_by)
            total_pages = (len(all_players) + 19) // 20
            
            text = format_players_display(manager_id, info, gameweek, sort_by=sort_by, page=page)
            reply_markup = get_players_buttons(manager_id, gameweek, sort_by, page, total_pages)
            
            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return
        
        # 8. التنقل بين الجولات
        elif parts[0] == "nav":
            gameweek = int(parts[2])
            current_text = query.message.text or ""
            
            # تحديد نوع العرض الحالي
            if "العرض المفصل" in current_text or "اللاعبون الأساسيون" in current_text:
                view_type = "detail"
            elif "الدوريات" in current_text:
                view_type = "leagues"
            elif "المباريات" in current_text or "نتائج" in current_text or "قائمة مباريات" in current_text:
                view_type = "fixtures"
            elif "المواعيد" in current_text:
                view_type = "deadline"
            elif "تغيرات وتوقعات" in current_text:
                view_type = "price"
            else:
                view_type = "simple"
            
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل بيانات الجولة {gameweek}...",
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
            
            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
                )
                return
            
            if view_type == "deadline":
                text = format_deadline_display(manager_id, info, gameweek)
                reply_markup = get_buttons(manager_id, gameweek, view_type)
            elif view_type == "price":
                text = format_price_changes_display(manager_id, info, gameweek)
                reply_markup = get_buttons(manager_id, gameweek, view_type)
            elif view_type == "fixtures":
                history = get_manager_history(manager_id)
                text, reply_markup = format_fixtures_display(manager_id, info, gameweek, history)
            else:
                picks_data = get_manager_picks(manager_id, gameweek)
                history = get_manager_history(manager_id)
                text_map = {
                    "simple": format_simple_display(manager_id, info, gameweek, picks_data, history),
                    "detail": format_detailed_display(manager_id, info, gameweek, picks_data, history),
                    "leagues": format_leagues_display(manager_id, info, gameweek, history),
                }
                text = text_map.get(view_type, "")
                reply_markup = get_buttons(manager_id, gameweek, view_type)
            
            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return
        
        # 9. عرض تفاصيل المباراة المختارة
        elif parts[0] == "matchdetail":
            manager_id = parts[1]
            gameweek = int(parts[2])
            fixture_id = int(parts[3])
            
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل تفاصيل المباراة...",
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
            
            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
                )
                return
            
            text, reply_markup = format_match_detail_display(manager_id, info, gameweek, fixture_id)
            
            # التأكد من وجود reply_markup
            if reply_markup is None:
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 العودة لقائمة المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
                    [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"simple_{manager_id}_{gameweek}")]
                ])
            
            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return
        
        # 10. معالجة القوائم الرئيسية الأخرى
        elif parts[0] in ["simple", "detail", "leagues", "fixtures", "deadline", "price"]:
            view_type = parts[0]
            gameweek = int(parts[2])
            
            loading_texts = {
                "simple": "العرض البسيط", "detail": "العرض المفصل",
                "leagues": "الدوريات والمواسم", "fixtures": "المباريات",
                "deadline": "مواعيد الجولة", "price": "توقعات وتغيرات الأسعار"
            }
            
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل {loading_texts[view_type]} للجولة {gameweek}...",
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
            
            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
                )
                return
            
            if view_type == "deadline":
                text = format_deadline_display(manager_id, info, gameweek)
                reply_markup = get_buttons(manager_id, gameweek, view_type)
            elif view_type == "price":
                text = format_price_changes_display(manager_id, info, gameweek)
                reply_markup = get_buttons(manager_id, gameweek, view_type)
            elif view_type == "fixtures":
                history = get_manager_history(manager_id)
                text, reply_markup = format_fixtures_display(manager_id, info, gameweek, history)
            else:
                picks_data = get_manager_picks(manager_id, gameweek)
                history = get_manager_history(manager_id)
                text_map = {
                    "simple": format_simple_display(manager_id, info, gameweek, picks_data, history),
                    "detail": format_detailed_display(manager_id, info, gameweek, picks_data, history),
                    "leagues": format_leagues_display(manager_id, info, gameweek, history),
                }
                text = text_map.get(view_type, "")
                reply_markup = get_buttons(manager_id, gameweek, view_type)
            
            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return
        
    except Exception as e:
        logger.error(f"خطأ في معالجة callback: {e}")
        try:
            await context.bot.edit_message_text(
                text=f"❌ حدث خطأ أثناء تحميل البيانات: {str(e)[:100]}\n\nيرجى المحاولة مرة أخرى بإرسال معرف المدرب.",
                chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
            )
        except Exception as edit_error:
            logger.error(f"فشل في إرسال رسالة الخطأ: {edit_error}")
            
# ============================================================
# تشغيل البوت
# ============================================================

players_dict = get_players_dict()
current_gameweek = get_current_gameweek()

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("=" * 50)
    print("🤖 البوت يعمل الآن (الإصدار مع زر المواعيد)")
    print(f"📅 آخر جولة لعبت: {current_gameweek}")
    print("✅ المميزات:")
    print("   • عرض بسيط ومفصل للمدربين")
    print("   • دعم البنش بوست والتربل كابتن")
    print("   • حالة البطاقات مع تقسيم الموسم لنصفين")
    print("   • عرض المباريات بنتائج وتفاصيل")
    print("   • مواعيد الجولة (الديدلاين) ⏰")
    print("   • توقيت مكة المكرمة حصراً")
    print("📡 أرسل معرف مدرب للبدء")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
