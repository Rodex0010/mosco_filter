import telebot
import time
import json
import os
import sqlite3

# --- Basic Bot Configuration ---

# يتم تحميل توكن البوت من متغيرات البيئة على Railway
MOSCO_TOKEN = os.getenv('MOSCO_TOKEN')
if not MOSCO_TOKEN:
    print("خطأ: متغير البيئة 'MOSCO_TOKEN' غير مضبوط. يرجى ضبطه على Railway.")
    exit()

bot = telebot.TeleBot(MOSCO_TOKEN)

# معرف المستخدم الخاص بالمالك (استبدله بمعرف مستخدم Telegram الحقيقي الخاص بك)
ADMIN_USER_ID = 7995806943 # يجب استبدال هذا بمعرف مستخدم Telegram الحقيقي الخاص بك
DATABASE_NAME = 'bot_data.db'

# القواميس الموجودة في الذاكرة لتتبع حالات المستخدم
user_share_mode = {}
last_shared_message = {}

# --- الثوابت لتقسيم الرسائل ---
MAX_MESSAGE_LENGTH = 4000 # حد آمن أقل قليلاً من 4096

# --- وظائف قاعدة بيانات SQLite ---
def init_db():
    """تهيئة قاعدة بيانات SQLite وإنشاء الجداول الضرورية."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # جدول المستخدمين المصرح لهم
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    # جدول المحادثات المستهدفة الخاصة بالمستخدم
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_target_chats (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    
    # التأكد من أن المستخدم المسؤول مصرح له دائمًا
    cursor.execute('INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)', (ADMIN_USER_ID,))
    
    conn.commit()
    conn.close()
    print("تم تهيئة قاعدة البيانات بنجاح.")

def get_authorized_users():
    """جلب جميع معرفات المستخدمين المصرح لهم من قاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM authorized_users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def add_authorized_user_to_db(user_id):
    """يضيف معرف مستخدم إلى جدول المستخدمين المصرح لهم."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO authorized_users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:  # المستخدم موجود بالفعل
        return False
    finally:
        conn.close()

def remove_authorized_user_from_db(user_id):
    """يزيل معرف مستخدم من جدول المستخدمين المصرح لهم ومحادثاتهم المستهدفة."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM authorized_users WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM user_target_chats WHERE user_id = ?', (user_id,)) # إزالة المحادثات المستهدفة أيضًا
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

def get_user_target_chats(user_id):
    """يجلب معرفات المحادثات المستهدفة لمستخدم معين.
        مُعدّل: الآن، يمكن لأي مستخدم مصرح له المشاركة في جميع المحادثات المميزة."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # هذا التعديل يسمح لجميع المستخدمين المصرح لهم (وليس فقط المسؤول) برؤية/المشاركة في جميع المحادثات المسجلة.
    # إذا كنت تريد أن يرى المسؤول فقط الجميع، قم بإعادة هذا الجزء إلى كود 'if is_admin(user_id):' الأصلي.
    cursor.execute('SELECT DISTINCT chat_id FROM user_target_chats')
        
    chats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return chats

def add_user_target_chat_to_db(user_id, chat_id):
    """يضيف معرف محادثة مستهدفة لمستخدم معين إلى قاعدة البيانات."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO user_target_chats (user_id, chat_id) VALUES (?, ?)', (user_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0 # يعود True إذا تم إدراج صف جديد
    finally:
        conn.close()

