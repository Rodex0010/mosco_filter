import telebot
import time
import json
import os
import sqlite3

# --- Basic Bot Configuration ---

# The bot token will be loaded from environment variables on Railway
MOSCO_TOKEN = os.getenv('MOSCO_TOKEN')
if not MOSCO_TOKEN:
    print("Error: The 'MOSCO_TOKEN' environment variable is not set. Please configure it on Railway.")
    exit()

bot = telebot.TeleBot(MOSCO_TOKEN)

# Owner's User ID (Replace with your actual Telegram User ID)
ADMIN_USER_ID = 7602163093  # You should replace this with your actual Telegram User ID
DATABASE_NAME = 'bot_data.db'

# In-memory dictionaries to track user states
user_share_mode = {}
last_shared_message = {}

# --- SQLite Database Functions ---
def init_db():
    """Initializes the SQLite database and creates necessary tables."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Table for authorized users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    # Table for user-specific target chats
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_target_chats (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    
    # Ensure the admin user is always authorized
    cursor.execute('INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)', (ADMIN_USER_ID,))
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_authorized_users():
    """Fetches all authorized user IDs from the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM authorized_users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def add_authorized_user_to_db(user_id):
    """Adds a user ID to the authorized users table."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO authorized_users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:  # User already exists
        return False
    finally:
        conn.close()

def remove_authorized_user_from_db(user_id):
    """Removes a user ID from the authorized users table and their target chats."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM authorized_users WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM user_target_chats WHERE user_id = ?', (user_id,))  # Also remove target chats
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

def get_user_target_chats(user_id):
    """Fetches target chat IDs for a specific user. Admin gets all distinct chats."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    if is_admin(user_id):
        # Admin can share to all registered chats by any user
        cursor.execute('SELECT DISTINCT chat_id FROM user_target_chats')
    else:
        # Regular user only shares to their own registered chats
        cursor.execute('SELECT chat_id FROM user_target_chats WHERE user_id = ?', (user_id,))
    
    chats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return chats

def add_user_target_chat_to_db(user_id, chat_id):
    """Adds a target chat ID for a specific user to the database."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO user_target_chats (user_id, chat_id) VALUES (?, ?)', (user_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0  # Returns True if a new row was inserted
    finally:
        conn.close()

def remove_user_target_chat_from_db(user_id, chat_id):
    """Removes a target chat ID. Admin can remove it for all users."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    if is_admin(user_id):
        # Admin can remove the chat from all users' lists
        cursor.execute('DELETE FROM user_target_chats WHERE chat_id = ?', (chat_id,))
    else:
        # Regular user can only remove the chat from their own list
        cursor.execute('DELETE FROM user_target_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

# Initialize the database and load authorized users on startup
init_db()
AUTHORIZED_USER_IDS = get_authorized_users()

print(f"Loaded {len(AUTHORIZED_USER_IDS)} authorized users from the database.")
print("Target chats handling is now specific to each user, but admin can share to all.")

# --- Helper Functions ---
def is_authorized(user_id):
    """Checks if a user is authorized to use the bot."""
    return user_id in AUTHORIZED_USER_IDS

def is_admin(user_id):
    """Checks if a user is the bot's administrator."""
    return user_id == ADMIN_USER_ID

