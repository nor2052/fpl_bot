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
        "Everton": "🍬", "Fulham": "🏁", "Ipswich Town": "🚜", "Leicester City": "🦊",
        "Liverpool": "🐦‍🔥", "Manchester City": "💎", "Manchester United": "🔱", "Newcastle United": "🐦‍⬛",
        "Nottingham Forest": "🎋", "Southampton": "⚪", "Tottenham Hotspur": "🐔", "West Ham United": "⚒️",
        "Wolverhampton Wanderers": "🐱", "Leeds United": "🦚", "Burnley": "🧱", "Sunderland": "🐈",
        "ARS": "🔫", "AVL": "🏰", "BOU": "🍒", "BRE": "🐝", "BHA": "🐦", "CHE": "🦁",
        "CRY": "🦅", "EVE": "🍬", "FUL": "🏁", "IPS": "🚜", "LEI": "🦊", "LIV": "🐦‍🔥",
        "MCI": "💎", "MUN": "🔱", "NEW": "🐦‍⬛", "NFO": "🎋", "SOU": "⚪", "TOT": "🐔",
        "WHU": "⚒️", "WOL": "🐱", "LEE": "🦚", "BUR": "🧱", "SUN": "🐈"
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
         InlineKeyboardButton("⚽ المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}"),
         InlineKeyboardButton("⏰ المواعيد", callback_data=f"deadline_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("⬅️ الجولة السابقة", callback_data=f"nav_{manager_id}_{prev_gw}"),
         InlineKeyboardButton("➡️ الجولة التالية", callback_data=f"nav_{manager_id}_{next_gw}")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    
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
            "✓ مواعيد الجولة (الديدلاين) 🕐\n"
            "🔑 **كيف تحصل على معرف مدرب؟**\n"
            "افتح موقع FPL، الرقم في الرابط:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📝 **مثال:** أرسل `2794801`",
            parse_mode='Markdown'
        )
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
    
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    parts = data.split("_")
    
    if len(parts) < 3:
        logger.warning(f"تنسيق غير صحيح للبيانات: {data}")
        return
    
    manager_id = context.user_data.get('current_manager_id')
    if not manager_id:
        try:
            manager_id = parts[1]
        except IndexError:
            await context.bot.edit_message_text(
                text="❌ حدث خطأ: يرجى إرسال معرف المدرب مرة أخرى باستخدام /start",
                chat_id=chat_id, message_id=message_id, parse_mode='Markdown'
            )
            return
    
    try:
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
        
        elif parts[0] in ["simple", "detail", "leagues", "fixtures", "deadline"]:
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
