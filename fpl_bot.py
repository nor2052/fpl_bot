import os
import logging
import calendar
from datetime import datetime, timezone, timedelta

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

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
    {"id": "@LFCREDS1", "name": "القناة الثالثة"},
]

ADMIN_IDS = [7095210809, 2046683919, 1401110823]  

USERS_SET = set()

LEAGUE_ID = 1185162
LEAGUE_JOIN_URL = "https://fantasy.premierleague.com/leagues/auto-join/wmvdke"

awaiting_ad_message = {}

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
            return False
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
            players[player["id"]] = {
                "web_name": player.get("web_name", f"{player.get('first_name', '')} {player.get('second_name', '')}"),
                "team": player.get("team"),
                "element_type": player.get("element_type")
            }
    logger.info(f"👥 تم تحميل {len(players)} لاعب")
    return players

def get_all_players_data(sort_by="points", team_id=None, position_id=None):
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

def get_gameweek_live_data(gameweek):
    url = f"https://fantasy.premierleague.com/api/event/{gameweek}/live/"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"خطأ في جلب live data للجولة {gameweek}: {e}")
    return {}

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
# دوال عرض المعلومات - المعدلة حسب كود fpl_bot
# ============================================================

def format_fdr_display(manager_id, info, start_gw):
    """تنسيق عرض صعوبة المباريات لـ 20 فريقاً لوليتين قادمتين مع إيموجي الفرق"""
    name = sanitize_markdown(safe_str(info.get("name")))
    
    # قاموس إيموجيز الفرق
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
    
    # 1. جلب بيانات الفرق والمباريات من الـ API
    bootstrap = safe_api_request(f"{BASE_URL}/bootstrap-static/", "fdr_bootstrap")
    fixtures = get_fixtures() or []
    
    if not bootstrap or "teams" not in bootstrap:
        return "❌ تعذر جلب بيانات صعوبة المباريات حالياً."
    
    teams = {t["id"]: t for t in bootstrap["teams"]}
    
    gw1 = start_gw
    gw2 = start_gw + 1 if start_gw < 38 else 38
    
    response = (
        f"📊 **صعوبة المباريات (FDR)**\n"
        f"👤 {name}\n"
        f"🗓 **الجولتان:** {gw1} - {gw2}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    fdr_emojis = {1: "🟢", 2: "🟢", 3: "⚪", 4: "🔴", 5: "🔴"}
    
    # 2. بناء بيانات كل فريق للجولتين
    for team_id, team_info in sorted(teams.items(), key=lambda x: x[1]["name"]):
        team_short = team_info.get("short_name", "???")
        team_name = team_info.get("name", "")
        # إحضار إيموجي الفريق الأساسي
        t_emoji = team_emojis.get(team_short) or team_emojis.get(team_name, "🛡️")
        
        gw1_matches = []
        gw2_matches = []
        
        for f in fixtures:
            event = f.get("event")
            if event == gw1:
                if f.get("team_h") == team_id:
                    opp_id = f.get("team_a")
                    opp_info = teams.get(opp_id, {})
                    opp_short = opp_info.get("short_name", "???")
                    opp_emoji = team_emojis.get(opp_short) or team_emojis.get(opp_info.get("name"), "")
                    diff = f.get("team_h_difficulty", 3)
                    gw1_matches.append(f"{opp_emoji}{opp_short}(H) {fdr_emojis.get(diff, '⚪')}{diff}")
                elif f.get("team_a") == team_id:
                    opp_id = f.get("team_h")
                    opp_info = teams.get(opp_id, {})
                    opp_short = opp_info.get("short_name", "???")
                    opp_emoji = team_emojis.get(opp_short) or team_emojis.get(opp_info.get("name"), "")
                    diff = f.get("team_a_difficulty", 3)
                    gw1_matches.append(f"{opp_emoji}{opp_short}(A) {fdr_emojis.get(diff, '⚪')}{diff}")
            
            elif event == gw2:
                if f.get("team_h") == team_id:
                    opp_id = f.get("team_a")
                    opp_info = teams.get(opp_id, {})
                    opp_short = opp_info.get("short_name", "???")
                    opp_emoji = team_emojis.get(opp_short) or team_emojis.get(opp_info.get("name"), "")
                    diff = f.get("team_h_difficulty", 3)
                    gw2_matches.append(f"{opp_emoji}{opp_short}(H) {fdr_emojis.get(diff, '⚪')}{diff}")
                elif f.get("team_a") == team_id:
                    opp_id = f.get("team_h")
                    opp_info = teams.get(opp_id, {})
                    opp_short = opp_info.get("short_name", "???")
                    opp_emoji = team_emojis.get(opp_short) or team_emojis.get(opp_info.get("name"), "")
                    diff = f.get("team_a_difficulty", 3)
                    gw2_matches.append(f"{opp_emoji}{opp_short}(A) {fdr_emojis.get(diff, '⚪')}{diff}")
        
        gw1_str = " | ".join(gw1_matches) if gw1_matches else "BLANK"
        gw2_str = " | ".join(gw2_matches) if gw2_matches else "BLANK"
        
        response += (
            f"{t_emoji} **{team_short}**\n"
            f"├ GW{gw1}: {gw1_str}\n"
            f"└ GW{gw2}: {gw2_str}\n\n"
        )
        
    return response
    

def format_detailed_display(manager_id, info, gameweek, picks_data, history):
    """عرض مبسط لمعلومات المدرب - مطابق لكود fpl_bot"""
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
    
    event_points = 0
    event_rank = 0
    transfers_made = 0
    transfers_cost = 0
    
    if picks_data and "picks" in picks_data:
        live_points_map = get_live_points(gameweek)
        active_chip = picks_data.get("active_chip")
        
        players_to_count = picks_data["picks"] if active_chip == "bboost" else picks_data["picks"][:11]
        for pick in players_to_count:
            player_id = pick.get("element")
            player_points = live_points_map.get(player_id, 0)
            multiplier = 3 if (pick.get("is_captain") and active_chip == "3xc") else (2 if pick.get("is_captain") else 1)
            event_points += player_points * multiplier
        
        if "entry_history" in picks_data:
            history_data = picks_data["entry_history"]
            transfers_made = safe_int(history_data.get("event_transfers", 0))
            transfers_cost = safe_int(history_data.get("event_transfers_cost", 0))
            event_rank = safe_int(history_data.get("rank", 0))
    
    event_points_after_hits = event_points - transfers_cost
    event_rank_str = f"{event_rank:,}" if event_rank > 0 else "غير مصنف"
    
    gw_stats = get_gameweek_stats(gameweek)
    avg_points = gw_stats["average_score"]
    
    rank_change_display = get_rank_change_display(manager_id, gameweek, history)
    
    response = (
        f"📊 **إحصائيات الجولة {gameweek}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐️ نقاط الجولة: **{event_points_after_hits}**\n"
        f"🌍 متوسط الجولة: **{avg_points}**\n"
        f"🏆 نقاط المدرب عمومًا: **{total_points:,}**\n"
        f"📈 الترتيب العالمي: **{rank_str}**{rank_change_display}\n"
        f"📊 ترتيب الجولة: **{event_rank_str}**\n"
        f"🔄 انتقالات الجولة: **{transfers_made}**" + (f" (-{transfers_cost})" if transfers_cost > 0 else "")
    )
    
    response += "\n\n🎭 **البطاقات:**\n"
    
    active_chip = picks_data.get("active_chip") if picks_data else None
    
    chips_info = {
        "3xc": {"name": "👑 TC", "display": "تثليث القائد"},
        "bboost": {"name": "💺 BB", "display": "تفعيل الدكة"},
        "freehit": {"name": "🃏 FH", "display": "ضربة الحظ"},
        "wildcard": {"name": "🛠 WC", "display": "بطاقة الوحش"}
    }
    
    used_chips = {}
    if history and "chips" in history:
        for chip in history["chips"]:
            chip_name = chip.get("name")
            chip_event = chip.get("event")
            if chip_name not in used_chips:
                used_chips[chip_name] = chip_event
    
    for chip_key, chip_info in chips_info.items():
        if active_chip == chip_key:
            response += f"{chip_info['name']} — تلعب الآن 🟢\n"
        elif chip_key in used_chips:
            response += f"{chip_info['name']} — الجولة {used_chips[chip_key]} 🔴\n"
        else:
            response += f"{chip_info['name']} — لم تُلعب 🟢\n"
    
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

def format_match_detail_display(fixture_id):
    all_fixtures = get_fixtures()
    fixture = next((f for f in all_fixtures if f.get("id") == fixture_id), None)

    if not fixture:
        return "❌ تعذر العثور على تفاصيل هذه المباراة."

    teams_dict = get_teams_dict()
    players_dict = get_players_dict()
    gameweek = fixture.get("event")

    team_h_id = fixture.get("team_h")
    team_a_id = fixture.get("team_a")

    team_h_info = teams_dict.get(team_h_id, {"short_name": "Home", "emoji_only": "⚪", "name": "Team A"})
    team_a_info = teams_dict.get(team_a_id, {"short_name": "Away", "emoji_only": "🔵", "name": "Team B"})

    score_h = fixture.get("team_h_score") if fixture.get("team_h_score") is not None else 0
    score_a = fixture.get("team_a_score") if fixture.get("team_a_score") is not None else 0

    live_data = get_gameweek_live_data(gameweek)

    raw_elements = live_data.get("elements", []) if isinstance(live_data, dict) else []

    elements_dict = {}
    if isinstance(raw_elements, list):
        for item in raw_elements:
            elements_dict[item.get("id")] = item
    elif isinstance(raw_elements, dict):
        elements_dict = raw_elements

    stats = fixture.get("stats", [])

    def extract_stat_map(stat_name):
        h_map, a_map = {}, {}
        for s in stats:
            if s.get("identifier") == stat_name:
                for item in s.get("h", []):
                    h_map[item["element"]] = item["value"]
                for item in s.get("a", []):
                    a_map[item["element"]] = item["value"]
        return h_map, a_map

    goals_h, goals_a = extract_stat_map("goals_scored")
    assists_h, assists_a = extract_stat_map("assists")
    yellow_h, yellow_a = extract_stat_map("yellow_cards")
    red_h, red_a = extract_stat_map("red_cards")
    bps_h, bps_a = extract_stat_map("bps")
    bonus_h, bonus_a = extract_stat_map("bonus")

    response = f"**{team_h_info.get('name', 'Team A')} {score_h} - {score_a} {team_a_info.get('name', 'Team B')}**\n\n\n"

    def generate_team_section(team_id, team_info, score, is_home):
        text = f"_-{team_info.get('emoji_only', '⚪')} {team_info.get('name', 'Team')}  {score}_\n"

        team_players = []
        for p_id, p_data in elements_dict.items():
            p_stats = p_data.get("stats", {})
            p_info = players_dict.get(p_id, {})
            p_team = p_info.get("team") if isinstance(p_info, dict) else None

            if p_team == team_id and p_stats.get("minutes", 0) > 0:
                team_players.append((p_id, p_stats))

        team_players.sort(key=lambda x: (x[1].get("minutes", 0), x[1].get("total_points", 0)), reverse=True)

        for p_id, p_stats in team_players:
            mins = p_stats.get("minutes", 0)
            pts = p_stats.get("total_points", 0)
            p_info = players_dict.get(p_id, {})
            p_name = p_info.get("web_name") if isinstance(p_info, dict) else f"Player {p_id}"

            icons = ""
            if isinstance(p_info, dict) and p_info.get("element_type") == 1:
                icons += " 🧤"
            if p_id in (goals_h if is_home else goals_a):
                icons += " ⚽️"
            if p_id in (yellow_h if is_home else yellow_a):
                icons += " 🟨"
            if p_id in (red_h if is_home else red_a):
                icons += " 🟥"
            if p_stats.get("defensive_contributions", 0) >= 10:
                icons += " 🛡"

            p_bonus = (bonus_h if is_home else bonus_a).get(p_id, 0)
            if p_bonus > 0:
                icons += " " + ("🎖" * p_bonus)

            text += f"{mins:2d}' {pts:2d} {p_name}{icons}\n"

        return text + "\n"

    response += generate_team_section(team_h_id, team_h_info, score_h, is_home=True)
    response += generate_team_section(team_a_id, team_a_info, score_a, is_home=False)

    all_xgi = []
    for p_id, p_data in elements_dict.items():
        p_info = players_dict.get(p_id, {})
        p_team = p_info.get("team") if isinstance(p_info, dict) else None
        if p_team in [team_h_id, team_a_id]:
            p_stats = p_data.get("stats", {})
            xg = float(p_stats.get("expected_goals", 0.0))
            xa = float(p_stats.get("expected_assists", 0.0))
            if xg + xa > 0:
                p_name = p_info.get("web_name", "لاعب") if isinstance(p_info, dict) else "لاعب"
                all_xgi.append((xg, xa, xg + xa, p_name))

    all_xgi.sort(key=lambda x: x[2], reverse=True)

    response += "**-Top xGI:**\n"
    for xg, xa, total, p_name in all_xgi[:10]:
        response += f"{xg:.2f} + {xa:.2f}  {p_name}\n"

    all_bps = []
    for p_id, val in bps_h.items():
        p_info = players_dict.get(p_id, {})
        p_name = p_info.get("web_name", "لاعب") if isinstance(p_info, dict) else "لاعب"
        all_bps.append((val, p_name))
    for p_id, val in bps_a.items():
        p_info = players_dict.get(p_id, {})
        p_name = p_info.get("web_name", "لاعب") if isinstance(p_info, dict) else "لاعب"
        all_bps.append((val, p_name))
    all_bps.sort(key=lambda x: x[0], reverse=True)

    response += "\n**-Top BPS:**\n"
    medals = ["🥇", "🥈", "🥉"]
    for idx, (val, p_name) in enumerate(all_bps[:10]):
        medal = f" {medals[idx]}" if idx < 3 else ""
        bonus_add = f" +{3-idx}" if idx < 3 else ""
        response += f"{val:2d} {p_name}{medal}{bonus_add}\n"

    all_defcon = []
    for p_id, p_data in elements_dict.items():
        p_info = players_dict.get(p_id, {})
        p_team = p_info.get("team") if isinstance(p_info, dict) else None
        if p_team in [team_h_id, team_a_id]:
            p_stats = p_data.get("stats", {})
            defcon_val = p_stats.get("defensive_contributions", 0)
            if defcon_val > 0:
                p_name = p_info.get("web_name", "لاعب") if isinstance(p_info, dict) else "لاعب"
                all_defcon.append((defcon_val, p_name))

    all_defcon.sort(key=lambda x: x[0], reverse=True)

    if all_defcon:
        response += "\n**Top DEFCON:**\n"
        for val, p_name in all_defcon[:10]:
            shield = " 🛡️ +2" if val >= 10 else ""
            response += f"{val:2d} {p_name}{shield}\n"

    return response
    
def format_fixtures_menu(gameweek):
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()

    return (
        f"⚽ **مباريات الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f" 🟢جارية 🔴 انتهت ⏳ لم تلعب بعد\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 **اختر المباراة لعرض التفاصيل الإحصائية الكاملة:**"
    )

def get_fixtures_keyboard(manager_id, gameweek):
    fixtures = get_fixtures(gameweek)
    teams_dict = get_teams_dict()
    keyboard = []

    if fixtures:
        for f in fixtures:
            f_id = f.get("id")
            team_h = teams_dict.get(f.get("team_h"), {}).get("short_name", "???")
            team_a = teams_dict.get(f.get("team_a"), {}).get("short_name", "???")

            score_h = f.get("team_h_score")
            score_a = f.get("team_a_score")

            finished = f.get("finished", False) or f.get("finished_provisional", False)
            started = f.get("started", False)

            if finished:
                status_emoji = "🔴"
            elif started and not finished:
                status_emoji = "🟢"
            else:
                status_emoji = "⏳"

            if score_h is not None and score_a is not None:
                match_label = f"{status_emoji} {team_h} {score_h} - {score_a} {team_a}"
            else:
                match_label = f"{status_emoji} {team_h} VS {team_a}"

            keyboard.append([InlineKeyboardButton(match_label, callback_data=f"match_{manager_id}_{gameweek}_{f_id}")])

    keyboard.append([InlineKeyboardButton("🔙 العودة للرئيسية", callback_data=f"detail_{manager_id}_{gameweek}")])
    return InlineKeyboardMarkup(keyboard)
    
# ============================================================
# دوال مواعيد الجولة - مطابقة لكود fpl_bot
# ============================================================

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
        f"📅 مواعيد الجولة {gameweek}\n"
        f"\n"
        f"🕐 آخر تحديث: {update_time_str} — {update_date_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 غلق الانتقالات: {deadline_display}\n"
        f"🎯 بداية الجولة: {first_match_display}\n"
        f"🏁 نهاية الجولة: {last_match_display}\n"
        f"\n"
        f"⏰ جميع الأوقات بتوقيت مكة المكرمة (UTC+3)"
    )
    return response

