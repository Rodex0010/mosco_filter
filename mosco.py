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
    # In a production environment, you might want to log this and exit gracefully.
    # For now, we'll exit to prevent the bot from crashing later.
    exit()

bot = telebot.TeleBot(MOSCO_TOKEN)

# Owner's User ID (Replace with your actual Telegram User ID)
ADMIN_USER_ID = 7602163093  # You should replace this with your actual Telegram User ID
DATABASE_NAME = 'bot_data.db'

# In-memory dictionaries to track user states
user_share_mode = {}  # Stores True/False if a user's sharing mode is active
last_shared_message = {}  # Stores a snippet of the last message shared by a user

# --- SQLite Database Functions ---
def init_db():
    """Initializes the SQLite database and creates necessary tables."""
    conn = None
    try:
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
        print("Database initialized successfully.")
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
    finally:
        if conn:
            conn.close()

def get_authorized_users():
    """Fetches all authorized user IDs from the database."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM authorized_users')
        users = [row[0] for row in cursor.fetchall()]
        return users
    except sqlite3.Error as e:
        print(f"Error fetching authorized users: {e}")
        return []
    finally:
        if conn:
            conn.close()

def add_authorized_user_to_db(user_id):
    """Adds a user ID to the authorized users table."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO authorized_users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:  # User already exists
        return False
    except sqlite3.Error as e:
        print(f"Error adding authorized user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def remove_authorized_user_from_db(user_id):
    """Removes a user ID from the authorized users table and their target chats."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM authorized_users WHERE user_id = ?', (user_id,))
        # Also remove target chats associated with this user
        cursor.execute('DELETE FROM user_target_chats WHERE user_id = ?', (user_id,))
        rows_affected = cursor.rowcount
        conn.commit()
        return rows_affected > 0
    except sqlite3.Error as e:
        print(f"Error removing authorized user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_target_chats(user_id):
    """Fetches target chat IDs for a specific user. Admin gets all distinct chats."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        if is_admin(user_id):
            # Admin can share to all distinct registered chats from any user
            cursor.execute('SELECT DISTINCT chat_id FROM user_target_chats')
        else:
            # Regular user only shares to their own registered chats
            cursor.execute('SELECT chat_id FROM user_target_chats WHERE user_id = ?', (user_id,))

        chats = [row[0] for row in cursor.fetchall()]
        return chats
    except sqlite3.Error as e:
        print(f"Error fetching target chats for user {user_id}: {e}")
        return []
    finally:
        if conn:
            conn.close()

def add_user_target_chat_to_db(user_id, chat_id):
    """Adds a target chat ID for a specific user to the database."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # INSERT OR IGNORE prevents adding duplicates and raises no error if exists
        cursor.execute('INSERT OR IGNORE INTO user_target_chats (user_id, chat_id) VALUES (?, ?)', (user_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0  # Returns True if a new row was inserted
    except sqlite3.Error as e:
        print(f"Error adding target chat {chat_id} for user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

def remove_user_target_chat_from_db(user_id, chat_id):
    """Removes a target chat ID. Admin can remove it for all users."""
    conn = None
    try:
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
        return rows_affected > 0
    except sqlite3.Error as e:
        print(f"Error removing target chat {chat_id} for user {user_id}: {e}")
        return False
    finally:
        if conn:
            conn.close()

# Initialize the database and load authorized users on startup
init_db()
# Load initial list of authorized users. This list will be updated in-memory after admin actions.
AUTHORIZED_USER_IDS = set(get_authorized_users()) # Use a set for faster lookups

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
    # Define user_first_name at the beginning to always be available.
    user_first_name = message.from_user.first_name if message.from_user.first_name else "صديقي"

    # Add the user's private chat with the bot to their target chats.
    # This ensures the bot can send messages back to the user's private chat.
    if add_user_target_chat_to_db(user_id, user_chat_id):
        print(f"User {user_id}'s private chat (ID: {user_chat_id}) added to their target chats.")
    else:
        print(f"User {user_id}'s private chat (ID: {user_chat_id}) already in their target chats.")

    if not is_authorized(user_id):
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow"))
        bot.send_message(user_chat_id, text=(
                "🔥 *مرحباً بك* 🔥\n\n"
                f"👋 مرحباً يا [{user_first_name}](tg://user?id={user_id})\n\n"
                "🚫 *هذا البوت خاص وغير مصرح لك باستخدامه.*\n"
                "إذا كنت ترغب في الوصول، يرجى التواصل مع المالك.\n\n"
                "🕵️‍♂️ *محتوى البوت:*\n"
                "1️⃣ دياثة وتجسس على المحارم - عربي وبدويات 🔥🥵\n"
                "2️⃣ تحرش وجيران واغتصاب حقيقي 🥴🥵\n\n"
                "🎉 بوت حفلات دياثة سوالب 🌶️\n\n"
                "👨‍💻 *المطور:* @Mo_sc_ow\n"
                "📢 *القناة:* @Vib_one"
            ), parse_mode="Markdown", reply_markup=markup)
        return

    # Authorized user welcome message
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
        "📢 Channal : @Vib_one"
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
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow"))
        bot.send_message(chat_id,
                         "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في الوصول، يرجى التواصل مع المالك.",
                         reply_markup=markup)
        return

    if data == "start_share_mode":
        user_share_mode[user_id] = True
        bot.send_message(chat_id, "🚀 **تم تفعيل وضع الشير.** الآن، أرسل لي أي شيء لعمل شير له في جميع المجموعات والقنوات الخاصة بك.", parse_mode="Markdown")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e): # Only log if it's a real error
                print(f"Error editing keyboard markup for user {user_id}: {e}")

    elif data == "stop_share_mode":
        user_share_mode[user_id] = False
        bot.send_message(chat_id, "🛑 **تم إيقاف وضع الشير.** لن أقوم بشير الرسائل بعد الآن.", parse_mode="Markdown")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e):
                print(f"Error editing keyboard markup for user {user_id}: {e}")

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
                if chat_info.type in ['group', 'supergroup']:
                    message_text += f"- مجموعة: `{chat_info.title}` (ID: `{target_id}`)\n"
                elif chat_info.type == 'channel':
                    message_text += f"- قناة: `{chat_info.title}` (ID: `{target_id}`)\n"
                elif chat_info.type == 'private':
                    message_text += f"- خاص مع: `{chat_info.first_name}` (ID: `{target_id}`)\n"
                else:
                    message_text += f"- نوع غير معروف (ID: `{target_id}`)\n"
            except telebot.apihelper.ApiTelegramException as e:
                if e.error_code == 400 and "chat not found" in e.description.lower():
                    message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (معرف غير صالح أو تم حذف الشات).\n"
                elif e.error_code == 403:  # Bot was blocked or removed from chat/channel
                    message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (البوت محظور أو تم إزالته).\n"
                else:
                    message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (خطأ غير معروف: {e.description}).\n"
                print(f"Error fetching chat info for {target_id}: {e}") # Log the full error
            except Exception as e:
                message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (خطأ عام: {e}).\n"
                print(f"General error fetching chat info for {target_id}: {e}")

        bot.send_message(chat_id, message_text, parse_mode="Markdown")

    elif data == "list_authorized_users":
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
            return

        # Always reload from DB to get the most current list
        global AUTHORIZED_USER_IDS
        AUTHORIZED_USER_IDS = set(get_authorized_users())

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
    global AUTHORIZED_USER_IDS # Declare global to modify the set in memory
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(user_id, "عذرًا، أنت غير مصرح لك بإجراء هذا الإجراء.")
        return

    try:
        user_id_to_add = int(message.text.strip())
        if add_authorized_user_to_db(user_id_to_add):
            AUTHORIZED_USER_IDS.add(user_id_to_add) # Add to the in-memory set
            bot.send_message(user_id, f"✅ تمت إضافة المستخدم `{user_id_to_add}` بنجاح.", parse_mode="Markdown")
            try:
                bot.send_message(user_id_to_add, "تهانينا! لقد تم التصريح لك الآن باستخدام بوت الشير. أرسل لي /start.")
            except telebot.apihelper.ApiTelegramException as e:
                print(f"Failed to send welcome message to new authorized user {user_id_to_add}: {e}")
                bot.send_message(user_id, f"⚠️ ملاحظة: لم أستطع إرسال رسالة ترحيب للمستخدم `{user_id_to_add}`. ربما لم يبدأ البوت من قبل.", parse_mode="Markdown")
        else:
            bot.send_message(user_id, f"المستخدم `{user_id_to_add}` موجود بالفعل في قائمة المصرح لهم.", parse_mode="Markdown")

    except ValueError:
        bot.send_message(user_id, "❌ الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(user_id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(user_id))

def remove_user_by_admin(message):
    """Handler for removing an authorized user by the admin."""
    global AUTHORIZED_USER_IDS # Declare global to modify the set in memory
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(user_id, "عذرًا، أنت غير مصرح لك بإجراء هذا الإجراء.")
        return

    try:
        user_id_to_remove = int(message.text.strip())
        if user_id_to_remove == ADMIN_USER_ID:
            bot.send_message(user_id, "❌ لا يمكنك إزالة نفسك من قائمة المشرفين.")
        elif remove_authorized_user_from_db(user_id_to_remove):
            AUTHORIZED_USER_IDS.discard(user_id_to_remove) # Remove from the in-memory set
            bot.send_message(user_id, f"✅ تمت إزالة المستخدم `{user_id_to_remove}` بنجاح.", parse_mode="Markdown")
            try:
                # Optionally inform the removed user
                bot.send_message(user_id_to_remove, "للأسف، تم إلغاء تصريحك باستخدام بوت الشير. لم يعد بإمكانك استخدامه.", parse_mode="Markdown")
            except telebot.apihelper.ApiTelegramException as e:
                print(f"Failed to send message to removed user {user_id_to_remove}: {e}")
                bot.send_message(user_id, f"⚠️ ملاحظة: لم أستطع إرسال رسالة للمستخدم `{user_id_to_remove}` بعد إزالته.", parse_mode="Markdown")
        else:
            bot.send_message(user_id, f"المستخدم `{user_id_to_remove}` ليس في قائمة المصرح لهم أصلاً.", parse_mode="Markdown")

    except ValueError:
        bot.send_message(user_id, "❌ الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(user_id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(user_id))

def remove_chat_by_admin(message):
    """Handler for removing a target chat by the admin."""
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(user_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
        return
    try:
        chat_id_to_remove = int(message.text.strip())
        # Admin's user ID is used here because they can remove the chat from all users' lists
        if remove_user_target_chat_from_db(user_id, chat_id_to_remove):
            bot.send_message(user_id, f"✅ تمت إزالة الشات `{chat_id_to_remove}` بنجاح من جميع قوائم الشير.", parse_mode="Markdown")
        else:
            bot.send_message(user_id, f"الشات `{chat_id_to_remove}` غير موجود في أي قائمة شير مسجلة.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(user_id, "❌ الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(user_id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(user_id))

# --- Main Message Handler (Performs Sharing) ---
# This handler receives all types of messages when sharing mode is active
@bot.message_handler(func=lambda message: user_share_mode.get(message.from_user.id, False),
                     content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def forward_all_messages_to_user_chats(message):
    """Forwards received messages to all target chats if sharing mode is active."""
    user_id = message.from_user.id
    if not is_authorized(user_id):
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow"))
        bot.send_message(message.chat.id,
                         "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في الوصول، يرجى التواصل مع المالك.",
                         reply_markup=markup)
        return

    user_target_chats = get_user_target_chats(user_id)

    successful_shares = 0
    failed_shares = 0

    bot.send_message(message.chat.id, "جاري معالجة الشير... قد يستغرق الأمر بعض الوقت.")

    if not user_target_chats:
        bot.send_message(message.chat.id, "لا توجد مجموعات أو قنوات مسجلة لك حاليًا للشير فيها. الرجاء إضافة البوت إلى مجموعات أو قنوات جديدة، أو أضف الـ IDs يدويًا.")
        return

    for target_chat_id in user_target_chats:
        try:
            bot.copy_message(target_chat_id, message.chat.id, message.message_id)
            successful_shares += 1
            time.sleep(2) # Delay to reduce the chance of hitting Telegram API limits
        except telebot.apihelper.ApiTelegramException as e:
            failed_shares += 1
            error_message_for_user = f"❌ فشل الشير إلى `{target_chat_id}`: "

            # Detailed error handling based on Telegram API error codes
            if e.error_code == 400: # Bad Request
                if "CHANNEL_FORWARDS_FORBIDDEN" in e.description:
                    error_message_for_user += "هذه القناة لا تسمح بإعادة توجيه الرسائل. (تحقق من إعدادات القناة)."
                elif "CHAT_SEND_WEBPAGE_FORBIDDEN" in e.description:
                    error_message_for_user += "هذه القناة/المجموعة لا تسمح بمعاينات صفحات الويب. (تحقق من إعدادات الشات، أو تأكد أن رسالتك لا تحتوي على روابط أو لا تحاول معاينتها)."
                elif "CHAT_WRITE_FORBIDDEN" in e.description or "not enough rights to send messages" in e.description:
                    error_message_for_user += "البوت ليس لديه صلاحية النشر في هذه القناة/المجموعة. (اجعله مشرفًا)."
                elif "chat not found" in e.description.lower():
                    error_message_for_user += "لم يتم العثور على الشات. (ID خاطئ أو تم حذف الشات)."
                else:
                    error_message_for_user += f"خطأ في الطلب (Bad Request): {e.description}"
            elif e.error_code == 403: # Forbidden
                error_message_for_user += "البوت محظور أو تم إزالته من هذه القناة/المجموعة. يرجى إعادة إضافته أو إلغاء حظره."
            elif e.error_code == 429: # Too Many Requests
                retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                print(f"⚠️ Rate limit hit for {target_chat_id} by user {user_id}. Waiting {retry_after} seconds.")
                error_message_for_user += f"تم تجاوز حد الطلبات في Telegram. سأستأنف الشير بعد {retry_after} ثوانٍ."
                time.sleep(retry_after + 1) # Add an extra second for safety
                try: # Attempt to resend after waiting
                    bot.copy_message(target_chat_id, message.chat.id, message.message_id)
                    successful_shares += 1
                    failed_shares -= 1 # If successful on retry, don't count as failed
                    time.sleep(2)
                    continue # Skip the rest of this iteration for the current chat
                except Exception as retry_e: # If retry also fails
                    error_message_for_user += f" فشل مرة أخرى بعد الانتظار: {retry_e}"
            else: # Any other unexpected Telegram API errors
                error_message_for_user += f"خطأ غير متوقع من Telegram API: {e.description}"

            print(f"{error_message_for_user} (Error Code: {e.error_code})")
            # Only send error message to user if the target chat is not the same as the source chat
            if target_chat_id != message.chat.id:
                 bot.send_message(message.chat.id, error_message_for_user, parse_mode="Markdown")
        except Exception as e: # Catch any other unexpected general errors
            failed_shares += 1
            print(f"❌ Failed to share to {target_chat_id} for user {user_id} due to general error: {e}")
            if target_chat_id != message.chat.id:
                bot.send_message(message.chat.id, f"❌ فشل الشير إلى `{target_chat_id}` بسبب خطأ عام: {e}", parse_mode="Markdown")

    bot.send_message(message.chat.id, f"✅ تم الشير بنجاح! ({successful_shares} شير ناجح، {failed_shares} شير فاشل).")

    # Save information about the last shared message
    if message.text:
        last_shared_message[user_id] = f"رسالة نصية: {message.text[:50]}{'...' if len(message.text) > 50 else ''}"
    elif message.photo:
        last_shared_message[user_id] = f"صورة (ID: {message.photo[-1].file_id})"
    elif message.video:
        last_shared_message[user_id] = f"فيديو (ID: {message.video.file_id})"
    elif message.document:
        last_shared_message[user_id] = f"ملف (الاسم: {message.document.file_name})"
    else: # For other content types
        last_shared_message[user_id] = f"نوع آخر من المحتوى (ID: {message.message_id})"

# --- Message Handler for Authorized Users (when sharing mode is OFF) ---
@bot.message_handler(func=lambda message: not user_share_mode.get(message.from_user.id, False) and is_authorized(message.from_user.id),
                     content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def handle_other_authorized_messages(message):
    """Informs authorized users that sharing mode is off if they send a message."""
    bot.send_message(
        message.chat.id,
        "لم أقم بشير رسالتك لأن وضع الشير غير مفعل. استخدم الأزرار للتحكم.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# --- Message Handler for Any Unauthorized User ---
@bot.message_handler(func=lambda message: not is_authorized(message.from_user.id),
                     content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def handle_unauthorized_messages(message):
    """Informs unauthorized users that they cannot use the bot and provides contact info."""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow"))
    bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك. MOSCO", reply_markup=markup)

# --- Handler when the Bot is Added to a New Group/Channel ---
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_members(message):
    """Handles the event when the bot is added to a new chat (group or channel)."""
    for member in message.new_chat_members:
        if member.id == bot.get_me().id: # Check if the new member is the bot itself
            chat_id = message.chat.id
            user_id = message.from_user.id # The user who added the bot
            chat_title = message.chat.title or message.chat.first_name

            # Check if the user who added the bot is authorized
            if not is_authorized(user_id):
                try:
                    bot.send_message(chat_id,
                                     "عذرًا، لا يمكنني العمل في هذا الشات لأن المستخدم الذي أضافني غير مصرح له. يرجى التواصل مع المالك.",
                                     reply_markup=telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow")))
                    bot.leave_chat(chat_id) # Have the bot leave if the adder is unauthorized
                    print(f"Bot left unauthorized chat {chat_id} added by user {user_id}.")
                except Exception as e:
                    print(f"Failed to send leave message or leave chat {chat_id}: {e}")
                return # Stop processing if unauthorized

            # Add the chat to the user's target chats
            if add_user_target_chat_to_db(user_id, chat_id):
                print(f"✅ New chat (ID: {chat_id}, Type: {message.chat.type}, Name: {chat_title}) added to user {user_id}'s target chats.")

                welcome_message_to_chat = f"شكرًا لإضافتي إلى *{chat_title}*! أنا هنا لمساعدتك في نشر الرسائل.\n"
                if message.chat.type == 'channel':
                    welcome_message_to_chat += "⚠️ **ملاحظة هامة للقنوات:** لكي أتمكن من النشر هنا، يرجى التأكد من أنني مشرف في هذه القناة ولدي صلاحية 'نشر الرسائل'."
                welcome_message_to_chat += "\nيمكنك العودة إلى رسائلك الخاصة معي للتحكم في البوت."

                try:
                    # Send message to the user who added the bot (private chat)
                    bot.send_message(user_id, f"✅ تم تسجيل هذه المجموعة/القناة (الاسم: `{chat_title}`, ID: `{chat_id}`) لقائمة الشير الخاصة بك.", parse_mode="Markdown")
                    time.sleep(1) # Small delay
                    # Send a welcome message in the new group/channel itself
                    bot.send_message(chat_id, welcome_message_to_chat, parse_mode="Markdown")
                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429: # Rate limit
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                        print(f"⚠️ Rate limit hit when bot added to new chat. Waiting {retry_after} seconds.")
                        time.sleep(retry_after + 1)
                        try: # Retry sending messages after delay
                            bot.send_message(user_id, f"✅ تم تسجيل هذه المجموعة/القناة (الاسم: `{chat_title}`, ID: `{chat_id}`) لقائمة الشير الخاصة بك.", parse_mode="Markdown")
                            time.sleep(1)
                            bot.send_message(chat_id, welcome_message_to_chat, parse_mode="Markdown")
                        except Exception as retry_e:
                            print(f"❌ Failed to send welcome messages after retry: {retry_e}")
                            bot.send_message(user_id, f"❌ حدث خطأ عند محاولة الترحيب بك في `{chat_title}` بعد إضافة البوت.")
                    else:
                        print(f"❌ Failed to send welcome messages when bot added to new chat: {e}")
                        bot.send_message(user_id, f"❌ حدث خطأ عند محاولة الترحيب بك في `{chat_title}` بعد إضافة البوت: {e.description}")
                except Exception as e:
                    print(f"❌ General error processing bot added to new chat: {e}")
                    bot.send_message(user_id, f"❌ حدث خطأ عام عند إضافة البوت إلى `{chat_title}`.")
            else:
                print(f"Chat (ID: {chat_id}) already exists in user {user_id}'s target chats.")
                try:
                    bot.send_message(user_id, f"هذه المجموعة/القناة (الاسم: `{chat_title}`, ID: `{chat_id}`) موجودة بالفعل في قائمة الشير الخاصة بك.", parse_mode="Markdown")
                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429:
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                        print(f"⚠️ Rate limit hit when informing user about existing chat. Waiting {retry_after} seconds.")
                        time.sleep(retry_after + 1)
                        try:
                            bot.send_message(user_id, f"هذه المجموعة/القناة (الاسم: `{chat_title}`, ID: `{chat_id}`) موجودة بالفعل في قائمة الشير الخاصة بك.", parse_mode="Markdown")
                        except Exception as retry_e:
                            print(f"❌ Failed to send existing chat notification after retry: {retry_e}")
                    else:
                        print(f"❌ Failed to send existing chat notification: {e}")
                except Exception as e:
                    print(f"❌ General error informing user about existing chat: {e}")
            break # Exit loop after handling the bot's addition

# --- Start the Bot ---
print("Bot is now running...")
# This function keeps the bot running and receives updates from the Telegram API
bot.polling(non_stop=True, interval=3) # Reduced interval slightly, can be adjusted
