# Gold Shop Manager — Enhanced with Performance Optimizations and Data Management
# Requirements: kivy, kivymd. Optional: pillow, plyer, arabic-reshaper, python-bidi

import os
import re
import sqlite3
import shutil
import csv
import zipfile
import uuid
import datetime
import json
from pathlib import Path
from functools import partial

from kivy.lang import Builder
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.properties import StringProperty, ListProperty, NumericProperty
from kivy.uix.screenmanager import Screen
from kivy.clock import Clock
from kivy.utils import platform as kivy_platform
from kivy.app import App
from kivy.metrics import dp
from kivy.cache import Cache

from kivymd.app import MDApp
from kivymd.toast import toast
from kivymd.uix.textfield import MDTextField

# Configure cache for performance
Cache.register('image_load', limit=100)
Cache.register('product_data', limit=200)

# optional libs
try:
    from PIL import Image as PILImage
except Exception:
    PILImage = None

try:
    from plyer import filechooser
except Exception:
    filechooser = None

# optional bidi/reshaper for Persian shaping (display)
try:
    import arabic_reshaper
    from bidi.algorithm import get_display as bidi_get_display
    _RESHAPER_AVAILABLE = True
except Exception:
    _RESHAPER_AVAILABLE = False

# --------------------------
# Helpers: font, reshape
# --------------------------
def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = ensure_dir(os.path.join(BASE_DIR, "fonts"))
VAZIR_FILENAME = "Vazir.ttf"
VAZIR_PATH = os.path.join(FONTS_DIR, VAZIR_FILENAME)

def try_download_vazir(dst_path):
    try:
        import urllib.request
        url = "https://raw.githubusercontent.com/rastikerdar/vazir-font/master/dist/Vazir-Regular.ttf"
        urllib.request.urlretrieve(url, dst_path)
        print("Downloaded Vazir to:", dst_path)
        return True
    except Exception as e:
        print("Could not download Vazir:", e)
        return False

def find_system_font_candidates():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for root, dirs, files in os.walk("/usr/share/fonts"):
        for f in files:
            fl = f.lower()
            if fl.endswith(".ttf") and ("dejav" in fl or "noto" in fl or "arab" in fl or "free" in fl):
                path = os.path.join(root, f)
                if path not in candidates:
                    candidates.append(path)
    win_fonts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    if os.path.isdir(win_fonts):
        for f in os.listdir(win_fonts):
            if f.lower().endswith(".ttf") and ("arab" in f.lower() or "noto" in f.lower() or "dejav" in f.lower() or "ara" in f.lower()):
                candidates.append(os.path.join(win_fonts, f))
    return candidates

def choose_font_file():
    if os.path.exists(VAZIR_PATH) and os.path.getsize(VAZIR_PATH) > 1000:
        return VAZIR_PATH
    try:
        if try_download_vazir(VAZIR_PATH):
            if os.path.exists(VAZIR_PATH) and os.path.getsize(VAZIR_PATH) > 1000:
                return VAZIR_PATH
    except Exception:
        pass
    for p in find_system_font_candidates():
        try:
            if os.path.exists(p) and os.path.getsize(p) > 1000:
                return p
        except Exception:
            continue
    return None

def register_font_variants(font_path):
    try:
        LabelBase.register(name="Vazir", fn_regular=font_path)
        LabelBase.register(name="AppFont", fn_regular=font_path)
        LabelBase.register(name="Roboto", fn_regular=font_path)
        return True
    except Exception as e:
        print("Font registration failed:", e)
        return False

_chosen_font = choose_font_file()
_font_registered = False
if _chosen_font:
    _font_registered = register_font_variants(_chosen_font)
else:
    print("No font found; for best Persian rendering put Vazir-Regular.ttf into ./fonts")

def reshape_text_if_needed(s):
    """
    Applies arabic_reshaper + bidi to a logical string (if libs available)
    """
    if not s:
        return s
    if not _RESHAPER_AVAILABLE:
        return s
    try:
        reshaped = arabic_reshaper.reshape(s)
        bidi_text = bidi_get_display(reshaped)
        return bidi_text
    except Exception:
        return s

def _reshape_display_for_widget_text(s: str) -> str:
    if not s:
        return ""
    try:
        if _RESHAPER_AVAILABLE:
            return bidi_get_display(arabic_reshaper.reshape(s))
    except Exception:
        pass
    return s

# --------------------------
# ArMDTextField: MDTextField with Arabic/Persian buffer + live reshape
# --------------------------
class ArMDTextField(MDTextField):
    """
    MDTextField subclass that keeps a logical buffer `arabic_buf`
    and updates displayed self.text with arabic_reshaper + bidi on every insert/backspace.
    Ensures cursor jumps to the end after each edit (use get_cursor_from_index if available).
    """
    arabic_buf = StringProperty("")  # logical text (not shaped)
    max_chars = NumericProperty(1024)

    def __init__(self, **kwargs):
        init_text = kwargs.get('text', "") or ""
        # strip any control chars if present
        for ch in ("\u200F", "\u202B", "\u202C"):
            init_text = init_text.replace(ch, "")
        super().__init__(**kwargs)
        if init_text:
            self.arabic_buf = init_text
            try:
                self.text = _reshape_display_for_widget_text(self.arabic_buf)
            except Exception:
                self.text = self.arabic_buf
        else:
            self.arabic_buf = ""
        # ensure cursor at end (safe)
        try:
            idx = len(self.text or "")
            try:
                self.cursor = self.get_cursor_from_index(idx)
            except Exception:
                self.cursor = (idx, 0)
        except Exception:
            pass

    def get_plain(self):
        return (self.arabic_buf or "")

    def _move_cursor_to_end(self):
        """Utility: move cursor to end robustly."""
        try:
            idx = len(self.text or "")
            try:
                # preferred: get cursor tuple from index
                self.cursor = self.get_cursor_from_index(idx)
            except Exception:
                # fallback if method missing
                self.cursor = (idx, 0)
        except Exception:
            pass

    def insert_text(self, substring, from_undo=False):
        # limit check
        try:
            if not from_undo and (len(self.arabic_buf or "") + len(substring or "")) > (self.max_chars or 1024):
                return
        except Exception:
            pass

        try:
            if substring is None:
                substring = ""
            plain = self.arabic_buf or ""
            try:
                # try to get cursor position in logical buffer; fallback to end
                ci = self.cursor_index()
            except Exception:
                ci = len(plain)
            if ci < 0: ci = 0
            if ci > len(plain): ci = len(plain)
            new_plain = plain[:ci] + substring + plain[ci:]
            self.arabic_buf = new_plain
            # update display (reshaped)
            try:
                self.text = _reshape_display_for_widget_text(self.arabic_buf)
            except Exception:
                self.text = self.arabic_buf
            # move cursor to end
            self._move_cursor_to_end()
            # do not call super().insert_text because we handled display
            return
        except Exception:
            try:
                return super().insert_text(substring, from_undo=from_undo)
            except Exception:
                return

    def do_backspace(self, from_undo=False, mode='bkspc'):
        try:
            plain = self.arabic_buf or ""
            try:
                ci = self.cursor_index()
            except Exception:
                ci = len(plain)
            if ci <= 0 and len(plain) == 0:
                return
            if ci <= 0:
                new_plain = plain[:-1]
            else:
                new_plain = plain[:max(0, ci-1)] + plain[ci:]
            self.arabic_buf = new_plain
            try:
                self.text = _reshape_display_for_widget_text(self.arabic_buf)
            except Exception:
                self.text = self.arabic_buf
            # move cursor to end
            self._move_cursor_to_end()
            return
        except Exception:
            try:
                return super().do_backspace(from_undo=from_undo, mode=mode)
            except Exception:
                return

# --------------------------
# Persian Date Converter - ENHANCED
# --------------------------
def gregorian_to_jalali(gy, gm, gd):
    """Convert Gregorian date to Jalali (Persian) date"""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gm > 2:
        gy2 = gy + 1
    else:
        gy2 = gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd

def get_jalali_date_string():
    """Get current Jalali date as string in format YYYY/MM/DD"""
    now = datetime.datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"

def get_jalali_datetime_string():
    """Get current Jalali date and time as string"""
    now = datetime.datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {now.hour:02d}:{now.minute:02d}"

def get_jalali_date_persian_string():
    """Get current Jalali date as Persian string"""
    now = datetime.datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    
    # نام ماه‌های شمسی
    months = [
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
    ]
    
    month_name = months[jm - 1] if 1 <= jm <= 12 else "نامعلوم"
    return f"{jd} {month_name} {jy}"

# --------------------------
# English number converter
# --------------------------
def convert_to_english_numbers(text):
    """Convert Persian/Arabic numbers to English numbers"""
    if not text:
        return text
    
    persian_to_english = {
        '۰': '0', '٠': '0',
        '۱': '1', '١': '1', 
        '۲': '2', '٢': '2',
        '۳': '3', '٣': '3',
        '۴': '4', '٤': '4',
        '۵': '5', '٥': '5',
        '۶': '6', '٦': '6',
        '۷': '7', '٧': '7',
        '۸': '8', '٨': '8',
        '۹': '9', '٩': '9'
    }
    
    result = []
    for char in str(text):
        result.append(persian_to_english.get(char, char))
    
    return ''.join(result)

# --------------------------
# Auto-deletion of old sold products
# --------------------------
def delete_old_sold_products(db_path, months=3):
    """حذف خودکار محصولات فروخته شده قدیمی"""
    try:
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=months*30)).isoformat()
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # پیدا کردن محصولات فروخته شده قدیمی
        c.execute('''
            SELECT id, image, thumb, sold_invoice 
            FROM products 
            WHERE sold_invoice IS NOT NULL AND sold_invoice != '' 
            AND created_at < ?
        ''', (cutoff_date,))
        
        old_products = c.fetchall()
        
        deleted_count = 0
        for product_id, image, thumb, invoice in old_products:
            try:
                # حذف فایل‌های عکس
                if image and os.path.exists(image):
                    os.remove(image)
                if thumb and os.path.exists(thumb):
                    os.remove(thumb)
                
                # حذف از دیتابیس
                c.execute('DELETE FROM products WHERE id = ?', (product_id,))
                deleted_count += 1
                
                # حذف فایل‌های متادیتا اگر وجود دارند
                sold_dir = os.path.join(os.path.dirname(db_path), 'sold', invoice)
                if os.path.exists(sold_dir):
                    meta_file = os.path.join(sold_dir, f"metadata_{product_id}.json")
                    if os.path.exists(meta_file):
                        os.remove(meta_file)
                        
            except Exception as e:
                print(f"Error deleting product {product_id}: {e}")
                continue
        
        conn.commit()
        conn.close()
        
        return deleted_count
        
    except Exception as e:
        print(f"Error in auto-deletion: {e}")
        return 0