def remove_user_target_chat_from_db(user_id, chat_id):
    """يزيل معرف محادثة مستهدفة. يمكن للمسؤول إزالته لجميع المستخدمين."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    if is_admin(user_id):
        # يمكن للمسؤول إزالة المحادثة من قوائم جميع المستخدمين
        cursor.execute('DELETE FROM user_target_chats WHERE chat_id = ?', (chat_id,))
    else:
        # يمكن للمستخدم العادي إزالة المحادثة من قائمته الخاصة فقط
        cursor.execute('DELETE FROM user_target_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

# تهيئة قاعدة البيانات وتحميل المستخدمين المصرح لهم عند بدء التشغيل
init_db()
AUTHORIZED_USER_IDS = get_authorized_users()

print(f"تم تحميل {len(AUTHORIZED_USER_IDS)} مستخدمين مصرح لهم من قاعدة البيانات.")
print("معالجة المحادثات المستهدفة الآن خاصة بكل مستخدم، ولكن يمكن للمسؤول المشاركة مع الجميع.")

# --- وظائف مساعدة ---
def is_authorized(user_id):
    """يتحقق مما إذا كان المستخدم مصرحًا له باستخدام البوت."""
    return user_id in AUTHORIZED_USER_IDS

def is_admin(user_id):
    """يتحقق مما إذا كان المستخدم هو مسؤول البوت."""
    return user_id == ADMIN_USER_ID

# Helper function to escape MarkdownV2 special characters - MOVED TO GLOBAL SCOPE
def safer_escape_markdown_v2(text):
    """
    Escapes special MarkdownV2 characters in the given text.
    This function is designed to make arbitrary text safe for MarkdownV2 parsing
    by escaping all characters that have special meaning, unless explicitly
    part of a desired MarkdownV2 formatting.
    """
    # List of characters that need to be escaped in MarkdownV2.
    # Order matters for some, e.g., backslash first.
    chars_to_escape = ['\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    escaped_text = text
    for char in chars_to_escape:
        # Escape the character unless it's part of a known valid MarkdownV2 structure
        # (e.g., inside [text](url) or **bold** which we handle by applying *after* escaping or manually).
        # For general text, it's safest to escape them all.
        escaped_text = escaped_text.replace(char, '\\' + char)
    return escaped_text

# --- الدالة الجديدة لتقسيم الرسائل الطويلة ---
def send_long_message(chat_id, text, parse_mode="MarkdownV2", reply_markup=None):
    """
    تقوم بتقسيم الرسائل الطويلة إلى أجزاء وإرسالها إلى المحادثة المحددة.
    تم تحديثها لاستخدام MarkdownV2 افتراضيًا.
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        # قم بتقسيم النص إلى أجزاء
        chunks = []
        for i in range(0, len(text), MAX_MESSAGE_LENGTH):
            chunks.append(text[i:i+MAX_MESSAGE_LENGTH])
            
        for i, chunk in enumerate(chunks):
            # أرسل كل جزء كرسالة منفصلة
            # فقط آخر جزء قد يحتوي على لوحة مفاتيح إذا كانت مرفقة
            current_reply_markup = reply_markup if i == len(chunks) - 1 else None
            try:
                bot.send_message(chat_id, chunk, parse_mode=parse_mode, reply_markup=current_reply_markup)
                time.sleep(0.5) # تأخير قصير بين الرسائل لتجنب حدود المعدل
            except telebot.apihelper.ApiTelegramException as e:
                print(f"خطأ في إرسال جزء من الرسالة الطويلة إلى {chat_id}: {e}")


def get_main_keyboard(user_id):
    """ينشئ لوحة المفاتيح المضمنة الرئيسية للبوت."""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🚀 بدء الشير", callback_data="start_share_mode"))
    
    if user_share_mode.get(user_id):
        markup.add(telebot.types.InlineKeyboardButton("🛑 إيقاف الشير", callback_data="stop_share_mode"))
    
    markup.add(telebot.types.InlineKeyboardButton("📊 حالة الشير", callback_data="show_share_status"))
    markup.add(telebot.types.InlineKeyboardButton("📜 المجموعات/القنوات الخاصة بي", callback_data="list_my_target_chats"))
    
    if is_admin(user_id):
        markup.add(telebot.types.InlineKeyboardButton("📋 قائمة المستخدمين المصرح لهم", callback_data="list_authorized_users"))
        markup.add(telebot.types.InlineKeyboardButton("➕ إضافة مستخدم (ID)", callback_data="admin_add_user_prompt"))
        markup.add(telebot.types.InlineKeyboardButton("➖ إزالة مستخدم (ID)", callback_data="admin_remove_user_prompt"))
        markup.add(telebot.types.InlineKeyboardButton("🗑️ إزالة شات (ID)", callback_data="admin_remove_chat_prompt"))
        
    return markup

