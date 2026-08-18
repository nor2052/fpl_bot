import os
import logging
import json
import calendar
from datetime import datetime, timezone, timedelta
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.ext import ApplicationHandlerStop

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

ADMIN_IDS = [7095210809, 2046683919, 1401110823]  

LEAGUE_ID = "1185162"  # ضع هنا معرف الدوري الخاص بك
LEAGUE_NAME = "Han bot league"  # اسم الدوري للعرض

USERS_FILE = "users_data.json"

def load_users():
    """تحميل المستخدمين من الملف"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.get('users', []))
        except Exception as e:
            logger.error(f"خطأ في تحميل المستخدمين: {e}")
    return set()

def save_users():
    """حفظ المستخدمين في الملف"""
    try:
        data = {
            'users': list(USERS_SET),
            'total': len(USERS_SET),
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ المستخدمين: {e}")
        return False

# تحميل المستخدمين عند بدء التشغيل
USERS_SET = load_users()
logger.info(f"✅ تم تحميل {len(USERS_SET)} مستخدم من الملف")

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


def get_team_difficulty_fixtures(team_id, fixtures_data, start_gw=None, match_count=2):
    """الحصول على مباريات فريق معين مع صعوبتها"""
    team_fixtures = []
    for f in fixtures_data:
        if f.get("team_h") == team_id or f.get("team_a") == team_id:
            opponent_id = f.get("team_a") if f.get("team_h") == team_id else f.get("team_h")
            is_home = f.get("team_h") == team_id
            difficulty = f.get("difficulty", 3)
            gw = f.get("event")
            
            # تصفية حسب الجولة البداية
            if start_gw and gw < start_gw:
                continue
            
            team_fixtures.append({
                "gameweek": gw,
                "opponent_id": opponent_id,
                "is_home": is_home,
                "difficulty": difficulty,
                "fixture_id": f.get("id")
            })
    
    # ترتيب حسب الجولة
    team_fixtures = sorted(team_fixtures, key=lambda x: x["gameweek"])
    
    # إرجاع عدد المباريات المطلوب
    return team_fixtures[:match_count]
    
def format_fdr_display(page=0, per_page=2):
    """عرض صعوبة المباريات مع تنقل بين الصفحات"""
    # جلب البيانات
    bootstrap_data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_bootstrap_fdr")
    fixtures = get_fixtures()
    teams_dict = get_teams_dict()
    
    if not bootstrap_data or not fixtures:
        return "❌ حدث خطأ في جلب البيانات", 0, 0
    
    # الحصول على الجولة الحالية
    current_gw = get_current_gameweek()
    
    # الحصول على جميع الجولات المتاحة للمباريات
    all_gws = sorted(set([f.get("event") for f in fixtures if f.get("event") and f.get("event") >= current_gw]))
    
    if not all_gws:
        return "❌ لا توجد مباريات قادمة", 0, 0
    
    # حساب عدد الصفحات (كل صفحة = مباراتين لكل فريق)
    total_pages = (len(all_gws) + per_page - 1) // per_page
    
    # تحديد الجولات المطلوب عرضها في هذه الصفحة
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(all_gws))
    display_gws = all_gws[start_idx:end_idx]
    
    if not display_gws:
        return "❌ لا توجد مباريات في هذه الصفحة", 0, 0
    
    # تصفية المباريات للجولات المحددة
    upcoming_fixtures = [f for f in fixtures if f.get("event") in display_gws]
    
    # ترتيب الفرق حسب الاسم
    sorted_teams = sorted(teams_dict.items(), key=lambda x: x[1]["name"])
    
    # بناء العرض
    response = "📊 **جدول صعوبة المباريات (FDR)**\n"
    response += f"📅 الجولات {display_gws[0]} - {display_gws[-1]}\n"
    response += f"📖 الصفحة {page + 1} من {total_pages}\n"
    response += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    response += "🔴 صعب | 🟡 متوسط | 🟢 سهل\n"
    response += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # عرض كل فريق مع مبارياته
    for team_id, team_info in sorted_teams:
        team_name = team_info["short_name"]
        team_emoji = team_info["emoji_only"]
        
        # الحصول على مباريات الفريق للجولات المحددة
        team_fixtures = get_team_difficulty_fixtures(team_id, upcoming_fixtures, start_gw=display_gws[0], match_count=per_page)
        
        if not team_fixtures:
            continue
        
        # بناء سطر الفريق
        line = f"{team_emoji} **{team_name}** | "
        
        for match in team_fixtures:
            gw = match["gameweek"]
            diff = match["difficulty"]
            home_away = "🏠" if match["is_home"] else "✈️"
            
            # تحديد لون الصعوبة
            if diff <= 2:
                color = "🟢"
            elif diff == 3:
                color = "🟡"
            else:
                color = "🔴"
            
            line += f"{color}{home_away}{gw} "
        
        response += line + "\n"
    
    # إضافة إحصائيات سريعة
    response += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    response += f"📊 عدد الفرق: {len(sorted_teams)}\n"
    response += f"📅 إجمالي الجولات القادمة: {len(all_gws)}"
    
    return response, total_pages, page

def get_fdr_keyboard(page=0, total_pages=1):
    """أزرار التنقل في FDR"""
    keyboard = []
    
    # أزرار التنقل
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"fdr_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"fdr_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # زر العودة للرئيسية
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="fdr_back")])
    
    return InlineKeyboardMarkup(keyboard)    

def get_h2h_league_standings(league_id, page=1):
    """جلب ترتيب الدوري بنظام الكأس (Head-to-Head)"""
    url = f"{BASE_URL}/en/leagues-h2h/{league_id}/standings"
    if page > 1:
        url += f"?page={page}"
    
    data = safe_api_request(url, "get_h2h_league_standings")
    
    if data and "standings" in data:
        return data
    return None

def get_all_h2h_league_entries(league_id):
    """جلب جميع المشاركين في دوري الكأس (مع الصفحات)"""
    all_entries = []
    page = 1
    
    while True:
        data = get_h2h_league_standings(league_id, page)
        if not data or "standings" not in data:
            break
        
        results = data["standings"].get("results", [])
        if not results:
            break
        
        all_entries.extend(results)
        
        # التحقق من وجود صفحة تالية
        if not data["standings"].get("has_next", False):
            break
        
        page += 1
    
    return all_entries

def get_h2h_league_matches(league_id, page=1):
    """جلب مباريات دوري الكأس"""
    url = f"{BASE_URL}/leagues-h2h/{league_id}/matches"
    if page > 1:
        url += f"?page={page}"
    
    data = safe_api_request(url, "get_h2h_league_matches")
    
    if data and "matches" in data:
        return data
    return None

def format_h2h_entry(entry, index, gameweek):
    """تنسيق عرض مشارك واحد في دوري الكأس"""
    manager_name = sanitize_markdown(entry.get("entry_name", "غير معروف"))
    player_name = sanitize_markdown(entry.get("player_name", "غير معروف"))
    
    # النقاط
    total_points = entry.get("total", 0)
    event_points = entry.get("event_total", 0)
    
    # الترتيب
    rank = entry.get("rank", 0)
    last_rank = entry.get("last_rank", 0)
    
    # نقاط الكأس (Head-to-Head)
    h2h_points = entry.get("h2h_points", 0)
    h2h_wins = entry.get("h2h_wins", 0)
    h2h_draws = entry.get("h2h_draws", 0)
    h2h_losses = entry.get("h2h_losses", 0)
    
    # تغير الترتيب
    rank_change = ""
    if last_rank > 0 and rank > 0:
        diff = last_rank - rank
        if diff > 0:
            rank_change = f"🚀 +{diff}"
        elif diff < 0:
            rank_change = f"🔻 {diff}"
        else:
            rank_change = "➖"
    
    # معرف المدرب
    entry_id = entry.get("entry", 0)
    
    # تنسيق العرض
    response = (
        f"**{index}.** {manager_name}\n"
        f"   👤 {player_name} | 🆔 `{entry_id}`\n"
        f"   📊 نقاط الجولة: **{event_points}** | 🏆 نقاط الموسم: **{total_points}**\n"
        f"   📈 الترتيب: **{rank}** {rank_change}\n"
        f"   🏅 كأس الدوري: **{h2h_points}** نقطة (فوز {h2h_wins} - تعادل {h2h_draws} - خسارة {h2h_losses})\n"
    )
    
    return response

def format_h2h_league_display(league_id, page=1, per_page=10, manager_id=None):
    """تنسيق عرض ترتيب دوري الكأس"""
    # جلب البيانات
    data = get_h2h_league_standings(league_id, page)
    
    if not data or "standings" not in data:
        return "❌ حدث خطأ في جلب بيانات دوري الكأس", None
    
    standings = data["standings"]
    entries = standings.get("results", [])
    total_entries = standings.get("total", 0)
    total_pages = (total_entries + per_page - 1) // per_page
    
    # اسم الدوري
    league_name = standings.get("league", {}).get("name", "كأس الدوري")
    
    # تاريخ التحديث
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")
    
    # بناء النص
    response = (
        f"🏆 **{league_name}** (نظام الكأس)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 الصفحة {page} من {total_pages}\n"
        f"👥 عدد المشاركين: {total_entries}\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not entries:
        response += "🚫 لا يوجد مشاركين في هذه الصفحة\n"
        return response, None
    
    # عرض المشاركين
    start_index = (page - 1) * per_page + 1
    for idx, entry in enumerate(entries, start=start_index):
        response += format_h2h_entry(entry, idx, get_current_gameweek())
        response += "\n"
    
    # إحصائيات سريعة
    if entries:
        top_score = max([e.get("event_total", 0) for e in entries])
        top_name = max(entries, key=lambda x: x.get("event_total", 0)).get("entry_name", "")
        top_h2h = max([e.get("h2h_points", 0) for e in entries])
        top_h2h_name = max(entries, key=lambda x: x.get("h2h_points", 0)).get("entry_name", "")
        
        response += f"━━━━━━━━━━━━━━━━━━━━━\n"
        response += f"⚡ أعلى نقاط في الجولة: **{top_score}** نقطة ({top_name})\n"
        response += f"🏅 أعلى نقاط في الكأس: **{top_h2h}** نقطة ({top_h2h_name})\n"
    
    return response, total_pages

def get_league_standings(league_id, page=1):
    """جلب ترتيب الدوري مع دعم الصفحات"""
    url = f"{BASE_URL}/leagues-classic/{league_id}/standings"
    if page > 1:
        url += f"?page={page}"
    
    data = safe_api_request(url, "get_league_standings")
    
    if data and "standings" in data:
        return data
    return None

def get_all_league_entries(league_id):
    """جلب جميع المشاركين في الدوري (مع الصفحات)"""
    all_entries = []
    page = 1
    
    while True:
        data = get_league_standings(league_id, page)
        if not data or "standings" not in data:
            break
        
        results = data["standings"].get("results", [])
        if not results:
            break
        
        all_entries.extend(results)
        
        # التحقق من وجود صفحة تالية
        if not data["standings"].get("has_next", False):
            break
        
        page += 1
    
    return all_entries

def get_league_rank_change(entry, previous_rank=None):
    """حساب تغير الترتيب في الدوري"""
    current_rank = entry.get("rank", 0)
    
    if previous_rank and previous_rank > 0 and current_rank > 0:
        diff = previous_rank - current_rank
        if diff > 0:
            return f"🚀 +{diff}"
        elif diff < 0:
            return f"🔻 {diff}"
    return "➖"

def format_league_entry(entry, index, gameweek, show_change=True):
    """تنسيق عرض مشارك واحد في الدوري"""
    manager_name = sanitize_markdown(entry.get("entry_name", "غير معروف"))
    player_name = sanitize_markdown(entry.get("player_name", "غير معروف"))
    
    # النقاط
    total_points = entry.get("total", 0)
    event_points = entry.get("event_total", 0)
    
    # الترتيب
    rank = entry.get("rank", 0)
    last_rank = entry.get("last_rank", 0)
    
    # الحصول على تغير الترتيب
    rank_change = ""
    if show_change and last_rank > 0:
        rank_change = get_league_rank_change(entry, last_rank)
    
    # معرف المدرب
    entry_id = entry.get("entry", 0)
    
    # تنسيق العرض
    response = (
        f"**{index}.** {manager_name}\n"
        f"   👤 {player_name} | 🆔 `{entry_id}`\n"
        f"   📊 نقاط الجولة: **{event_points}** | 🏆 نقاط الموسم: **{total_points}**\n"
        f"   📈 الترتيب: **{rank}** {rank_change}\n"
    )
    
    return response
    
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
# دوال عرض المعلومات
# ============================================================


async def match_diff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض صعوبة المباريات القادمة (FDR)"""
    user_id = update.effective_user.id
    
    # التحقق من الاشتراك
    is_subscribed = await check_subscription(context, user_id)
    if not is_subscribed:
        await update.message.reply_text(
            "🔒 **يرجى الاشتراك في القنوات أولاً!**\n"
            "استخدم /start للتحقق من الاشتراك.",
            parse_mode='Markdown'
        )
        return
    
    msg = await update.message.reply_text("🔄 جاري تحميل جدول صعوبة المباريات...")
    
    try:
        text, total_pages, current_page = format_fdr_display(page=0, per_page=2)
        
        if text:
            keyboard = get_fdr_keyboard(page=current_page, total_pages=total_pages)
            await msg.delete()
            await update.message.reply_text(
                text=text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        else:
            await msg.edit_text("❌ حدث خطأ في تحميل البيانات")
            
    except Exception as e:
        logger.error(f"خطأ في عرض FDR: {e}")
        await msg.edit_text(f"❌ حدث خطأ: {str(e)[:100]}")

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
    """عرض مبسط لمعلومات المدرب"""
    name = sanitize_markdown(safe_str(info.get("name")))
    
    # النقاط والترتيب
    total_points = safe_int(info.get("summary_overall_points"))
    
    # ترتيب الجولة الحالية
    target_gw_rank = 0
    if history and "current" in history:
        for gw_entry in history["current"]:
            if gw_entry.get("event") == gameweek:
                target_gw_rank = safe_int(gw_entry.get("overall_rank"))
                break
    
    rank = target_gw_rank if target_gw_rank > 0 else safe_int(info.get("summary_overall_rank"))
    rank_str = f"{rank:,}" if rank > 0 else "غير مصنف"
    
    # نقاط الجولة والترتيب
    event_points = 0
    event_rank = 0
    transfers_made = 0
    transfers_cost = 0
    
    if picks_data and "picks" in picks_data:
        live_points_map = get_live_points(gameweek)
        active_chip = picks_data.get("active_chip")
        
        # حساب نقاط الجولة
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
    
    # متوسط نقاط الجولة
    gw_stats = get_gameweek_stats(gameweek)
    avg_points = gw_stats["average_score"]
    
    # تغير الترتيب
    rank_change_display = get_rank_change_display(manager_id, gameweek, history)
    
    # ============================================================
    # بناء العرض المبسط
    # ============================================================
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
    
    # ============================================================
    # عرض البطاقات (Chips)
    # ============================================================
    response += "\n\n🎭 **البطاقات:**\n"
    
    # تحديد البطاقة النشطة حالياً
    active_chip = picks_data.get("active_chip") if picks_data else None
    
    # تعريف البطاقات
    chips_info = {
        "3xc": {"name": "👑 TC", "display": "تثليث القائد"},
        "bboost": {"name": "💺 BB", "display": "تفعيل الدكة"},
        "freehit": {"name": "🃏 FH", "display": "ضربة الحظ"},
        "wildcard": {"name": "🛠 WC", "display": "بطاقة الوحش"}
    }
    
    # الحصول على تاريخ استخدام البطاقات
    used_chips = {}
    if history and "chips" in history:
        for chip in history["chips"]:
            chip_name = chip.get("name")
            chip_event = chip.get("event")
            # تخزين الجولة التي استخدمت فيها البطاقة
            if chip_name not in used_chips:
                used_chips[chip_name] = chip_event
    
    # عرض كل بطاقة
    for chip_key, chip_info in chips_info.items():
        if active_chip == chip_key:
            # البطاقة نشطة حالياً
            response += f"{chip_info['name']} — تلعب الآن 🟢\n"
        elif chip_key in used_chips:
            # البطاقة استخدمت سابقاً
            response += f"{chip_info['name']} — الجولة {used_chips[chip_key]} 🔴\n"
        else:
            # البطاقة لم تستخدم
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

    def generate_team_section(team_id, team_info, score, is_home):
        text = f"{team_info.get('emoji_only', '⚪')} {team_info.get('name', 'Team')} [ {score} ]\n"

        team_players = []
        for p_id, p_data in elements_dict.items():
            p_stats = p_data.get("stats", {})
            p_team = players_dict.get(p_id, {}).get("team")

            if p_team == team_id and p_stats.get("minutes", 0) > 0:
                team_players.append((p_id, p_stats))

        team_players.sort(key=lambda x: (x[1].get("minutes", 0), x[1].get("total_points", 0)), reverse=True)

        for p_id, p_stats in team_players:
            mins = p_stats.get("minutes", 0)
            pts = p_stats.get("total_points", 0)
            p_name = players_dict.get(p_id, {}).get("web_name") or f"Player {p_id}"

            icons = ""
            if players_dict.get(p_id, {}).get("element_type") == 1: icons += " 🧤"
            if p_id in (goals_h if is_home else goals_a): icons += " ⚽️"
            if p_id in (yellow_h if is_home else yellow_a): icons += " 🟨"
            if p_id in (red_h if is_home else red_a): icons += " 🟥"
            if p_stats.get("defensive_contributions", 0) >= 10: icons += " 🛡"

            p_bonus = (bonus_h if is_home else bonus_a).get(p_id, 0)
            if p_bonus > 0:
                icons += " " + ("🎖" * p_bonus)

            text += f"{mins:2d}' {pts:2d} {p_name}{icons}\n"

        return text + "\n"

    response = generate_team_section(team_h_id, team_h_info, score_h, is_home=True)
    response += generate_team_section(team_a_id, team_a_info, score_a, is_home=False)

    all_xgi = []
    for p_id, p_data in elements_dict.items():
        p_team = players_dict.get(p_id, {}).get("team")
        if p_team in [team_h_id, team_a_id]:
            p_stats = p_data.get("stats", {})
            xg = float(p_stats.get("expected_goals", 0.0))
            xa = float(p_stats.get("expected_assists", 0.0))
            if xg + xa > 0:
                p_name = players_dict.get(p_id, {}).get("web_name", "لاعب")
                all_xgi.append((xg, xa, xg + xa, p_name))

    all_xgi.sort(key=lambda x: x[2], reverse=True)

    response += "Top xGI:\n"
    for xg, xa, total, p_name in all_xgi[:10]:
        response += f"{xg:.2f} + {xa:.2f}  {p_name}\n"

    all_bps = []
    for p_id, val in bps_h.items():
        all_bps.append((val, players_dict.get(p_id, {}).get("web_name", "لاعب")))
    for p_id, val in bps_a.items():
        all_bps.append((val, players_dict.get(p_id, {}).get("web_name", "لاعب")))
    all_bps.sort(key=lambda x: x[0], reverse=True)

    response += "\nTop BPS:\n"
    medals = ["🥇", "🥈", "🥉"]
    for idx, (val, p_name) in enumerate(all_bps[:10]):
        medal = f" {medals[idx]}" if idx < 3 else ""
        bonus_add = f" +{3-idx}" if idx < 3 else ""
        response += f"{val:2d} {p_name}{medal}{bonus_add}\n"

    all_defcon = []
    for p_id, p_data in elements_dict.items():
        p_team = players_dict.get(p_id, {}).get("team")
        if p_team in [team_h_id, team_a_id]:
            p_stats = p_data.get("stats", {})
            defcon_val = p_stats.get("defensive_contributions", 0)
            if defcon_val > 0:
                p_name = players_dict.get(p_id, {}).get("web_name", "لاعب")
                all_defcon.append((defcon_val, p_name))

    all_defcon.sort(key=lambda x: x[0], reverse=True)

    if all_defcon:
        response += "\nTop DEFCON:\n"
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

            finished = f.get("finished", False)
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

def format_price_changes_display(manager_id, info, gameweek):
    name = sanitize_markdown(safe_str(info.get("name")))
    data = safe_api_request(f"{BASE_URL}/bootstrap-static/", "get_price_changes")

    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")

    if not data or "elements" not in data:
        return "❌ حدث خطأ أثناء جلب بيانات الأسعار."

    elements = data["elements"]

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

    predicted_rise = sorted(players_list, key=lambda x: x["net_transfers"], reverse=True)[:5]
    predicted_fall = sorted(players_list, key=lambda x: x["net_transfers"])[:5]

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

    response += "🚀 **أكثر 5 لاعبين متوقع ارتفاعهم:**\n"
    for idx, p in enumerate(predicted_rise, 1):
        prediction_pct = min(100.0, max(0.0, (p["net_transfers"] / 50000.0) * 100))
        response += (
            f"{idx}. **{p['name']}**\n"
            f"   💰 السعر: £{p['price']:.1f}m | 📊 الملكية: {p['ownership']}% | 📈 نسبة التوقع: {prediction_pct:.1f}%\n"
        )
    response += "\n"

    response += "🔻 **أكثر 5 لاعبين متوقع انخفاضهم:**\n"
    for idx, p in enumerate(predicted_fall, 1):
        prediction_pct = min(100.0, max(0.0, (abs(p["net_transfers"]) / 50000.0) * 100))
        response += (
            f"{idx}. **{p['name']}**\n"
            f"   💰 السعر: £{p['price']:.1f}m | 📊 الملكية: {p['ownership']}% | 📉 نسبة التوقع: {prediction_pct:.1f}%\n"
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

    return response

# ============================================================
# دوال التحقق من الدوري
# ============================================================


def get_league_entries(league_id):
    """جلب قائمة المشاركين في الدوري"""
    url = f"{BASE_URL}/leagues-classic/{league_id}/standings"
    data = safe_api_request(url, "get_league_entries")
    
    if data and "standings" in data and "results" in data["standings"]:
        entries = []
        for result in data["standings"]["results"]:
            entry_id = result.get("entry")
            if entry_id:
                entries.append(entry_id)
        return entries
    return []

def is_user_in_league(manager_id, target_league_id):
    """
    التحقق مما إذا كان المدرب مشاركاً في الدوري المحدد
    عن طريق فحص قائمة دوريات المدرب مباشرة
    """
    try:
        target_league_id = str(target_league_id)
        info = get_manager_info(manager_id)
        
        if not info or "leagues" not in info:
            logger.warning(f"⚠️ تعذر جلب بيانات الدوريات للمدرب {manager_id}")
            return False

        # فحص الدوريات الكلاسيكية للمدرب
        classic_leagues = info.get("leagues", {}).get("classic", [])
        for league in classic_leagues:
            if str(league.get("id")) == target_league_id:
                logger.info(f"✅ المدرب {manager_id} موجود في الدوري الكلاسيكي {target_league_id}")
                return True

        # فحص دوريات المواجهات المباشرة (H2H) إن وجدت
        h2h_leagues = info.get("leagues", {}).get("h2h", [])
        for league in h2h_leagues:
            if str(league.get("id")) == target_league_id:
                logger.info(f"✅ المدرب {manager_id} موجود في دوري H2H {target_league_id}")
                return True

        logger.info(f"❌ المدرب {manager_id} غير مشترك في الدوري {target_league_id}")
        return False

    except Exception as e:
        logger.error(f"❌ خطأ أثناء التحقق من وجود المدرب في الدوري: {e}")
        return False
        
# ============================================================
# دوال الأزرار ومعالجات البوت
# ============================================================



def get_league_keyboard(league_id, page, total_pages, manager_id=None, league_type="classic"):
    """إنشاء أزرار التنقل في الدوري"""
    keyboard = []
    
    # أزرار التنقل
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"league_{league_type}_{league_id}_{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"league_{league_type}_{league_id}_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # أزرار تبديل نوع الدوري
    toggle_buttons = []
    if league_type == "classic":
        toggle_buttons.append(InlineKeyboardButton("🏆 كأس الدوري", callback_data=f"league_h2h_{league_id}_1"))
    else:
        toggle_buttons.append(InlineKeyboardButton("📊 الدوري العادي", callback_data=f"league_classic_{league_id}_1"))
    
    keyboard.append(toggle_buttons)
    
    # أزرار إضافية
    bottom_buttons = []
    if manager_id:
        bottom_buttons.append(InlineKeyboardButton("🔙 الرئيسية", callback_data=f"simple_{manager_id}_{get_current_gameweek()}"))
    
    if bottom_buttons:
        keyboard.append(bottom_buttons)
    
    return InlineKeyboardMarkup(keyboard)

def format_league_display(league_id, page=1, per_page=10, manager_id=None, league_type="classic"):
    """تنسيق عرض ترتيب الدوري (مع دعم الكأس)"""
    if league_type == "h2h":
        return format_h2h_league_display(league_id, page, per_page, manager_id)
    
    # الدوري العادي (Classic)
    data = get_league_standings(league_id, page)
    
    if not data or "standings" not in data:
        return "❌ حدث خطأ في جلب بيانات الدوري", None
    
    standings = data["standings"]
    entries = standings.get("results", [])
    total_entries = standings.get("total", 0)
    total_pages = (total_entries + per_page - 1) // per_page
    
    # اسم الدوري
    league_name = standings.get("league", {}).get("name", "الدوري الخاص")
    
    # تاريخ التحديث
    now_mecca = datetime.now(timezone.utc) + timedelta(hours=3)
    update_time = now_mecca.strftime("%I:%M %p").lstrip('0').lower()
    update_date = now_mecca.strftime("%d/%m/%Y")
    
    # بناء النص
    response = (
        f"🏆 **{league_name}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 الصفحة {page} من {total_pages}\n"
        f"👥 عدد المشاركين: {total_entries}\n"
        f"🕐 آخر تحديث: {update_time} - {update_date} (توقيت مكة)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    if not entries:
        response += "🚫 لا يوجد مشاركين في هذه الصفحة\n"
        return response, None
    
    # عرض المشاركين
    start_index = (page - 1) * per_page + 1
    for idx, entry in enumerate(entries, start=start_index):
        response += format_league_entry(entry, idx, get_current_gameweek())
        response += "\n"
    
    # إحصائيات سريعة
    if entries:
        top_score = max([e.get("event_total", 0) for e in entries])
        top_name = max(entries, key=lambda x: x.get("event_total", 0)).get("entry_name", "")
        response += f"━━━━━━━━━━━━━━━━━━━━━\n"
        response += f"⚡ أعلى نقاط في الجولة: **{top_score}** نقطة ({top_name})\n"
    
    return response, total_pages

def get_buttons(manager_id, gameweek, current_view):
    next_gw = get_next_gameweek(gameweek)
    prev_gw = get_previous_gameweek(gameweek)

    keyboard = [
        [InlineKeyboardButton("📊 عرض معلومات المدرب", callback_data=f"detail_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🏆 الدوريات", callback_data=f"leagues_{manager_id}_{gameweek}"),
         InlineKeyboardButton("⚽ المباريات", callback_data=f"fixtures_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("🚨 بدء الجولة", callback_data=f"deadline_{manager_id}_{gameweek}"),
         InlineKeyboardButton("📈 أسعار اللاعبين", callback_data=f"price_{manager_id}_{gameweek}")],
        [InlineKeyboardButton("👥 جميع اللاعبين", callback_data=f"players_{manager_id}_{gameweek}_0")],
        [InlineKeyboardButton("🤖 دوري البوت", callback_data=f"league_classic_{LEAGUE_ID}_1")],
        [InlineKeyboardButton("🆚 صعوبة المباريات", callback_data="fdr_0")], 
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

def get_subscription_button():
    keyboard = []
    
    # أزرار القنوات
    for channel in CHANNELS:
        keyboard.append([
            InlineKeyboardButton(f"📢 اشترك في {channel['name']}", url=f"https://t.me/{channel['id'].replace('@', '')}")
        ])
    
    # زر الدوري الخاص
    keyboard.append([
        InlineKeyboardButton(f"🏆 انضم للدوري {LEAGUE_NAME}", url=f"https://fantasy.premierleague.com/leagues/{LEAGUE_ID}/")
    ])
    
    # زر التحقق
    keyboard.append([
        InlineKeyboardButton("✅ تم الاشتراك - تحقق مرة أخرى", callback_data="check_0")
    ])
    
    return InlineKeyboardMarkup(keyboard)

# ============================================================
# دوال إدارة الأزرار
# ============================================================


async def league_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # جلب معرف المدرب المحفوظ في جلسة المستخدم
    manager_id = context.user_data.get("current_manager_id") or context.user_data.get("manager_id")

    if not manager_id:
        await update.message.reply_text("⚠️ يرجى إرسال رقم مدربك (Manager ID) أولاً لاستعراض بيانات الدوري.")
        return

    msg = await update.message.reply_text("🔄 جاري التحقق من الترتيب في الدوري...")

    if is_user_in_league(manager_id, LEAGUE_ID):
        text, total_pages = format_league_display(LEAGUE_ID, page=1, manager_id=manager_id)
        keyboard = get_league_keyboard(LEAGUE_ID, page=1, total_pages=total_pages, manager_id=manager_id)
        await msg.edit_text(text=text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await msg.edit_text(
            f"🏆 **أنت غير مشترك في دوري {LEAGUE_NAME} حالياً.**\n\n"
            f"للانضمام واستعراض الترتيب، استخدم الرابط التالي:\n"
            f"https://fantasy.premierleague.com/leagues/auto-join/wmvdke",
            disable_web_page_preview=True
        )
        
        
async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر /admin - لوحة تحكم المدير"""
    user_id = update.effective_user.id
    
    # التحقق من أن المستخدم أدمن
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ **عذراً، هذا الأمر متاح للأدمن فقط.**",
            parse_mode='Markdown'
        )
        return
    
    # إنشاء أزرار التحكم
    keyboard = [
        [
            InlineKeyboardButton("📊 إحصائيات المستخدمين", callback_data="admin_stats"),
            InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_ads")  # تم تغيير النص
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # عرض لوحة التحكم
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
    """معالجة أزرار لوحة التحكم"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    # التحقق من أن المستخدم أدمن
    if user_id not in ADMIN_IDS:
        await query.edit_message_text(
            "❌ **عذراً، هذا الإجراء متاح للأدمن فقط.**",
            parse_mode='Markdown'
        )
        return
    
    if data == "admin_stats":
        # عرض إحصائيات المستخدمين
        total_users = len(USERS_SET)
        current_time = datetime.now(timezone.utc) + timedelta(hours=3)
        time_str = current_time.strftime("%Y-%m-%d %I:%M %p").lstrip('0').lower()
        
        # عرض قائمة بأول 20 مستخدم (اختياري)
        users_list = list(USERS_SET)
        users_preview = ""
        if users_list:
            preview_count = min(20, len(users_list))
            users_preview = "\n📋 **أول 20 مستخدم:**\n"
            for i, uid in enumerate(users_list[:preview_count], 1):
                users_preview += f"{i}. `{uid}`\n"
            if len(users_list) > 20:
                users_preview += f"... و {len(users_list) - 20} مستخدم آخر"
        
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
        # ===== قسم الإعلانات المبسط =====
        # زر واحد فقط لإرسال الإعلان + زر العودة
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
            f"3️⃣ سيتم إرساله لجميع المستخدمين\n\n"
            f"🔹 لإلغاء الإرسال، أرسل /cancel",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif data == "ad_send":
        # طلب كتابة الإعلان
        awaiting_ad_message[user_id] = "waiting_for_message"
        
        await query.edit_message_text(
            f"✍️ **أرسل نص الإعلان الآن**\n\n"
            f"👥 سيتم الإرسال لـ **{len(USERS_SET)}** مستخدم\n",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إلغاء", callback_data="ad_cancel")]
            ])
        )
        
    elif data == "ad_cancel":
        # إلغاء الإعلان والعودة للوحة الإعلانات
        if user_id in awaiting_ad_message:
            del awaiting_ad_message[user_id]
        
        # العودة لقائمة الإعلانات المبسطة
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
        # العودة للوحة التحكم الرئيسية
        keyboard = [
            [
                InlineKeyboardButton("📊 إحصائيات المستخدمين", callback_data="admin_stats"),
                InlineKeyboardButton("📢 إرسال إعلان", callback_data="admin_ads")  # تم تغيير النص
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
    """إرسال الإعلان لجميع المستخدمين"""
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

# ⚠️ تأكد من إضافة هذا الاستيراد في أعلى الملف مع باقي الاستيرادات:
from telegram.ext import ApplicationHandlerStop

async def handle_ad_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل الإعلان المرسلة من المدير"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # التحقق من أن المستخدم أدمن
    if user_id not in ADMIN_IDS:
        return
    
    # التحقق من وجود حالة انتظار إعلان
    if user_id not in awaiting_ad_message:
        return
    
    state = awaiting_ad_message[user_id]
    
    # إلغاء الإعلان عند إرسال /cancel
    if message_text.lower() == "/cancel":
        del awaiting_ad_message[user_id]
        await update.message.reply_text(
            "✅ **تم إلغاء الإعلان**",
            parse_mode='Markdown'
        )
        # 🛑 يمنع تمرير أمر الإلغاء للدالة التالية في Group 2
        raise ApplicationHandlerStop
    
    # معالجة إرسال الإعلان
    if state == "waiting_for_message":
        # إشعار البدء بالارسال
        await update.message.reply_text(
            f"🔄 **جاري إرسال الإعلان للمستخدمين...**\n"
            f"👥 عدد المستخدمين: {len(USERS_SET)}\n"
            f"⏳ قد يستغرق هذا دقائق...",
            parse_mode='Markdown'
        )
        
        # إرسال الإعلان لجميع المستخدمين
        success, fail = await send_ad_to_users(
            context,
            message_text,
            list(USERS_SET),
            is_markdown=True
        )
        
        # حذف حالة الانتظار بعد الانتهاء
        del awaiting_ad_message[user_id]
        
        # إرسال التقرير النهائي للأدمن
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
        
        # 🛑 يمنع البوت من نقل نص الإعلان لـ Group 2 ومعاملته كمعرف مدرب
        raise ApplicationHandlerStop
        

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    message_text = update.message.text.strip()
    user_id = update.effective_user.id

    # ============================================================
    # ✅ التحقق المسبق: إذا كان المستخدم أدمن وفي حالة انتظار إعلان
    # ============================================================
    if user_id in ADMIN_IDS and user_id in awaiting_ad_message:
        logger.info(f"⏭️ تم تجاهل رسالة من الأدمن {user_id} - في حالة انتظار إعلان")
        return

    # ============================================================
    # حفظ المستخدم في الملف إذا لم يكن موجوداً
    # ============================================================
    if user_id not in USERS_SET:
        USERS_SET.add(user_id)
        save_users()
        logger.info(f"👤 مستخدم جديد: {user_id} - إجمالي المستخدمين: {len(USERS_SET)}")

    # ============================================================
    # التحقق من الاشتراك في القنوات
    # ============================================================
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

    # ============================================================
    # معالجة أوامر /start و /help
    # ============================================================
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
            "✓ نتائج المباريات وتفاصيلها ⚽️\n"
            "✓ مواعيد الديدلاين والانتقالات ⏰\n\n"
            "🔑 **كيف تحصل على معرف المدرب؟**\n"
            "افتح موقع FPL، الرقم في رابط حسابك:\n"
            "`https://fantasy.premierleague.com/entry/1234567/`\n\n"
            "📝 **جرب الآن:** أرسل `2794801`"
        )
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        return

    # ============================================================
    # محاولة تحويل النص إلى رقم معرف المدرب
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


    # ============================================================
    # جلب بيانات المدرب من API
    # ============================================================
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

    # ============================================================
    # جلب التشكيلة والتاريخ وعرض البيانات
    # ============================================================
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

    # معالجة أزرار لوحة التحكم (تبدأ بـ admin_ أو ad_)
    if data.startswith("admin_") or data.startswith("ad_"):
        await handle_admin_callback(update, context)
        return

    # ============================================================
    # ✅ معالجة التنقل في الدوري (معدل)
    # ============================================================
    if parts[0] == "league":
        if len(parts) >= 4:
            league_type = parts[1]  # "classic" أو "h2h"
            league_id = parts[2]
            page = int(parts[3])
            
            # التحقق من الاشتراك في القنوات
            is_subscribed_channels = await check_subscription(context, user_id)
            if not is_subscribed_channels:
                channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
                await query.edit_message_text(
                    text=f"🔒 **يرجى الاشتراك في جميع القنوات أولاً!**\n\n"
                         f"{channels_list}\n\n"
                         f"✅ بعد الاشتراك في الكل، اضغط على زر 'تم الاشتراك - تحقق مرة أخرى'.",
                    parse_mode='Markdown',
                    reply_markup=get_subscription_button()
                )
                return
            
            # الحصول على معرف المدرب
            manager_id = context.user_data.get('current_manager_id')
            
            # التحقق من وجود معرف مدرب
            if not manager_id:
                await query.edit_message_text(
                    text="❌ **يرجى إرسال معرف مدربك أولاً!**\n\n"
                         f"أرسل رقم معرفك لبدء استخدام البوت.\n"
                         f"مثال: `2794801`",
                    parse_mode='Markdown'
                )
                return
            
            
            await query.edit_message_text(f"🔄 جاري تحميل {'كأس' if league_type == 'h2h' else ''} الدوري...")
            
            try:
                text, total_pages = format_league_display(
                    league_id, 
                    page=page, 
                    per_page=10, 
                    manager_id=manager_id, 
                    league_type=league_type
                )
                
                if text and total_pages:
                    keyboard = get_league_keyboard(league_id, page, total_pages, manager_id, league_type)
                    await query.edit_message_text(
                        text=text,
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                else:
                    await query.edit_message_text("❌ حدث خطأ في تحميل بيانات الدوري")
                    
            except Exception as e:
                logger.error(f"خطأ في تحميل صفحة الدوري: {e}")
                await query.edit_message_text(f"❌ حدث خطأ: {str(e)[:100]}")
            return

    # ============================================================
    # ✅ معالجة FDR
    # ============================================================
    if parts[0] == "fdr":
        # التحقق من الاشتراك في القنوات
        is_subscribed_channels = await check_subscription(context, user_id)
        if not is_subscribed_channels:
            channels_list = "\n".join([f"📢 {ch['id']}" for ch in CHANNELS])
            await query.edit_message_text(
                text=f"🔒 **يرجى الاشتراك في جميع القنوات أولاً!**\n\n"
                     f"{channels_list}\n\n"
                     f"✅ بعد الاشتراك في الكل، اضغط على زر 'تم الاشتراك - تحقق مرة أخرى'.",
                parse_mode='Markdown',
                reply_markup=get_subscription_button()
            )
            return
        
        if len(parts) >= 2:
            action = parts[1]
            
            if action == "back":
                # العودة للقائمة الرئيسية
                manager_id = context.user_data.get('current_manager_id')
                if not manager_id:
                    await query.edit_message_text("❌ يرجى إرسال معرف المدرب")
                    return
                
                gameweek = get_current_gameweek()
                info = get_manager_info(manager_id)
                if not info:
                    await query.edit_message_text("❌ لم أتمكن من العثور على المدرب")
                    return
                
                picks_data = get_manager_picks(manager_id, gameweek)
                history = get_manager_history(manager_id)
                text = format_detailed_display(manager_id, info, gameweek, picks_data, history)
                reply_markup = get_buttons(manager_id, gameweek, "detail")
                
                await query.edit_message_text(
                    text=text,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                return
            else:
                # التنقل بين الصفحات
                try:
                    page = int(action)
                    
                    await query.edit_message_text("🔄 جاري تحميل جدول صعوبة المباريات...")
                    
                    text, total_pages, current_page = format_fdr_display(page=page, per_page=2)
                    
                    if text:
                        keyboard = get_fdr_keyboard(page=current_page, total_pages=total_pages)
                        await query.edit_message_text(
                            text=text,
                            parse_mode='Markdown',
                            reply_markup=keyboard
                        )
                    else:
                        await query.edit_message_text("❌ حدث خطأ في تحميل البيانات")
                        
                except ValueError:
                    await query.edit_message_text("❌ حدث خطأ غير متوقع")
                except Exception as e:
                    logger.error(f"خطأ في عرض FDR: {e}")
                    await query.edit_message_text(f"❌ حدث خطأ: {str(e)[:100]}")
            return

    # ============================================================
    # التحقق من الاشتراك في القنوات والدوري لجميع الأزرار الأخرى
    # ============================================================
    if parts[0] == "check":
        logger.info(f"✅ تم الضغط على زر التحقق للمستخدم {user_id}")
        
        # 1. التحقق من القنوات
        is_subscribed_channels = await check_subscription(context, user_id)
        
        # 2. التحقق من وجود معرف مدرب في context
        manager_id = context.user_data.get('current_manager_id')
        is_in_league = False
        
        if manager_id:
            is_in_league = is_user_in_league(manager_id, LEAGUE_ID)
        else:
            # إذا لم يكن هناك معرف مدرب، نطلب إرساله أولاً
            await context.bot.edit_message_text(
                text=f"📝 **يرجى إرسال معرف مدربك أولاً!**\n\n"
                     f"أرسل رقم معرفك لبدء استخدام البوت.\n"
                     f"مثال: `2794801`",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown'
            )
            return

        if is_subscribed_channels and is_in_league:
            # ✅ جميع الشروط محققة
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
                "✓ ترتيبك في الدوريات المختلفة\n"
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
            # ❌ فشل التحقق
            error_messages = []
            
            if not is_subscribed_channels:
                error_messages.append("📢 اشترك في جميع القنوات")
            
            if not is_in_league:
                error_messages.append(f"🏆 انضم للدوري {LEAGUE_NAME}")
            
            error_text = "❌ **لم يتم العثور على اشتراكك في:**\n\n" + "\n".join([f"• {msg}" for msg in error_messages])
            
            await context.bot.edit_message_text(
                text=error_text + "\n\n✅ بعد الانضمام للكل، اضغط على زر 'تم الاشتراك - تحقق مرة أخرى'.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='Markdown',
                reply_markup=get_subscription_button()
            )
        return

    # ============================================================
    # التحقق من الاشتراك في القنوات والدوري لجميع الأزرار الأخرى
    # ============================================================
    is_subscribed_channels = await check_subscription(context, user_id)
    
    if not is_subscribed_channels:
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



    # ============================================================
    # معالجة الأزرار المختلفة
    # ============================================================
    try:
        if parts[0] == "poslist":
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

        elif parts[0] == "nav":
            gameweek = int(parts[2])
            current_text = query.message.text or ""

            if "الدوريات" in current_text:
                view_type = "leagues"
            elif "مباريات الجولة" in current_text or "اختر المباراة" in current_text:
                view_type = "fixtures"
            elif "المواعيد" in current_text:
                view_type = "deadline"
            elif "تغيرات وتوقعات" in current_text:
                view_type = "price"
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

            if view_type == "deadline":
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
            else:  # detail
                picks_data = get_manager_picks(manager_id, gameweek)
                history = get_manager_history(manager_id)
                text = format_detailed_display(manager_id, info, gameweek, picks_data, history)

            await context.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                parse_mode='Markdown', reply_markup=get_buttons(manager_id, gameweek, view_type)
            )
            return

        elif parts[0] in ["detail", "leagues", "deadline", "price"]:
            view_type = parts[0]
            gameweek = int(parts[2])

            loading_texts = {
                "detail": "عرض معلومات المدرب",
                "leagues": "الدوريات والمواسم",
                "deadline": "مواعيد الجولة", 
                "price": "توقعات وتغيرات الأسعار"
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
            elif view_type == "price":
                text = format_price_changes_display(manager_id, info, gameweek)
            elif view_type == "leagues":
                history = get_manager_history(manager_id)
                text = format_leagues_display(manager_id, info, gameweek, history)
            else:  # detail
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
    
    # 1. الأوامر
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("help", handle_message))
    application.add_handler(CommandHandler("admin", handle_admin_command))
    application.add_handler(CommandHandler("league", league_command))
    application.add_handler(CommandHandler("match_diff", match_diff_command))
    # 2. معالج الإعلانات في (Group 1)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ad_message),
        group=1
    )
    
    # 3. المعالج العام للرسائل في (Group 2)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
        group=2
    )
    
    # 4. معالج الأزرار
    application.add_handler(CallbackQueryHandler(handle_callback))

    application.run_polling()
        
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
