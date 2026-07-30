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
# للتصحيح فقط - احذفه بعد التأكد
print("BOT_TOKEN exists:", "BOT_TOKEN" in os.environ)
# لا تطبع التوكن نفسه في السجلات للأمان
BASE_URL = "https://fantasy.premierleague.com/api"
CHANNELS = [
    {"id": "@Fantasypremierlea", "name": "القناة الأولى"},
    {"id": "@Fantasyargoal", "name": "القناة الثانية"},  # غيّر إلى قناتك الثانية
]

POSITION_OVERRIDES_26_27 = {
    # id: (المركز الجديد, الاسم الكامل)
    # 1=حارس, 2=مدافع, 3=وسط, 4=مهاجم
    # هذه أمثلة - يجب تحديثها بالأرقام الصحيحة من الموسم الجديد
    
    # مثال: 12345: (4, "Omar Marmoush"),  # من وسط إلى مهاجم
    # مثال: 67890: (3, "Patrick Dorgu"),   # من مدافع إلى وسط
    # أضف باقي اللاعبين هنا عند معرفة أرقامهم
}

# ============================================================
# دوال مساعدة عامة
# ============================================================

def safe_int(value):
    return int(value) if value is not None else 0

def safe_str(value):
    return str(value) if value is not None else "غير معروف"

def sanitize_markdown(text):
    """إزالة الأحرف التي قد تعطل تنسيق Markdown"""
    if not text:
        return "غير معروف"
    dangerous_chars = ['[', ']', '(', ')', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in dangerous_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def check_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """
    التحقق من اشتراك المستخدم في جميع القنوات المطلوبة
    يعيد True إذا كان مشتركاً في الكل، False إذا لم يكن مشتركاً في واحدة على الأقل
    """
    for channel in CHANNELS:
        channel_id = channel["id"]
        try:
            # محاولة جلب معلومات عضو القناة
            chat_member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            
            # الحالات التي تعني أن المستخدم مشترك
            if chat_member.status not in ["member", "administrator", "creator"]:
                # غير مشترك في هذه القناة
                logger.info(f"المستخدم {user_id} غير مشترك في القناة {channel_id}")
                return False
        except Exception as e:
            logger.error(f"خطأ في التحقق من اشتراك المستخدم {user_id} في القناة {channel_id}: {e}")
            # إذا حدث خطأ (مثل البوت ليس مشرفاً في القناة)، نسمح بالدخول مؤقتاً
            return True
    
    # مشترك في جميع القنوات
    return True

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

def format_number_abbreviation(num):
    """تحويل الأرقام الكبيرة إلى اختصارات (K, M)"""
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
    """
    حساب تغير الترتيب من بيانات history مباشرة
    """
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
    """
    إرجاع نص التغير في ترتيب الدوري مع إيموجي ورقم مختصر
    """
    if previous_rank <= 0 or current_rank <= 0:
        return ""
    
    diff = previous_rank - current_rank  # موجب = تحسن، سالب = تراجع
    
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
    """جلب بيانات اللاعبين الخام مع المساهمات الدفاعية"""
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

def get_all_players_data(sort_by="points"):
    """
    جلب جميع اللاعبين مع مراكزهم وأسعارهم ونقاطهم
    sort_by: "points" | "price" | "ownership"
    """
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_all_players_data")
    players_list = []
    
    if data and "elements" in data:
        for player in data["elements"]:
            # تطبيق التعديلات اليدوية للمراكز من الموسم الجديد
            player_id = player["id"]
            if player_id in POSITION_OVERRIDES_26_27:
                new_pos, _ = POSITION_OVERRIDES_26_27[player_id]
                player["element_type"] = new_pos
            
            # تأكد من تحويل القيم إلى أرقام
            try:
                total_points = int(player.get("total_points", 0))
            except (ValueError, TypeError):
                total_points = 0
                
            try:
                price = float(player.get("now_cost", 0)) / 10
            except (ValueError, TypeError):
                price = 0.0
                
            try:
                selected_by = float(player.get("selected_by_percent", 0))
            except (ValueError, TypeError):
                selected_by = 0.0
                
            try:
                form = float(player.get("form", 0))
            except (ValueError, TypeError):
                form = 0.0
            
            players_list.append({
                "id": player["id"],
                "name": f"{player['first_name']} {player['second_name']}",
                "position": player.get("element_type", 0),
                "price": price,
                "total_points": total_points,
                "team": player.get("team", 0),
                "selected_by": selected_by,
                "form": form
            })
    
    # ترتيب اللاعبين حسب الخيار المحدد
    if sort_by == "price":
        players_list.sort(key=lambda x: x["price"], reverse=True)
    elif sort_by == "ownership":
        players_list.sort(key=lambda x: x["selected_by"], reverse=True)
    else:  # points (الافتراضي)
        players_list.sort(key=lambda x: x["total_points"], reverse=True)
    
    logger.info(f"👥 تم تحميل {len(players_list)} لاعب مرتب حسب {sort_by}")
    return players_list

def get_fixtures(gameweek=None):
    if gameweek:
        url = f"{BASE_URL}/fixtures/?event={gameweek}"
    else:
        url = f"{BASE_URL}/fixtures/"
    data = safe_api_request(url, "get_fixtures")
    return data if data else []

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
                "id": team_id, "name": team_name, "short_name": team_short_name,
                "emoji": f"{emoji} {team_short_name}", "emoji_only": emoji
            }
    return teams


