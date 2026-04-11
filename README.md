# بوت مساعد الفانتاسي (FPL Assistant Bot)

هذا مشروع بوت تلغرام -مكتوب بمساعدة الذكاء الاصطناعي- يقوم بعرض إحصائيات مدربي لعبة Fantasy Premier League (FPL). الفكرة الأساسية هي إدخال رقم معرف المدرب (Manager ID) للحصول على معلومات مفصلة عن فريقه، نقاطه، ترتيبه في الدوريات، وتاريخه السابق.

This is a Telegram bot -written by AI model- that displays statistics for Fantasy Premier League (FPL) managers. The main idea is to enter a manager ID to get detailed information about their team, points, league rankings, and past history.

## How it works

يقوم البوت بالاتصال بـ API الرسمي للعبة FPL لجلب البيانات:
- إرسال رقم معرف المدرب (Manager ID) إلى البوت
- اختيار عرض بسيط أو عرض مفصل
- التنقل بين الجولات (السابقة/التالية) عبر أزرار تفاعلية
- عرض نقاط اللاعبين، ترتيب المدرب في الدوريات، وتاريخ المواسم السابقة

The bot connects to the official FPL API to fetch data:
- Send a manager ID to the bot
- Choose between simple or detailed view
- Navigate between gameweeks (previous/next) using interactive buttons
- Display player points, manager league rankings, and past season history

## Features

- ✅ عرض نقاط الجولة للمدرب (محسوبة من نقاط اللاعبين مباشرة)
- ✅ عرض النقاط الكلية والترتيب العالمي
- ✅ عرض لاعبي الفريق الأساسيين مع نقاطهم ونقاط الكابتن
- ✅ عرض ترتيب المدرب في جميع الدوريات المشارك بها
- ✅ عرض آخر 3 مواسم مع النقاط والترتيب
- ✅ التنقل الدائري بين الجولات (من 1 إلى 38 والعكس)
- ✅ دعم متعدد المستخدمين (يعمل لجميع المستخدمين في نفس الوقت)

## Requirements

- Python 3.11.9
- Telegram Bot Token (from @BotFather)
- Railway account (for hosting)

## Installation

```bash
pip install python-telegram-bot requests
