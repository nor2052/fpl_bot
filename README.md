# README.md

# =============================================================================
# FPL Manager Stats Bot - بوت إحصائيات مدربي الفانتاسي
# =============================================================================
#
# -----------------------------------------------------------------------------
# English Version
# -----------------------------------------------------------------------------
#
# Project Title: FPL Manager Stats Telegram Bot
#
# Description:
# This Telegram bot provides comprehensive statistics for Fantasy Premier League
# (FPL) managers. By simply sending a manager ID, users can retrieve detailed
# information including gameweek points, overall rankings, team lineups with
# individual player points, league standings, and historical performance data.
#
# Features:
# - Display current gameweek points and overall rankings
# - Show team lineup with individual player points and captain's points
# - Display classic leagues standings with manager's rank
# - Navigate between gameweeks using interactive buttons
# - Toggle between simple and detailed view modes
# - Show historical performance from previous seasons
#
# Technical Requirements:
# - Python 3.11 or higher
# - Required libraries: python-telegram-bot==20.7, requests
# - Hosting: Railway.app (recommended) or any Python-compatible cloud platform
# - Telegram Bot Token (obtain from @BotFather on Telegram)
#
# Installation Steps:
# 1. Clone the repository
# 2. Install dependencies: pip install -r requirements.txt
# 3. Set environment variable: BOT_TOKEN=your_bot_token
# 4. Run the bot: python main.py
#
# Deployment on Railway.app:
# 1. Push code to GitHub repository
# 2. Connect Railway.app to your GitHub repository
# 3. Add BOT_TOKEN as environment variable in Railway dashboard
# 4. Set start command: python main.py
# 5. Deploy the application
#
# How to Get a Manager ID:
# 1. Visit https://fantasy.premierleague.com
# 2. Navigate to any manager's points page
# 3. Copy the numeric ID from the URL: https://fantasy.premierleague.com/entry/1234567/
# 4. Send this number to the bot
#
# Bot Commands:
# - Send any manager ID number to display statistics
# - /start or /help - Display help message
#
# Interactive Buttons:
# - 📋 Simple View: Basic statistics (points, ranking, captain points)
# - 📊 Detailed View: Complete statistics including player points and league standings
# - ⬅️ Previous Gameweek: Navigate to previous gameweek
# - ➡️ Next Gameweek: Navigate to next gameweek (circular navigation 1-38)
#
# Data Source:
# All data is fetched from the official Fantasy Premier League API:
# https://fantasy.premierleague.com/api/
#
# License:
# This project is open source and available for personal and educational use.
#
# Contact:
# For issues or contributions, please open an issue on GitHub.
#
# -----------------------------------------------------------------------------
# Arabic Version - النسخة العربية
# -----------------------------------------------------------------------------
#
# عنوان المشروع: بوت إحصائيات مدربي الفانتاسي لتليغرام
#
# الوصف:
# يقدم هذا البوت إحصائيات شاملة لمدربي لعبة Fantasy Premier League (FPL)
# على تطبيق تليغرام. بمجرد إرسال رقم معرف المدرب، يمكن للمستخدم الحصول على
# معلومات مفصلة تشمل نقاط الجولة، الترتيب العام، تشكيلة الفريق مع نقاط كل لاعب،
# ترتيب المدرب في الدوريات، والأداء في المواسم السابقة.
#
# الميزات:
# - عرض نقاط الجولة الحالية والترتيب العام
# - عرض تشكيلة الفريق مع نقاط كل لاعب ونقاط الكابتن
# - عرض ترتيب المدرب في الدوريات الكلاسيكية
# - التنقل بين الجولات باستخدام أزرار تفاعلية
# - التبديل بين وضع العرض البسيط والعرض المفصل
# - عرض الأداء التاريخي من المواسم السابقة
#
# المتطلبات التقنية:
# - إصدار Python 3.11 أو أحدث
# - المكتبات المطلوبة: python-telegram-bot==20.7, requests
# - الاستضافة: Railway.app (موصى به) أو أي منصة سحابية تدعم Python
# - توكن البوت من تليغرام (يتم الحصول عليه من @BotFather)
#
# خطوات التثبيت:
# 1. استنساخ المستودع (Repository)
# 2. تثبيت المتطلبات: pip install -r requirements.txt
# 3. إعداد متغير البيئة: BOT_TOKEN=your_bot_token
# 4. تشغيل البوت: python main.py
#
# النشر على منصة Railway.app:
# 1. رفع الكود إلى مستودع على GitHub
# 2. ربط حساب Railway.app بمستودع GitHub
# 3. إضافة BOT_TOKEN كمتغير بيئة في لوحة تحكم Railway
# 4. تعيين أمر التشغيل: python main.py
# 5. نشر التطبيق
#
# كيفية الحصول على معرف المدرب:
# 1. زيارة موقع https://fantasy.premierleague.com
# 2. الانتقال إلى صفحة نقاط أي مدرب
# 3. نسخ الرقم الموجود في الرابط: https://fantasy.premierleague.com/entry/1234567/
# 4. إرسال هذا الرقم إلى البوت
#
# أوامر البوت:
# - إرسال أي رقم معرف مدرب لعرض الإحصائيات
# - /start أو /help - عرض رسالة المساعدة
#
# الأزرار التفاعلية:
# - 📋 عرض بسيط: الإحصائيات الأساسية (النقاط، الترتيب، نقاط الكابتن)
# - 📊 عرض مفصل: الإحصائيات الكاملة (نقاط اللاعبين وترتيب الدوريات)
# - ⬅️ الجولة السابقة: الانتقال إلى الجولة السابقة
# - ➡️ الجولة التالية: الانتقال إلى الجولة التالية (تنقل دائري 1-38)
#
# مصدر البيانات:
# جميع البيانات تُجلب من واجهة برمجة التطبيقات (API) الرسمية للعبة:
# https://fantasy.premierleague.com/api/
#
# الترخيص:
# هذا المشروع مفتوح المصدر ومتاح للاستخدام الشخصي والتعليمي.
#
# التواصل:
# للاستفسارات أو المساهمات، يرجى فتح موضوع (Issue) على GitHub.
#
# =============================================================================