# ========== أضف هنا ==========
# قاموس أسماء المراكز
POSITION_NAMES = {
    1: "🥅 حارس",
    2: "🛡️ مدافع", 
    3: "⚡ وسط",
    4: "🎯 مهاجم"
}

# قاموس أسماء الفرق بالإنجليزية (للاستخدام في عرض اللاعبين)
TEAM_NAMES = {
    1: "ARS", 2: "AVL", 3: "BOU", 4: "BRE", 5: "BHA",
    6: "CHE", 7: "CRY", 8: "EVE", 9: "FUL", 10: "LEI",
    11: "LIV", 12: "MCI", 13: "MUN", 14: "NEW", 15: "NFO",
    16: "SOU", 17: "TOT", 18: "WOL", 19: "IPS", 20: "COV"
}
# =============================

def get_defensive_contribution_status(player_id, element_type, full_live_data):
    """التحقق من استحقاق المساهمة الدفاعية"""
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
    """تنسيق وقت المباراة بتوقيت مكة المكرمة"""
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
    """جلب إحصائيات الجولة مثل المتوسط وأعلى نقاط"""
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

    # ========== جلب الترتيب الصحيح للجولة ==========
    target_gw_rank = 0
    if history and "current" in history:
        for gw_entry in history["current"]:
            if gw_entry.get("event") == gameweek:
                target_gw_rank = safe_int(gw_entry.get("overall_rank"))
                break
    
    rank = target_gw_rank if target_gw_rank > 0 else safe_int(info.get("summary_overall_rank"))
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    # ================================================
    
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
            history = picks_data["entry_history"]
            transfers_made = safe_int(history.get("event_transfers", 0))
            transfers_cost = safe_int(history.get("event_transfers_cost", 0))
            event_rank = safe_int(history.get("rank", 0))
    
    event_points_after_hits = event_points_before_hits - transfers_cost
    transfer_line = f"🔄 الانتقالات: *{transfers_made}*" + (f" (-{transfers_cost})" if transfers_cost > 0 else "")
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"

    # حساب تغير الترتيب
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

#  انتهت دالة العرض البسيط وبعدها دالة العرض المفصل

