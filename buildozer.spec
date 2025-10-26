[app]
title = GoldShopManager
package.name = goldshopmanager
package.domain = org.example

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,json,ttf
version = 0.1
orientation = portrait
android.ndk = 23b
android.sdk = 28
android.minapi = 21
android.api = 28
# فایلِ اصلی شما:
# (اگر main.py نامِ فایل اصلی است، buildozer به طور پیش‌فرض main.py را اجرا می‌کند)
# (در غیر این صورت مقدار entrypoint را تنظیم کن)
# entrypoint = main.py

# لیست پکیج‌های پایتون که برنامه استفاده می‌کند:
requirements = python3,kivy,kivymd,pillow,plyer,arabic-reshaper,python-bidi

# دسترسی‌ها (در صورت استفاده از خواندن/نوشتن فایل‌ها روی حافظه):
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,INTERNET

# (اختیاری) برای مشکلات NDK: مشخص کردن NDK پیشنهادی
# android.ndk = 25b

[buildozer]
log_level = 2
warn_on_root = 1

[android]
# target api level را نمی‌توان خیلی قدیمی گرفت؛ نگه‌داشتن پیش‌فرض معمولاً کافی است.
# اگر مشکل NDK داری، مقدار android.ndk را صریح بذار (مثلاً 25b)
# android.ndk = 25b

# اگر می‌خواهی AAB بسازی:
# android.release_artifact = aab