# --- Command Handlers (/start and /help) ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """يتعامل مع أوامر /start و /help، ويرحب بالمستخدمين المصرح لهم أو يوجه غير المصرح لهم."""
    
    user_chat_id = message.chat.id 
    user_id = message.from_user.id
    # الحصول على الاسم الأول للمستخدم
    user_first_name = message.from_user.first_name if message.from_user.first_name else "صديقي"

    # إضافة المحادثة الخاصة بالمستخدم مع البوت إلى محادثاته المستهدفة
    if add_user_target_chat_to_db(user_id, user_chat_id):
        print(f"المحادثة الخاصة بالمستخدم {user_id} (المعرف: {user_chat_id}) تمت إضافتها إلى محادثاته المستهدفة.")
    else:
        print(f"المحادثة الخاصة بالمستخدم {user_id} (المعرف: {user_chat_id}) موجودة بالفعل في محادثاته المستهدفة.")

    if not is_authorized(user_id):
        markup = telebot.types.InlineKeyboardMarkup()
        owner_link = "https://t.me/MoOos_CcOo"
        channel_link = "https://t.me/+P9BOtTPcss9jMGFk"
        
        # For unauthorized users, escape all special characters in the text
        unauthorized_welcome_text = (
            "مرحباً بك 🔥\n\n"
            f"مرحباً بك يا {safer_escape_markdown_v2(user_first_name)} 👋\n\n"
            "1\\- دياثة وتجسس محارم عربي وبدويات 🔥🥵\n\n"
            "2\\- تحرش وتجسس جيران اغتصاب حقيقي🥴🥵\n\n"
            "بـوت حــفـلات ديـاثة سوالــب🥵🌶️\n\n"
            "🌟 مرحباً بك في بوت الشير المتطور\\! 🌟\n\n"
            " لا يمكنك استخدام هذا البوت عليك الرجوع الي المالك \n\n"
            "𝓜𝓸𝓼𝓬𝓸𝔀 ☠\n\n"
            f"✨ Developer: [{safer_escape_markdown_v2('@MoOos_CcOo')}]({owner_link})\n\n"
            f"📢 Channal : {channel_link}"
        )
        markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url=owner_link))  
        bot.send_message(user_chat_id, unauthorized_welcome_text, reply_markup=markup, parse_mode="MarkdownV2")
        return

    # For authorized users, the main welcome text.
    # Corrected welcome_text for MarkdownV2
    welcome_text = (
        "مرحباً بك 🔥\n\n"
        f"مرحباً بك يا {safer_escape_markdown_v2(user_first_name)} 👋\n\n"
        "1\\- دياثة وتجسس محارم عربي وبدويات 🔥🥵\n\n"
        "2\\- تحرش وتجسس جيران اغتصاب حقيقي🥴🥵\n\n"
        "بـوت حــفـلات ديـاثة سوالــب🥵🌶️\n\n"
        "🌟 مرحباً بك في بوت الشير المتطور\\! 🌟\n"
        "هنا يمكنك التحكم في نشر رسائلك بسهولة\\.\n"
        "عند تفعيل وضع الشير، سيتم إرسال محتواك لجميع المجموعات والقنوات التي \\*\\*أنت\\*\\* قمت بإعدادها\\.\n\n"
        "𝓜𝓸𝓼𝓬𝓸𝔀 ☠\n\n"
        f"✨ Developer: [{safer_escape_markdown_v2('@MoOos_CcOo')}]({safer_escape_markdown_v2('https://t.me/MoOos_CcOo')})\n\n"
        f"📢 Channal : [{safer_escape_markdown_v2('https://t.me/+P9BOtTPcss9jMGFk')}]({safer_escape_markdown_v2('https://t.me/+P9BOtTPcss9jMGFk')})"
    )

    # استخدام الدالة الجديدة لإرسال رسالة الترحيب
    send_long_message(
        user_chat_id,
        welcome_text,
        parse_mode="MarkdownV2", # Explicitly use MarkdownV2 here
        reply_markup=get_main_keyboard(user_id)
    )