def format_detailed_display(manager_id, info, gameweek, picks_data, history):
    name = sanitize_markdown(safe_str(info.get("name")))
    joined = safe_str(info.get("joined_time", ""))[:10]
    if joined == "" or joined == "None":
        joined = "غير معروف"
    
    total_points = safe_int(info.get("summary_overall_points"))

    # ========== جلب الترتيب الصحيح للجولة ==========
    target_gw_rank = 0
    if history and "current" in history:
        for gw_entry in history["current"]:
            if gw_entry.get("event") == gameweek:
                target_gw_rank = safe_int(gw_entry.get("overall_rank"))
                break
    
    rank = target_gw_rank if target_gw_rank > 0 else safe_int(info.get("summary_overall_rank"))
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    # ================================================
    
    # القيمة المالية
    team_value = bank_value = total_value_display = 0.0
    if picks_data and "entry_history" in picks_data:
        history_info = picks_data["entry_history"]
        raw_total_value = safe_int(history_info.get("value", 0))
        raw_bank = safe_int(history_info.get("bank", 0))
        bank_value = raw_bank / 10
        team_value = (raw_total_value - raw_bank) / 10
        total_value_display = raw_total_value / 10
    
    # جلب البيانات
    full_live_data = get_full_live_data(gameweek)
    active_chip = picks_data.get("active_chip") if picks_data else None

    # حساب تغير الترتيب
    rank_change_display = get_rank_change_display(manager_id, gameweek, history)

    # جلب إحصائيات الجولة (المتوسط)
    gw_stats = get_gameweek_stats(gameweek)
    avg_points = gw_stats["average_score"]
    
    # بيانات مراكز اللاعبين
    players_full_data = {}
    bootstrap_data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_players_full_data")
    if bootstrap_data and "elements" in bootstrap_data:
        for player in bootstrap_data["elements"]:
            players_full_data[player["id"]] = {"element_type": player.get("element_type")}
    
    position_names = {1: "🥅 الحراسة", 2: "🪖 الدفاع", 3: "⚡ الوسط", 4: "🎯 الهجوم"}
    
    # دالة معالجة اللاعب
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
    
    # حساب النقاط
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
        
        # عرض اللاعبين البدلاء (الاحتياط)
        if len(picks_data["picks"]) > 11:
            players_output += "🔄 **اللاعبون البدلاء:**\n\n"
            for pick in picks_data["picks"][11:]:
                p_id = pick['element']
                p_name = sanitize_markdown(players_dict.get(p_id, "Unknown"))
                p_pts_val, p_pts_raw, p_icons, def_icon = get_player_row(p_id, 1)
                players_output += f"• {p_name} {p_icons}{def_icon}: **{p_pts_val}**\n"
                # ✅ إضافة نقاط البدلاء فقط عند تفعيل بطاقة bench boost
                if active_chip == "bboost":
                    event_points_before_hits += p_pts_raw
            players_output += "\n"
        
        if "entry_history" in picks_data:
            event_rank = safe_int(picks_data["entry_history"].get("rank", 0))
            transfers_cost = safe_int(picks_data["entry_history"].get("event_transfers_cost", 0))
            total_transfers = safe_int(picks_data["entry_history"].get("event_transfers", total_transfers))
    
    event_points_after_hits = event_points_before_hits - transfers_cost
    
    # حالة البطاقات
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
    
    # تنسيق الأرقام
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
    
    # بناء الرد
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
            # إزالة الأحرف التي تفشل مع Markdown حتى بعد sanitize
            clean_name = raw_name.replace('*', '✦').replace('_', '-').replace('`', "'")
            clean_name = clean_name.replace('[', '(').replace(']', ')')
            # الآن نطبق sanitize_markdown بأمان
            league_name = sanitize_markdown(clean_name)
            
            league_rank = league.get('entry_rank') or league.get('rank')
            league_total = league.get('rank_count')
            
            previous_league_rank = league.get('entry_last_rank') or league.get('last_rank', 0)
            
            # حساب نص تغير ترتيب الدوري
            league_change_display = get_league_change_display(league_rank, previous_league_rank) if league_rank else ""
            
            try:
                if league_rank is not None and league_total is not None:
                    response += f"{idx}. {league_name}: {league_rank:,} / {league_total:,}{league_change_display}\n\n"
                elif league_rank is not None:
                    response += f"{idx}. {league_name}: الترتيب {league_rank}{league_change_display}\n\n"
                else:
                    response += f"{idx}. {league_name}\n\n"
            except Exception as e:
                # في حال فشل التنسيق، نستخدم أبسط صيغة ممكنة
                logger.warning(f"⚠️ فشل تنسيق الدوري {idx} للمدرب {manager_id}: {e}")
                try:
                    # محاولة أخيرة بنص خالٍ تماماً من التنسيق
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
                # تنظيف اسم الموسم
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
        f"⚽ **نتائج وتفاصيل المباريات**\n"
        f"📅 **الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (بتوقيت مكة المكرمة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not fixtures:
        response += "🚫 لا توجد مباريات في هذه الجولة\n"
    else:
        matches_by_day = {}
        for fixture in fixtures:
            kickoff = fixture.get("kickoff_time")
            if kickoff:
                date_str = kickoff[:10]
                matches_by_day.setdefault(date_str, []).append(fixture)
            else:
                matches_by_day.setdefault("unknown", []).append(fixture)
        
        sorted_dates = sorted([d for d in matches_by_day.keys() if d != "unknown"])
        if "unknown" in matches_by_day:
            sorted_dates.append("unknown")
        
        for date_str in sorted_dates:
            if date_str == "unknown":
                response += "📅 **مواعيد غير محددة**\n"
            else:
                try:
                    dt = datetime.fromisoformat(date_str)
                    day_name_ar = {
                        "Monday": "الإثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء",
                        "Thursday": "الخميس", "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد"
                    }.get(calendar.day_name[dt.weekday()], calendar.day_name[dt.weekday()])
                    response += f"📆 **{day_name_ar} {dt.strftime('%d/%m/%Y')}**\n"
                except:
                    response += f"📆 **{date_str}**\n"
            
            for fixture in matches_by_day[date_str]:
                match_time = format_match_time(fixture.get("kickoff_time"))
                team_h_info = teams_dict.get(fixture.get("team_h"), {"emoji_only": "⚽", "short_name": "?"})
                team_a_info = teams_dict.get(fixture.get("team_a"), {"emoji_only": "⚽", "short_name": "?"})
                team_h_display = f"{team_h_info['emoji_only']} {team_h_info['short_name']}"
                team_a_display = f"{team_a_info['emoji_only']} {team_a_info['short_name']}"
                
                if fixture.get("team_h_score") is not None and fixture.get("team_a_score") is not None:
                    score_display = f"**{fixture['team_h_score']}** - **{fixture['team_a_score']}**"
                else:
                    score_display = "VS"
                
                response += f"• {match_time} | {team_h_display} {score_display} {team_a_display} | {format_match_status(fixture)}\n"
            response += "\n"
    
    response += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += "🟢 جارية | 🔴 انتهت | ⚪ لم تبدأ\n"
    response += f"🕐 جميع الأوقات بتوقيت مكة المكرمة (UTC+3)"
    
    return response