# --------------------------
# KV — UI (use ArMDTextField where we need Arabic/Persian typing)
# --------------------------
KV = '''
<MDLabel>:
    font_size: "14sp"
    
ScreenManager:
    MainScreen:
    CategoryScreen:
    BaseProductsScreen:
    AddProductScreen:
    BatchAddScreen:
    SoldScreen:
    StatsScreen:
    DetailScreen:
    SettingsScreen:
    WeightInventoryScreen:

<MainScreen>:
    name: 'main'
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            id: topbar
            title: app.reshape("امار طلا")
            font_name: app.font_name
            elevation: 6
            right_action_items: [["magnify", lambda x: None], ["plus", lambda x: app.open_add_screen()]]

        MDBoxLayout:
            padding: "10dp"
            spacing: "8dp"
            size_hint_y: None
            height: "64dp"
            ArMDTextField:
                id: search_field
                hint_text: app.reshape("جستجو: نام، شماره گروه، دسته یا آیدی محصول")
                mode: "rectangle"
                size_hint_x: .82
                on_text: app.search_products(self.arabic_buf)
                font_name: app.font_name
                halign: "right"
                multiline: False
                size_hint_y: None
                height: "44dp"
            MDRaisedButton:
                id: filter_btn
                text: app.reshape("فیلتر")
                pos_hint: {"center_y": .5}
                on_release: app.open_filter_menu(self)
                size_hint_x: .18

        MDBoxLayout:
            padding: "10dp"
            size_hint_y: None
            height: "120dp"
            orientation: "vertical"
            MDLabel:
                id: total_count_lbl
                text: app.reshape("کل محصولات: 0")
                halign: "right"
                font_name: app.font_name
                size_hint_y: None
                height: "30dp"
                theme_text_color: "Primary"
            ScrollView:
                do_scroll_x: True
                do_scroll_y: False
                MDBoxLayout:
                    id: categories_box
                    orientation: 'horizontal'
                    adaptive_height: True
                    size_hint_x: None
                    width: self.minimum_width
                    spacing: "8dp"
                    padding: "6dp"

        ScrollView:
            MDGridLayout:
                id: cards_box
                cols: 1
                adaptive_height: True
                padding: "12dp"
                spacing: "12dp"

        MDBoxLayout:
            size_hint_y: None
            height: '64dp'
            padding: '12dp'
            MDRaisedButton:
                text: app.reshape('افزودن محصول جدید')
                on_release: app.open_add_screen()
                md_bg_color: app.theme_cls.primary_color

    MDFloatingActionButton:
        icon: "dots-vertical"
        md_bg_color: app.theme_cls.primary_color
        pos_hint: {"right": .96, "y": .02}
        on_release: app.open_actions_menu()

<CategoryScreen>:
    name: 'category'
    title: ""
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            title: app.reshape(root.title)
            font_name: app.font_name
            id: cat_top
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
        ScrollView:
            MDGridLayout:
                id: bases_box
                cols: 1
                adaptive_height: True
                padding: '12dp'
                spacing: '12dp'

<BaseProductsScreen>:
    name: 'base_products'
    title: ""
    category: ""
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            id: base_top
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.open_category(root.category)]]
        ScrollView:
            MDGridLayout:
                id: base_products_box
                cols: 1
                adaptive_height: True
                padding: '12dp'
                spacing: '10dp'

<AddProductScreen>:
    name: 'add'
    title: "add new"
    BoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            id: add_bar
            title: root.title
            elevation: 6
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
            size_hint_y: None
            height: "56dp"
        
        ScrollView:
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: "16dp"
                spacing: "16dp"

                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: "12dp"
                    
                    MDCard:
                        size_hint_y: None
                        height: "400dp"
                        padding: "16dp"
                        radius: [12,]
                        elevation: 3
                        BoxLayout:
                            orientation: 'vertical'
                            spacing: "12dp"
                            
                            ArMDTextField:
                                id: name_input
                                hint_text: app.reshape("نام محصول (مثلاً: النگو)")
                                font_name: app.font_name
                                halign: "right"
                                mode: "rectangle"
                                multiline: False
                                size_hint_y: None
                                height: "56dp"
                            
                            BoxLayout:
                                orientation: 'horizontal'
                                size_hint_y: None
                                height: "56dp"
                                spacing: "8dp"
                                ArMDTextField:
                                    id: category_input
                                    hint_text: app.reshape("دسته‌بندی")
                                    font_name: app.font_name
                                    halign: "right"
                                    mode: "rectangle"
                                    multiline: False
                                MDIconButton:
                                    icon: "menu-down"
                                    size_hint_x: None
                                    width: "48dp"
                                    on_release: app.open_category_menu(category_input)

                            BoxLayout:
                                orientation: 'horizontal'
                                size_hint_y: None
                                height: "56dp"
                                spacing: "8dp"
                                ArMDTextField:
                                    id: base_number_input
                                    hint_text: app.reshape("شماره گروه / صفحه")
                                    font_name: app.font_name
                                    halign: "right"
                                    mode: "rectangle"
                                    multiline: False
                                MDTextField:
                                    id: quantity_input
                                    hint_text: app.reshape("تعداد")
                                    input_filter: "int"
                                    font_name: app.font_name
                                    halign: "right"
                                    mode: "rectangle"
                                    multiline: False

                            BoxLayout:
                                orientation: 'horizontal'
                                size_hint_y: None
                                height: "56dp"
                                spacing: "8dp"
                                MDTextField:
                                    id: weight_input
                                    hint_text: app.reshape("وزن (گرم)")
                                    input_filter: "float"
                                    font_name: app.font_name
                                    halign: "right"
                                    mode: "rectangle"
                                    multiline: False
                                ArMDTextField:
                                    id: purity_input
                                    hint_text: app.reshape("عیار (اختیاری)")
                                    font_name: app.font_name
                                    halign: "right"
                                    mode: "rectangle"
                                    multiline: False

                            ArMDTextField:
                                id: notes_input
                                hint_text: app.reshape("توضیحات (اختیاری)")
                                font_name: app.font_name
                                halign: "right"
                                mode: "rectangle"
                                size_hint_y: None
                                height: "120dp"
                                multiline: True

                    MDCard:
                        size_hint_y: None
                        height: "240dp"
                        padding: "16dp"
                        radius: [12,]
                        elevation: 2
                        BoxLayout:
                            orientation: 'horizontal'
                            spacing: "12dp"
                            
                            Image:
                                id: preview_image
                                source: app.default_image
                                size_hint_x: 0.4
                                allow_stretch: True
                                keep_ratio: True
                            
                            BoxLayout:
                                orientation: 'vertical'
                                spacing: "8dp"
                                size_hint_x: 0.6
                                
                                MDRaisedButton:
                                    id: pick_img_btn
                                    text: app.reshape("انتخاب عکس از گالری")
                                    on_release: app.pick_image()
                                    md_bg_color: app.theme_cls.primary_color
                                    size_hint_y: None
                                    height: "48dp"
                                
                                MDFlatButton:
                                    text: app.reshape("ثبت عکس گروه برای این دسته/گروه")
                                    on_release: app.pick_base_image_from_add()
                                    size_hint_y: None
                                    height: "48dp"
                                
                                MDLabel:
                                    id: image_path_label
                                    text: app.reshape("عکسی انتخاب نشده")
                                    font_name: app.font_name
                                    halign: "right"
                                    theme_text_color: "Secondary"
                                    size_hint_y: None
                                    height: "40dp"

                BoxLayout:
                    orientation: 'horizontal'
                    size_hint_y: None
                    height: "64dp"
                    padding: "0dp", "16dp", "0dp", "0dp"
                    spacing: "12dp"
                    
                    MDRaisedButton:
                        text: app.reshape("ذخیره")
                        on_release: app.save_product()
                        md_bg_color: app.theme_cls.primary_color
                        size_hint_x: 0.5
                    
                    MDFlatButton:
                        text: app.reshape("انصراف")
                        on_release: app.back_to_main()
                        size_hint_x: 0.5

<BatchAddScreen>:
    name: 'batch_add'
    title: ""
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back_to_add_from_batch()]]
        ScrollView:
            MDGridLayout:
                id: batch_container
                cols: 1
                adaptive_height: True
                padding: '12dp'
                spacing: '12dp'
        MDBoxLayout:
            size_hint_y: None
            height: '64dp'
            padding: '12dp'
            spacing: '12dp'
            MDRaisedButton:
                text: app.reshape('ذخیره همه')
                on_release: app.save_batch_products()
                md_bg_color: app.theme_cls.primary_color
            MDFlatButton:
                text: app.reshape('انصراف')
                on_release: app.back_to_add_from_batch()

<SoldScreen>:
    name: 'sold'
    title: app.reshape("فروش رفته‌ها")
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
        
        MDBoxLayout:
            padding: "10dp"
            spacing: "8dp"
            size_hint_y: None
            height: "64dp"
            ArMDTextField:
                id: search_invoice_field
                hint_text: app.reshape("جستجو بر اساس شماره فاکتور")
                mode: "rectangle"
                size_hint_x: 0.8
                on_text: app.search_sold_by_invoice(self.arabic_buf)
                font_name: app.font_name
                halign: "right"
                multiline: False
                size_hint_y: None
                height: "44dp"
            MDFlatButton:
                text: app.reshape("پاک کردن")
                on_release: app.clear_sold_search()
                size_hint_x: 0.2
                size_hint_y: None
                height: "44dp"

        ScrollView:
            MDGridLayout:
                id: sold_cards_box
                cols: 1
                adaptive_height: True
                padding: "12dp"
                spacing: "12dp"

<StatsScreen>:
    name: 'stats'
    title: app.reshape("آمار فروش")
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            font_name: app.font_name
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
        ScrollView:
            MDGridLayout:
                id: stats_box
                cols: 1
                adaptive_height: True
                padding: "12dp"
                spacing: "12dp"

<DetailScreen>:
    name: 'detail'
    detail_title: app.reshape("جزئیات محصول")
    BoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            title: "جزئیات محصول"
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
            right_action_items: [["pencil", lambda x: app._open_edit(app.current_product['id'])], ["delete", lambda x: app._confirm_delete(app.current_product['id'])]]
            size_hint_y: None
            height: "56dp"
        
        ScrollView:
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: "16dp"
                spacing: "16dp"
                
                MDCard:
                    orientation: 'vertical'
                    padding: "16dp"
                    spacing: "8dp"
                    radius: [12,]
                    elevation: 3
                    size_hint_y: None
                    height: "320dp"
                    
                    MDLabel:
                        text: root.detail_title
                        font_name: app.font_name
                        halign: "center"
                        theme_text_color: "Primary"
                        font_style: "H6"
                        size_hint_y: None
                        height: "40dp"
                    
                    Image:
                        id: detail_image
                        source: app.default_image
                        size_hint_y: None
                        height: "200dp"
                        allow_stretch: True
                        keep_ratio: True
                        radius: [8,]

                GridLayout:
                    cols: 2
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: "12dp"
                    padding: "8dp"
                    
                    MDCard:
                        font_name: app.font_name
                        halign: 'right'
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("نام محصول")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_name
                            text: app.reshape("")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"
                            
                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("کد محصول")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_code
                            text: ""
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"

                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("دسته‌بندی")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_category
                            text: ""
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"
                            
                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("شماره گروه")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_base
                            text: ""
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"

                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("وزن")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_weight
                            text: ""
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"
                            
                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("تعداد")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_quantity
                            text: ""
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"

                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("عیار")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_purity
                            text: ""
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"
                            
                    MDCard:
                        orientation: 'vertical'
                        padding: "16dp"
                        spacing: "8dp"
                        radius: [8,]
                        elevation: 2
                        size_hint_y: None
                        height: "100dp"
                        MDLabel:
                            text: app.reshape("وضعیت")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Primary"
                            bold: True
                            size_hint_y: None
                            height: "30dp"
                        MDLabel:
                            id: detail_status
                            text: app.reshape("موجود")
                            font_name: app.font_name
                            halign: "center"
                            theme_text_color: "Secondary"

                MDCard:
                    orientation: 'vertical'
                    padding: "16dp"
                    spacing: "8dp"
                    radius: [12,]
                    elevation: 2
                    size_hint_y: None
                    height: "150dp"
                    
                    MDLabel:
                        text: app.reshape("توضیحات")
                        font_name: app.font_name
                        halign: "right"
                        theme_text_color: "Primary"
                        bold: True
                        size_hint_y: None
                        height: "30dp"
                    
                    ScrollView:
                        MDLabel:
                            id: detail_notes
                            text: ""
                            font_name: app.font_name
                            halign: "right"
                            theme_text_color: "Secondary"
                            size_hint_y: None
                            height: self.texture_size[1] + 20 if self.texture_size else 0

        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: "80dp"
            padding: "16dp"
            spacing: "12dp"
            
            MDRaisedButton:
                text: app.reshape('فروش / ثبت فروش')
                on_release: app.sell_current_product()
                md_bg_color: app.theme_cls.primary_color
                size_hint_x: 0.6
            
            MDFlatButton:
                text: app.reshape('ویرایش')
                on_release: app._open_edit(app.current_product['id'])
                size_hint_x: 0.4

<SettingsScreen>:
    name: 'settings'
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            title: app.reshape("تنظیمات")
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
        ScrollView:
            MDGridLayout:
                cols: 1
                adaptive_height: True
                padding: "12dp"
                spacing: "8dp"
                MDRaisedButton:
                    text: app.reshape("بکاپ کامل (DB + عکس‌ها)")
                    on_release: app.backup_all()
                MDRaisedButton:
                    text: app.reshape("بازیابی از ZIP")
                    on_release: app.restore_from_zip()
                MDLabel:
                    text: app.reshape("فایل‌ها در:")
                    font_name: app.font_name
                    halign: "right"
                    theme_text_color: "Secondary"
                MDLabel:
                    text: app.storage_path
                    font_name: app.font_name
                    halign: "right"
                    theme_text_color: "Secondary"

<WeightInventoryScreen>:
    name: 'weight_inventory'
    title: app.reshape("موجودی وزنی")
    MDBoxLayout:
        orientation: 'vertical'
        MDTopAppBar:
            title: root.title
            left_action_items: [["arrow-left", lambda x: app.back_to_main()]]
        ScrollView:
            MDGridLayout:
                id: weight_inventory_box
                cols: 1
                adaptive_height: True
                padding: "12dp"
                spacing: "12dp"
'''

