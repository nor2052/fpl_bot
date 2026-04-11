#FPL Manager Stats Bot

هذا بوت تفاعلي لتلغرام -مكتوب بمساعدة الذكاء الاصطناعي- يقوم بجلب وعرض إحصائيات المدربين في لعبة Fantasy Premier League (FPL). الفكرة الأساسية هي إرسال رقم معرف المدرب، ثم الحصول على معلومات مفصلة عن فريقه، نقاطه، ترتيبه، والمجموعات التي يشارك فيها.

This is an interactive Telegram bot -written by AI model- that fetches and displays manager statistics from the Fantasy Premier League (FPL) game. The main idea is to send a manager ID, then receive detailed information about their team, points, rank, and the leagues they participate in.

📋 Table of Contents | فهرس المحتويات
English	العربية
How It Works	كيف يعمل
Features	الميزات
Requirements	المتطلبات
Installation	التثبيت
Deployment on Railway	النشر على Railway
Environment Variables	متغيرات البيئة
Commands	الأوامر
API Endpoints Used	نقاط الاتصال المستخدمة
Project Structure	هيكل المشروع
Troubleshooting	استكشاف الأخطاء
License	الترخيص
How It Works
يقوم البوت بالاتصال بـ API الرسمي للعبة Fantasy Premier League لجلب البيانات التالية:

المعلومات الأساسية للمدرب (الاسم، تاريخ الانضمام)

النقاط الكلية والترتيب العالمي

نقاط الجولة الحالية وترتيبها

تشكيلة الفريق مع نقاط كل لاعب

المجموعات (الدوريات) التي يشارك فيها المدرب مع ترتيبه فيها

تاريخ المواسم السابقة

The bot connects to the official Fantasy Premier League API to fetch the following data:

Basic manager information (name, join date)

Total points and overall rank

Current gameweek points and rank

Team lineup with each player's points

Leagues the manager participates in with their rank

Past seasons history

Features
English
Feature	Description
🔍 Simple ID Lookup	Send any manager ID to get their statistics
📊 Two Display Modes	Simple view (points, rank, captain) and Detailed view (full team, leagues, history)
🔄 Gameweek Navigation	Browse through previous and next gameweeks with circular navigation (1↔38)
👑 Captain Points	Displays captain name and points in simple view
🏅 League Rankings	Shows manager's rank within each classic league they participate in
📜 Season History	Displays last 3 seasons performance
🚀 Fast & Responsive	Optimized API calls with caching for better performance
👥 Multi-User Support	Handles multiple users simultaneously without interference
العربية
الميزة	الوصف
🔍 بحث بسيط بالمعرف	أرسل أي معرف مدرب للحصول على إحصائياته
📊 وضعا عرض	عرض بسيط (نقاط، ترتيب، كابتن) وعرض مفصل (الفريق كاملاً، المجموعات، التاريخ)
🔄 التنقل بين الجولات	تصفح الجولات السابقة والتالية مع تنقل دائري (1↔38)
👑 نقاط الكابتن	عرض اسم الكابتن ونقاطه في العرض البسيط
🏅 ترتيب المجموعات	عرض ترتيب المدرب في كل دوري كلاسيكي يشارك فيه
📜 تاريخ المواسم	عرض أداء آخر 3 مواسم
🚀 سرعة واستجابة	تحسين استدعاءات API مع تخزين مؤقت للأداء الأفضل
👥 دعم متعدد المستخدمين	التعامل مع عدة مستخدمين في نفس الوقت دون تداخل
Requirements
English
Python 3.11 or higher

Telegram Bot Token (from @BotFather)

Railway account (for hosting) or any Python-capable server

العربية
Python 3.11 أو أحدث

توكن بوت تلغرام (من @BotFather)

حساب على Railway (للاستضافة) أو أي خادم يدعم Python

Installation
English
Clone the repository

bash
git clone https://github.com/yourusername/fpl-manager-bot.git
cd fpl-manager-bot
Create a virtual environment

bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
Install dependencies

bash
pip install -r requirements.txt
Set up environment variables

bash
# Create a .env file with:
BOT_TOKEN=your_telegram_bot_token_here
Run the bot locally

bash
python main.py
العربية
استنساخ المستودع

bash
git clone https://github.com/yourusername/fpl-manager-bot.git
cd fpl-manager-bot
إنشاء بيئة افتراضية

bash
python -m venv venv
source venv/bin/activate  # في Windows: venv\Scripts\activate
تثبيت المتطلبات

bash
pip install -r requirements.txt
إعداد متغيرات البيئة

bash
# أنشئ ملف .env وأضف فيه:
BOT_TOKEN=your_telegram_bot_token_here
تشغيل البوت محلياً

bash
python main.py
Deployment on Railway
English
Push your code to GitHub

bash
git add .
git commit -m "Initial commit"
git push origin main
Create a new project on Railway

Click "New Project"

Select "Deploy from GitHub repo"

Choose your repository

Add environment variables

Go to your project dashboard

Click on the "Variables" tab

Add BOT_TOKEN with your Telegram bot token

Set start command (if needed)

Go to "Settings" → "Start Command"

Set to: python main.py

Deploy

Railway will automatically deploy your bot

Monitor logs in the "Deployments" tab

العربية
ارفع الكود إلى GitHub

bash
git add .
git commit -m "الإصدار الأول"
git push origin main
أنشئ مشروعاً جديداً على Railway

اضغط "New Project"

اختر "Deploy from GitHub repo"

حدد المستودع الخاص بك