def format_deadline_display(manager_id, info, gameweek):
    """
    عرض مواعيد الجولة: تاريخ التحديث، بداية الجولة (أول مباراة)،
    نهاية الجولة (آخر مباراة)، وموعد غلق الانتقالات (deadline)
    - جميع الأوقات بتوقيت مكة المكرمة حصراً
    """
    name = sanitize_markdown(safe_str(info.get("name")))
    
    # وقت التحديث الحالي
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time_str = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date_str = now_mecca.strftime("%d/%m/%Y")
    
    # موعد غلق الانتقالات (deadline)
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
    
    # أول وآخر مباراة في الجولة
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

def format_players_display(manager_id, info, gameweek, page=0, sort_by="points"):
    """
    عرض جميع اللاعبين مع ترقيم الصفحات
    كل صفحة تعرض 20 لاعب
    sort_by: "points" | "price" | "ownership"
    """
    name = sanitize_markdown(safe_str(info.get("name")))
    players_per_page = 20
    
    # جلب جميع اللاعبين مع الترتيب المطلوب
    all_players = get_all_players_data(sort_by)
    total_players = len(all_players)
    total_pages = (total_players + players_per_page - 1) // players_per_page
    
    # حساب نطاق اللاعبين في الصفحة الحالية
    start_idx = page * players_per_page
    end_idx = min(start_idx + players_per_page, total_players)
    page_players = all_players[start_idx:end_idx]
    
    # وقت التحديث
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")
    
    # أسماء الترتيب للعرض
    sort_names = {
        "points": "🏆 النقاط",
        "price": "💰 السعر",
        "ownership": "👥 الملكية"
    }
    sort_display = sort_names.get(sort_by, "النقاط")
    
    response = (
        f"👥 **جميع لاعبي الدوري الإنجليزي**\n"
        f"👤 {name}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 الصفحة {page + 1} من {total_pages}\n"
        f"👥 إجمالي اللاعبين: {total_players}\n"
        f"📌 مرتب حسب: {sort_display}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not page_players:
        response += "🚫 لا يوجد لاعبين للعرض\n"
        return response
    
    # عرض اللاعبين في جدول مرتب
    for idx, player in enumerate(page_players, start=start_idx + 1):
        # تنظيف اسم اللاعب
        player_name = sanitize_markdown(player['name'])
        
        # تنسيق المركز
        pos_id = player["position"]
        pos_name = POSITION_NAMES.get(pos_id, "❓ غير معروف")
        
        # تنسيق السعر
        price = player["price"]
        price_str = f"£{price:.1f}M" if price > 0 else "غير متاح"
        
        # تنسيق النقاط
        points = player["total_points"]
        
        # اسم الفريق (اختصار)
        team_id = player.get("team", 0)
        team_short = TEAM_NAMES.get(team_id, "???")
        
        # نسبة الاختيار
        selected = player.get("selected_by", 0)
        selected_str = f"{selected:.1f}%" if selected > 0 else "0%"
        
        # الفورم
        form = player.get("form", 0)
        form_str = f"{form:.1f}" if form > 0 else "-"
        
        # تنسيق الصف
        response += (
            f"{idx:3d}. **{player_name}**\n"
            f"   {pos_name} | {team_short} | السعر: {price_str} | النقاط: {points} | الفورم: {form_str} | الاختيار: {selected_str}\n\n"
        )
    
    # إضافة معلومات إضافية
    response += "━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"📊 إجمالي اللاعبين المعروضين: {len(page_players)}\n"
    response += "🔄 استخدم الأزرار أدناه للتنقل والترتيب"
    
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
         InlineKeyboardButton("👥 جميع اللاعبين", callback_data=f"players_{manager_id}_{gameweek}_0_points")],
        [InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{prev_gw}"),
         InlineKeyboardButton("➡️ الجولة التالية", callback_data=f"nav_{manager_id}_{next_gw}")]
    ]
    return InlineKeyboardMarkup(keyboard)
    