# --------------------------
# Enhanced Database helper with performance optimizations
# --------------------------
class DBHelper:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA cache_size = -64000")
        self.create_tables()
        self._migrate_schema()
        self.create_indexes()

    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT UNIQUE,
                name TEXT,
                category TEXT,
                base_number TEXT,
                weight REAL,
                quantity INTEGER,
                purity TEXT,
                image TEXT,
                thumb TEXT,
                notes TEXT,
                created_at TEXT,
                sold_invoice TEXT,
                sold_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS bases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                base_number TEXT,
                image TEXT,
                UNIQUE(category, base_number)
            )
        ''')
        self.conn.commit()

    def create_indexes(self):
        """Create indexes for faster searches"""
        c = self.conn.cursor()
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)",
            "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)",
            "CREATE INDEX IF NOT EXISTS idx_products_base_number ON products(base_number)",
            "CREATE INDEX IF NOT EXISTS idx_products_product_code ON products(product_code)",
            "CREATE INDEX IF NOT EXISTS idx_products_sold_invoice ON products(sold_invoice)",
            "CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_products_sold_at ON products(sold_at)",
            "CREATE INDEX IF NOT EXISTS idx_bases_category_number ON bases(category, base_number)"
        ]
        for index_sql in indexes:
            try:
                c.execute(index_sql)
            except Exception as e:
                print(f"Error creating index: {e}")
        self.conn.commit()

    def _migrate_schema(self):
        c = self.conn.cursor()
        try:
            c.execute("PRAGMA table_info(products)")
            cols = [r[1] for r in c.fetchall()]
        except Exception:
            cols = []
        if 'product_code' not in cols:
            try:
                c.execute("ALTER TABLE products ADD COLUMN product_code TEXT")
            except Exception:
                pass
        if 'created_at' not in cols:
            try:
                c.execute("ALTER TABLE products ADD COLUMN created_at TEXT")
            except Exception:
                pass
        if 'sold_invoice' not in cols:
            try:
                c.execute("ALTER TABLE products ADD COLUMN sold_invoice TEXT")
            except Exception:
                pass
        if 'sold_at' not in cols:
            try:
                c.execute("ALTER TABLE products ADD COLUMN sold_at TEXT")
            except Exception:
                pass
        self.conn.commit()

    def add_product(self, p):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO products
            (product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            p.get('product_code'),
            p['name'],
            p['category'],
            p['base_number'],
            p['weight'],
            p['quantity'],
            p.get('purity'),
            p.get('image'),
            p.get('thumb'),
            p.get('notes'),
            p.get('created_at'),
            p.get('sold_invoice') if p.get('sold_invoice') else None,
            p.get('sold_at') if p.get('sold_at') else None
        ))
        self.conn.commit()
        return c.lastrowid

    def update_product(self, pid, p):
        c = self.conn.cursor()
        c.execute('''
            UPDATE products SET
                product_code=?, name=?, category=?, base_number=?, weight=?, quantity=?, purity=?, image=?, thumb=?, notes=?, created_at=?, sold_invoice=?, sold_at=?
            WHERE id=?
        ''', (
            p.get('product_code'),
            p['name'],
            p['category'],
            p['base_number'],
            p['weight'],
            p['quantity'],
            p.get('purity'),
            p.get('image'),
            p.get('thumb'),
            p.get('notes'),
            p.get('created_at'),
            p.get('sold_invoice'),
            p.get('sold_at'),
            pid
        ))
        self.conn.commit()

    def delete_product(self, pid):
        try:
            pid_int = int(pid)
        except Exception:
            return
        c = self.conn.cursor()
        c.execute('SELECT image, thumb FROM products WHERE id=?', (pid_int,))
        row = c.fetchone()
        if row:
            img, thumb = row
            try:
                if img and os.path.exists(img):
                    os.remove(img)
            except Exception:
                pass
            try:
                if thumb and os.path.exists(thumb):
                    os.remove(thumb)
            except Exception:
                pass
        c.execute('DELETE FROM products WHERE id=?', (pid_int,))
        self.conn.commit()

    def get_all_products(self, include_sold=False, limit=None, offset=0):
        c = self.conn.cursor()
        query = 'SELECT id, product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at FROM products'
        if not include_sold:
            query += ' WHERE COALESCE(sold_invoice, "") = ""'
        query += ' ORDER BY id DESC'
        if limit:
            query += f' LIMIT {limit} OFFSET {offset}'
        c.execute(query)
        rows = c.fetchall()
        products = []
        for r in rows:
            products.append({
                'id': r[0],
                'product_code': r[1],
                'name': r[2],
                'category': r[3],
                'base_number': r[4],
                'weight': r[5],
                'quantity': r[6],
                'purity': r[7],
                'image': r[8],
                'thumb': r[9],
                'notes': r[10],
                'created_at': r[11],
                'sold_invoice': r[12] if len(r) > 12 else None,
                'sold_at': r[13] if len(r) > 13 else None
            })
        return products

    def get_total_products_count(self):
        """گرفتن تعداد کل محصولات (غیر فروخته شده)"""
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM products WHERE COALESCE(sold_invoice, "") = ""')
        return c.fetchone()[0]

    def get_category_counts(self):
        """گرفتن تعداد محصولات هر دسته"""
        c = self.conn.cursor()
        c.execute('''
            SELECT category, COUNT(*) as count 
            FROM products 
            WHERE COALESCE(sold_invoice, "") = ""
            GROUP BY category
        ''')
        rows = c.fetchall()
        return {row[0]: row[1] for row in rows}

    def search(self, q, include_sold=False, limit=100):
        if not q:
            return self.get_all_products(include_sold=include_sold, limit=limit)
            
        q_like = f'%{q}%'
        c = self.conn.cursor()
        if include_sold:
            c.execute('''
                SELECT id, product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at
                FROM products
                WHERE name LIKE ? OR base_number LIKE ? OR category LIKE ? OR product_code LIKE ?
                ORDER BY 
                    CASE WHEN product_code LIKE ? THEN 1
                         WHEN name LIKE ? THEN 2
                         ELSE 3
                    END,
                    id DESC
                LIMIT ?
            ''', (q_like, q_like, q_like, q_like, f'{q}%', f'{q}%', limit))
        else:
            c.execute('''
                SELECT id, product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at
                FROM products
                WHERE (name LIKE ? OR base_number LIKE ? OR category LIKE ? OR product_code LIKE ?) 
                AND COALESCE(sold_invoice, "") = ""
                ORDER BY 
                    CASE WHEN product_code LIKE ? THEN 1
                         WHEN name LIKE ? THEN 2
                         ELSE 3
                    END,
                    id DESC
                LIMIT ?
            ''', (q_like, q_like, q_like, q_like, f'{q}%', f'{q}%', limit))
        rows = c.fetchall()
        products = []
        for r in rows:
            products.append({
                'id': r[0],
                'product_code': r[1],
                'name': r[2],
                'category': r[3],
                'base_number': r[4],
                'weight': r[5],
                'quantity': r[6],
                'purity': r[7],
                'image': r[8],
                'thumb': r[9],
                'notes': r[10],
                'created_at': r[11],
                'sold_invoice': r[12] if len(r) > 12 else None,
                'sold_at': r[13] if len(r) > 13 else None
            })
        return products

    def get_product_by_code(self, code):
        c = self.conn.cursor()
        c.execute('SELECT id, product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at FROM products WHERE product_code=?', (code,))
        r = c.fetchone()
        if not r:
            return None
        return {
            'id': r[0],
            'product_code': r[1],
            'name': r[2],
            'category': r[3],
            'base_number': r[4],
            'weight': r[5],
            'quantity': r[6],
            'purity': r[7],
            'image': r[8],
            'thumb': r[9],
            'notes': r[10],
            'created_at': r[11],
            'sold_invoice': r[12] if len(r) > 12 else None,
            'sold_at': r[13] if len(r) > 13 else None
        }

    def get_bases_by_category(self, category):
        c = self.conn.cursor()
        c.execute('''
            SELECT COALESCE(base_number, '-') as b, COUNT(*) as cnt
            FROM products
            WHERE category=? AND COALESCE(sold_invoice, "") = ""
            GROUP BY b
            ORDER BY cnt DESC
        ''', (category.strip(),))
        rows = c.fetchall()
        return [{'base_number': r[0], 'count': r[1]} for r in rows]

    def get_products_by_category_and_base(self, category, base_number, limit=100):
        c = self.conn.cursor()
        c.execute('''
            SELECT id, product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at
            FROM products
            WHERE category=? AND base_number=? AND COALESCE(sold_invoice, "") = ""
            ORDER BY id DESC
            LIMIT ?
        ''', (category.strip(), base_number, limit))
        rows = c.fetchall()
        prods = []
        for r in rows:
            prods.append({
                'id': r[0],
                'product_code': r[1],
                'name': r[2],
                'category': r[3],
                'base_number': r[4],
                'weight': r[5],
                'quantity': r[6],
                'purity': r[7],
                'image': r[8],
                'thumb': r[9],
                'notes': r[10],
                'created_at': r[11],
                'sold_invoice': r[12] if len(r) > 12 else None,
                'sold_at': r[13] if len(r) > 13 else None
            })
        return prods

    def set_base_image(self, category, base_number, image_path):
        c = self.conn.cursor()
        try:
            c.execute('UPDATE bases SET image=? WHERE category=? AND base_number=?', (image_path, category, base_number))
            if c.rowcount == 0:
                c.execute('INSERT INTO bases (category, base_number, image) VALUES (?, ?, ?)', (category, base_number, image_path))
            self.conn.commit()
        except Exception as e:
            print("set_base_image error:", e)

    def get_base_image(self, category, base_number):
        c = self.conn.cursor()
        c.execute('SELECT image FROM bases WHERE category=? AND base_number=?', (category.strip(), base_number))
        r = c.fetchone()
        return r[0] if r else None

    def mark_as_sold(self, pid, invoice, sold_image=None, sold_thumb=None, metadata=None, user_data_dir=None):
        try:
            pid_int = int(pid)
        except Exception:
            return
        c = self.conn.cursor()
        c.execute('SELECT product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at FROM products WHERE id=?', (pid_int,))
        r = c.fetchone()
        if not r:
            return
        product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at = r
        img_to_set = sold_image if sold_image else image
        thumb_to_set = sold_thumb if sold_thumb else thumb
        try:
            c.execute('''
                UPDATE products SET sold_invoice=?, image=?, thumb=?, quantity=?, sold_at=?
                WHERE id=?
            ''', (invoice, img_to_set, thumb_to_set, 0, get_jalali_datetime_string(), pid_int))
            self.conn.commit()
            if metadata:
                ud = user_data_dir or os.path.dirname(self.db_path)
                sold_dir = ensure_dir(os.path.join(ud, 'sold', invoice))
                meta_fn = f"metadata_{pid_int}.json"
                with open(os.path.join(sold_dir, meta_fn), 'w', encoding='utf-8') as mf:
                    json.dump(metadata, mf, ensure_ascii=False, indent=2)
        except Exception as e:
            print("mark_as_sold error:", e)

    def get_weight_inventory(self):
        """محاسبه موجودی وزنی بر اساس دسته‌بندی"""
        c = self.conn.cursor()
        c.execute('''
            SELECT category, SUM(weight * quantity) as total_weight, COUNT(*) as product_count
            FROM products 
            WHERE COALESCE(sold_invoice, "") = ""
            GROUP BY category
            ORDER BY total_weight DESC
        ''')
        rows = c.fetchall()
        return [{'category': row[0], 'total_weight': row[1] or 0.0, 'product_count': row[2]} for row in rows]

    def get_total_weight_inventory(self):
        """محاسبه کل موجودی وزنی"""
        c = self.conn.cursor()
        c.execute('''
            SELECT SUM(weight * quantity) as total_weight, COUNT(*) as total_count
            FROM products 
            WHERE COALESCE(sold_invoice, "") = ""
        ''')
        row = c.fetchone()
        return {'total_weight': row[0] or 0.0, 'total_count': row[1] or 0}

    def get_recent_invoices(self, limit=10):
        """گرفتن آخرین فاکتورها"""
        c = self.conn.cursor()
        c.execute('''
            SELECT DISTINCT sold_invoice, MAX(created_at) as latest_date
            FROM products 
            WHERE sold_invoice IS NOT NULL AND sold_invoice != ''
            GROUP BY sold_invoice
            ORDER BY latest_date DESC
            LIMIT ?
        ''', (limit,))
        rows = c.fetchall()
        return [row[0] for row in rows]

    def get_products_by_invoices(self, invoices, limit=200):
        """گرفتن محصولات بر اساس لیست فاکتورها"""
        if not invoices:
            return []
        placeholders = ','.join('?' for _ in invoices)
        c = self.conn.cursor()
        c.execute(f'''
            SELECT id, product_code, name, category, base_number, weight, quantity, purity, image, thumb, notes, created_at, sold_invoice, sold_at
            FROM products
            WHERE sold_invoice IN ({placeholders})
            ORDER BY sold_invoice DESC, id DESC
            LIMIT ?
        ''', invoices + [limit])
        rows = c.fetchall()
        products = []
        for r in rows:
            products.append({
                'id': r[0],
                'product_code': r[1],
                'name': r[2],
                'category': r[3],
                'base_number': r[4],
                'weight': r[5],
                'quantity': r[6],
                'purity': r[7],
                'image': r[8],
                'thumb': r[9],
                'notes': r[10],
                'created_at': r[11],
                'sold_invoice': r[12] if len(r) > 12 else None,
                'sold_at': r[13] if len(r) > 13 else None
            })
        return products

    def clear_all_data(self):
        """پاک کردن تمام داده‌های برنامه"""
        c = self.conn.cursor()
        try:
            # پاک کردن جداول
            c.execute('DELETE FROM products')
            c.execute('DELETE FROM bases')
            # بهینه‌سازی پایگاه داده بعد از پاک کردن
            c.execute('VACUUM')
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error clearing data: {e}")
            return False

# --------------------------
# Utilities: images, thumbs with caching
# --------------------------
def make_unique_filename(orig_name):
    ext = os.path.splitext(orig_name)[1] or ".jpg"
    return f"{uuid.uuid4().hex}{ext}"

def create_thumbnail(src_path, dest_path, size=(400,400)):
    if PILImage is None:
        try:
            shutil.copy2(src_path, dest_path)
            return True
        except Exception:
            return False
    try:
        # بررسی کش اول
        cache_key = f"thumb_{src_path}_{size[0]}_{size[1]}"
        cached_path = Cache.get('image_load', cache_key)
        if cached_path and os.path.exists(cached_path):
            shutil.copy2(cached_path, dest_path)
            return True
            
        img = PILImage.open(src_path)
        img.thumbnail(size)
        ensure_dir(os.path.dirname(dest_path))
        img.save(dest_path)
        
        # کش کردن تصویر کوچک شده
        Cache.append('image_load', cache_key, dest_path)
        return True
    except Exception:
        try:
            shutil.copy2(src_path, dest_path)
            return True
        except Exception:
            return False

# --------------------------
# Enhanced Screens
# --------------------------
class MainScreen(Screen): 
    current_page = NumericProperty(0)
    page_size = NumericProperty(20)

class CategoryScreen(Screen): pass

class BaseProductsScreen(Screen):
    title = StringProperty("")
    category = StringProperty("")
    base_number = StringProperty("")
    
    # def on_enter(self):
    #     """بارگذاری محصولات هنگام ورود به صفحه"""
    #     app = MDApp.get_running_app()
    #     if app:
    #         app.open_base_products()

class AddProductScreen(Screen): pass
class BatchAddScreen(Screen):
    title = StringProperty("")
class SoldScreen(Screen):
    title = StringProperty("فروش رفته‌ها")
class StatsScreen(Screen):
    title = StringProperty("آمار فروش")
class DetailScreen(Screen):
    detail_title = StringProperty("جزئیات محصول")
class SettingsScreen(Screen): pass
class WeightInventoryScreen(Screen):
    title = StringProperty("موجودی وزنی")

# --------------------------
# Enhanced Main App with New Features
# --------------------------
class GoldApp(MDApp):
    db = None
    images_dir = None
    thumbs_dir = None
    db_path = None
    storage_path = StringProperty("")
    default_image = StringProperty("")
    current_product = None
    editing_id = None
    search_clock = None
    current_search_term = ""

    prefix_map = {
        'النگو': 'L',
        'گوشواره': 'G',
        'دستبند': 'D',
        'گردنبند': 'N',
        'انگشتر': 'R',
        'پلاک': 'P',
        'پارسیان': 'PS',
        'زنجیر': 'Z',
        'شمش': 'SH',
        'سکه': 'S',
        'متفرقه': 'M',
        'ابشده': 'A'
    }
    category_options = ['النگو','گوشواره','دستبند','گردنبند','انگشتر','پلاک','پارسیان','زنجیر','شمش','سکه','متفرقه','ابشده']
    _batch_entries = ListProperty([])

    def notify(self, msg):
        try:
            toast(self.reshape(msg))
        except Exception:
            print("NOTIFY:", msg)

    def reshape(self, s):
        return reshape_text_if_needed(s)

    @property
    def font_name(self):
        return "AppFont" if _font_registered else "Roboto"

    def build(self):
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Amber"
        if os.name == 'posix' and "DISPLAY" in os.environ:
            Window.size = (420, 820)

        # storage path selection:
        if kivy_platform == 'android':
            try:
                # استفاده از مسیر ذخیره‌سازی استاندارد اندروید
                from android.storage import primary_external_storage_path
                ud = primary_external_storage_path()
                ud = os.path.join(ud, "GoldShopManager")
            except Exception:
                try:
                    ud = self.user_data_dir
                except Exception:
                    ud = os.path.join(str(Path.home()), ".local", "share", "gold_app")
        else:
            ud = os.path.join(os.getcwd(), "gold_app_data")

        self._user_data_dir = ensure_dir(ud)
        self.images_dir = ensure_dir(os.path.join(self._user_data_dir, 'images'))
        self.thumbs_dir = ensure_dir(os.path.join(self._user_data_dir, 'thumbs'))
        self.db_path = os.path.join(self._user_data_dir, 'goldshop.db')
        self.storage_path = str(Path(self._user_data_dir))
        self.default_image = os.path.join(self.images_dir, 'no-image.png')
        if not os.path.exists(self.default_image):
            try:
                if PILImage:
                    img = PILImage.new("RGB", (800,600), color=(250,250,250))
                    img.save(self.default_image)
                else:
                    open(self.default_image, 'wb').close()
            except Exception:
                pass

        self.db = DBHelper(self.db_path)

        # اجرای پاکسازی خودکار محصولات فروخته شده قدیمی
        self.auto_cleanup_old_sold_on_start()

        # load KV
        root = Builder.load_string(KV)
        self.root = root

        Clock.schedule_once(lambda dt: self.setup_category_menu(), 0.1)
        Clock.schedule_once(lambda dt: self.refresh_product_list(), 0.3)
        Clock.schedule_once(lambda dt: self._fix_topbar_titles(), 0.25) 

        return root

    def auto_cleanup_old_sold_on_start(self):
        """پاکسازی خودکار محصولات فروخته شده قدیمی هنگام راه‌اندازی برنامه"""
        try:
            deleted_count = delete_old_sold_products(self.db_path, months=3)
            if deleted_count > 0:
                print(f"Auto-deleted {deleted_count} old sold products")
        except Exception as e:
            print(f"Error in auto-cleanup on start: {e}")

    def auto_cleanup_old_sold(self):
        """پاکسازی خودکار محصولات فروخته شده قدیمی از طریق رابط کاربری"""
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton
        
        def perform_cleanup(*args):
            try:
                deleted_count = delete_old_sold_products(self.db_path, months=3)
                dialog.dismiss()
                if deleted_count > 0:
                    self.notify(f"{deleted_count} محصول فروخته شده قدیمی حذف شد")
                else:
                    self.notify("هیچ محصول فروخته شده قدیمی برای حذف یافت نشد")
            except Exception as e:
                self.notify(f"خطا در پاکسازی: {str(e)}")
        
        dialog = MDDialog(
            title=self.reshape("پاکسازی خودکار"),
            text=self.reshape("آیا مطمئن هستید که می‌خواهید محصولات فروخته شده قدیمی (بیش از 3 ماه) حذف شوند؟"),
            buttons=[
                MDFlatButton(
                    text=self.reshape("انصراف"),
                    on_release=lambda x: dialog.dismiss()
                ),
                MDFlatButton(
                    text=self.reshape("پاکسازی"),
                    on_release=perform_cleanup
                ),
            ]
        )
        dialog.open()

    def _contains_arabic(self, s):
        try:
            return bool(re.search(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]', s))
        except Exception:
            return False

    def _fix_topbar_titles(self, *a):
        try:
            from kivymd.uix.toolbar import MDTopAppBar
            
            print(">>> _fix_topbar_titles - COMPREHENSIVE SEARCH")

            def find_all_topbars(widget, path="", depth=0):
                topbars = []
                
                if depth > 20:
                    return topbars
                    
                if isinstance(widget, MDTopAppBar):
                    topbars.append((widget, path))
                    print(f"Found TopAppBar at depth {depth}: {path}")
                
                try:
                    if hasattr(widget, 'children'):
                        for child in widget.children:
                            topbars.extend(find_all_topbars(child, f"{path}.children", depth+1))
                    
                    if hasattr(widget, 'content'):
                        topbars.extend(find_all_topbars(widget.content, f"{path}.content", depth+1))
                    
                    if hasattr(widget, 'screens'):
                        for i, screen in enumerate(widget.screens):
                            topbars.extend(find_all_topbars(screen, f"{path}.screens[{i}]", depth+1))
                    
                    if hasattr(widget, 'current_screen') and widget.current_screen:
                        topbars.extend(find_all_topbars(widget.current_screen, f"{path}.current_screen", depth+1))
                        
                except Exception as e:
                    print(f"  Error exploring widget at {path}: {e}")
                
                return topbars
            
            all_topbars = find_all_topbars(self.root, "root")
            print(f">>> Total TopAppBars found: {len(all_topbars)}")
            
            for topbar, path in all_topbars:
                try:
                    print(f"Fixing TopAppBar at: {path}")
                    
                    old_title = getattr(topbar, 'title', '') or ''
                    if old_title:
                        new_title = self.reshape(old_title)
                        topbar.title = new_title
                        print(f"  Title: '{old_title}' -> '{new_title}'")
                    
                    if hasattr(topbar, 'font_name'):
                        topbar.font_name = getattr(self, 'font_name', '')
                    
                    fixed = False
                    
                    if hasattr(topbar, 'ids'):
                        for id_name, child in topbar.ids.items():
                            if hasattr(child, 'text') and ('title' in id_name.lower() or 'label' in id_name.lower()):
                                old_text = getattr(child, 'text', '') or ''
                                if old_text:
                                    new_text = self.reshape(old_text)
                                    child.text = new_text
                                    child.font_name = getattr(self, 'font_name', '')
                                    child.halign = 'right'
                                    if hasattr(child, 'text_size'):
                                        child.text_size = (child.width, None)
                                    print(f"  Fixed via ids['{id_name}']: '{old_text}' -> '{new_text}'")
                                    fixed = True
                    
                    if not fixed:
                        for child in topbar.walk(restrict=True):
                            if child == topbar:
                                continue
                            if hasattr(child, 'text') and hasattr(child, 'font_name'):
                                old_text = getattr(child, 'text', '') or ''
                                if old_text and any(keyword in str(child.__class__.__name__).lower() 
                                                for keyword in ['label', 'title']):
                                    new_text = self.reshape(old_text)
                                    child.text = new_text
                                    child.font_name = getattr(self, 'font_name', '')
                                    child.halign = 'right'
                                    if hasattr(child, 'text_size'):
                                        child.text_size = (child.width, None)
                                    print(f"  Fixed via walk: '{old_text}' -> '{new_text}'")
                                    fixed = True
                                    break
                    
                    if not fixed and hasattr(topbar, 'title_label'):
                        child = topbar.title_label
                        if hasattr(child, 'text'):
                            old_text = getattr(child, 'text', '') or ''
                            if old_text:
                                new_text = self.reshape(old_text)
                                child.text = new_text
                                child.font_name = getattr(self, 'font_name', '')
                                child.halign = 'right'
                                if hasattr(child, 'text_size'):
                                    child.text_size = (child.width, None)
                                print(f"  Fixed via title_label: '{old_text}' -> '{new_text}'")
                    
                except Exception as e:
                    print(f"  Error fixing TopAppBar at {path}: {e}")
            
            print(">>> Additional: Direct ScreenManager access")
            try:
                if hasattr(self.root, 'ids'):
                    for id_name, widget in self.root.ids.items():
                        print(f"Root ID: {id_name} -> {type(widget)}")
                        if hasattr(widget, 'screens'):
                            print(f"Found ScreenManager: {id_name}")
                            for screen in widget.screens:
                                screen_topbars = find_all_topbars(screen, f"screen_manager.{screen.name}")
                                for topbar, path in screen_topbars:
                                    old_title = getattr(topbar, 'title', '') or ''
                                    if old_title:
                                        topbar.title = self.reshape(old_title)
                                        print(f"Fixed via ScreenManager: '{old_title}' -> '{topbar.title}'")
            except Exception as e:
                print(f"Error in ScreenManager access: {e}")
                
        except Exception as e:
            print(f"ERROR in _fix_topbar_titles: {e}")
            import traceback
            traceback.print_exc()
        
        print(">>> _fix_topbar_titles COMPLETED")

    def toggle_nav_drawer(self):
        pass

    # -----------------------
    # NEW FEATURE: Data Deletion with Confirmation
    # -----------------------
    def confirm_delete_all_data(self):
        """نمایش دیالوگ تأیید برای حذف تمام داده‌ها"""
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton
        
        def delete_data(*args):
            success = self.delete_all_data()
            dialog.dismiss()
            if success:
                self.notify("تمام داده‌ها با موفقیت حذف شد")
                # راه‌اندازی مجدد برنامه
                self.restart_app()
            else:
                self.notify("خطا در حذف داده‌ها")
        
        dialog = MDDialog(
            title=self.reshape("حذف تمام داده‌ها"),
            text=self.reshape("آیا مطمئن هستید؟ این عمل غیرقابل بازگشت است و تمام محصولات، عکس‌ها و تاریخچه حذف خواهند شد."),
            buttons=[
                MDFlatButton(
                    text=self.reshape("انصراف"),
                    on_release=lambda x: dialog.dismiss()
                ),
                MDFlatButton(
                    text=self.reshape("حذف همه"),
                    on_release=delete_data
                ),
            ]
        )
        dialog.open()

    def delete_all_data(self):
        """حذف تمام داده‌های برنامه"""
        try:
            # بستن اتصال پایگاه داده
            if self.db and self.db.conn:
                self.db.conn.close()
            
            # حذف فایل پایگاه داده
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            
            # حذف دایرکتوری‌های عکس‌ها
            for directory in [self.images_dir, self.thumbs_dir]:
                if os.path.exists(directory):
                    shutil.rmtree(directory)
            
            # ایجاد مجدد دایرکتوری‌ها
            self.images_dir = ensure_dir(os.path.join(self._user_data_dir, 'images'))
            self.thumbs_dir = ensure_dir(os.path.join(self._user_data_dir, 'thumbs'))
            
            # راه‌اندازی مجدد پایگاه داده
            self.db = DBHelper(self.db_path)
            
            # پاک کردن کش‌ها
            Cache.remove('image_load')
            Cache.remove('product_data')
            
            return True
        except Exception as e:
            print(f"Error deleting data: {e}")
            return False

    def restart_app(self):
        """راه‌اندازی مجدد برنامه"""
        try:
            # رفرش رابط کاربری
            self.refresh_product_list()
            self.back_to_main()
            self.notify("برنامه با داده‌های جدید راه‌اندازی شد")
        except Exception as e:
            print(f"Error restarting app: {e}")

    # -----------------------
    # NEW FEATURE: Optimized Search with Delayed Execution
    # -----------------------
    def delayed_search(self, search_term):
        """جستجوی با تأخیر برای عملکرد بهتر"""
        if self.search_clock:
            self.search_clock.cancel()
        
        self.search_clock = Clock.schedule_once(
            lambda dt: self.perform_search(search_term), 
            0.3  # تأخیر 300 میلی‌ثانیه
        )

    def perform_search(self, search_term):
        """انجام جستجوی واقعی"""
        self.current_search_term = search_term
        if not search_term.strip():
            self.refresh_product_list()
            return
            
        # استفاده از جستجوی بهینه‌شده با محدودیت
        results = self.db.search(search_term, limit=100)
        self.refresh_product_list(products=results)

    # -----------------------
    # FIXED: pick_base_image method to handle button click properly
    # -----------------------
    def pick_base_image(self, category, base_number, callback=None, *args):
        """انتخاب عکس گروه - اصلاح شده برای مدیریت کلیک دکمه"""
        def _on_sel(selection):
            if not selection:
                if callback: callback(None)
                return
            src = selection[0] if isinstance(selection, (list, tuple)) else selection
            if not src or not os.path.exists(src):
                self.notify("فایل انتخاب‌شده وجود ندارد")
                if callback: callback(None)
                return
            try:
                fn = make_unique_filename(os.path.basename(src))
                dest = os.path.join(self.images_dir, fn)
                shutil.copy2(src, dest)
                thumb_path = os.path.join(self.thumbs_dir, "base_" + os.path.basename(dest))
                create_thumbnail(dest, thumb_path, size=(800,800))
                self.db.set_base_image(category.strip(), base_number, dest)
                self.notify("عکس گروه ذخیره شد")
                if callback: callback(dest)
            except Exception as e:
                self.notify("خطا در ذخیره عکس گروه: " + str(e))
                if callback: callback(None)

        if filechooser is not None:
            try:
                filechooser.open_file(on_selection=_on_sel)
                return
            except Exception:
                pass

        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            p = filedialog.askopenfilename(title=self.reshape("انتخاب عکس گروه"), filetypes=[('Images', ('*.png','*.jpg','*.jpeg','*.bmp','*.webp'))])
            root.destroy()
            if p:
                _on_sel([p])
                return
        except Exception:
            pass

        self.notify("انتخاب عکس پشتیبانی نمی‌شود")
        if callback: callback(None)

    # -----------------------
    # NEW FEATURE: Always go to batch add screen (even for single product)
    # -----------------------
    def save_product(self):
        try:
            scr = self.root.get_screen('add')
        except Exception:
            self.notify("صفحه افزودن در دسترس نیست")
            return
        
        name = getattr(scr.ids.name_input, "arabic_buf", (scr.ids.name_input.text or "")).strip()
        if not name:
            self.notify("لطفاً نام محصول را وارد کنید")
            return
        category = getattr(scr.ids.category_input, "arabic_buf", (scr.ids.category_input.text or "")).strip() or "عمومی"
        base_number = getattr(scr.ids.base_number_input, "arabic_buf", (scr.ids.base_number_input.text or "")).strip() or "-"
        try:
            quantity = int(scr.ids.quantity_input.text.strip() or "1")
        except Exception:
            quantity = 1
        try:
            default_weight = float(scr.ids.weight_input.text.strip() or "0")
        except Exception:
            default_weight = 0.0
        purity = getattr(scr.ids.purity_input, "arabic_buf", (scr.ids.purity_input.text or "")).strip()
        notes = getattr(scr.ids.notes_input, "arabic_buf", (scr.ids.notes_input.text or "")).strip()
        image = getattr(self, "_selected_image", "")
        thumb = getattr(self, "_selected_thumb", "")

        # همیشه به صفحه ثبت جداگانه برو - حتی برای یک محصول
        if quantity and quantity >= 1:
            base_img = self.db.get_base_image(category, base_number)
            if not base_img:
                self.notify("لطفاً ابتدا عکس گروه را انتخاب کنید")
                self.pick_base_image(category, base_number, callback=lambda p: self.open_batch_add(name, category, base_number, quantity, default_weight, purity, notes))
            else:
                self.open_batch_add(name, category, base_number, quantity, default_weight, purity, notes)
        else:
            self.notify("تعداد باید حداقل 1 باشد")

    # -----------------------
    # NEW FEATURE: Force English invoice numbers with Persian date default
    # -----------------------
    def sell_current_product(self):
        prod = self.current_product
        if not prod:
            self.notify("محصولی انتخاب نشده")
            return

        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton

        # استفاده از تاریخ شمسی به عنوان شماره فاکتور پیشفرض
        default_invoice = get_jalali_date_string()

        def ask_invoice_and_do_sell(*args):
            try:
                from kivymd.uix.boxlayout import MDBoxLayout
                from kivymd.uix.textfield import MDTextField

                content = MDBoxLayout(orientation='vertical', spacing=6, padding=6)
                
                # ایجاد فیلد ورودی با مقدار پیشفرض تاریخ شمسی
                invoice_input = MDTextField(
                    hint_text=self.reshape("شماره فاکتور فروش را وارد کنید"), 
                    text=default_invoice,
                    multiline=False
                )
                content.add_widget(invoice_input)

                dlg2 = MDDialog(
                    title=self.reshape("شماره فاکتور"), 
                    type="custom", 
                    content_cls=content, 
                    buttons=[
                        MDFlatButton(text=self.reshape("انصراف"), on_release=lambda x: dlg2.dismiss()),
                        MDFlatButton(text=self.reshape("ثبت"), on_release=lambda x: do_sell_with_invoice(invoice_input.text, dlg2))
                    ]
                )
                dlg2.open()
            except Exception as e:
                self.notify("خطا در نمایش شماره فاکتور: " + str(e))

        def do_sell_with_invoice(invoice_str, dialog_ref):
            try:
                # تبدیل اعداد فارسی/عربی به انگلیسی
                invoice = convert_to_english_numbers(invoice_str.strip())
                if not invoice:
                    self.notify("شماره فاکتور خالی است")
                    return
                    
                sold_dir = ensure_dir(os.path.join(self._user_data_dir, 'sold', invoice))

                def copy_to_sold(path):
                    if not path or not os.path.exists(path):
                        return None
                    try:
                        dest = os.path.join(sold_dir, os.path.basename(path))
                        if os.path.exists(dest):
                            base, ext = os.path.splitext(os.path.basename(path))
                            dest = os.path.join(sold_dir, f"{base}_{datetime.datetime.now().strftime('%H%M%S')}{ext}")
                        shutil.copy2(path, dest)
                        return dest
                    except Exception:
                        return None

                if prod.get('quantity') and prod['quantity'] > 1:
                    new_q = prod['quantity'] - 1
                    updated = {**prod, 'quantity': new_q}
                    if 'created_at' not in updated or not updated['created_at']:
                        updated['created_at'] = get_jalali_datetime_string()  # استفاده از تاریخ شمسی
                    self.db.update_product(prod['id'], updated)

                    sold_img = copy_to_sold(prod.get('image'))
                    sold_thumb = copy_to_sold(prod.get('thumb'))
                    sold_code = f"{prod.get('product_code')}-S{datetime.datetime.now().strftime('%H%M%S')}"
                    sold_entry = {
                        'product_code': sold_code,
                        'name': prod.get('name') + " (فروش)",
                        'category': prod.get('category'),
                        'base_number': prod.get('base_number'),
                        'weight': prod.get('weight') or 0.0,
                        'quantity': 0,
                        'purity': prod.get('purity'),
                        'image': sold_img,
                        'thumb': sold_thumb,
                        'notes': f"فروش فاکتور: {invoice} | " + (prod.get('notes') or ""),
                        'created_at': get_jalali_datetime_string(),  # استفاده از تاریخ شمسی
                        'sold_invoice': invoice,
                        'sold_at': get_jalali_datetime_string()  # اضافه کردن تاریخ فروش
                    }
                    new_id = self.db.add_product(sold_entry)
                    meta = {
                        'sold_id': new_id,
                        'original_id': prod.get('id'),
                        'product_code': sold_code,
                        'name': sold_entry['name'],
                        'category': sold_entry['category'],
                        'base_number': sold_entry['base_number'],
                        'weight': sold_entry['weight'],
                        'purity': sold_entry['purity'],
                        'notes': sold_entry['notes'],
                        'image': sold_img,
                        'thumb': sold_thumb,
                        'invoice': invoice,
                        'sold_at': get_jalali_datetime_string()  # استفاده از تاریخ شمسی
                    }
                    meta_fn = os.path.join(sold_dir, f"meta_{new_id}.json")
                    with open(meta_fn, 'w', encoding='utf-8') as mf:
                        json.dump(meta, mf, ensure_ascii=False, indent=2)
                else:
                    new_img = copy_to_sold(prod.get('image')) or prod.get('image')
                    new_thumb = copy_to_sold(prod.get('thumb')) or prod.get('thumb')
                    meta = {
                        'original_id': prod.get('id'),
                        'product_code': prod.get('product_code'),
                        'name': prod.get('name'),
                        'category': prod.get('category'),
                        'base_number': prod.get('base_number'),
                        'weight': prod.get('weight'),
                        'purity': prod.get('purity'),
                        'notes': prod.get('notes'),
                        'image': new_img,
                        'thumb': new_thumb,
                        'invoice': invoice,
                        'sold_at': get_jalali_datetime_string()  # استفاده از تاریخ شمسی
                    }
                    self.db.mark_as_sold(prod['id'], invoice, sold_image=new_img, sold_thumb=new_thumb, metadata=meta, user_data_dir=self._user_data_dir)

                self.notify("فروش ثبت شد — فاکتور: " + invoice)
                try:
                    dialog_ref.dismiss()
                except Exception:
                    pass
                self.refresh_after_sell()
            except Exception as e:
                self.notify("خطا در ثبت فروش: " + str(e))

        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton
        dlg = MDDialog(
            title=self.reshape("ثبت فروش"), 
            text=self.reshape(f"آیا مطمئنید که می‌خواهید '{prod['name']}' را فروش بزنید؟\nشماره فاکتور پیشنهادی: {default_invoice}"), 
            buttons=[
                MDFlatButton(text=self.reshape("خیر"), on_release=lambda x: dlg.dismiss()),
                MDFlatButton(text=self.reshape("بله"), on_release=lambda x: (dlg.dismiss(), ask_invoice_and_do_sell()))
            ]
        )
        dlg.open()

    # -----------------------
    # Enhanced Sold Products Display with Persian dates
    # -----------------------
    def _display_sold_products_enhanced(self, sorted_invoices, screen):
        """نمایش پیشرفته محصولات فروخته شده با تاریخ شمسی"""
        box = screen.ids.sold_cards_box
        box.clear_widgets()

        if not sorted_invoices:
            from kivymd.uix.label import MDLabel
            box.add_widget(MDLabel(
                text=self.reshape("هیچ فاکتوری یافت نشد"), 
                halign="center", 
                font_name=self.font_name
            ))
            return

        from kivymd.uix.card import MDCard
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDFlatButton
        from kivy.uix.image import Image as KivyImage
        from kivymd.uix.label import MDLabel

        for invoice, items in sorted_invoices:
            # ایجاد هدر برای هر فاکتور
            header = MDCard(
                padding=8, 
                size_hint_y=None, 
                height='64dp', 
                radius=[8], 
                elevation=1
            )
            header_layout = MDBoxLayout(orientation='vertical', spacing=4)
            
            # نمایش شماره فاکتور و تاریخ
            invoice_date = items[0].get('sold_at') or items[0].get('created_at') or 'تاریخ نامعلوم'
            header_layout.add_widget(MDLabel(
                text=self.reshape(f"فاکتور: {invoice}"), 
                halign='right', 
                font_name=self.font_name,
                theme_text_color="Primary",
                bold=True
            ))
            header_layout.add_widget(MDLabel(
                text=self.reshape(f"تاریخ فروش: {invoice_date} - تعداد: {len(items)}"), 
                halign='right', 
                font_name=self.font_name,
                theme_text_color="Secondary"
            ))
            
            # دکمه بازگرداندن تمام محصولات این فاکتور
            btn_layout = MDBoxLayout(size_hint_y=None, height='36dp')
            restore_btn = MDFlatButton(
                text=self.reshape('بازگرداندن همه'),
                on_release=lambda x, inv=invoice: self.restore_invoice_products(inv)
            )
            btn_layout.add_widget(restore_btn)
            header_layout.add_widget(btn_layout)
            
            header.add_widget(header_layout)
            box.add_widget(header)

            for product in items:
                try:
                    card = MDCard(
                        orientation='horizontal', 
                        size_hint_y=None, 
                        height="160dp", 
                        padding="12dp", 
                        radius=[12], 
                        elevation=3
                    )
                    
                    left = MDBoxLayout(orientation='vertical', size_hint_x=0.3)
                    img_src = product.get('thumb') if product.get('thumb') and os.path.exists(product.get('thumb')) else (
                        product.get('image') if product.get('image') and os.path.exists(product.get('image')) else self.default_image
                    )
                    left.add_widget(KivyImage(
                        source=img_src, 
                        allow_stretch=True, 
                        keep_ratio=True
                    ))
                    
                    right = MDBoxLayout(orientation='vertical', padding=(8,0), spacing=6)
                    
                    title = f"{product['name']}  —  {product.get('product_code') or ''}"
                    lbl_title = MDLabel(
                        text=self.reshape(title), 
                        font_name=self.font_name, 
                        halign="right", 
                        theme_text_color="Primary", 
                        adaptive_height=True, 
                        shorten=True, 
                        shorten_from="right"
                    )
                    right.add_widget(lbl_title)
                    
                    # اطلاعات محصول
                    info_row1 = MDBoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height="30dp")
                    info_row1.add_widget(MDLabel(
                        text=self.reshape(f"دسته: {product.get('category')}"), 
                        font_name=self.font_name, 
                        halign="right", 
                        size_hint_x=0.6
                    ))
                    info_row1.add_widget(MDLabel(
                        text=self.reshape(f"وزن: {product.get('weight',0)}g"), 
                        font_name=self.font_name, 
                        halign="right", 
                        size_hint_x=0.4
                    ))
                    right.add_widget(info_row1)
                    
                    # تاریخ‌ها
                    info_row2 = MDBoxLayout(orientation='horizontal', spacing=8, size_hint_y=None, height="30dp")
                    created_date = product.get('created_at') or 'ثبت نشده'
                    sold_date = product.get('sold_at') or product.get('created_at') or 'فروش نامعلوم'
                    info_row2.add_widget(MDLabel(
                        text=self.reshape(f"ثبت: {created_date}"), 
                        font_name=self.font_name, 
                        halign="right", 
                        size_hint_x=0.6
                    ))
                    info_row2.add_widget(MDLabel(
                        text=self.reshape(f"فروش: {sold_date}"), 
                        font_name=self.font_name, 
                        halign="right", 
                        size_hint_x=0.4
                    ))
                    right.add_widget(info_row2)
                    
                    btn_row = MDBoxLayout(size_hint_y=None, height="40dp", spacing=8)
                    btn_restore = MDFlatButton(
                        text=self.reshape('بازگرداندن'), 
                        on_release=lambda x, pid=product['id']: self.restore_sold_product(pid)
                    )
                    btn_view = MDFlatButton(
                        text=self.reshape('نمایش'), 
                        on_release=lambda x, pid=product['id']: self.open_detail(pid)
                    )
                    btn_row.add_widget(btn_restore)
                    btn_row.add_widget(btn_view)
                    right.add_widget(btn_row)

                    card.add_widget(right)
                    card.add_widget(left)
                    box.add_widget(card)
                except Exception as e:
                    print(f"Error displaying sold product: {e}")
                    continue

    def restore_invoice_products(self, invoice):
        """بازگرداندن تمام محصولات یک فاکتور"""
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton
        
        def confirm_restore_invoice(*args):
            try:
                # پیدا کردن تمام محصولات این فاکتور
                products = [p for p in self.db.get_all_products(include_sold=True) 
                           if p.get('sold_invoice') == invoice]
                
                for product in products:
                    self.db.conn.execute('''
                        UPDATE products SET sold_invoice = NULL, quantity = 1, sold_at = NULL
                        WHERE id = ?
                    ''', (product['id'],))
                self.db.conn.commit()
                
                self.notify(f"تمام محصولات فاکتور {invoice} بازگردانده شدند")
                dialog.dismiss()
                self.open_sold_screen()
                
            except Exception as e:
                self.notify(f"خطا در بازگرداندن فاکتور: {str(e)}")
        
        dialog = MDDialog(
            title=self.reshape("بازگرداندن فاکتور"),
            text=self.reshape(f"آیا مطمئنید که می‌خواهید تمام محصولات فاکتور '{invoice}' را بازگردانید؟"),
            buttons=[
                MDFlatButton(
                    text=self.reshape("انصراف"),
                    on_release=lambda x: dialog.dismiss()
                ),
                MDFlatButton(
                    text=self.reshape("بازگرداندن همه"),
                    on_release=lambda x: confirm_restore_invoice()
                ),
            ]
        )
        dialog.open()

    # -----------------------
    # Existing methods (kept for compatibility)
    # -----------------------
    def open_actions_menu(self):
        items = [
            {"text": self.reshape("موجودی وزنی"), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a: self.open_weight_inventory_and_close_menu()},
            {"text": self.reshape("بکاپ کامل"), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a: self.backup_all_and_close_menu()},
            {"text": self.reshape("خروجی CSV"), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a: self.export_all_csv_and_close_menu()},
            {"text": self.reshape("فروش رفته‌ها"), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a: (self.open_sold_screen())},
            {"text": self.reshape("آمار فروش"), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a: (self.open_stats_screen())},
            {"text": self.reshape("تنظیمات"), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a: self.open_settings_and_close_menu()},
        ]
        try:
            from kivymd.uix.menu import MDDropdownMenu
            caller = self.root.get_screen('main')
            self.actions_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
            self.actions_menu.open()
        except Exception:
            self.open_settings_and_close_menu()

    def open_weight_inventory_and_close_menu(self):
        try:
            if hasattr(self, 'actions_menu'):
                self.actions_menu.dismiss()
        except Exception:
            pass
        self.open_weight_inventory()

    def backup_all_and_close_menu(self):
        try:
            if hasattr(self, 'actions_menu'):
                self.actions_menu.dismiss()
        except Exception:
            pass
        self.backup_all()

    def export_all_csv_and_close_menu(self):
        try:
            if hasattr(self, 'actions_menu'):
                self.actions_menu.dismiss()
        except Exception:
            pass
        self.export_all_csv()

    def open_settings_and_close_menu(self):
        try:
            if hasattr(self, 'actions_menu'):
                self.actions_menu.dismiss()
        except Exception:
            pass
        self.root.current = 'settings'

    def open_weight_inventory(self):
        """نمایش صفحه موجودی وزنی"""
        try:
            scr = self.root.get_screen('weight_inventory')
        except Exception:
            self.notify("صفحه موجودی وزنی در دسترس نیست")
            return

        box = scr.ids.weight_inventory_box
        box.clear_widgets()

        # محاسبه موجودی کل
        total_inventory = self.db.get_total_weight_inventory()
        category_inventory = self.db.get_weight_inventory()

        from kivymd.uix.card import MDCard
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel

        # کارت موجودی کل
        total_card = MDCard(padding=16, size_hint_y=None, height='120dp', radius=[12], elevation=3)
        total_layout = MDBoxLayout(orientation='vertical', spacing=8)
        
        total_layout.add_widget(MDLabel(
            text=self.reshape("موجودی کل"),
            font_name=self.font_name,
            halign="center",
            theme_text_color="Primary",
            font_style="H6"
        ))
        
        total_layout.add_widget(MDLabel(
            text=self.reshape(f"تعداد کل محصولات: {total_inventory['total_count']}"),
            font_name=self.font_name,
            halign="center",
            theme_text_color="Secondary"
        ))
        
        total_layout.add_widget(MDLabel(
            text=self.reshape(f"وزن کل: {total_inventory['total_weight']:.2f} گرم"),
            font_name=self.font_name,
            halign="center",
            theme_text_color="Secondary",
            font_style="H6"
        ))
        
        total_card.add_widget(total_layout)
        box.add_widget(total_card)

        # کارت‌های موجودی بر اساس دسته‌بندی
        for cat_inv in category_inventory:
            cat_card = MDCard(padding=12, size_hint_y=None, height='100dp', radius=[10], elevation=2)
            cat_layout = MDBoxLayout(orientation='vertical', spacing=6)
            
            cat_layout.add_widget(MDLabel(
                text=self.reshape(f"{cat_inv['category']}"),
                font_name=self.font_name,
                halign="right",
                theme_text_color="Primary",
                bold=True
            ))
            
            cat_layout.add_widget(MDLabel(
                text=self.reshape(f"تعداد: {cat_inv['product_count']} - وزن: {cat_inv['total_weight']:.2f} گرم"),
                font_name=self.font_name,
                halign="right",
                theme_text_color="Secondary"
            ))
            
            cat_card.add_widget(cat_layout)
            box.add_widget(cat_card)

        self.root.current = 'weight_inventory'

    def open_filter_menu(self, caller):
        cats = ['همه'] + self.category_options + ['فروش رفته']
        items = []
        for c in cats:
            items.append({"text": self.reshape(c), "viewclass": "OneLineListItem", "height": 44, "on_release": lambda *a, cat=c: self._apply_filter(cat)})
        try:
            from kivymd.uix.menu import MDDropdownMenu
            self.filter_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
            self.filter_menu.open()
        except Exception:
            pass

    def _apply_filter(self, cat):
        try:
            if hasattr(self, 'filter_menu'):
                try: self.filter_menu.dismiss()
                except Exception: pass
        except Exception:
            pass
        if not cat or cat == 'همه':
            self.refresh_product_list()
            return
        if cat == 'فروش رفته':
            prods = self.db.search("", include_sold=True)
            sold = [p for p in prods if p.get('sold_invoice')]
            self.refresh_product_list(products=sold)
            return
        results = [p for p in self.db.get_all_products() if (p.get('category') or '').strip() and cat in (p.get('category') or '')]
        self.refresh_product_list(products=results)

    # -----------------------
    # category menu
    # -----------------------
    def setup_category_menu(self):
        try:
            scr = self.root.get_screen('add')
        except Exception:
            return
        items = []
        for c in self.category_options:
            items.append({'viewclass': 'OneLineListItem', 'text': self.reshape(c), 'height': 44, 'on_release': lambda *a, cat=c: self._set_category_from_menu(cat)})
        try:
            from kivymd.uix.menu import MDDropdownMenu
            # تنظیم ارتفاع منو برای نمایش بهتر در موبایل
            self.category_menu = MDDropdownMenu(caller=scr.ids.category_input, items=items, width_mult=4, max_height=300)
        except Exception:
            self.category_menu = None

    def open_category_menu(self, caller):
        try:
            if not hasattr(self, 'category_menu') or self.category_menu is None:
                self.setup_category_menu()
            self.category_menu.caller = caller
            self.category_menu.open()
        except Exception as e:
            print('open_category_menu error:', e)

    def _set_category_from_menu(self, cat):
        try:
            scr = self.root.get_screen('add')
            try:
                w = scr.ids.category_input
                if hasattr(w, 'arabic_buf'):
                    w.arabic_buf = cat
                    w.text = _reshape_display_for_widget_text(cat)
                else:
                    w.text = cat
            except Exception:
                scr.ids.category_input.text = cat
            if hasattr(self, 'category_menu'):
                try:
                    self.category_menu.dismiss()
                except Exception:
                    pass
        except Exception:
            pass

    # -----------------------
    # Image pickers
    # -----------------------
    def pick_image(self):
        if filechooser is not None:
            try:
                filechooser.open_file(on_selection=self._on_file_selected)
                return
            except Exception:
                pass

        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            p = filedialog.askopenfilename(title=self.reshape("انتخاب عکس"), filetypes=[('Images', ('*.png','*.jpg','*.jpeg','*.bmp','*.webp'))])
            root.destroy()
            if p:
                self._on_file_selected([p])
                return
        except Exception:
            pass

        self.notify("انتخاب عکس پشتیبانی نمی‌شود")

    def _on_file_selected(self, selection):
        if not selection:
            return
        src = selection[0] if isinstance(selection, (list, tuple)) else selection
        if not src or not os.path.exists(src):
            self.notify("فایل انتخاب‌شده وجود ندارد")
            return
        try:
            fn = make_unique_filename(os.path.basename(src))
            dest = os.path.join(self.images_dir, fn)
            shutil.copy2(src, dest)
            thumb_path = os.path.join(self.thumbs_dir, "t_" + os.path.basename(dest))
            create_thumbnail(dest, thumb_path)
            scr = self.root.get_screen('add')
            scr.ids.preview_image.source = dest
            scr.ids.image_path_label.text = self.reshape("عکس انتخاب شد: ") + os.path.basename(dest)
            self._selected_image = dest
            self._selected_thumb = thumb_path
        except Exception as e:
            self.notify("خطا در کپی عکس: " + str(e))

    def pick_base_image_from_add(self):
        try:
            scr = self.root.get_screen('add')
            cat_w = scr.ids.category_input
            base_w = scr.ids.base_number_input
            category = getattr(cat_w, 'arabic_buf', (cat_w.text or "")).strip()
            base_number = getattr(base_w, 'arabic_buf', (base_w.text or "")).strip() or "-"
            if not category:
                self.notify("لطفاً ابتدا دسته را انتخاب کنید")
                return
            
            # چک کردن اینکه آیا قبلاً عکس گروه برای این دسته/گروه ثبت شده یا نه
            existing_base_image = self.db.get_base_image(category, base_number)
            if existing_base_image:
                from kivymd.uix.dialog import MDDialog
                from kivymd.uix.button import MDFlatButton
                
                def replace_base_image(*args):
                    self.pick_base_image(category, base_number, callback=lambda p: self._after_base_from_add(p, category, base_number))
                    dialog.dismiss()
                
                def cancel(*args):
                    dialog.dismiss()
                
                dialog = MDDialog(
                    title=self.reshape("عکس گروه موجود"),
                    text=self.reshape("برای این دسته/گروه قبلاً عکس گروه ثبت شده. آیا می‌خواهید جایگزین کنید؟"),
                    buttons=[
                        MDFlatButton(text=self.reshape("خیر"), on_release=cancel),
                        MDFlatButton(text=self.reshape("بله"), on_release=replace_base_image),
                    ]
                )
                dialog.open()
            else:
                self.pick_base_image(category, base_number, callback=lambda p: self._after_base_from_add(p, category, base_number))
                
        except Exception as e:
            self.notify("خطا: " + str(e))

    def _after_base_from_add(self, path, category, base_number):
        if path:
            self.notify(self.reshape(f"عکس گروه برای {category} — {base_number} ذخیره شد"))
        else:
            self.notify("عکس گروه ذخیره نشد")

    # -----------------------
    # ID generation (short IDs)
    # -----------------------
    def get_next_seq_for_category(self, category):
        pref = self.prefix_map.get(category, 'X')
        prods = self.db.get_all_products(include_sold=True)
        max_n = 0
        pattern = re.compile(rf"^{re.escape(pref)}(\d+)$", re.IGNORECASE)
        for p in prods:
            pc = (p.get('product_code') or "").strip()
            if not pc:
                continue
            m = pattern.match(pc)
            if m:
                try:
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
                except Exception:
                    pass
        return max_n + 1

    # -----------------------
    # Batch add - FIXED VERSION
    # -----------------------
    def open_batch_add(self, name, category, base_number, quantity, default_weight, purity, notes):
        self._batch_entries = []
        for i in range(quantity):
            self._batch_entries.append({
                'name': f"{name} #{i+1}",
                'weight': default_weight or 0.0,
                'purity': purity or '',
                'notes': notes or '',
                'image': '',
                'thumb': ''
            })
        try:
            scr = self.root.get_screen('batch_add')
            scr.title = self.reshape(f"ثبت جداگانه: {category} — گروه {base_number}")
            container = scr.ids.batch_container
            container.clear_widgets()
            from kivymd.uix.card import MDCard
            from kivymd.uix.boxlayout import MDBoxLayout
            from kivymd.uix.button import MDRaisedButton, MDFlatButton
            from kivymd.uix.textfield import MDTextField
            from kivy.uix.image import Image as KivyImage

            for idx, entry in enumerate(self._batch_entries):
                card = MDCard(padding=8, radius=[10], size_hint_y=None, height='190dp', elevation=2)
                box = MDBoxLayout(orientation='horizontal', spacing=8)
                left = MDBoxLayout(orientation='vertical', size_hint_x=.42, spacing=8)
                
                # نمایش عکس - استفاده از image widget
                img = KivyImage(
                    source=entry['image'] if entry['image'] and os.path.exists(entry['image']) else self.default_image, 
                    allow_stretch=True, 
                    keep_ratio=True,
                    size_hint_y=0.6
                )
                left.add_widget(img)
                
                btn_pick = MDRaisedButton(
                    text=self.reshape('انتخاب عکس'), 
                    size_hint_y=None, 
                    height='36dp', 
                    on_release=partial(self._batch_pick_image, idx, img)
                )
                left.add_widget(btn_pick)
                
                if idx > 0:
                    btn_copy = MDFlatButton(
                        text=self.reshape('کپی از قبلی'), 
                        size_hint_y=None, 
                        height='36dp', 
                        on_release=partial(self._batch_copy_from_prev, idx)
                    )
                    left.add_widget(btn_copy)

                right = MDBoxLayout(orientation='vertical', spacing=6)
                name_input = ArMDTextField(  # استفاده از کلاس محلی ArMDTextField
                    text=entry['name'], 
                    hint_text=self.reshape('نام محصول'), 
                    font_name=self.font_name, 
                    multiline=False,
                    size_hint_y=None,
                    height='44dp'
                )
                name_input.bind(arabic_buf=lambda inst, val, i=idx: self._batch_set_name(i, val))
                right.add_widget(name_input)

                w_box = MDBoxLayout(size_hint_y=None, height='44dp', spacing=8)
                w_input = MDTextField(
                    text=str(entry['weight']), 
                    hint_text=self.reshape('وزن (گرم)'), 
                    input_filter='float', 
                    font_name=self.font_name, 
                    multiline=False
                )
                w_input.bind(text=lambda inst, val, i=idx: self._update_batch_weight(i, val))
                w_box.add_widget(w_input)
                
                purity_input = ArMDTextField(  # استفاده از کلاس محلی ArMDTextField
                    text=entry.get('purity') or '', 
                    hint_text=self.reshape('عیار'), 
                    font_name=self.font_name, 
                    multiline=False
                )
                purity_input.bind(arabic_buf=lambda inst, val, i=idx: self._update_batch_purity(i, val))
                w_box.add_widget(purity_input)
                right.add_widget(w_box)

                notes_input = ArMDTextField(  # استفاده از کلاس محلی ArMDTextField
                    text=entry.get('notes') or '', 
                    hint_text=self.reshape('توضیحات'), 
                    size_hint_y=None, 
                    height='48dp', 
                    font_name=self.font_name
                )
                notes_input.bind(arabic_buf=lambda inst, val, i=idx: self._update_batch_notes(i, val))
                right.add_widget(notes_input)

                box.add_widget(right)
                box.add_widget(left)
                card.add_widget(box)
                container.add_widget(card)

            self.root.current = 'batch_add'
        except Exception as e:
            print('open_batch_add error:', e)
            self.notify('خطا در باز کردن صفحه ثبت جداگانه')

    def _batch_set_name(self, i, val):
        try:
            self._batch_entries[i]['name'] = val
        except Exception:
            pass

    def _batch_copy_from_prev(self, index, *args):
        if index <= 0 or index >= len(self._batch_entries):
            return
        prev = self._batch_entries[index-1]
        cur = self._batch_entries[index]
        
        # کپی کردن تمام اطلاعات از محصول قبلی
        cur.update({
            'name': prev['name'].replace(f"#{index}", f"#{index+1}"),
            'weight': prev['weight'],
            'purity': prev['purity'],
            'notes': prev['notes'],
            'image': prev['image'],
            'thumb': prev['thumb']
        })
        
        # رفرش کردن صفحه
        try:
            scr_add = self.root.get_screen('add')
            name0 = getattr(scr_add.ids.name_input, 'arabic_buf', (scr_add.ids.name_input.text or "")).strip() or (self._batch_entries[0]['name'].rsplit('#',1)[0].strip() if self._batch_entries else '')
            category = getattr(scr_add.ids.category_input, 'arabic_buf', (scr_add.ids.category_input.text or "")).strip() or ''
            base_number = getattr(scr_add.ids.base_number_input, 'arabic_buf', (scr_add.ids.base_number_input.text or "")).strip() or ''
            quantity = len(self._batch_entries)
            default_weight = 0.0
            purity = ''
            notes = ''
            self.open_batch_add(name0, category, base_number, quantity, default_weight, purity, notes)
        except Exception as e:
            print("Error refreshing batch screen:", e)

    def _batch_pick_image(self, index, image_widget, *args):
        def _cb(selection):
            if not selection:
                return
            src = selection[0]
            if not src or not os.path.exists(src):
                self.notify('فایل انتخاب‌شده وجود ندارد')
                return
            try:
                fn = make_unique_filename(os.path.basename(src))
                dest = os.path.join(self.images_dir, fn)
                shutil.copy2(src, dest)
                thumb_path = os.path.join(self.thumbs_dir, 't_' + os.path.basename(dest))
                create_thumbnail(dest, thumb_path)
                
                # آپدیت entry با مسیرهای جدید
                self._batch_entries[index]['image'] = dest
                self._batch_entries[index]['thumb'] = thumb_path
                
                # آپدیت تصویر نمایش داده شده
                image_widget.source = dest
                
                self.notify('عکس با موفقیت انتخاب شد')
            except Exception as e:
                self.notify('خطا در کپی عکس: ' + str(e))

        if filechooser is not None:
            try:
                filechooser.open_file(on_selection=_cb)
                return
            except Exception:
                pass
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            p = filedialog.askopenfilename(title=self.reshape("انتخاب عکس"), filetypes=[('Images', ('*.png','*.jpg','*.jpeg','*.bmp','*.webp'))])
            root.destroy()
            if p:
                _cb([p])
                return
        except Exception:
            pass
        self.notify('انتخاب عکس پشتیبانی نمی‌شود')

    def _update_batch_weight(self, i, val):
        try:
            self._batch_entries[i]['weight'] = float(val) if val else 0.0
        except Exception:
            self._batch_entries[i]['weight'] = 0.0

    def _update_batch_purity(self, i, val):
        self._batch_entries[i]['purity'] = val

    def _update_batch_notes(self, i, val):
        self._batch_entries[i]['notes'] = val

    def back_to_add_from_batch(self):
        self.root.current = 'add'

    def save_batch_products(self):
        try:
            scr_add = self.root.get_screen('add')
            category = getattr(scr_add.ids.category_input, "arabic_buf", (scr_add.ids.category_input.text or "")).strip() or 'عمومی'
            base_number = getattr(scr_add.ids.base_number_input, "arabic_buf", (scr_add.ids.base_number_input.text or "")).strip() or '-'
            
            saved_count = 0
            for idx, e in enumerate(self._batch_entries):
                seq = self.get_next_seq_for_category(category)
                prefix = self.prefix_map.get(category, 'X')
                code = f"{prefix}{seq}"
                
                # اطمینان از یکتا بودن کد
                while self.db.get_product_by_code(code) is not None:
                    seq += 1
                    code = f"{prefix}{seq}"
                
                p = {
                    'product_code': code,
                    'name': e.get('name') or f"محصول {idx+1}",
                    'category': category,
                    'base_number': base_number,
                    'weight': float(e.get('weight') or 0.0),
                    'quantity': 1,
                    'purity': e.get('purity'),
                    'image': e.get('image'),
                    'thumb': e.get('thumb'),
                    'notes': e.get('notes'),
                    'created_at': get_jalali_datetime_string()  # استفاده از تاریخ شمسی
                }
                self.db.add_product(p)
                saved_count += 1
            
            self.notify(f'{saved_count} محصول ذخیره شد')
            self._batch_entries = []
            self.back_to_main()
        except Exception as e:
            self.notify('خطا در ذخیره اقلام: ' + str(e))

    def _save_single_product(self, name, category, base_number, weight, purity, notes, image, thumb):
        """ذخیره محصول تکی"""
        try:
            seq = self.get_next_seq_for_category(category)
            prefix = self.prefix_map.get(category, 'X')
            code = f"{prefix}{seq}"
            while self.db.get_product_by_code(code) is not None:
                seq += 1
                code = f"{prefix}{seq}"

            p = {
                'product_code': code,
                'name': name,
                'category': category.strip(),
                'base_number': base_number,
                'weight': weight,
                'quantity': 1,
                'purity': purity,
                'image': image,
                'thumb': thumb,
                'notes': notes,
                'created_at': get_jalali_datetime_string()  # استفاده از تاریخ شمسی
            }

            if getattr(self, "editing_id", None):
                prod = next((x for x in self.db.get_all_products(include_sold=True) if x['id'] == self.editing_id), None)
                if prod and prod.get('product_code'):
                    p['product_code'] = prod['product_code']
                self.db.update_product(self.editing_id, p)
                self.notify("محصول به‌روزرسانی شد")
                self.editing_id = None
            else:
                self.db.add_product(p)
                self.notify(f"محصول ذخیره شد — آیدی: {p['product_code']}")
        except Exception as e:
            self.notify("خطا در ذخیره محصول: " + str(e))
            return

        self._selected_image = ""
        self._selected_thumb = ""
        self.clear_add_form()
        self.back_to_main()
        self.refresh_product_list()

    def clear_add_form(self):
        try:
            scr = self.root.get_screen('add')
            for wid in ('name_input','category_input','base_number_input','weight_input','quantity_input','purity_input','notes_input'):
                try:
                    w = scr.ids[wid]
                    if hasattr(w, 'arabic_buf'):
                        w.arabic_buf = ""
                    w.text = ""
                except Exception:
                    pass
            scr.ids.preview_image.source = self.default_image
            scr.ids.image_path_label.text = self.reshape("عکسی انتخاب نشده")
            self._selected_image = ""
            self._selected_thumb = ""
        except Exception:
            pass

    def open_add_screen(self):
        self.clear_add_form()
        try:
            scr = self.root.get_screen('add')
            scr.title = self.reshape("ثبت محصول جدید")
        except Exception:
            pass
        self.root.current = 'add'

    def back_to_main(self):
        self.editing_id = None
        self._selected_image = ""
        self._selected_thumb = ""
        try:
            self.root.current = 'main'
        except Exception:
            pass
        self.refresh_product_list()

    # -----------------------
    # refresh & display products - MODIFIED: Show only last 5 products but show total counts
    # -----------------------
    def refresh_product_list(self, products=None):
        try:
            main_screen = self.root.get_screen('main')
        except Exception:
            return

        try:
            cards_container = main_screen.ids.cards_box
        except Exception:
            return

        cards_container.clear_widgets()
        
        # فقط 5 محصول آخر را نمایش بده
        prods_all = self.db.get_all_products(limit=5) if products is None else products
        
        # اگر تعداد محصولات بیشتر از 5 است، فقط 5 تا اول را بگیر
        if products is None and len(prods_all) > 5:
            prods_all = prods_all[:5]
            
        # گرفتن تعداد کل محصولات و تعداد هر دسته
        total_count = self.db.get_total_products_count()
        category_counts = self.db.get_category_counts()
        
        cats = self.category_options
        cat_counts = {c: category_counts.get(c, 0) for c in cats}

        try:
            main_screen.ids.total_count_lbl.text = self.reshape(f"آخرین محصولات: {len(prods_all)} از {total_count} کل")
            catbox = main_screen.ids.categories_box
            catbox.clear_widgets()
            from kivymd.uix.button import MDRaisedButton
            for c in cats:
                count = cat_counts.get(c, 0)
                if count > 0:  # فقط دسته‌هایی که محصول دارند را نمایش بده
                    btn = MDRaisedButton(text=self.reshape(f"{c} ({count})"), on_release=partial(lambda cat, *a: self.open_category(cat), c))
                    catbox.add_widget(btn)
        except Exception:
            pass

        if not prods_all:
            from kivymd.uix.label import MDLabel
            lbl = MDLabel(text=self.reshape("هیچ محصولی ثبت نشده است"), halign="center", font_name=self.font_name)
            cards_container.add_widget(lbl)
            return

        grouped = {}
        for p in prods_all:
            key = (p.get('category') or 'عمومی').strip()
            grouped.setdefault(key, []).append(p)

        ordered_keys = [k for k in cats if k in grouped]
        other_keys = [k for k in grouped.keys() if k not in ordered_keys]
        ordered_keys += sorted(other_keys)

        from kivymd.uix.card import MDCard
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDFlatButton
        from kivy.uix.image import Image as KivyImage
        from kivymd.uix.label import MDLabel

        for cat in ordered_keys:
            try:
                header = MDCard(padding=10, size_hint_y=None, height='48dp', radius=[8], elevation=1)
                header.add_widget(MDLabel(text=self.reshape(f"{cat} ({len(grouped.get(cat, []))} از {category_counts.get(cat, 0)})"), halign='right', font_name=self.font_name))
                cards_container.add_widget(header)

                for p in grouped.get(cat, []):
                    card = MDCard(orientation='horizontal', size_hint_y=None, height="140dp", padding="12dp", radius=[12], elevation=4)
                    right = MDBoxLayout(orientation='vertical', padding=(8,0), spacing=8)
                    title = f"{p['name']}  —  {p.get('product_code') or ''}"
                    lbl_title = MDLabel(text=self.reshape(title), font_name=self.font_name, halign="right", theme_text_color="Primary", adaptive_height=True, shorten=True, shorten_from="right")
                    right.add_widget(lbl_title)
                    row = MDBoxLayout(orientation='horizontal', spacing=8)
                    cat_lbl = MDLabel(text=self.reshape(f"دسته: {p['category']}"), font_name=self.font_name, halign="right", size_hint_x=.6, shorten=True, shorten_from="right")
                    wq_lbl = MDLabel(text=self.reshape(f"وزن: {p.get('weight',0)}g — تعداد: {p.get('quantity',0)}"), font_name=self.font_name, halign="right", size_hint_x=.4, shorten=True, shorten_from="right")
                    row.add_widget(cat_lbl)
                    row.add_widget(wq_lbl)
                    right.add_widget(row)
                    notes_lbl = MDLabel(text=self.reshape(p.get('notes') or "-"), font_name=self.font_name, halign="right", theme_text_color="Secondary", adaptive_height=True, shorten=True, shorten_from="right")
                    right.add_widget(notes_lbl)
                    btn_row = MDBoxLayout(size_hint_y=None, height="40dp", spacing=8)
                    btn_view = MDFlatButton(text=self.reshape("نمایش"), on_release=partial(self.open_detail, p['id']))
                    btn_edit = MDFlatButton(text=self.reshape("ویرایش"), on_release=partial(self._open_edit, p['id']))
                    btn_row.add_widget(btn_view)
                    btn_row.add_widget(btn_edit)
                    right.add_widget(btn_row)

                    left = MDBoxLayout(orientation='vertical', size_hint_x=.35)
                    img_src = p.get('thumb') if p.get('thumb') and os.path.exists(p.get('thumb')) else (p.get('image') if p.get('image') and os.path.exists(p.get('image')) else self.default_image)
                    left.add_widget(KivyImage(source=img_src, allow_stretch=True, keep_ratio=True))

                    card.add_widget(right)
                    card.add_widget(left)
                    cards_container.add_widget(card)
            except Exception:
                continue

    # -----------------------
    # Category / base screens
    # -----------------------
    def open_category(self, category, *args):
        try:
            scr = self.root.get_screen('category')
        except Exception:
            self.notify("صفحه دسته در دسترس نیست")
            return
        scr.title = self.reshape(f"دسته: {category}")

        box = scr.ids.bases_box
        box.clear_widgets()

        bases = self.db.get_bases_by_category(category)
        if not bases:
            prods = [p for p in self.db.get_all_products() if (p.get('category') or '').strip() == category]
            uniq = {}
            for p in prods:
                key = p.get('base_number') or '-'
                uniq.setdefault(key, 0)
                uniq[key] += (p.get('quantity') or 0)
            bases = [{'base_number': k, 'count': v} for k, v in uniq.items()]

        if not bases:
            from kivymd.uix.label import MDLabel
            box.add_widget(MDLabel(text=self.reshape("گروه‌ای یافت نشد"), halign='center'))
        for b in bases:
            try:
                from kivymd.uix.card import MDCard
                from kivymd.uix.boxlayout import MDBoxLayout
                from kivymd.uix.button import MDFlatButton
                from kivy.uix.image import Image as KivyImage
                from kivymd.uix.label import MDLabel
                card = MDCard(orientation='horizontal', size_hint_y=None, height="120dp", padding="8dp", radius=[12], elevation=2)
                right = MDBoxLayout(orientation='vertical', padding=(8,0), spacing=6)
                lbl_title = MDLabel(text=self.reshape(f"گروه: {b['base_number']}  —  تعداد: {b['count']}"), font_name=self.font_name, halign="right", theme_text_color="Primary", adaptive_height=True, shorten=True, shorten_from="right")
                right.add_widget(lbl_title)
                btn_row = MDBoxLayout(size_hint_y=None, height="36dp", spacing=8)
                btn_open = MDFlatButton(text=self.reshape("مشاهده"), on_release=partial(self.open_base_products, category, b['base_number']))
                btn_pick_img = MDFlatButton(text=self.reshape("عکس گروه"), on_release=partial(self.pick_base_image, category, b['base_number'], lambda p: self.refresh_after_base_change(category)))
                btn_row.add_widget(btn_open)
                btn_row.add_widget(btn_pick_img)
                right.add_widget(btn_row)
                left = MDBoxLayout(orientation='vertical', size_hint_x=.35)
                base_img = self.db.get_base_image(category, b['base_number'])
                img_src = base_img if base_img and os.path.exists(base_img) else self.default_image
                left.add_widget(KivyImage(source=img_src, allow_stretch=True, keep_ratio=True))
                card.add_widget(right)
                card.add_widget(left)
                box.add_widget(card)
            except Exception:
                continue

        self.root.current = 'category'

    def refresh_after_base_change(self, category):
        self.open_category(category)

    def open_base_products(self, category, base_number, *args):
        try:
            scr = self.root.get_screen('base_products')
        except Exception:
            self.notify("صفحه گروه‌ها در دسترس نیست")
            return
        scr.title = self.reshape(f"{category} — گروه: {base_number}")
        scr.category = category
        box = scr.ids.base_products_box
        box.clear_widgets()
        prods = self.db.get_products_by_category_and_base(category, base_number)
        if not prods:
            from kivymd.uix.label import MDLabel
            box.add_widget(MDLabel(text=self.reshape("موردی یافت نشد"), halign='center'))
        for p in prods:
            try:
                from kivymd.uix.card import MDCard
                from kivymd.uix.boxlayout import MDBoxLayout
                from kivymd.uix.button import MDFlatButton
                from kivy.uix.image import Image as KivyImage
                from kivymd.uix.label import MDLabel
                card = MDCard(orientation='horizontal', size_hint_y=None, height="120dp", padding='8dp', radius=[10], elevation=3)
                right = MDBoxLayout(orientation='vertical')
                title = MDLabel(text=self.reshape(f"{p['name']} — {p.get('product_code') or ''}"), halign='right', shorten=True, shorten_from='right', font_name=self.font_name)
                right.add_widget(title)
                info = MDLabel(text=self.reshape(f"وزن: {p['weight']}g — تعداد: {p['quantity']}"), halign='right', font_name=self.font_name)
                right.add_widget(info)
                btn_row = MDBoxLayout(size_hint_y=None, height='36dp')
                btn_row.add_widget(MDFlatButton(text=self.reshape('نمایش'), on_release=partial(self.open_detail, p['id'])))
                btn_row.add_widget(MDFlatButton(text=self.reshape('فروش سریع'), on_release=partial(self.quick_sell, p['id'])))
                right.add_widget(btn_row)
                left = MDBoxLayout(orientation='vertical', size_hint_x=.35)
                img_src = p.get('thumb') if p.get('thumb') and os.path.exists(p.get('thumb')) else (p.get('image') if p.get('image') and os.path.exists(p.get('image')) else self.default_image)
                left.add_widget(KivyImage(source=img_src, allow_stretch=True, keep_ratio=True))
                card.add_widget(right)
                card.add_widget(left)
                box.add_widget(card)
            except Exception:
                continue
        self.root.current = 'base_products'


    # -----------------------
    # edit/detail
    # -----------------------
    def _open_edit(self, pid, *args):
        prod = next((x for x in self.db.get_all_products(include_sold=True) if x['id'] == pid), None)
        if not prod:
            self.notify("محصول پیدا نشد")
            return
        self.editing_id = pid
        try:
            scr = self.root.get_screen('add')
            try:
                w = scr.ids.name_input
                if hasattr(w, 'arabic_buf'):
                    w.arabic_buf = prod.get('name') or ""
                    w.text = _reshape_display_for_widget_text(w.arabic_buf)
                else:
                    w.text = prod.get('name') or ""
            except Exception:
                scr.ids.name_input.text = prod.get('name') or ""
            try:
                w = scr.ids.category_input
                if hasattr(w, 'arabic_buf'):
                    w.arabic_buf = prod.get('category') or ""
                    w.text = _reshape_display_for_widget_text(w.arabic_buf)
                else:
                    w.text = prod.get('category') or ""
            except Exception:
                scr.ids.category_input.text = prod.get('category') or ""
            try:
                w = scr.ids.base_number_input
                if hasattr(w, 'arabic_buf'):
                    w.arabic_buf = prod.get('base_number') or ""
                    w.text = _reshape_display_for_widget_text(w.arabic_buf)
                else:
                    w.text = prod.get('base_number') or ""
            except Exception:
                scr.ids.base_number_input.text = prod.get('base_number') or ""
            try:
                scr.ids.weight_input.text = str(prod.get('weight') or "")
            except Exception:
                pass
            try:
                scr.ids.quantity_input.text = str(prod.get('quantity') or "")
            except Exception:
                pass
            try:
                w = scr.ids.purity_input
                if hasattr(w, 'arabic_buf'):
                    w.arabic_buf = prod.get('purity') or ""
                    w.text = _reshape_display_for_widget_text(w.arabic_buf)
                else:
                    w.text = prod.get('purity') or ""
            except Exception:
                scr.ids.purity_input.text = prod.get('purity') or ""
            try:
                w = scr.ids.notes_input
                if hasattr(w, 'arabic_buf'):
                    w.arabic_buf = prod.get('notes') or ""
                    w.text = _reshape_display_for_widget_text(w.arabic_buf)
                else:
                    w.text = prod.get('notes') or ""
            except Exception:
                scr.ids.notes_input.text = prod.get('notes') or ""
            scr.ids.preview_image.source = prod.get('image') if prod.get('image') and os.path.exists(prod.get('image')) else self.default_image
            scr.ids.image_path_label.text = prod.get('image') or self.reshape("عکسی انتخاب نشده")
            self._selected_image = prod.get('image')
            self._selected_thumb = prod.get('thumb')
            scr.title = self.reshape("ویرایش محصول")
            self.root.current = 'add'
        except Exception:
            self.notify("صفحه افزودن در دسترس نیست")

    def _confirm_delete(self, pid, *args):
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton
        prod = next((x for x in self.db.get_all_products(include_sold=True) if x['id'] == pid), None)
        if not prod:
            self.notify("محصول پیدا نشد")
            return
        def on_yes(*_a):
            try:
                self.db.delete_product(pid)
                self.notify("محصول حذف شد")
            except Exception as e:
                self.notify("خطا در حذف: " + str(e))
            finally:
                try:
                    dlg.dismiss()
                except Exception:
                    pass
                self.refresh_product_list()
        dlg = MDDialog(title=self.reshape("حذف محصول"), text=self.reshape(f"آیا مایل به حذف '{prod['name']}' هستید؟"), buttons=[
            MDFlatButton(text=self.reshape("خیر"), on_release=lambda x: dlg.dismiss()),
            MDFlatButton(text=self.reshape("بله"), on_release=lambda x: on_yes())
        ])
        dlg.open()

    def open_detail(self, pid, *args):
        prod = next((x for x in self.db.get_all_products(include_sold=True) if x['id'] == pid), None)
        if not prod:
            self.notify("محصول پیدا نشد")
            return
        self.current_product = prod
        try:
            ds = self.root.get_screen('detail')
            ds.detail_title = self.reshape(f"جزئیات: {prod.get('name','')}")
            ds.ids.detail_image.source = prod.get('image') if prod.get('image') and os.path.exists(prod.get('image')) else self.default_image
            ds.ids.detail_name.text = self.reshape(prod.get('name', ''))
            ds.ids.detail_code.text = self.reshape(prod.get('product_code') or 'ندارد')
            ds.ids.detail_category.text = self.reshape(prod.get('category', 'ندارد'))
            ds.ids.detail_base.text = self.reshape(prod.get('base_number', 'ندارد'))
            ds.ids.detail_weight.text = self.reshape(str(prod.get('weight', '0')))
            ds.ids.detail_quantity.text = self.reshape(str(prod.get('quantity', '0')))
            ds.ids.detail_purity.text = self.reshape(prod.get('purity', 'ندارد'))
            ds.ids.detail_notes.text = self.reshape(prod.get('notes', 'توضیحاتی ثبت نشده'))
            ds.ids.detail_created.text = self.reshape(prod.get('created_at', 'ثبت نشده'))
            
            self.root.current = 'detail'
        except Exception as e:
            print(f"Error in open_detail: {e}")
            self.notify("صفحه جزئیات در دسترس نیست")

    # -----------------------
    # search
    # -----------------------
    def search_products(self, q):
        q = (q or "").strip()
        if not q:
            self.refresh_product_list()
            return
        prod = self.db.get_product_by_code(q)
        if prod:
            self.open_detail(prod['id'])
            return
        res = self.db.search(q)
        self.refresh_product_list(products=res)

    # -----------------------
    # Sold products management - ENHANCED: Show latest invoices first with better organization
    # -----------------------
    def search_sold_by_invoice(self, invoice_query):
        invoice_query = (invoice_query or "").strip()
        try:
            scr = self.root.get_screen('sold')
        except Exception:
            return
        
        if not invoice_query:
            # اگر جستجو خالی است، فاکتورهای آخر را نشان بده
            self.open_sold_screen()
            return
            
        # جستجو بر اساس شماره فاکتور
        all_sold = [p for p in self.db.get_all_products(include_sold=True) 
                    if p.get('sold_invoice') and invoice_query in p.get('sold_invoice', '')]
        
        # گروه‌بندی بر اساس فاکتور
        invoices_dict = {}
        for product in all_sold:
            invoice = product.get('sold_invoice', 'بدون فاکتور')
            if invoice not in invoices_dict:
                invoices_dict[invoice] = []
            invoices_dict[invoice].append(product)
        
        # مرتب‌سازی فاکتورها
        sorted_invoices = sorted(invoices_dict.items(), key=lambda x: x[0], reverse=True)
        
        self._display_sold_products_enhanced(sorted_invoices, scr)

    def clear_sold_search(self):
        try:
            scr = self.root.get_screen('sold')
            scr.ids.search_invoice_field.arabic_buf = ""
            scr.ids.search_invoice_field.text = ""
            self.open_sold_screen()
        except Exception:
            pass

    def restore_sold_product(self, product_id):
        """بازگرداندن محصول فروخته شده"""
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton
        
        product = next((p for p in self.db.get_all_products(include_sold=True) 
                       if p['id'] == product_id), None)
        
        if not product:
            self.notify("محصول پیدا نشد")
            return
        
        def confirm_restore(*args):
            try:
                # بازگرداندن محصول با تنظیم sold_invoice به null و quantity به 1
                self.db.conn.execute('''
                    UPDATE products SET sold_invoice = NULL, quantity = 1, sold_at = NULL
                    WHERE id = ?
                ''', (product_id,))
                self.db.conn.commit()
                
                self.notify("محصول با موفقیت بازگردانده شد")
                dialog.dismiss()
                self.open_sold_screen()
                
            except Exception as e:
                self.notify(f"خطا در بازگرداندن محصول: {str(e)}")
        
        product_name = product.get('name', 'بدون نام')
        dialog = MDDialog(
            title=self.reshape("بازگرداندن محصول"),
            text=self.reshape(f"آیا مطمئنید که می‌خواهید محصول '{product_name}' را به موجودی بازگردانید؟"),
            buttons=[
                MDFlatButton(
                    text=self.reshape("انصراف"),
                    on_release=lambda x: dialog.dismiss()
                ),
                MDFlatButton(
                    text=self.reshape("بازگرداندن"),
                    on_release=lambda x: confirm_restore()
                ),
            ]
        )
        dialog.open()

    def open_sold_screen(self, *args):
        """صفحه فروش رفته‌ها با نمایش فاکتورهای آخر"""
        try:
            scr = self.root.get_screen('sold')
        except Exception:
            self.notify("صفحه فروش رفته‌ها در دسترس نیست")
            return
            
        # گرفتن فاکتورهای اخیر
        recent_invoices = self.db.get_recent_invoices(limit=10)
        sold_products = self.db.get_products_by_invoices(recent_invoices, limit=200)
        
        # گروه‌بندی بر اساس فاکتور
        invoices_dict = {}
        for product in sold_products:
            invoice = product.get('sold_invoice', 'بدون فاکتور')
            if invoice not in invoices_dict:
                invoices_dict[invoice] = []
            invoices_dict[invoice].append(product)
        
        # مرتب‌سازی فاکتورها به ترتیب نزولی (آخرین فاکتور اول)
        sorted_invoices = sorted(invoices_dict.items(), key=lambda x: x[0], reverse=True)
        
        self._display_sold_products_enhanced(sorted_invoices, scr)
        self.root.current = 'sold'

    def refresh_sold_list(self):
        try:
            if self.root.current == 'sold':
                self.open_sold_screen()
        except Exception:
            pass

    def refresh_after_sell(self):
        """رفرش لیست‌ها بعد از فروش"""
        try:
            if self.root.current == 'main':
                self.refresh_product_list()
            elif self.root.current == 'sold':
                self.open_sold_screen()
            elif self.root.current == 'detail':
                self.back_to_main()
        except Exception:
            pass

    # -----------------------
    # Sales metadata reader & stats
    # -----------------------
    def _gather_all_sold_metadata(self):
        sales = []
        sold_root = os.path.join(self._user_data_dir, 'sold')
        if os.path.isdir(sold_root):
            for invoice in os.listdir(sold_root):
                inv_dir = os.path.join(sold_root, invoice)
                if not os.path.isdir(inv_dir):
                    continue
                for fname in os.listdir(inv_dir):
                    if fname.lower().endswith('.json'):
                        try:
                            with open(os.path.join(inv_dir, fname), 'r', encoding='utf-8') as jf:
                                data = json.load(jf)
                            sold_at = None
                            if data.get('sold_at'):
                                try:
                                    sold_at = datetime.datetime.fromisoformat(data.get('sold_at'))
                                except Exception:
                                    try:
                                        sold_at = datetime.datetime.strptime(data.get('sold_at'), '%Y-%m-%dT%H:%M:%S')
                                    except Exception:
                                        sold_at = None
                            if not sold_at and data.get('created_at'):
                                try:
                                    sold_at = datetime.datetime.fromisoformat(data.get('created_at'))
                                except Exception:
                                    sold_at = None
                            weight = 0.0
                            try:
                                weight = float(data.get('weight') or 0.0)
                            except Exception:
                                weight = 0.0
                            sales.append({
                                'invoice': invoice,
                                'sold_at': sold_at,
                                'weight': weight,
                                'sold_id': data.get('sold_id') or data.get('original_id'),
                                'name': data.get('name') or data.get('product_code') or data.get('original_name')
                            })
                        except Exception:
                            continue
        try:
            rows = self.db.get_all_products(include_sold=True)
            for r in rows:
                if r.get('sold_invoice'):
                    sold_at = None
                    if r.get('created_at'):
                        try:
                            sold_at = datetime.datetime.fromisoformat(r.get('created_at'))
                        except Exception:
                            sold_at = None
                    weight = r.get('weight') or 0.0
                    sales.append({
                        'invoice': r.get('sold_invoice'),
                        'sold_at': sold_at,
                        'weight': float(weight or 0.0),
                        'sold_id': r.get('id'),
                        'name': r.get('name')
                    })
        except Exception:
            pass
        uniq = {}
        cleaned = []
        for s in sales:
            key = f"{s.get('sold_id')}_{s.get('invoice')}"
            if key in uniq:
                continue
            uniq[key] = True
            cleaned.append(s)
        return cleaned

    def compute_sales_stats(self):
        sales = self._gather_all_sold_metadata()
        now = datetime.datetime.now()
        start_today = datetime.datetime(now.year, now.month, now.day)
        start_week = start_today - datetime.timedelta(days=start_today.weekday())
        start_month = datetime.datetime(now.year, now.month, 1)

        stats = {
            'today': {'count':0, 'weight':0.0},
            'week': {'count':0, 'weight':0.0},
            'month': {'count':0, 'weight':0.0},
            'recent_invoices': {}
        }
        for s in sales:
            sold_at = s.get('sold_at')
            if not sold_at:
                sold_at = start_today
            if sold_at >= start_today:
                stats['today']['count'] += 1
                stats['today']['weight'] += float(s.get('weight') or 0.0)
            if sold_at >= start_week:
                stats['week']['count'] += 1
                stats['week']['weight'] += float(s.get('weight') or 0.0)
            if sold_at >= start_month:
                stats['month']['count'] += 1
                stats['month']['weight'] += float(s.get('weight') or 0.0)
            inv = s.get('invoice') or 'بدون فاکتور'
            stats['recent_invoices'].setdefault(inv, {'count':0, 'weight':0.0})
            stats['recent_invoices'][inv]['count'] += 1
            try:
                stats['recent_invoices'][inv]['weight'] += float(s.get('weight') or 0.0)
            except Exception:
                pass
        return stats

    def open_stats_screen(self):
        try:
            scr = self.root.get_screen('stats')
        except Exception:
            self.notify("صفحه آمار در دسترس نیست")
            return
        box = scr.ids.stats_box
        box.clear_widgets()
        stats = self.compute_sales_stats()

        from kivymd.uix.card import MDCard
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        from kivymd.uix.button import MDFlatButton

        card_today = MDCard(padding=12, size_hint_y=None, height='86dp', radius=[10], elevation=2)
        bl = MDBoxLayout(orientation='vertical')
        bl.add_widget(MDLabel(text=self.reshape(f"امروز — تعداد: {stats['today']['count']}"), halign='right', font_name=self.font_name))
        bl.add_widget(MDLabel(text=self.reshape(f"مجموع وزن: {round(stats['today']['weight'], 3)} g"), halign='right', font_name=self.font_name))
        card_today.add_widget(bl)
        box.add_widget(card_today)

        card_week = MDCard(padding=12, size_hint_y=None, height='86dp', radius=[10], elevation=2)
        bl2 = MDBoxLayout(orientation='vertical')
        bl2.add_widget(MDLabel(text=self.reshape(f"این هفته — تعداد: {stats['week']['count']}"), halign='right', font_name=self.font_name))
        bl2.add_widget(MDLabel(text=self.reshape(f"مجموع وزن: {round(stats['week']['weight'],3)} g"), halign='right', font_name=self.font_name))
        card_week.add_widget(bl2)
        box.add_widget(card_week)

        card_month = MDCard(padding=12, size_hint_y=None, height='86dp', radius=[10], elevation=2)
        bl3 = MDBoxLayout(orientation='vertical')
        bl3.add_widget(MDLabel(text=self.reshape(f"این ماه — تعداد: {stats['month']['count']}"), halign='right', font_name=self.font_name))
        bl3.add_widget(MDLabel(text=self.reshape(f"مجموع وزن: {round(stats['month']['weight'],3)} g"), halign='right', font_name=self.font_name))
        card_month.add_widget(bl3)
        box.add_widget(card_month)

        invs = sorted(stats['recent_invoices'].items(), key=lambda x: (x[1].get('count',0)), reverse=True)
        from kivymd.uix.label import MDLabel
        box.add_widget(MDLabel(text=self.reshape("فاکتورهای اخیر:"), halign='right', font_name=self.font_name))
        for inv, info in invs[:20]:
            try:
                c = MDCard(padding=8, size_hint_y=None, height='56dp', radius=[8], elevation=1)
                inner = MDBoxLayout(orientation='horizontal')
                left = MDBoxLayout(orientation='vertical', size_hint_x=0.7)
                left.add_widget(MDLabel(text=self.reshape(f"فاکتور: {inv}"), halign='right', font_name=self.font_name))
                left.add_widget(MDLabel(text=self.reshape(f"تعداد: {info.get('count',0)} — وزن: {round(info.get('weight',0.0),3)} g"), halign='right', font_name=self.font_name))
                c.add_widget(left)
                box.add_widget(c)
            except Exception:
                continue

        self.root.current = 'stats'

    def refresh_stats_if_open(self):
        try:
            if self.root.current == 'stats':
                self.open_stats_screen()
        except Exception:
            pass

    # -----------------------
    # selling logic
    # -----------------------
    def quick_sell(self, pid, *args):
        prod = next((x for x in self.db.get_all_products() if x['id'] == pid), None)
        if not prod:
            self.notify("محصول پیدا نشد")
            return
        self.current_product = prod
        self.sell_current_product()

    # -----------------------
    # export/backup - FIXED VERSION
    # -----------------------
    def export_all_csv(self):
        try:
            prods = self.db.get_all_products(include_sold=True)
            if not prods:
                self.notify("هیچ محصولی برای خروجی وجود ندارد")
                return
            export_dir = ensure_dir(os.path.join(self._user_data_dir, 'exports'))
            fn = f"all_products_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            path = os.path.join(export_dir, fn)
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['id','product_code','name','category','base_number','weight','quantity','purity','notes','image','sold_invoice','created_at','sold_at'])
                for p in prods:
                    writer.writerow([p['id'],p.get('product_code'),p['name'],p['category'],p['base_number'],p['weight'],p['quantity'],p['purity'],p['notes'],p.get('image'),p.get('sold_invoice'),p['created_at'],p.get('sold_at')])
            self.notify("خروجی ساخته شد: " + path)
        except Exception as e:
            self.notify("خطا در خروجی: " + str(e))

    def backup_all(self):
        try:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"goldshop_backup_{ts}.zip"
            backup_dir = ensure_dir(os.path.join(self._user_data_dir, 'backups'))
            backup_path = os.path.join(backup_dir, backup_name)
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(self.db_path):
                    zf.write(self.db_path, arcname=os.path.basename(self.db_path))
                for root_dir, dirs, files in os.walk(self.images_dir):
                    for f in files:
                        full = os.path.join(root_dir, f)
                        arc = os.path.join('images', os.path.relpath(full, self.images_dir))
                        zf.write(full, arcname=arc)
                for root_dir, dirs, files in os.walk(self.thumbs_dir):
                    for f in files:
                        full = os.path.join(root_dir, f)
                        arc = os.path.join('thumbs', os.path.relpath(full, self.thumbs_dir))
                        zf.write(full, arcname=arc)
            self.notify("بکاپ ساخته شد: " + backup_path)
        except Exception as e:
            self.notify("خطا در بکاپ: " + str(e))

    def restore_from_zip(self):
        if filechooser is None:
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                p = filedialog.askopenfilename(title=self.reshape('انتخاب فایل.zip'), filetypes=[('Zip files','*.zip')])
                root.destroy()
                if p:
                    self._on_restore_selected([p])
                return
            except Exception:
                self.notify("بازیابی پشتیبانی نمی‌شود")
                return
        try:
            filechooser.open_file(on_selection=self._on_restore_selected)
        except TypeError:
            sel = filechooser.open_file()
            self._on_restore_selected(sel)
        except Exception as e:
            self.notify("خطا در باز کردن filechooser: " + str(e))

    def _on_restore_selected(self, selection):
        if not selection:
            return
        path = selection[0]
        try:
            # بستن اتصال پایگاه داده قبل از بازیابی
            if self.db and self.db.conn:
                self.db.conn.close()
                self.db = None

            with zipfile.ZipFile(path, 'r') as zf:
                for member in zf.namelist():
                    normalized = os.path.normpath(member)
                    if normalized.startswith('..'):
                        continue
                    if member == os.path.basename(self.db_path):
                        zf.extract(member, path=self._user_data_dir)
                        extracted_path = os.path.join(self._user_data_dir, member)
                        shutil.move(extracted_path, self.db_path)
                    elif member.startswith('images/'):
                        dest = os.path.join(self.images_dir, os.path.relpath(member, 'images'))
                        ensure_dir(os.path.dirname(dest))
                        with zf.open(member) as srcf, open(dest, 'wb') as outf:
                            shutil.copyfileobj(srcf, outf)
                    elif member.startswith('thumbs/'):
                        dest = os.path.join(self.thumbs_dir, os.path.relpath(member, 'thumbs'))
                        ensure_dir(os.path.dirname(dest))
                        with zf.open(member) as srcf, open(dest, 'wb') as outf:
                            shutil.copyfileobj(srcf, outf)
            
            # راه‌اندازی مجدد پایگاه داده
            self.db = DBHelper(self.db_path)
            
            self.notify("بازیابی انجام شد")
            self.back_to_main()
            self.refresh_product_list()
        except Exception as e:
            self.notify("خطا در بازیابی: " + str(e))
            # در صورت خطا، پایگاه داده را مجدداً راه‌اندازی کن
            self.db = DBHelper(self.db_path)

    def on_stop(self):
        try:
            if self.db and getattr(self.db, "conn", None):
                try:
                    self.db.conn.close()
                except Exception:
                    pass
        except Exception:
            pass

# --------------------------
# entrypoint
# --------------------------
if __name__ == '__main__':
    GoldApp().run()