import os  # أضف هذا السطر في البداية
import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# تفعيل تسجيل الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================================================
# ✨ اقرأ التوكن من متغيرات البيئة ✨
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # سيأخذ التوكن من Railway Variables

if not BOT_TOKEN:
    print("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    exit(1)
# ==================================================

# باقي الكود كما هو...
BASE_URL = "https://fantasy.premierleague.com/api"

# ... (ضع باقي دوال البوت هنا، نفس الكود السابق)