def get_players_buttons(manager_id, gameweek, page, total_pages, current_sort="points"):
    """
    أزرار خاصة بعرض اللاعبين مع التنقل بين الصفحات وزر الرجوع وأزرار الترتيب
    """
    keyboard = []
    
    # ========== أزرار الترتيب ==========
    sort_buttons = []
    
    # زر النقاط
    if current_sort != "points":
        sort_buttons.append(InlineKeyboardButton("🏆 نقاط", callback_data=f"players_sort_{manager_id}_{gameweek}_points_{page}"))
    else:
        sort_buttons.append(InlineKeyboardButton("✅ نقاط", callback_data=f"players_sort_{manager_id}_{gameweek}_points_{page}"))
    
    # زر السعر
    if current_sort != "price":
        sort_buttons.append(InlineKeyboardButton("💰 سعر", callback_data=f"players_sort_{manager_id}_{gameweek}_price_{page}"))
    else:
        sort_buttons.append(InlineKeyboardButton("✅ سعر", callback_data=f"players_sort_{manager_id}_{gameweek}_price_{page}"))
    
    # زر الملكية
    if current_sort != "ownership":
        sort_buttons.append(InlineKeyboardButton("👥 ملكية", callback_data=f"players_sort_{manager_id}_{gameweek}_ownership_{page}"))
    else:
        sort_buttons.append(InlineKeyboardButton("✅ ملكية", callback_data=f"players_sort_{manager_id}_{gameweek}_ownership_{page}"))
    
    keyboard.append(sort_buttons)
    
    # ========== أزرار التنقل بين الصفحات ==========
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"players_{manager_id}_{gameweek}_{page-1}_{current_sort}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"players_{manager_id}_{gameweek}_{page+1}_{current_sort}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # ========== زر الرجوع للصفحة الرئيسية ==========
    keyboard.append([InlineKeyboardButton("🔙 العودة للصفحة الرئيسية", callback_data=f"simple_{manager_id}_{gameweek}")])
    
    return InlineKeyboardMarkup(keyboard)
    
