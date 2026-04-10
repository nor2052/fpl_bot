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

BASE_URL = "https://fantasy.premierleague.com/api"

# ==================================================
# دوال جلب البيانات (تعمل بشكل صحيح)
# ==================================================

def safe_api_request(url):
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
    url = f"{BASE_URL}/entry/{manager_id}/"
    return safe_api_request(url)

def get_manager_history(manager_id):
    url = f"{BASE_URL}/entry/{manager_id}/history/"
    return safe_api_request(url)

def get_manager_picks(manager_id, gameweek):
    url = f"{BASE_URL}/entry/{manager_id}/event/{gameweek}/picks/"
    return safe_api_request(url)

def get_players_dict():
    url = f"{BASE_URL}/bootstrap-static/"
    data = safe_api_request(url)
    if data and "elements" in data:
        players = {}
        for player in data["elements"]:
            players[player["id"]] = f"{player['first_name']} {player['second_name']}"
        return players
    return {}

def get_last_played_gameweek():
    url = f"{BASE_URL}/bootstrap-static/"
    data = safe_api_request(url)
    if data and "events" in data:
        for event in reversed(data["events"]):
            if event.get("finished"):
                return event["id"]
    return 1

def get_next_gameweek(current_gw):
    next_gw = current_gw + 1
    return next_gw if next_gw <= 38 else 1

def get_previous_gameweek(current_gw):
    prev_gw = current_gw - 1
    return prev_gw if prev_gw >= 1 else 38

# تحميل البيانات الأساسية
players_dict = get_players_dict()
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
# دوال عرض المعلومات (المصححة)
# ==================================================

def format_simple_display(manager_id, info, gameweek, picks_data):
    name = safe_str(info.get("name"))
    total_points = safe_int(info.get("summary_overall_points"))
    
    # --- التصحيح 1: استخراج نقاط الجولة من entry_history ---
    event_points = 0
    if picks_data and "entry_history" in picks_data:
        event_points = safe_int(picks_data["entry_history"].get("points", 0))
    
    # --- التصحيح 2: استخراج نقاط الكابتن من picks ---
    captain_points = 0
    captain_name = ""
    if picks_data and "picks" in picks_data:
        for pick in picks_data["picks"]:
            if pick.get("is_captain"):
                # النقطة الذهبية: استخراج points مباشرة من pick
                captain_points = safe_int(pick.get("points", 0))
                player_id = pick.get("element", 0)
                if player_id in players_dict:
                    captain_name = players_dict[player_id]
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
    # عرض لاعبي الفريق مع نقاطهم (المعلومة المصححة)
    # ==========================================
    if picks_data and "picks" in picks_data:
        response += "🧑‍🤝‍🧑 **لاعبو الفريق (الأساسيون):**\n"
        for idx, pick in enumerate(picks_data["picks"][:11], 1):
            player_id = pick.get("element", 0)
            player_name = players_dict.get(player_id, f"لاعب {player_id}")
            # النقطة الذهبية: استخراج points مباشرة من pick
            points = safe_int(pick.get("points", 0))
            is_captain = " 👑 (C)" if pick.get("is_captain") else ""
            is_vice = " (VC)" if pick.get("is_vice_captain") else ""
            response += f"{idx}. {player_name}{is_captain}{is_vice}: {points} نقطة\n"
        response += "\n"
    else:
        response += "⚠️ لا توجد بيانات للاعبين في هذه الجولة.\n\n"
    
    # ==========================================
    # عرض المجموعات مع الترتيب (المعلومة المصححة)
    # ==========================================
    leagues = info.get("leagues", {})
    classic_leagues = leagues.get("classic", [])
    
    if classic_leagues:
        response += "🏅 **المجموعات (الدوريات):**\n"
        for idx, league in enumerate(classic_leagues[:5], 1):
            league_name = safe_str(league.get("name", "غير معروف"))
            # النقطة الذهبية: استخراج rank و total_teams من league
            league_rank = league.get("rank")
            league_total = league.get("total_teams")
            
            if league_rank is not None and league_total is not None:
                response += f"{idx}. {league_name}: {league_rank}/{league_total}\n"
            elif league_rank is not None:
                response += f"{idx}. {league_name}: الترتيب {league_rank}\n"
            else:
                response += f"{idx}. {league_name}\n"
        response += "\n"
    else:
        response += "🏅 **المجموعات:** لا يشارك في مجموعات حالياً\n\n"
    
    # ==========================================
    # عرض تاريخ المواسم السابقة (كان يعمل بشكل صحيح)
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

# ==================================================
# دوال إنشاء الأزرار ومعالجات البوت (بدون تغيير)
# ==================================================

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
            "🎮 **بوت مساعد الفانتاسي التفاعلي**\n\n"
            "✨ **كيف يعمل؟**\n"
            "1️⃣ أرسل **رقم معرف المدرب**\n"
            "2️⃣ سيظهر لك بيانات **آخر جولة لعبت** تلقائياً\n\n"
            "📊 **جميع البيانات متاحة للعموم:**\n"
            "✓ نقاط الجولة للمدرب\n"
            "✓ النقاط الكلية والترتيب العالمي\n"
            "✓ **نقاط كل لاعب في الفريق**\n"
            "✓ **ترتيب المدرب في كل دوري**\n"
            "✓ تاريخ المواسم السابقة\n\n"
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
    
    text = format_simple_display(manager_id, info, start_gameweek, picks_data)
    reply_markup = get_buttons(manager_id, start_gameweek, "simple")
    
    await update.message.reply_text(
        text=text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

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
    print("🤖 البوت التفاعلي (النسخة النهائية المصححة) يعمل الآن...")
    print(f"📅 آخر جولة لعبت: {last_gameweek}")
    print("✅ يعرض نقاط اللاعبين وترتيب الدوريات بشكل صحيح")
    print("📡 أرسل معرف مدرب للبدء")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()