# ============================================================
# دوال الأزرار ومعالجات البوت - المعدلة
# ============================================================

def get_custom_league_standings(page=1):
    """جلب ترتيب الدوري الخاص بالبوت من الـ API"""
    url = f"{BASE_URL}/leagues-classic/{LEAGUE_ID}/standings/?page_standings={page}"
    return safe_api_request(url, "get_custom_league_standings")

def check_user_in_league(manager_id, league_id):
    """فحص مباشر ودقيق لمعرفة ما إذا كان المدرب منضماً للدوري المحدد"""
    url = f"{BASE_URL}/entry/{manager_id}/"
    data = safe_api_request(url, "check_user_in_league")
    
    if data and "leagues" in data and "classic" in data["leagues"]:
        classic_leagues = data["leagues"]["classic"]
        for league in classic_leagues:
            if str(league.get("id")) == str(league_id):
                return True, league # إرجاع True وبيانات الدوري الخاصة بالمدرب
    return False, None

def format_custom_league_display(manager_id, gameweek, page=1):
    """صياغة عرض دوري البوت بعد التحقق المباشر من بروفايل المدرب"""
    
    # 1. التحقق المباشر والدقيق من اشتراك المدرب في الدوري
    is_member, user_league_data = check_user_in_league(manager_id, LEAGUE_ID)

    # إذا كان غير مشترك حقاً
    if not is_member:
        response = (
            f"❌ **أنت غير مشترك في دوري البوت الخاص بنا!**\n\n"
            f"⚠️ يجب عليك الانضمام للدوري أولاً للحصول على كامل المعلومات والمنافسة.\n\n"
            f"🔗 **رابط الانضمام للدوري:**\n{LEAGUE_JOIN_URL}\n\n"
            f"🆔 **كود الدوري:** `wmvdke`\n\n"
            f"بعد الانضمام، اعد الضغط على زر '🏆 دوري البوت' لمشاهدة ترتيبك والإحصائيات."
        )
        return response, False, 1

    # 2. إذا كان مشتركاً، نجلب ترتيب الدوري للصفحة المطلوبة
    league_data = get_custom_league_standings(page=page)
    
    if not league_data or "standings" not in league_data:
        return "❌ تعذر جلب بيانات دوري البوت حالياً.", True, 1

    page_results = league_data["standings"].get("results", [])
    has_next = league_data["standings"].get("has_next", False)
    total_pages = page + 1 if has_next else page

    # استخراج بيانات المدرب في الدوري
    p_rank = user_league_data.get("entry_rank", 0)
    p_last_rank = user_league_data.get("entry_last_rank", 0)
    rank_change = get_league_change_display(p_rank, p_last_rank)
    
    # البحث عن أعلى مدرب نقاطاً بالجولة في الصفحة الحالية
    highest_gw_player = None
    max_gw_points = -1
    
    for p in page_results:
        event_total = safe_int(p.get("event_total", 0))
        if event_total > max_gw_points:
            max_gw_points = event_total
            highest_gw_player = p

    response = (
        f"🏆 **ترتيب دوري البوت**\n"
        f"📊 **الجولة {gameweek}** | الصفحة {page}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **بياناتك في الدوري:**\n"
        f"🥇 الترتيب: **#{p_rank}**{rank_change}\n"
        f"⚽ النقاط الكلية: **{user_league_data.get('entry_total', 0)}**\n"
        f"🔥 نقاط الجولة: **{user_league_data.get('entry_event_total', 0)}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if highest_gw_player:
        h_name = sanitize_markdown(safe_str(highest_gw_player.get("player_name")))
        h_entry = sanitize_markdown(safe_str(highest_gw_player.get("entry_name")))
        h_pts = highest_gw_player.get("event_total", 0)
        response += f"🌟 **أعلى مدرب نقاطاً بالجولة (في هذه الصفحة):** {h_entry} ({h_name}) - **{h_pts} نقطة**\n"
        response += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

    response += "👥 **قائمة لاعبي الدوري:**\n\n"

    for p in page_results: # عرض جميع لاعبي الصفحة الجاري جلبها من API الدوري
        rank = p.get("rank", 0)
        last_rank = p.get("last_rank", 0)
        change = get_league_change_display(rank, last_rank)
        
        player_name = sanitize_markdown(safe_str(p.get("player_name")))
        entry_name = sanitize_markdown(safe_str(p.get("entry_name")))
        event_pts = p.get("event_total", 0)
        total_pts = p.get("total", 0)

        response += (
            f"**{rank}. {entry_name}** ({player_name}){change}\n"
            f"    🎯 نقاط الجولة: **{event_pts}** | الإجمالي: **{total_pts}**\n\n"
        )

    return response, True, total_pages
    
def get_custom_league_keyboard(manager_id, gameweek, page, total_pages, is_member):
    """أزرار التحكم بصفحات دوري البوت"""
    keyboard = []
    
    if is_member:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"botleague_{manager_id}_{gameweek}_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"botleague_{manager_id}_{gameweek}_{page+1}"))
        if nav_buttons:
            keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"detail_{manager_id}_{gameweek}")])
    return InlineKeyboardMarkup(keyboard)
    