# --- Callback Query Handler (Button Presses) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """يتعامل مع ضغطات زر لوحة المفاتيح المضمنة."""
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    bot.answer_callback_query(call.id) # لإخفاء أيقونة التحميل على الزر

    if not is_authorized(user_id):
        bot.send_message(chat_id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك. MOSCO", parse_mode="MarkdownV2") # Ensure this message is also correctly parsed.
        return

    if data == "start_share_mode":
        user_share_mode[user_id] = True
        # Using safer_escape_markdown_v2 for bot messages
        bot.send_message(chat_id, safer_escape_markdown_v2("🚀 \\*\\*تم تفعيل وضع الشير\\.\\*\\* الآن، أرسل لي أي شيء لعمل شير له في جميع المجموعات والقنوات الخاصة بك\\."), parse_mode="MarkdownV2")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass # لا تفعل شيئًا إذا لم تتغير لوحة المفاتيح
            else:
                print(f"خطأ في تعديل لوحة المفاتيح: {e}") # سجل الأخطاء الأخرى
    
    elif data == "stop_share_mode":
        user_share_mode[user_id] = False
        bot.send_message(chat_id, safer_escape_markdown_v2("🛑 \\*\\*تم إيقاف وضع الشير\\.\\*\\* لن أقوم بشير الرسائل بعد الآن\\."), parse_mode="MarkdownV2")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass
            else:
                print(f"خطأ في تعديل لوحة المفاتيح: {e}")

    elif data == "show_share_status":
        if user_id in last_shared_message:
            # Using safer_escape_markdown_v2 for bot messages
            send_long_message(chat_id, f"آخر رسالة قمت بشيرها كانت:\\n\\n`{safer_escape_markdown_v2(last_shared_message[user_id])}`", parse_mode="MarkdownV2")
        else:
            bot.send_message(chat_id, safer_escape_markdown_v2("لم تقم بشير أي رسالة بعد\\."), parse_mode="MarkdownV2")
    
    elif data == "list_my_target_chats":
        my_target_chats = get_user_target_chats(user_id)

        if not my_target_chats:
            bot.send_message(chat_id, safer_escape_markdown_v2("لا توجد مجموعات أو قنوات مسجلة لك حاليًا للشير فيها\\. يمكنك إضافتي إلى مجموعة أو قناة لتسجيلها\\."), parse_mode="MarkdownV2")
            return
        
        # Apply bolding directly in the string
        message_text = safer_escape_markdown_v2("\\*\\*المجموعات والقنوات التي تشارك فيها\\:\\*\\*\n") 
        for target_id in my_target_chats:
            try:
                chat_info = bot.get_chat(target_id)
                if chat_info.type == 'group' or chat_info.type == 'supergroup':
                    message_text += safer_escape_markdown_v2(f"- مجموعة: `{chat_info.title}` (ID: `{target_id}`)\n")
                elif chat_info.type == 'channel':
                    message_text += safer_escape_markdown_v2(f"- قناة: `{chat_info.title}` (ID: `{target_id}`)\n")
                elif chat_info.type == 'private':
                    message_text += safer_escape_markdown_v2(f"- خاص مع: `{chat_info.first_name}` (ID: `{target_id}`)\n")
                else:
                    message_text += safer_escape_markdown_v2(f"- نوع غير معروف (ID: `{target_id}`)\n")
            except telebot.apihelper.ApiTelegramException as e:
                if e.error_code == 400 and "chat not found" in e.description.lower():
                    message_text += safer_escape_markdown_v2(f"- لا يمكن الوصول لـ ID: `{target_id}` (معرف غير صالح أو البوت غير موجود به)\n")
                    if remove_user_target_chat_from_db(user_id, target_id):
                        message_text += safer_escape_markdown_v2(" تم إزالة الشات تلقائيًا من قائمة الشير الخاصة بك\\.\n")
                elif e.error_code == 403: # تم حظر البوت أو إزالته من المحادثة/القناة
                    message_text += safer_escape_markdown_v2(f"- لا يمكن الوصول لـ ID: `{target_id}` (البوت محظور أو تم إزالته)\n")
                    if remove_user_target_chat_from_db(user_id, target_id):
                        message_text += safer_escape_markdown_v2(" تم إزالة الشات تلقائيًا من قائمة الشير الخاصة بك بسبب طرد البوت\\.\n")
                else:
                    message_text += safer_escape_markdown_v2(f"- لا يمكن الوصول لـ ID: `{target_id}` (خطأ غير معروف: {e.description})\n")
                print(f"خطأ في جلب معلومات الشات {target_id}: {e}")
            except Exception as e:
                message_text += safer_escape_markdown_v2(f"- لا يمكن الوصول لـ ID: `{target_id}` (خطأ عام: {e})\n")
                print(f"خطأ عام في جلب معلومات الشات {target_id}: {e}")
        
        send_long_message(chat_id, message_text, parse_mode="MarkdownV2")

    elif data == "list_authorized_users":  
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط\\.", parse_mode="MarkdownV2")
            return
        
        global AUTHORIZED_USER_IDS
        AUTHORIZED_USER_IDS = get_authorized_users() # إعادة التحميل لضمان أحدث قائمة

        if not AUTHORIZED_USER_IDS:
            bot.send_message(chat_id, "لا يوجد مستخدمون مصرح لهم حاليًا\\.", parse_mode="MarkdownV2")
            return
        
        users_list = "\n".join([str(uid) for uid in AUTHORIZED_USER_IDS])
        send_long_message(chat_id, safer_escape_markdown_v2(f"\\*\\*المستخدمون المصرح لهم\\:\\*\\*\n{users_list}"), parse_mode="MarkdownV2")

    elif data == "admin_add_user_prompt":  
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط\\.", parse_mode="MarkdownV2")
            return
        msg = bot.send_message(chat_id, safer_escape_markdown_v2("الرجاء إدخال ID المستخدم الذي تريد إضافته:"), parse_mode="MarkdownV2")
        bot.register_next_step_handler(msg, add_user_by_admin)

    elif data == "admin_remove_user_prompt":  
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط\\.", parse_mode="MarkdownV2")
            return
        msg = bot.send_message(chat_id, safer_escape_markdown_v2("الرجاء إدخال ID المستخدم الذي تريد إزالته:"), parse_mode="MarkdownV2")
        bot.register_next_step_handler(msg, remove_user_by_admin)
    
    elif data == "admin_remove_chat_prompt":
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط\\.", parse_mode="MarkdownV2")
            return
        msg = bot.send_message(chat_id, safer_escape_markdown_v2("الرجاء إدخال ID الشات الذي تريد إزالته من قائمة الشير (سواء كان شات خاص بك أو بأي مستخدم آخر):"), parse_mode="MarkdownV2")
        bot.register_next_step_handler(msg, remove_chat_by_admin)

# --- Admin Functions for User Management ---
def add_user_by_admin(message):
    """معالج لإضافة مستخدم مصرح به من قبل المسؤول."""
    global AUTHORIZED_USER_IDS
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك\\.", parse_mode="MarkdownV2")
        return
    try:
        user_id_to_add = int(message.text.strip())
        if add_authorized_user_to_db(user_id_to_add):
            AUTHORIZED_USER_IDS.append(user_id_to_add) # إضافة مؤقتة إلى القائمة في الذاكرة
            bot.send_message(message.chat.id, safer_escape_markdown_v2(f"تمت إضافة المستخدم {user_id_to_add} بنجاح\\."), parse_mode="MarkdownV2")
            try:
                bot.send_message(user_id_to_add, safer_escape_markdown_v2("تهانينا\\! لقد تم التصريح لك الآن باستخدام بوت الشير\\. أرسل لي /start\\."), parse_mode="MarkdownV2")
            except Exception as e:
                print(f"فشل إرسال رسالة للمستخدم {user_id_to_add}: {e}")
                bot.send_message(message.chat.id, safer_escape_markdown_v2(f"ملاحظة: لم أستطع إرسال رسالة للمستخدم {user_id_to_add}\\. ربما لم يبدأ البوت من قبل\\."), parse_mode="MarkdownV2")
        else:
            bot.send_message(message.chat.id, safer_escape_markdown_v2(f"المستخدم {user_id_to_add} موجود بالفعل في قائمة المصرح لهم\\."), parse_mode="MarkdownV2")

    except ValueError:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("الرجاء إدخال ID صحيح (رقم)\\."), parse_mode="MarkdownV2")
    finally:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("اختر من القائمة الرئيسية:"), reply_markup=get_main_keyboard(message.from_user.id), parse_mode="MarkdownV2")