def get_subscription_button():
    keyboard = []
    
    for channel in CHANNELS:
        channel_id = channel["id"]
        channel_name = channel.get("name", channel_id)
        channel_link = channel_id
        if channel_link.startswith('@'):
            channel_link = channel_link[1:]
        
        keyboard.append([InlineKeyboardButton(
            f"📢 اشترك في {channel_name}", 
            url=f"https://t.me/{channel_link}"
        )])
    
    # ✅ تأكد من أن هذا هو نفس الاسم المستخدم في handle_callback
    keyboard.append([InlineKeyboardButton(
        "✅ تم الاشتراك - تحقق مرة أخرى", 
        callback_data="check_subscription"  # هذا سيصبح parts[0] = "check"
    )])
    
    return InlineKeyboardMarkup(keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # ============================================================
    # أوامر /start و /help - نتحقق من الاشتراك أولاً
    # ============================================================
    if message_text.startswith(('/start', '/help')):
        # التحقق من الاشتراك قبل عرض رسالة الترحيب
        is_subscribed = await check_subscription(context, user_id)
        
        if not is_subscribed:
            # المستخدم غير مشترك - عرض رسالة الاشتراك الإجباري مع زر
            # بناء قائمة القنوات المطلوبة
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
        
        # المستخدم مشترك - عرض رسالة الترحيب
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
    
    # ============================================================
    # أي رسالة أخرى (غير /start و /help) - نتحقق من الاشتراك
    # ============================================================
    is_subscribed = await check_subscription(context, user_id)
    
    if not is_subscribed:
        # بناء قائمة القنوات المطلوبة
        channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
        
        await update.message.reply_text(
            f"🔒 **يرجى الاشتراك في جميع القنوات أولاً!**\n\n"
            f"{channels_list}\n\n"
            f"✅ بعد الاشتراك في الكل، اضغط على زر 'تم الاشتراك - تحقق مرة أخرى'.",
            parse_mode='Markdown',
            reply_markup=get_subscription_button()
        )
        return
    
    # ============================================================
    # معالجة معرف المدرب (المستخدم مشترك)
    # ============================================================
    try:
        manager_id = int(message_text)
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
    history = get_manager_history(manager_id)
    text = format_simple_display(manager_id, info, start_gameweek, picks_data, history)
    reply_markup = get_buttons(manager_id, start_gameweek, "simple")
    
    await update.message.reply_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"فشل في answer callback: {e}")
    
    # ========== التحقق من الاشتراك قبل أي إجراء ==========
    user_id = update.effective_user.id
    is_subscribed = await check_subscription(context, user_id)
    
    if not is_subscribed:
        # بناء قائمة القنوات المطلوبة
        channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
        
        await context.bot.edit_message_text(
            text=f"🔒 **يرجى الاشتراك في جميع القنوات أولاً!**\n\n"
                 f"{channels_list}\n\n"
                 f"✅ بعد الاشتراك في الكل، اضغط على زر 'تم الاشتراك - تحقق مرة أخرى'.",
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            parse_mode='Markdown',
            reply_markup=get_subscription_button()
        )
        return
    # ======================================================
    
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    parts = data.split("_")
    
    # ========== طباعة للتصحيح ==========
    logger.info(f"📩 تم استلام callback: {data}")
    logger.info(f"📩 الأجزاء: {parts}")
    # ===================================
    
    if len(parts) < 2:
        logger.warning(f"تنسيق غير صحيح للبيانات: {data}")
        return
    
    # ========== ✅ تعريف manager_id هنا ==========
    # محاولة استخراج manager_id من الـ context أولاً
    manager_id = context.user_data.get('current_manager_id')
    
    # إذا لم يكن موجوداً في الـ context، نحاول استخراجه من الأجزاء
    if not manager_id:
        try:
            # الأجزاء عادة تكون: [type, manager_id, ...]
            if len(parts) >= 2:
                manager_id = parts[1]
        except:
            pass
    
    # إذا لم نجد manager_id، نطلب من المستخدم إرساله مرة أخرى
    if not manager_id:
        await context.bot.edit_message_text(
            text="❌ حدث خطأ: يرجى إرسال معرف المدرب مرة أخرى باستخدام /start",
            chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
        )
        return
    # =============================================
    
    # ============================================================
    # معالجة زر "تم الاشتراك - تحقق مرة أخرى"
    # ============================================================
    if parts[0] == "check":
        logger.info(f"✅ تم الضغط على زر التحقق للمستخدم {user_id}")
        
        # إعادة التحقق من الاشتراك
        is_subscribed = await check_subscription(context, user_id)
        logger.info(f"نتيجة التحقق: {is_subscribed}")
        
        if is_subscribed:
            # ✅ المستخدم مشترك الآن - نحذف رسالة الاشتراك ونرسل رسالة الترحيب
            logger.info(f"✅ المستخدم {user_id} مشترك في جميع القنوات")
            
            # 1. حذف رسالة الاشتراك القديمة
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
                logger.info(f"✅ تم حذف رسالة الاشتراك بنجاح")
            except Exception as e:
                logger.error(f"فشل في حذف رسالة الاشتراك: {e}")
                # إذا فشل الحذف، نقوم بتعديلها بدلاً من ذلك
                await context.bot.edit_message_text(
                    text="✅ **تم التحقق من اشتراكك!**\n\nأرسل معرف المدرب للبدء.",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='Markdown'
                )
                return
            
            # 2. إرسال رسالة الترحيب الجديدة
            welcome_text = (
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
                "📝 **مثال:** أرسل `2794801`"
            )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                parse_mode='Markdown'
            )
            logger.info(f"✅ تم إرسال رسالة الترحيب للمستخدم {user_id}")
            
        else:
            # ❌ المستخدم لا يزال غير مشترك في جميع القنوات
            logger.info(f"❌ المستخدم {user_id} لا يزال غير مشترك في جميع القنوات")
            channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
            
            await context.bot.edit_message_text(
                text=f"❌ **لم يتم العثور على اشتراكك في جميع القنوات بعد.**\n\n"
                     f"يرجى الانضمام إلى جميع القنوات أولاً:\n"
                     f"{channels_list}\n\n"
                     f"📌 **خطوات الاشتراك:**\n"
                     f"1️⃣ اضغط على أزرار 'اشترك في القناة' لكل قناة\n"
                     f"2️⃣ انضم إلى جميع القنوات\n"
                     f"3️⃣ عد إلى البوت واضغط 'تم الاشتراك - تحقق مرة أخرى'",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown',
                reply_markup=get_subscription_button()
            )
        return
    
    # ============================================================
    # معالجة أزرار ترتيب اللاعبين (جديد)
    # ============================================================
    if parts[0] == "players_sort":
        # التنسيق: players_sort_{manager_id}_{gameweek}_{sort_by}_{page}
        gameweek = int(parts[2])
        sort_by = parts[3]  # points, price, ownership
        page = int(parts[4]) if len(parts) > 4 else 0
        
        logger.info(f"📊 تغيير الترتيب إلى: {sort_by} للصفحة {page}")
        
        await context.bot.edit_message_text(
            text=f"🔄 جاري ترتيب اللاعبين حسب {sort_by}...",
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
        
        info = get_manager_info(manager_id)
        if not info:
            await context.bot.edit_message_text(
                text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
            )
            return
        
        # حساب عدد الصفحات
        all_players = get_all_players_data(sort_by)
        total_pages = (len(all_players) + 19) // 20  # 20 لاعب في الصفحة
        
        # التأكد من أن الصفحة الحالية ضمن النطاق
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
        text = format_players_display(manager_id, info, gameweek, page, sort_by)
        reply_markup = get_players_buttons(manager_id, gameweek, page, total_pages, sort_by)
        
        await context.bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            parse_mode='Markdown', reply_markup=reply_markup
        )
        return
    
    # ============================================================
    # معالجة زر اللاعبين (معدل)
    # ============================================================
    if parts[0] == "players":
        gameweek = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        sort_by = parts[4] if len(parts) > 4 else "points"  # استخراج نوع الترتيب
        
        await context.bot.edit_message_text(
            text=f"🔄 جاري تحميل قائمة اللاعبين - الصفحة {page + 1}...",
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
        
        info = get_manager_info(manager_id)
        if not info:
            await context.bot.edit_message_text(
                text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
            )
            return
        
        # حساب عدد الصفحات
        all_players = get_all_players_data(sort_by)
        total_pages = (len(all_players) + 19) // 20  # 20 لاعب في الصفحة
        
        # التأكد من أن الصفحة الحالية ضمن النطاق
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
        text = format_players_display(manager_id, info, gameweek, page, sort_by)
        reply_markup = get_players_buttons(manager_id, gameweek, page, total_pages, sort_by)
        
        await context.bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            parse_mode='Markdown', reply_markup=reply_markup
        )
        return
    
    # ============================================================
    # معالجة التنقل بين الجولات
    # ============================================================
    if parts[0] == "nav":
        gameweek = int(parts[2])
        current_text = query.message.text
        
        if "العرض المفصل" in current_text or "اللاعبون الأساسيون" in current_text:
            view_type = "detail"
        elif "الدوريات" in current_text:
            view_type = "leagues"
        elif "المباريات" in current_text or "نتائج" in current_text:
            view_type = "fixtures"
        elif "المواعيد" in current_text:
            view_type = "deadline"
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
        else:
            picks_data = get_manager_picks(manager_id, gameweek)
            history = get_manager_history(manager_id)
            text_map = {
                "simple": format_simple_display(manager_id, info, gameweek, picks_data, history),
                "detail": format_detailed_display(manager_id, info, gameweek, picks_data, history),
                "leagues": format_leagues_display(manager_id, info, gameweek, history),
                "fixtures": format_fixtures_display(manager_id, info, gameweek, history)
            }
            text = text_map.get(view_type, "")
        
        await context.bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            parse_mode='Markdown', reply_markup=get_buttons(manager_id, gameweek, view_type)
        )
        return
    
    # ============================================================
    # معالجة الأزرار الأخرى (simple, detail, leagues, fixtures, deadline)
    # ============================================================
    if parts[0] in ["simple", "detail", "leagues", "fixtures", "deadline"]:
        view_type = parts[0]
        gameweek = int(parts[2])
        
        loading_texts = {
            "simple": "العرض البسيط",
            "detail": "العرض المفصل",
            "leagues": "الدوريات والمواسم",
            "fixtures": "المباريات",
            "deadline": "مواعيد الجولة"
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
        else:
            picks_data = get_manager_picks(manager_id, gameweek)
            history = get_manager_history(manager_id)
            text_map = {
                "simple": format_simple_display(manager_id, info, gameweek, picks_data, history),
                "detail": format_detailed_display(manager_id, info, gameweek, picks_data, history),
                "leagues": format_leagues_display(manager_id, info, gameweek, history),
                "fixtures": format_fixtures_display(manager_id, info, gameweek, history)
            }
            text = text_map.get(view_type, "")
        
        await context.bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            parse_mode='Markdown', reply_markup=get_buttons(manager_id, gameweek, view_type)
        )
        return
    
    # ============================================================
    # إذا لم يطابق أي من الشروط السابقة
    # ============================================================
    logger.warning(f"⚠️ Callback غير معروف: {data}")
    await context.bot.edit_message_text(
        text="❌ حدث خطأ: أمر غير معروف. يرجى المحاولة مرة أخرى.",
        chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
    )