أضف متغيرات البيئة

اذهب إلى لوحة تحكم المشروع

اضغط على تبويب "Variables"

أضف BOT_TOKEN مع توكن البوت الخاص بك

حدد أمر التشغيل (إذا لزم الأمر)

اذهب إلى "Settings" ← "Start Command"

اكتب: python main.py

انشر البوت

سيقوم Railway بنشر البوت تلقائياً

تابع السجلات في تبويب "Deployments"

Environment Variables
English
Variable	Description	Required
BOT_TOKEN	Telegram bot token from @BotFather	✅ Yes
العربية
المتغير	الوصف	مطلوب
BOT_TOKEN	توكن بوت تلغرام من @BotFather	✅ نعم
Commands
English
Command	Description
/start	Display welcome message and instructions
/help	Show help information
Main usage: Simply send any manager ID (e.g., 2794801) to get their statistics.

العربية
الأمر	الوصف
/start	عرض رسالة الترحيب والتعليمات
/help	عرض معلومات المساعدة
الاستخدام الرئيسي: أرسل أي معرف مدرب (مثال: 2794801) للحصول على إحصائياته.

API Endpoints Used
English
The bot uses the following official FPL API endpoints:

Endpoint	Purpose
/api/bootstrap-static/	Get static game data (players, teams, gameweeks)
/api/entry/{manager_id}/	Get manager basic info and leagues
/api/entry/{manager_id}/history/	Get manager's past seasons history
/api/entry/{manager_id}/event/{gw}/picks/	Get manager's team lineup for a specific gameweek
/api/event/{gw}/live/	Get live points for all players in a gameweek
العربية
يستخدم البوت نقاط الاتصال التالية من API الرسمي للعبة:

نقطة الاتصال	الغرض
/api/bootstrap-static/	الحصول على بيانات اللعبة الثابتة (اللاعبين، الفرق، الجولات)
/api/entry/{manager_id}/	الحصول على معلومات المدرب الأساسية والمجموعات
/api/entry/{manager_id}/history/	الحصول على تاريخ المدرب في المواسم السابقة
/api/entry/{manager_id}/event/{gw}/picks/	الحصول على تشكيلة المدرب لجولة محددة
/api/event/{gw}/live/	الحصول على النقاط الحية لجميع اللاعبين في جولة معينة
Project Structure
English
text
fpl-manager-bot/
├── main.py                 # Main bot code
├── requirements.txt        # Python dependencies
├── Procfile               # Railway deployment config (optional)
├── .env                   # Environment variables (not committed)
└── README.md              # This file
العربية
text
fpl-manager-bot/
├── main.py                 # كود البوت الرئيسي
├── requirements.txt        # مكتبات Python المطلوبة
├── Procfile               # إعدادات النشر على Railway (اختياري)
├── .env                   # متغيرات البيئة (غير مرفوع للمستودع)
└── README.md              # هذا الملف
Troubleshooting
English
Issue	Solution
Bot doesn't respond	Check Railway logs for errors. Ensure BOT_TOKEN is set correctly
"Manager not found"	Verify the manager ID is correct. Try 2794801 as a test
Player points show 0	This happens when the gameweek is still in progress. Wait for the gameweek to finish
League ranks not showing	The manager might not be in the top ranks. The bot searches through multiple pages
Markdown parsing errors	The bot sanitizes special characters automatically
العربية
المشكلة	الحل
البوت لا يستجيب	راجع سجلات Railway للأخطاء. تأكد من صحة BOT_TOKEN
"لم يتم العثور على مدرب"	تأكد من صحة معرف المدرب. جرب 2794801 كاختبار
نقاط اللاعبين تظهر 0	يحدث هذا عندما تكون الجولة لا تزال قيد اللعب. انتظر حتى انتهاء الجولة
ترتيب المجموعات لا يظهر	قد لا يكون المدرب ضمن المراكز الأولى. البوت يبحث عبر عدة صفحات
أخطاء في تنسيق Markdown	البوت يقوم بتنظيف الأحرف الخاصة تلقائياً
Getting a Manager ID | كيفية الحصول على معرف مدرب
English
Open the official FPL website: https://fantasy.premierleague.com

Navigate to any manager's "Points" page

Look at the URL: https://fantasy.premierleague.com/entry/1234567/

The number 1234567 is the manager ID

العربية
افتح موقع FPL الرسمي: https://fantasy.premierleague.com

اذهب إلى صفحة "Points" لأي مدرب

انظر إلى الرابط: https://fantasy.premierleague.com/entry/1234567/

الرقم 1234567 هو معرف المدرب

Example Usage | مثال على الاستخدام
English
User sends: 2794801

Bot responds with:

text
🎮 Mohamed Salah
🆔 2794801
📊 الجولة 32
⭐ نقاط الجولة: 55
🏆 النقاط الكلية: 1796
📈 الترتيب العالمي: 410,356
📊 ترتيب الجولة: 2,545,048
👑 الكابتن (Erling Haaland): 12 نقطة
العربية
يرسل المستخدم: 2794801

يرد البوت:

text
🎮 محمد صلاح
🆔 2794801
📊 الجولة 32
⭐ نقاط الجولة: 55
🏆 النقاط الكلية: 1796
📈 الترتيب العالمي: 410,356
📊 ترتيب الجولة: 2,545,048
👑 الكابتن (إيرلينغ هالاند): 12 نقطة
Dependencies | المتطلبات
English
text
python-telegram-bot==20.7
requests
العربية
text
python-telegram-bot==20.7
requests