def remove_user_by_admin(message):
    """معالج لإزالة مستخدم مصرح به من قبل المسؤول."""
    global AUTHORIZED_USER_IDS
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك\\.", parse_mode="MarkdownV2")
        return
    try:
        user_id_to_remove = int(message.text.strip())
        if user_id_to_remove == ADMIN_USER_ID:
            bot.send_message(message.chat.id, safer_escape_markdown_v2("لا يمكنك إزالة نفسك من قائمة المشرفين\\."), parse_mode="MarkdownV2")
        elif remove_authorized_user_from_db(user_id_to_remove):
            if user_id_to_remove in AUTHORIZED_USER_IDS:
                AUTHORIZED_USER_IDS.remove(user_id_to_remove) # إزالة مؤقتة من القائمة في الذاكرة
            bot.send_message(message.chat.id, safer_escape_markdown_v2(f"تمت إزالة المستخدم {user_id_to_remove} بنجاح\\."), parse_mode="MarkdownV2")  
        else:
            bot.send_message(message.chat.id, safer_escape_markdown_v2(f"المستخدم {user_id_to_remove} ليس في قائمة المصرح لهم أصلاً\\."), parse_mode="MarkdownV2")

    except ValueError:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("الرجاء إدخال ID صحيح (رقم)\\."), parse_mode="MarkdownV2")
    finally:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("اختر من القائمة الرئيسية:"), reply_markup=get_main_keyboard(message.from_user.id), parse_mode="MarkdownV2")

def remove_chat_by_admin(message):
    """معالج لإزالة محادثة مستهدفة من قبل المسؤول."""
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط\\.", parse_mode="MarkdownV2")
        return
    try:
        chat_id_to_remove = int(message.text.strip())
        if remove_user_target_chat_from_db(message.from_user.id, chat_id_to_remove):  
            bot.send_message(message.chat.id, safer_escape_markdown_v2(f"تمت إزالة الشات {chat_id_to_remove} بنجاح من جميع قوائم الشير\\."), parse_mode="MarkdownV2")
        else:
            bot.send_message(message.chat.id, safer_escape_markdown_v2(f"الشات {chat_id_to_remove} غير موجود في أي قائمة شير مسجلة\\."), parse_mode="MarkdownV2")
    except ValueError:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("الرجاء إدخال ID صحيح (رقم)\\."), parse_mode="MarkdownV2")
    finally:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("اختر من القائمة الرئيسية:"), reply_markup=get_main_keyboard(message.from_user.id), parse_mode="MarkdownV2")