def get_main_keyboard(user_id):
    """Generates the main inline keyboard for the bot."""
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
    """Handles /start and /help commands, welcoming authorized users or directing unauthorized ones."""
    
    user_chat_id = message.chat.id 
    user_id = message.from_user.id

    # Add the user's private chat with the bot to their target chats
    if add_user_target_chat_to_db(user_id, user_chat_id):
        print(f"User  {user_id}'s private chat (ID: {user_chat_id}) added to their target chats.")
    else:
        print(f"User  {user_id}'s private chat (ID: {user_chat_id}) already in their target chats.")

    if not is_authorized(user_id):
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow")) 
        bot.send_message(
            user_chat_id,
            (
                "🔥 مرحباً بك يا {user_first_name} 👋\n\n"
                "💥 *قائمة المحتوى:* \n"
                "1️⃣ دياثة وتجسس على المحارم - عربي وبدويات 🥵\n"
                "2️⃣ تحرش وجيران - اغتصاب حقيقي 🥴🥵\n\n"
                "🎉 بوت حفلات دياثة وسوالب 🔥🌶️\n\n"
                "🚫 *أنت غير مصرح لك باستخدام هذا البوت.*\n"
                "هذا البوت *خاص* ومتاح فقط لمستخدمين محددين.\n"
                "للتواصل وطلب الوصول، راسل المالك 👇\n\n"
                "👨‍💻 *Developer:* @Mo_sc_ow\n"
                "📢 *Channel:* @Vib_one"
            ).format(user_first_name=message.from_user.first_name or "صديقي"),
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return

    user_first_name = message.from_user.first_name if message.from_user.first_name else "صديقي"
    
    welcome_text = (
        "مرحباً بك 🔥\n\n"
        f"مرحباً بك يا {user_first_name} 👋\n\n"
        "1- دياثة وتجسس محارم عربي وبدويات 🔥🥵\n"
        "2- تحرش وتجسس جيران اغتصاب حقيقي🥴🥵\n\n"
        "بـوت حــفـلات ديـاثة سوالــب🥵🌶️\n\n"
        "🌟 مرحباً بك في بوت الشير المتطور! 🌟\n"
        "هنا يمكنك التحكم في نشر رسائلك بسهولة.\n"
        "عند تفعيل وضع الشير، سيتم إرسال محتواك لجميع المجموعات والقنوات التي **أنت** قمت بإعدادها.\n\n"
        "✨ Developer: @Mo_sc_ow\n\n"
        "📢 Channel: @Vib_one"
    )

    bot.send_message(
        user_chat_id,
        welcome_text,
        reply_markup=get_main_keyboard(user_id)
    )

# --- Callback Query Handler (Button Presses) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """Handles inline keyboard button presses."""
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    bot.answer_callback_query(call.id)  # Dismisses the loading icon on the button

    if not is_authorized(user_id):
        bot.send_message(chat_id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك. MOSCO")
        return

    if data == "start_share_mode":
        user_share_mode[user_id] = True
        bot.send_message(chat_id, "🚀 **تم تفعيل وضع الشير.** الآن، أرسل لي أي شيء لعمل شير له في جميع المجموعات والقنوات الخاصة بك.")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass  # Do nothing if the keyboard hasn't changed
            else:
                print(f"خطأ في تعديل لوحة المفاتيح: {e}")  # Log other errors
    
    elif data == "stop_share_mode":
        user_share_mode[user_id] = False
        bot.send_message(chat_id, "🛑 **تم إيقاف وضع الشير.** لن أقوم بشير الرسائل بعد الآن.")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass
            else:
                print(f"خطأ في تعديل لوحة المفاتيح: {e}")

    elif data == "show_share_status":
        if user_id in last_shared_message:
            bot.send_message(chat_id, f"آخر رسالة قمت بشيرها كانت:\n\n`{last_shared_message[user_id]}`", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "لم تقم بشير أي رسالة بعد.")
    
    elif data == "list_my_target_chats":
        my_target_chats = get_user_target_chats(user_id)

        if not my_target_chats:
            bot.send_message(chat_id, "لا توجد مجموعات أو قنوات مسجلة لك حاليًا للشير فيها. يمكنك إضافتي إلى مجموعة أو قناة لتسجيلها.")
            return
        
        message_text = "**المجموعات والقنوات التي تشارك فيها:**\n"
        for target_id in my_target_chats:
            try:
                chat_info = bot.get_chat(target_id)
                if chat_info.type == 'group' or chat_info.type == 'supergroup':
                    message_text += f"- مجموعة: `{chat_info.title}` (ID: `{target_id}`)\n"
                elif chat_info.type == 'channel':
                    message_text += f"- قناة: `{chat_info.title}` (ID: `{target_id}`)\n"
                elif chat_info.type == 'private':
                    message_text += f"- خاص مع: `{chat_info.first_name}` (ID: `{target_id}`)\n"
                else:
                    message_text += f"- نوع غير معروف (ID: `{target_id}`)\n"
            except telebot.apihelper.ApiTelegramException as e:
                # More detailed error messages to aid debugging
                if e.error_code == 400 and "chat not found" in e.description.lower():
                    message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (معرف غير صالح أو البوت غير موجود به)\n"
                elif e.error_code == 403:  # Bot was blocked or removed from chat/channel
                    message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (البوت محظور أو تم إزالته)\n"
                else:
                    message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (خطأ غير معروف: {e.description})\n"
                print(f"خطأ في جلب معلومات الشات {target_id}: {e}")  # Log the full error
            except Exception as e:
                message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (خطأ عام: {e})\n"
                print(f"خطأ عام في جلب معلومات الشات {target_id}: {e}")
        
        bot.send_message(chat_id, message_text, parse_mode="Markdown")

    elif data == "list_authorized_users": 
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
            return
        
        global AUTHORIZED_USER_IDS
        AUTHORIZED_USER_IDS = get_authorized_users()  # Reload to ensure latest list

        if not AUTHORIZED_USER_IDS:
            bot.send_message(chat_id, "لا يوجد مستخدمون مصرح لهم حاليًا.")
            return
        
        users_list = "\n".join([str(uid) for uid in AUTHORIZED_USER_IDS])
        bot.send_message(chat_id, f"**المستخدمون المصرح لهم:**\n{users_list}", parse_mode="Markdown")

    elif data == "admin_add_user_prompt": 
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
            return
        msg = bot.send_message(chat_id, "الرجاء إدخال ID المستخدم الذي تريد إضافته:")
        bot.register_next_step_handler(msg, add_user_by_admin)

    elif data == "admin_remove_user_prompt": 
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
            return
        msg = bot.send_message(chat_id, "الرجاء إدخال ID المستخدم الذي تريد إزالته:")
        bot.register_next_step_handler(msg, remove_user_by_admin)
    
    elif data == "admin_remove_chat_prompt":
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
            return
        msg = bot.send_message(chat_id, "الرجاء إدخال ID الشات الذي تريد إزالته من قائمة الشير (سواء كان شات خاص بك أو بأي مستخدم آخر):")
        bot.register_next_step_handler(msg, remove_chat_by_admin)

# --- Admin Functions for User Management ---
def add_user_by_admin(message):
    """Handler for adding an authorized user by the admin."""
    global AUTHORIZED_USER_IDS
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك.")
        return
    try:
        user_id_to_add = int(message.text.strip())
        if add_authorized_user_to_db(user_id_to_add):
            AUTHORIZED_USER_IDS.append(user_id_to_add)  # Temporarily add to in-memory list
            bot.send_message(message.chat.id, f"تمت إضافة المستخدم {user_id_to_add} بنجاح.")
            try:
                bot.send_message(user_id_to_add, "تهانينا! لقد تم التصريح لك الآن باستخدام بوت الشير. أرسل لي /start.")
            except Exception as e:
                print(f"فشل إرسال رسالة للمستخدم {user_id_to_add}: {e}")
                bot.send_message(message.chat.id, f"ملاحظة: لم أستطع إرسال رسالة للمستخدم {user_id_to_add}. ربما لم يبدأ البوت من قبل.")
        else:
            bot.send_message(message.chat.id, f"المستخدم {user_id_to_add} موجود بالفعل في قائمة المصرح لهم.")

    except ValueError:
        bot.send_message(message.chat.id, "الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(message.chat.id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(message.from_user.id))

def remove_user_by_admin(message):
    """Handler for removing an authorized user by the admin."""
    global AUTHORIZED_USER_IDS
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك.")
        return
    try:
        user_id_to_remove = int(message.text.strip())
        if user_id_to_remove == ADMIN_USER_ID:
            bot.send_message(message.chat.id, "لا يمكنك إزالة نفسك من قائمة المشرفين.")
        elif remove_authorized_user_from_db(user_id_to_remove):
            if user_id_to_remove in AUTHORIZED_USER_IDS:
                AUTHORIZED_USER_IDS.remove(user_id_to_remove)  # Temporarily remove from in-memory list
            bot.send_message(message.chat.id, f"تمت إزالة المستخدم {user_id_to_remove} بنجاح.")
        else:
            bot.send_message(message.chat.id, f"المستخدم {user_id_to_remove} ليس في قائمة المصرح لهم أصلاً.")

    except ValueError:
        bot.send_message(message.chat.id, "الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(message.chat.id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(message.from_user.id))

def remove_chat_by_admin(message):
    """Handler for removing a target chat by the admin."""
    if not is_admin