def get_fdr_keyboard(manager_id, gameweek):
    """أزرار الانتقال بين الجولات والعودة للقائمة الرئيسية لصفحة FDR"""
    prev_gw = gameweek - 1 if gameweek > 1 else 37
    next_gw = gameweek + 1 if gameweek < 37 else 1
    
    keyboard = [
        [
            InlineKeyboardButton("⬅️ القائمة السابقة", callback_data=f"fdr_{manager_id}_{prev_gw}"),
            InlineKeyboardButton("➡️ القائمة التالية", callback_data=f"fdr_{manager_id}_{next_gw}")
        ],
        [
            InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"detail_{manager_id}_{gameweek}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_buttons(manager_id, gameweek, current_view):
    """أزرار القائمة الرئيسية - معدلة لتشمل زر دوري البوت"""
    next_gw = get_next_gameweek(gameweek)
    prev_gw = get_previous_gameweek(gameweek)

    keyboard = [
        [InlineKeyboardButton("📊 عرض معلومات المدرب", callback_data=f"detail_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🏆 الدوريات", callback_data=f"leagues_{manager_id}_{gameweek}"),
         InlineKeyboardButton("⚽ المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🚨 بدء الجولة", callback_data=f"deadline_{manager_id}_{gameweek}"),
         InlineKeyboardButton("💰 أسعار اللاعبين", callback_data=f"price_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🆚 صعوبة المباريات", callback_data=f"fdr_{manager_id}_{gameweek}"),
         InlineKeyboardButton("👥 جميع اللاعبين", callback_data=f"players_{manager_id}_{gameweek}_0")],
        [InlineKeyboardButton("🤖 دوري البوت", callback_data=f"botleague_{manager_id}_{gameweek}_1")],
        [InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{prev_gw}"),
         InlineKeyboardButton("➡️ الجولة التالية", callback_data=f"nav_{manager_id}_{next_gw}")]
    ]
    return InlineKeyboardMarkup(keyboard)
    
def get_subscription_button():
    """إنشاء أزرار الانضمام للقنوات الإجبارية وزر التحقق"""
    keyboard = []
    for channel in CHANNELS:
        # إزالة علامة @ من معرف القناة لبناء رابط التليجرام
        channel_username = channel["id"].replace("@", "")
        keyboard.append([
            InlineKeyboardButton(
                f"📢 اشترك في {channel['name']}", 
                url=f"https://t.me/{channel_username}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("✅ تم الاشتراك - تحقق مرة أخرى", callback_data="check_subscription")
    ])
    
    return InlineKeyboardMarkup(keyboard)

# ============================================================
# دوال إدارة الأزرار - كود no butt مع تعديل العودة للـ detail
# ============================================================

async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ **عذراً، هذا الأمر متاح للأدمن فقط.**",
            parse_mode='Markdown'
        )
        return
    
    keyboard = [
        [
            InlineKeyboardButton("📊 إحصائيات المستخدمين", callback_data="admin_stats"),
            InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_ads")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    total_users = len(USERS_SET)
    current_time = datetime.now(timezone.utc) + timedelta(hours=3)
    time_str = current_time.strftime("%Y-%m-%d %I:%M %p").lstrip('0').lower()
    
    await update.message.reply_text(
        f"🔐 **لوحة تحكم المدير**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 المدير: {update.effective_user.first_name}\n"
        f"🆔 معرفك: `{user_id}`\n"
        f"👥 عدد المستخدمين: **{total_users}**\n"
        f"🕐 آخر تحديث: {time_str} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"اختر الإجراء المناسب:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if user_id not in ADMIN_IDS:
        await query.edit_message_text(
            "❌ **عذراً، هذا الإجراء متاح للأدمن فقط.**",
            parse_mode='Markdown'
        )
        return
    
    if data == "admin_stats":
        total_users = len(USERS_SET)
        current_time = datetime.now(timezone.utc) + timedelta(hours=3)
        time_str = current_time.strftime("%Y-%m-%d %I:%M %p").lstrip('0').lower()
        
        users_list = list(USERS_SET)
        users_preview = ""
        if users_list:
            preview_count = min(200, len(users_list))
            users_preview = "\n📋 **أول 200 مستخدم:**\n"
            for i, uid in enumerate(users_list[:preview_count], 1):
                users_preview += f"{i}. `{uid}`\n"
            if len(users_list) > 200:
                users_preview += f"... و {len(users_list) - 200} مستخدم آخر"
        
        message = f"""
📊 **إحصائيات المستخدمين**

👥 إجمالي المستخدمين: **{total_users}**

📅 آخر تحديث: {time_str} (توقيت مكة)

━━━━━━━━━━━━━━━━━━━━━
💡 يمكنك إرسال إعلان لكل هؤلاء المستخدمين
{users_preview}
"""
        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="admin_back")]
            ])
        )
        
    elif data == "admin_ads":
        keyboard = [
            [
                InlineKeyboardButton("📢 إرسال إعلان", callback_data="ad_send")
            ],
            [
                InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="admin_back")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📢 **إرسال إعلان للمستخدمين**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 عدد المستخدمين المستهدفين: **{len(USERS_SET)}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 **طريقة الإرسال:**\n"
            f"1️⃣ اضغط على زر '📢 إرسال إعلان'\n"
            f"2️⃣ أرسل النص الذي تريد نشره\n"
            f"3️⃣ سيتم إرساله لجميع المستخدمين\n\n",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif data == "ad_send":
        awaiting_ad_message[user_id] = "waiting_for_message"
        
        await query.edit_message_text(
            f"✍️ **أرسل نص الإعلان الآن**\n\n"
            f"👥 سيتم الإرسال لـ **{len(USERS_SET)}** مستخدم\n"
            f"🔹 لإلغاء الإرسال، أرسل /cancel",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إلغاء", callback_data="ad_cancel")]
            ])
        )
        
    elif data == "ad_cancel":
        if user_id in awaiting_ad_message:
            del awaiting_ad_message[user_id]
        
        keyboard = [
            [
                InlineKeyboardButton("📢 إرسال إعلان", callback_data="ad_send")
            ],
            [
                InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="admin_back")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ **تم إلغاء عملية الإعلان**\n\n"
            f"📢 **إرسال إعلان للمستخدمين**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 عدد المستخدمين المستهدفين: **{len(USERS_SET)}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 **طريقة الإرسال:**\n"
            f"1️⃣ اضغط على زر '📢 إرسال إعلان'\n"
            f"2️⃣ أرسل النص الذي تريد نشره\n"
            f"3️⃣ سيتم إرساله لجميع المستخدمين\n\n"
            f"🔹 لإلغاء الإرسال، أرسل /cancel",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif data == "admin_back":
        keyboard = [
            [
                InlineKeyboardButton("📊 إحصائيات المستخدمين", callback_data="admin_stats"),
                InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_ads")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        total_users = len(USERS_SET)
        current_time = datetime.now(timezone.utc) + timedelta(hours=3)
        time_str = current_time.strftime("%Y-%m-%d %I:%M %p").lstrip('0').lower()
        
        await query.edit_message_text(
            f"🔐 **لوحة تحكم المدير**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 المدير: {update.effective_user.first_name}\n"
            f"🆔 معرفك: `{user_id}`\n"
            f"👥 عدد المستخدمين: **{total_users}**\n"
            f"🕐 آخر تحديث: {time_str} (توقيت مكة)\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"اختر الإجراء المناسب:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def send_ad_to_users(context: ContextTypes.DEFAULT_TYPE, ad_text: str, user_ids: list, is_markdown: bool = True):
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            if is_markdown:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=ad_text,
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=ad_text
                )
            success_count += 1
        except Exception as e:
            fail_count += 1
            logger.error(f"فشل إرسال الإعلان للمستخدم {user_id}: {e}")
    
    return success_count, fail_count

async def handle_ad_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if user_id not in ADMIN_IDS:
        return
    
    if user_id not in awaiting_ad_message:
        return
    
    state = awaiting_ad_message[user_id]
    
    if message_text.lower() == "/cancel":
        del awaiting_ad_message[user_id]
        await update.message.reply_text(
            "✅ **تم إلغاء الإعلان**",
            parse_mode='Markdown'
        )
        raise ApplicationHandlerStop
    
    if state == "waiting_for_message":
        await update.message.reply_text(
            f"🔄 **جاري إرسال الإعلان للمستخدمين...**\n"
            f"👥 عدد المستخدمين: {len(USERS_SET)}\n"
            f"⏳ قد يستغرق هذا دقائق...",
            parse_mode='Markdown'
        )
        
        success, fail = await send_ad_to_users(
            context,
            message_text,
            list(USERS_SET),
            is_markdown=True
        )
        
        del awaiting_ad_message[user_id]
        
        report = f"""
✅ **تم إرسال الإعلان بنجاح!**

📊 **التقرير:**
• تم الإرسال لـ: **{success}** مستخدم
• فشل الإرسال لـ: **{fail}** مستخدم
• إجمالي المستخدمين: **{len(USERS_SET)}**

📝 **نص الإعلان:**
{message_text[:200]}{'...' if len(message_text) > 200 else ''}
"""
        await update.message.reply_text(report, parse_mode='Markdown')
        raise ApplicationHandlerStop

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    message_text = update.message.text.strip()
    user_id = update.effective_user.id

    if user_id in ADMIN_IDS and user_id in awaiting_ad_message:
        logger.info(f"⏭️ تم تجاهل رسالة من الأدمن {user_id} - في حالة انتظار إعلان")
        return

    if user_id not in USERS_SET:
        USERS_SET.add(user_id)
        logger.info(f"👤 مستخدم جديد: {user_id} - إجمالي المستخدمين: {len(USERS_SET)}")
    
    try:
        is_subscribed = await check_subscription(context, user_id)
    except Exception as e:
        logger.error(f"خطأ أثناء فحص الاشتراك للمستخدم {user_id}: {e}")
        is_subscribed = False

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

    if message_text.startswith(('/start', '/help')):
        welcome_text = (
            "✨ **مرحباً بك في بوت مساعد الفانتاسي!** ✨\n\n"
            "🎮 **كيف يعمل البوت؟**\n"
            "• أرسل **رقم معرف المدرب** الخاص بك\n"
            "• سأعرض لك إحصائيات الجولة الحالية فوراً\n\n"
            "📊 **ماذا يمكنك معرفة؟**\n"
            "✓ نقاط الجولة والنقاط الكلية والترتيب العالمي\n"
            "✓ تفاصيل أداء كل لاعب في الفريق\n"
            "✓ نقاط القائد والبدلاء\n"
            "✓ قيمة الفريق والرصيد البنكي 💰\n"
            "✓ ترتيبك في الدوريات المختلفة\n"
            "✓ تاريخ المواسم السابقة\n"
            "✓ نتائج المباريات وتفاصيلها ⚽\n"
            "✓ مواعيد الديدلاين والانتقالات ⏰\n\n"
            "🔑 **كيف تحصل على معرف المدرب؟**\n"
            "افتح موقع FPL، الرقم في رابط حسابك:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📝 **جرب الآن:** أرسل `2794801`"
        )
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        return

    try:
        manager_id = int(message_text)
        context.user_data['current_manager_id'] = manager_id
    except ValueError:
        await update.message.reply_text(
            "❌ يرجى إرسال **رقم معرف المدرب** فقط.\nمثال: `1234567`\nأو أرسل /help للمساعدة",
            parse_mode='Markdown'
        )
        return

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
    text = format_detailed_display(manager_id, info, start_gameweek, picks_data, history)
    reply_markup = get_buttons(manager_id, start_gameweek, "detail")

    try:
        await msg_checking.delete()
        await msg_loading.delete()
    except Exception as e:
        logger.warning(f"فشل حذف الرسائل المؤقتة: {e}")

    await update.message.reply_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

# ============================================================
# دوال عرض اللاعبين - كما في no butt
# ============================================================

def get_teams_keyboard(manager_id, gameweek):
    teams_dict = get_teams_dict()
    keyboard = []
    row = []

    for team_id, t_info in sorted(teams_dict.items()):
        btn_text = f"{t_info['emoji_only']} {t_info['short_name']}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"teamview_{manager_id}_{gameweek}_{team_id}_points"))
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 العودة لقائمة اللاعبين", callback_data=f"players_{manager_id}_{gameweek}_points_0")])
    return InlineKeyboardMarkup(keyboard)

def get_team_players_buttons(manager_id, gameweek, team_id, sort_by):
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
    keyboard = []

    def btn(label, key):
        icon = "✅ " if sort_by == key else ""
        return InlineKeyboardButton(f"{icon}{label}", callback_data=f"posview_{manager_id}_{gameweek}_{pos_id}_{key}_0")

    if pos_id == 4:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("الأهداف ⚽", "goals")])
        keyboard.append([btn("الأسيستات 🅰️", "assists")])

    elif pos_id == 3:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("الأهداف ⚽", "goals")])
        keyboard.append([btn("الأسيستات 🅰️", "assists"), btn("مساهمات دفاعية 🧱", "defcontrib")])

    elif pos_id == 2:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("الأهداف ⚽", "goals")])
        keyboard.append([btn("الأسيستات 🅰️", "assists"), btn("كلين شيت 🛡️", "cleansheets")])
        keyboard.append([btn("مساهمات دفاعية 🧱", "defcontrib")])

    elif pos_id == 1:
        keyboard.append([btn("النقاط 🏆", "points"), btn("السعر 💰", "price")])
        keyboard.append([btn("الملكية 📊", "selected"), btn("كلين شيت 🛡️", "cleansheets")])
        keyboard.append([btn("التصديات 🧤", "saves")])

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