# --- Main Message Handler (Performs Sharing) ---
# هذا المعالج يستقبل جميع أنواع الرسائل عندما يكون وضع المشاركة نشطًا
@bot.message_handler(func=lambda message: user_share_mode.get(message.from_user.id, False),  
                      content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def forward_all_messages_to_user_chats(message):
    """يعيد توجيه الرسائل المستلمة إلى جميع المحادثات المستهدفة إذا كان وضع المشاركة نشطًا."""
    user_id = message.from_user.id
    if not is_authorized(user_id):
        bot.send_message(message.chat.id, safer_escape_markdown_v2("عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك. MOSCO"), parse_mode="MarkdownV2") # Ensure this message is also correctly parsed.
        return

    user_target_chats = get_user_target_chats(user_id)  

    successful_shares = 0
    failed_shares = 0
    
    bot.send_message(message.chat.id, safer_escape_markdown_v2("جاري معالجة الشير... قد يستغرق الأمر بعض الوقت\\."), parse_mode="MarkdownV2")

    if not user_target_chats:
        bot.send_message(message.chat.id, safer_escape_markdown_v2("لا توجد مجموعات أو قنوات مسجلة لك حاليًا للشير فيها\\. الرجاء إضافة البوت إلى مجموعات أو قنوات جديدة، أو أضف الـ IDs يدويًا\\."), parse_mode="MarkdownV2")
        return

    for target_chat_id in user_target_chats:
        try:
            bot.copy_message(target_chat_id, message.chat.id, message.message_id)
            successful_shares += 1
            time.sleep(2) # تأخير لتقليل فرصة الوصول إلى حدود API في تيليجرام
        except telebot.apihelper.ApiTelegramException as e:
            failed_shares += 1  
            # Use `safer_escape_markdown_v2` for parts of the error message that might contain special characters.
            error_message_for_user = safer_escape_markdown_v2(f"❌ فشل الشير إلى `{target_chat_id}`: ") # إضافة علامات الاقتباس المائلة لمعرف المحادثة
            
            # معالجة مفصلة للأخطاء بناءً على رموز خطأ Telegram API
            if e.error_code == 400: # طلب سيء
                if "CHANNEL_FORWARDS_FORBIDDEN" in e.description:
                    error_message_for_user += safer_escape_markdown_v2("هذه القناة لا تسمح بإعادة توجيه الرسائل\\. (تحقق من إعدادات القناة)\\.")
                elif "CHAT_SEND_WEBPAGE_FORBIDDEN" in e.description:
                    error_message_for_user += safer_escape_markdown_v2("هذه القناة/المجموعة لا تسمح بمعاينات صفحات الويب\\. (تحقق من إعدادات الشات، أو تأكد أن رسالتك لا تحتوي على روابط أو لا تحاول معاينتها)\\.")
                elif "CHAT_WRITE_FORBIDDEN" in e.description:
                    error_message_for_user += safer_escape_markdown_v2("البوت ليس لديه صلاحية النشر في هذه القناة/المجموعة\\. (اجعله مشرفًا)\\.")
                elif "chat not found" in e.description.lower():
                    error_message_for_user += safer_escape_markdown_v2("لم يتم العثور على الشات\\. (ID خاطئ أو تم حذف الشات)\\.")
                    # إزالة المحادثة تلقائيًا من قائمة المستخدم إذا لم يتم العثور عليها
                    if remove_user_target_chat_from_db(user_id, target_chat_id):
                        error_message_for_user += safer_escape_markdown_v2(" تم إزالة الشات تلقائيًا من قائمة الشير الخاصة بك\\.")
                else: # Generic 400 error
                    error_message_for_user += safer_escape_markdown_v2(f"خطأ غير متوقع من Telegram API: {e.description}")

            elif e.error_code == 403: # ممنوع
                error_message_for_user += safer_escape_markdown_v2("البوت محظور أو تم إزالته من هذه القناة/المجموعة\\. يرجى إعادة إضافته أو إلغاء حظره\\.")
                # إزالة المحادثة تلقائيًا من قائمة المستخدم إذا كانت ممنوعة
                if remove_user_target_chat_from_db(user_id, target_chat_id):
                    error_message_for_user += safer_escape_markdown_v2(" تم إزالة الشات تلقائيًا من قائمة الشير الخاصة بك بسبب طرد البوت\\.")
            elif e.error_code == 429: # طلبات كثيرة جدًا
                retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                print(f"⚠️ تجاوز حد الطلبات إلى {target_chat_id} للمستخدم {user_id}. سأنتظر {retry_after} ثوانٍ.")
                error_message_for_user += safer_escape_markdown_v2(f"تم تجاوز حد الطلبات في Telegram\\. سأستأنف الشير بعد {retry_after} ثوانٍ\\.")
                # محاولة إعادة الإرسال بعد الانتظار
                time.sleep(retry_after + 1) # إضافة ثانية إضافية للسلامة
                try:
                    bot.copy_message(target_chat_id, message.chat.id, message.message_id)
                    successful_shares += 1
                    failed_shares -= 1 # إذا نجحت إعادة المحاولة، لا تعد فاشلة
                    time.sleep(2)
                    continue # تخطي بقية هذه الدورة للمحادثة الحالية
                except Exception as retry_e: # إذا فشلت إعادة المحاولة أيضًا
                    error_message_for_user += safer_escape_markdown_v2(f" فشل مرة أخرى بعد الانتظار: {retry_e}")
            else: # أي أخطاء أخرى غير متوقعة في Telegram API
                error_message_for_user += safer_escape_markdown_v2(f"خطأ غير متوقع من Telegram API: {e.description}")

            print(f"{error_message_for_user} (كود الخطأ: {e.error_code})")
            # إرسال رسالة الخطأ للمستخدم فقط إذا كانت المحادثة المستهدفة ليست هي نفس المحادثة المصدر
            if target_chat_id != message.chat.id:  
                send_long_message(message.chat.id, error_message_for_user, parse_mode="MarkdownV2")  
        except Exception as e: # Catch any other unexpected general errors
            failed_shares += 1
            print(f"❌ فشل الشير إلى {target_chat_id} للمستخدم {user_id} بسبب خطأ عام: {e}")
            if target_chat_id != message.chat.id:
                send_long_message(message.chat.id, safer_escape_markdown_v2(f"❌ فشل الشير إلى `{target_chat_id}` بسبب خطأ عام: {e}"), parse_mode="MarkdownV2")  

    bot.send_message(message.chat.id, safer_escape_markdown_v2(f"✅ تم الشير بنجاح\\! ({successful_shares} شير ناجح، {failed_shares} شير فاشل)\\."), parse_mode="MarkdownV2")
    
    # حفظ معلومات حول آخر رسالة تمت مشاركتها
    # Ensure saved message also has escaped characters if it's text.
    if message.text:
        last_shared_message[user_id] = safer_escape_markdown_v2(f"رسالة نصية: {message.text[:50]}...")
    elif message.photo:
        last_shared_message[user_id] = safer_escape_markdown_v2(f"صورة (ID: {message.photo[-1].file_id})")
    elif message.video:
        last_shared_message[user_id] = safer_escape_markdown_v2(f"فيديو (ID: {message.video.file_id})")
    elif message.document:
        last_shared_message[user_id] = safer_escape_markdown_v2(f"ملف (الاسم: {message.document.file_name})")
    else: # لأنواع المحتوى الأخرى
        last_shared_message[user_id] = safer_escape_markdown_v2(f"نوع آخر من المحتوى (ID: {message.message_id})")

# --- Message Handler for Authorized Users (when sharing mode is OFF) ---
@bot.message_handler(func=lambda message: not user_share_mode.get(message.from_user.id, False) and is_authorized(message.from_user.id),  
                      content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def handle_other_authorized_messages(message):
    """يخبر المستخدمين المصرح لهم أن وضع المشاركة متوقف إذا أرسلوا رسالة."""
    bot.send_message(
        message.chat.id,
        safer_escape_markdown_v2("لم أقم بشير رسالتك لأن وضع الشير غير مفعل\\. استخدم الأزرار للتحكم\\."),
        reply_markup=get_main_keyboard(message.from_user.id),
        parse_mode="MarkdownV2"
    )

# --- Message Handler for Any Unauthorized User ---
@bot.message_handler(func=lambda message: not is_authorized(message.from_user.id))
def handle_unauthorized_messages(message):
    """يخبر المستخدمين غير المصرح لهم أنهم لا يستطيعون استخدام البوت ويوفر معلومات الاتصال."""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow"))  
    bot.send_message(message.chat.id, safer_escape_markdown_v2("عذرًا، أنت غير مصرح لك باستخدام هذا البوت\\. هذا البوت خاص\\. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك\\. MOSCO"), reply_markup=markup, parse_mode="MarkdownV2")

# --- Handler when the Bot is Added to a New Group/Channel ---
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_members(message):
    """يتعامل مع حدث إضافة البوت إلى محادثة جديدة (مجموعة أو قناة)."""
    for member in message.new_chat_members:
        if member.id == bot.get_me().id: # التحقق مما إذا كان العضو الجديد هو البوت نفسه
            chat_id = message.chat.id
            user_id = message.from_user.id # المستخدم الذي أضاف البوت

            # التحقق مما إذا كان المستخدم الذي أضاف البوت مصرحًا له
            if not is_authorized(user_id):
                try:
                    bot.send_message(chat_id, safer_escape_markdown_v2("عذرًا، لا يمكنني العمل في هذا الشات لأن المستخدم الذي أضافني غير مصرح له\\. يرجى التواصل مع المالك\\. MOSCO"),  
                                     reply_markup=telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow")), parse_mode="MarkdownV2")
                    bot.leave_chat(chat_id) # اختياريًا، اجعل البوت يغادر إذا كان المضيف غير مصرح له
                except Exception as e:
                    print(f"فشل إرسال رسالة المغادرة أو المغادرة من شات {chat_id}: {e}")
                return # توقف عن المعالجة إذا كان غير مصرح به

            # إضافة المحادثة إلى المحادثات المستهدفة للمستخدم
            if add_user_target_chat_to_db(user_id, chat_id):
                print(f"✅ تم إضافة الشات الجديد (ID: {chat_id}, النوع: {message.chat.type}, الاسم: {message.chat.title or message.chat.first_name}) إلى قائمة الشير للمستخدم {user_id}.")
                
                welcome_message_to_chat = safer_escape_markdown_v2(f"شكرًا لإضافتي\\! أنا هنا لمساعدتك في نشر الرسائل\\.\n")
                if message.chat.type == 'channel':
                    welcome_message_to_chat += safer_escape_markdown_v2("⚠️ \\*\\*ملاحظة هامة للقنوات\\:\\*\\* لكي أتمكن من النشر هنا، يرجى التأكد من أنني مشرف في هذه القناة ولدي صلاحية 'نشر الرسائل'\\.")
                
                try:
                    # إرسال رسالة إلى المستخدم الذي أضاف البوت
                    send_long_message(user_id, safer_escape_markdown_v2(f"تم تسجيل هذه المجموعة/القناة (ID: `{chat_id}`, الاسم: `{message.chat.title or message.chat.first_name}`) لقائمة الشير الخاصة بك\\."), parse_mode="MarkdownV2")
                    time.sleep(1) # تأخير قصير
                    # إرسال رسالة ترحيب في المجموعة/القناة الجديدة نفسها
                    send_long_message(chat_id, welcome_message_to_chat, parse_mode="MarkdownV2")
                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429: # تجاوز حد المعدل
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                        print(f"⚠️ تجاوز حد الطلبات عند إضافة بوت لشات جديد. سأنتظر {retry_after} ثوانٍ.")
                        time.sleep(retry_after + 1)
                        try: # إعادة محاولة إرسال الرسائل بعد التأخير
                            send_long_message(user_id, safer_escape_markdown_v2(f"تم تسجيل هذه المجموعة/القناة (ID: `{chat_id}`, الاسم: `{message.chat.title or message.chat.first_name}`) لقائمة الشير الخاصة بك\\."), parse_mode="MarkdownV2")
                            time.sleep(1)
                            send_long_message(chat_id, welcome_message_to_chat, parse_mode="MarkdownV2")
                        except Exception as retry_e:
                            print(f"❌ فشل إرسال رسالة الترحيب بعد الانتظار: {retry_e}")
                    else:
                        print(f"❌ فشل إرسال رسالة الترحيب عند إضافة البوت لشات جديد: {e}")
                except Exception as e:
                    print(f"❌ خطأ عام في معالجة إضافة البوت لشات جديد: {e}")
            else:
                print(f"الشات (ID: {chat_id}) موجود بالفعل في قائمة الشير للمستخدم {user_id}.")
                try:
                    send_long_message(user_id, safer_escape_markdown_v2(f"هذه المجموعة/القناة (ID: `{chat_id}`, الاسم: `{message.chat.title or message.chat.first_name}`) موجودة بالفعل في قائمة الشير الخاصة بك\\."), parse_mode="MarkdownV2")
                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429:
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                        print(f"⚠️ تجاوز حد الطلبات عند إبلاغ مستخدم بشات موجود. سأنتظر {retry_after} ثوانٍ.")
                        time.sleep(retry_after + 1)
                        try:
                            send_long_message(user_id, safer_escape_markdown_v2(f"هذه المجموعة/القناة (ID: `{chat_id}`, الاسم: `{message.chat.title or message.chat.first_name}`) موجودة بالفعل في قائمة الشير الخاصة بك\\."), parse_mode="MarkdownV2")
                        except Exception as retry_e:
                            print(f"❌ فشل إرسال رسالة التنبيه بعد الانتظار: {retry_e}")
                    else:
                        print(f"❌ فشل إرسال رسالة التنبيه عند إضافة البوت لشات جديد: {e}")
                except Exception as e:
                    print(f"❌ خطأ عام في معالجة إبلاغ المستخدم بشات موجود: {e}")
            break # الخروج من الحلقة بعد التعامل مع إضافة البوت

# --- بدء البوت ---
print("البوت يعمل الآن...")
# هذه الدالة تبقي البوت قيد التشغيل وتستقبل التحديثات من Telegram API
bot.polling(non_stop=True, interval=5)