# ============================================================
# تشغيل البوت
# ============================================================

def get_all_players_data():
    """جلب جميع اللاعبين مع مراكزهم وأسعارهم ونقاطهم"""
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_all_players_data")
    players_list = []
    
    if data and "elements" in data:
        for player in data["elements"]:
            # تطبيق التعديلات اليدوية للمراكز من الموسم الجديد
            player_id = player["id"]
            if player_id in POSITION_OVERRIDES_26_27:
                new_pos, _ = POSITION_OVERRIDES_26_27[player_id]
                player["element_type"] = new_pos
            
            # تأكد من تحويل القيم إلى أرقام
            try:
                total_points = int(player.get("total_points", 0))
            except (ValueError, TypeError):
                total_points = 0
                
            try:
                price = float(player.get("now_cost", 0)) / 10
            except (ValueError, TypeError):
                price = 0.0
                
            try:
                selected_by = float(player.get("selected_by_percent", 0))
            except (ValueError, TypeError):
                selected_by = 0.0
                
            try:
                form = float(player.get("form", 0))
            except (ValueError, TypeError):
                form = 0.0
            
            players_list.append({
                "id": player["id"],
                "name": f"{player['first_name']} {player['second_name']}",
                "position": player.get("element_type", 0),
                "price": price,
                "total_points": total_points,
                "team": player.get("team", 0),
                "selected_by": selected_by,
                "form": form
            })
    
    # ترتيب اللاعبين حسب النقاط (تنازلي) - تأكد من أن total_points رقم
    players_list.sort(key=lambda x: x["total_points"] if isinstance(x["total_points"], (int, float)) else 0, reverse=True)
    logger.info(f"👥 تم تحميل {len(players_list)} لاعب مع بياناتهم الكاملة")
    return players_list
    
# ==========================================
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