def format_players_display(manager_id, info, gameweek, sort_by="points", page=0):
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

    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"detail_{manager_id}_{gameweek}")])

    return InlineKeyboardMarkup(keyboard)

def calculate_dynamic_threshold(player):
    """حساب العتبة المطلوبة لتغير السعر بناءً على الملكية والإصابات"""
    try:
        ownership_pct = float(player.get("selected_by_percent", "0.1"))
    except (ValueError, TypeError):
        ownership_pct = 0.1

    status = player.get("status", "a")
    factor = 2.0 if status in ['i', 's', 'u'] else 1.0

    return max(5000.0, ownership_pct * 1200.0) * factor


def calculate_price_transfers(player):
    """حساب صافي الشراء والبيع المباشر للاعب خلال الجولة"""
    transfers_in = safe_int(player.get("transfers_in_event", 0))
    transfers_out = safe_int(player.get("transfers_out_event", 0))
    net_transfers = transfers_in - transfers_out
    return net_transfers


def format_price_changes_display(manager_id, info, gameweek):
    name = sanitize_markdown(safe_str(info.get("name")))
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_price_changes")

    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")

    if not data or "elements" not in data:
        return "❌ حدث خطأ أثناء جلب بيانات الأسعار."

    elements = data["elements"]

    # جلب التغيرات الفعلية للأيام الأخيرة
    actual_risen_all = [p for p in elements if safe_int(p.get("cost_change_event", 0)) > 0]
    actual_fallen_all = [p for p in elements if safe_int(p.get("cost_change_event", 0)) < 0]

    actual_risen = sorted(actual_risen_all, key=lambda x: x.get("cost_change_event", 0), reverse=True)[:5]
    actual_fallen = sorted(actual_fallen_all, key=lambda x: x.get("cost_change_event", 0))[:5]

    # تجهيز قائمة التوقعات بناءً على صافي حركة الانتقالات
    players_list = []
    for p in elements:
        net_transfers = calculate_price_transfers(p)
        p_name = sanitize_markdown(f"{p.get('first_name', '')} {p.get('second_name', '')}".strip())
        price = safe_int(p.get("now_cost", 0)) / 10.0
        ownership = safe_str(p.get("selected_by_percent", "0.0"))

        players_list.append({
            "name": p_name,
            "price": price,
            "ownership": ownership,
            "net_transfers": net_transfers
        })

    # أكثر 5 لاعبين شراءً (متوقع ارتفاعهم)
    predicted_rise = sorted(players_list, key=lambda x: x["net_transfers"], reverse=True)[:5]
    # أكثر 5 لاعبين بيعاً (متوقع انخفاضهم)
    predicted_fall = sorted(players_list, key=lambda x: x["net_transfers"])[:5]

    response = (
        f"📈 **تغيرات وتوقعات أسعار اللاعبين**\n"
        f"👤 {name}\n"
        f"📊 **الجولة {gameweek}**\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    response += "🚀 **أكثر 5 لاعبين متوقع ارتفاعهم:**\n"
    for idx, p in enumerate(predicted_rise, 1):
        net_buy = max(0, p['net_transfers'])
        response += (
            f"{idx}. **{p['name']}**\n"
            f"   💰 السعر: £{p['price']:.1f}m | 📊 الملكية: {p['ownership']}% | 📈 صافي الشراء: {net_buy}\n"
        )
    response += "\n"

    response += "🔻 **أكثر 5 لاعبين متوقع انخفاضهم:**\n"
    for idx, p in enumerate(predicted_fall, 1):
        net_sell = abs(min(0, p['net_transfers']))
        response += (
            f"{idx}. **{p['name']}**\n"
            f"   💰 السعر: £{p['price']:.1f}m | 📊 الملكية: {p['ownership']}% | 📉 صافي البيع: {net_sell}\n"
        )
    response += "\n━━━━━━━━━━━━━━━━━━━━━\n\n"

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

    response += "🔴 **آخر 5 لاعبين انخفض سعرهم:**\n"
    if actual_fallen:
        for idx, p in enumerate(actual_fallen, 1):
            p_name = sanitize_markdown(f"{p.get('first_name', '')} {p.get('second_name', '')}".strip())
            price = safe_int(p.get("now_cost", 0)) / 10.0
            ownership = safe_str(p.get("selected_by_percent", "0.0"))
            response += f"{idx}. **{p_name}** | 💰 السعر: £{price:.1f}m | 📊 الملكية: {ownership}%\n"
    else:
        response += "لا يوجد انخفاضات في الأسعار مؤخراً\n"

    response += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += "صافي الشراء = عدد عمليات الشراء - عدد عمليات البيع\n"
    response += "صافي البيع = عدد عمليات البيع - عدد عمليات الشراء"

    return response
    
# ============================================================
# معالج الأزرار (Callback) المعدل
# ============================================================
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

    if data.startswith("admin_") or data.startswith("ad_"):
        await handle_admin_callback(update, context)
        return

    if parts[0] == "check":
        logger.info(f"✅ تم الضغط على زر التحقق للمستخدم {user_id}")
        is_subscribed = await check_subscription(context, user_id)

        if is_subscribed:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                logger.error(f"فشل في حذف رسالة الاشتراك: {e}")

            welcome_text = (
                "✨ **مرحباً بك في بوت مساعد الفانتاسي!** ✨\n\n"
                "🎮 **كيف يعمل البوت؟**\n"
                "• أرسل **رقم معرف المدرب** الخاص بك\n"
                "• سأعرض لك إحصائيات الجولة الحالية فوراً\n\n"
                "📊 **ماذا يمكنك معرفة؟**\n"
                "✓ نقاط الجولة والنقاط الكلية والترتيب العالمي\n"
                "✓ تفاصيل أداء كل لاعب في الفريق\n"
                "✓ نقاط القائد والبدلاء\n"
                "✓ قيمة الفريق والرصيد البنكي 💰\n"
                "✓ ترتيبك في الدوريات المختلفة ودوري البوت 🏆\n"
                "✓ تاريخ المواسم السابقة\n"
                "✓ نتائج المباريات وتفاصيلها ⚽\n"
                "✓ مواعيد الديدلاين والانتقالات ⏰\n\n"
                "🔑 **كيف تحصل على معرف المدرب؟**\n"
                "افتح موقع FPL، الرقم في رابط حسابك:\n"
                "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
                "📝 **جرب الآن:** أرسل `2794801`"
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
        if parts[0] == "botleague":
            gameweek = int(parts[2])
            page = int(parts[3]) if len(parts) > 3 else 1

            await context.bot.edit_message_text(
                text="🔄 جاري التحقق من الاشتراك وتحميل بيانات دوري البوت...",
                chat_id=chat_id, message_id=message_id
            )

            text, is_member, total_pages = format_custom_league_display(manager_id, gameweek, page)
            reply_markup = get_custom_league_keyboard(manager_id, gameweek, page, total_pages, is_member)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            return

        elif parts[0] == "poslist":
            gameweek = int(parts[2])
            await context.bot.edit_message_text(
                text="🎯 **اختر المركز المطلوب لعرض لاعبيه:**",
                chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown',
                reply_markup=get_positions_keyboard(manager_id, gameweek)
            )
            return

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

        elif parts[0] == "teamslist":
            gameweek = int(parts[2])
            await context.bot.edit_message_text(
                text="🏢 **اختر الفريق لعرض لاعبيه:**",
                chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown',
                reply_markup=get_teams_keyboard(manager_id, gameweek)
            )
            return

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

        elif parts[0] == "fixtures":
            gameweek = int(parts[2])
            text = format_fixtures_menu(gameweek)
            reply_markup = get_fixtures_keyboard(manager_id, gameweek)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return

        elif parts[0] == "match":
            gameweek = int(parts[2])
            fixture_id = int(parts[3])

            await context.bot.edit_message_text(
                text="🔄 جاري تحميل تفاصيل المباراة...",
                chat_id=chat_id, message_id=message_id
            )

            text = format_match_detail_display(fixture_id)

            match_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 العودة لقائمة المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
                [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data=f"detail_{manager_id}_{gameweek}")]
            ])

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=match_keyboard
            )
            return

        elif parts[0] == "fdr":
            gameweek = int(parts[2])
            
            await context.bot.edit_message_text(
                text=f"🔄 جاري تحميل جدول صعوبة المباريات للجولتين {gameweek} و {gameweek+1}...",
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )

            info = get_manager_info(manager_id)
            if not info:
                await context.bot.edit_message_text(
                    text=f"❌ لم أتمكن من العثور على مدرب بالمعرف `{manager_id}`.",
                    chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
                )
                return

            text = format_fdr_display(manager_id, info, gameweek)
            reply_markup = get_fdr_keyboard(manager_id, gameweek)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=reply_markup
            )
            return

        elif parts[0] == "nav":
            gameweek = int(parts[2])
            current_text = query.message.text or ""

            if "الدوريات" in current_text:
                view_type = "leagues"
            elif "مباريات الجولة" in current_text or "اختر المباراة" in current_text:
                view_type = "fixtures"
            elif "مواعيد" in current_text:
                view_type = "deadline"
            elif "تغيرات وتوقعات" in current_text:
                view_type = "price"
            elif "صعوبة المباريات" in current_text:
                view_type = "fdr"
            else:
                view_type = "detail"

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

            if view_type == "fdr":
                text = format_fdr_display(manager_id, info, gameweek)
                reply_markup = get_fdr_keyboard(manager_id, gameweek)
                await context.bot.edit_message_text(
                    text=text, chat_id=chat_id, message_id=message_id,
                    parse_mode='Markdown', reply_markup=reply_markup
                )
                return
            elif view_type == "deadline":
                text = format_deadline_display(manager_id, info, gameweek)
            elif view_type == "price":
                text = format_price_changes_display(manager_id, info, gameweek)
            elif view_type == "fixtures":
                text = format_fixtures_menu(gameweek)
                reply_markup = get_fixtures_keyboard(manager_id, gameweek)
                await context.bot.edit_message_text(
                    text=text, chat_id=chat_id, message_id=message_id,
                    parse_mode='Markdown', reply_markup=reply_markup
                )
                return
            elif view_type == "leagues":
                history = get_manager_history(manager_id)
                text = format_leagues_display(manager_id, info, gameweek, history)
            else:
                picks_data = get_manager_picks(manager_id, gameweek)
                history = get_manager_history(manager_id)
                text = format_detailed_display(manager_id, info, gameweek, picks_data, history)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=get_buttons(manager_id, gameweek, view_type)
            )
            return

        elif parts[0] in ["detail", "leagues", "deadline", "price", "fdr"]:
            view_type = parts[0]
            gameweek = int(parts[2])

            loading_texts = {
                "detail": "عرض معلومات المدرب",
                "leagues": "الدوريات والمواسم",
                "deadline": "مواعيد الجولة",
                "price": "توقعات وتغيرات الأسعار",
                "fdr": "جدول صعوبة المباريات"
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

            if view_type == "fdr":
                text = format_fdr_display(manager_id, info, gameweek)
                reply_markup = get_fdr_keyboard(manager_id, gameweek)
                await context.bot.edit_message_text(
                    text=text, chat_id=chat_id, message_id=message_id,
                    parse_mode='Markdown', reply_markup=reply_markup
                )
                return
            elif view_type == "deadline":
                text = format_deadline_display(manager_id, info, gameweek)
            elif view_type == "price":
                text = format_price_changes_display(manager_id, info, gameweek)
            elif view_type == "leagues":
                history = get_manager_history(manager_id)
                text = format_leagues_display(manager_id, info, gameweek, history)
            else:
                picks_data = get_manager_picks(manager_id, gameweek)
                history = get_manager_history(manager_id)
                text = format_detailed_display(manager_id, info, gameweek, picks_data, history)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=get_buttons(manager_id, gameweek, view_type)
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
    application.add_handler(CommandHandler("admin", handle_admin_command))
    
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ad_message),
        group=1
    )
    
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        group=2
    )
    
    application.add_handler(CallbackQueryHandler(handle_callback))

    print("=" * 50)
    print("🤖 البوت يعمل الآن (نسخة معدلة - عرض واحد فقط + مواعيد الجولة)")
    print(f"📅 آخر جولة لعبت: {current_gameweek}")
    print("✅ المميزات:")
    print("   • عرض معلومات المدرب (بدون عرض بسيط)")
    print("   • دعم البنش بوست والتربل كابتن")
    print("   • حالة البطاقات مع تقسيم الموسم لنصفين")
    print("   • عرض المباريات بنتائج وتفاصيل")
    print("   • مواعيد الجولة (الديدلاين) ⏰")
    print("   • توقيت مكة المكرمة حصراً")
    print("   • نظام الاشتراك الإجباري في القنوات")
    print("📡 أرسل معرف مدرب للبدء")
    print("=" * 50)

    application.run_polling()

if __name__ == '__main__':
    main()
