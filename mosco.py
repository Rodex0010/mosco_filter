import telebot
import time
import json
import os # تم إضافة هذه المكتبة لتحميل متغيرات البيئة
import sqlite3

# --- إعدادات البوت الأساسية (يجب تعديلها) ---
# تم تغيير اسم متغير البيئة هنا إلى MOSCO_TOKEN
MOSCO_TOKEN = os.getenv('MOSCO_TOKEN')
if not MOSCO_TOKEN:
    print("خطأ: متغير البيئة 'MOSCO_TOKEN' غير موجود. يرجى تعيينه في Railway.")
    exit() # إيقاف التشغيل إذا لم يكن التوكن موجودًا

# استخدام MOSCO_TOKEN عند إنشاء كائن البوت
bot = telebot.TeleBot(MOSCO_TOKEN)

ADMIN_USER_ID = 7602163093  # هذا هو معرّف المالك
DATABASE_NAME = 'bot_data.db'


user_share_mode = {}
last_shared_message = {}

# --- دوال التعامل مع قاعدة البيانات SQLite ---
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_target_chats (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')
    
    cursor.execute('INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)', (ADMIN_USER_ID,))
    
    conn.commit()
    conn.close()
    print("تم تهيئة قاعدة البيانات بنجاح.")

def get_authorized_users():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM authorized_users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def add_authorized_user_to_db(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO authorized_users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_authorized_user_from_db(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM authorized_users WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM user_target_chats WHERE user_id = ?', (user_id,))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

def get_user_target_chats(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    if is_admin(user_id):
        # المسؤول يمكنه الشير في جميع الشاتات المسجلة من قبل أي مستخدم
        cursor.execute('SELECT DISTINCT chat_id FROM user_target_chats')
    else:
        # المستخدم العادي يشير فقط في الشاتات الخاصة به
        cursor.execute('SELECT chat_id FROM user_target_chats WHERE user_id = ?', (user_id,))
    
    chats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return chats

def add_user_target_chat_to_db(user_id, chat_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO user_target_chats (user_id, chat_id) VALUES (?, ?)', (user_id, chat_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def remove_user_target_chat_from_db(user_id, chat_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    if is_admin(user_id):
        # المسؤول يمكنه حذف الشات من قوائم جميع المستخدمين
        cursor.execute('DELETE FROM user_target_chats WHERE chat_id = ?', (chat_id,))
    else:
        # المستخدم العادي يمكنه حذف الشات من قائمته فقط
        cursor.execute('DELETE FROM user_target_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

init_db()

AUTHORIZED_USER_IDS = get_authorized_users()

print(f"تم تحميل {len(AUTHORIZED_USER_IDS)} مستخدم مصرح له من قاعدة البيانات.")
print("تم تغيير طريقة التعامل مع الشاتات المستهدفة لتكون خاصة بكل مستخدم.")
print("تأكد أن المالك (Admin) فقط هو من يمكنه الشير في جميع الجروبات المسجلة.")

# --- وظائف مساعدة ---
def is_authorized(user_id):
    return user_id in AUTHORIZED_USER_IDS

def is_admin(user_id):
    return user_id == ADMIN_USER_ID

def get_main_keyboard(user_id):
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

# --- معالجات الأوامر (/start و /help) ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message.from_user.id):
        # هذا هو الجزء الذي يضيف زر التواصل مع المالك
        markup = telebot.types.InlineKeyboardMarkup()
        # تأكد من أن 'Mo_sc_ow' هو اسم المستخدم (اليوزرنيم) الخاص بك بالضبط في تيليجرام (بدون علامة @)
        markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow")) 
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك.", reply_markup=markup)
        return

    user_first_name = message.from_user.first_name if message.from_user.first_name else "صديقي"
    
    welcome_text = (
        f"أهلاً بك يا {user_first_name} 👋\n\n"
        "🌟 مرحباً بك في بوت الشير المتطور! 🌟\n"
        "هنا يمكنك التحكم في نشر رسائلك بسهولة.\n"
        "عند تفعيل وضع الشير، سيتم إرسال محتواك لجميع المجموعات والقنوات التي **أنت** قمت بإعدادها.\n\n"
        "✨ Developer: @Mo_sc_ow\n\n"
        "📢 Channal : @Vib_one"
    )

    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# --- معالجات الأزرار (Callback Queries) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    bot.answer_callback_query(call.id)

    if not is_authorized(user_id):
        bot.send_message(chat_id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت.")
        return

    if data == "start_share_mode":
        user_share_mode[user_id] = True
        bot.send_message(chat_id, "🚀 **تم تفعيل وضع الشير.** الآن، أرسل لي أي شيء لعمل شير له في جميع المجموعات والقنوات الخاصة بك.")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise e
    
    elif data == "stop_share_mode":
        user_share_mode[user_id] = False
        bot.send_message(chat_id, "🛑 **تم إيقاف وضع الشير.** لن أقوم بشير الرسائل بعد الآن.")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_main_keyboard(user_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise e

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
            except Exception as e:
                message_text += f"- لا يمكن الوصول لـ ID: `{target_id}` (ربما تم إزالة البوت أو ليس مشرفًا)\n"
        
        bot.send_message(chat_id, message_text, parse_mode="Markdown")

    elif data == "list_authorized_users": 
        if not is_admin(user_id):
            bot.send_message(chat_id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
            return
        
        global AUTHORIZED_USER_IDS
        AUTHORIZED_USER_IDS = get_authorized_users()

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

# --- وظائف المشرف لإدارة المستخدمين المصرح لهم ---
def add_user_by_admin(message):
    global AUTHORIZED_USER_IDS
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك.")
        return
    try:
        user_id_to_add = int(message.text.strip())
        if add_authorized_user_to_db(user_id_to_add):
            AUTHORIZED_USER_IDS.append(user_id_to_add)
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
                AUTHORIZED_USER_IDS.remove(user_id_to_remove)
            bot.send_message(message.chat.id, f"تمت إزالة المستخدم {user_id_to_remove} بنجاح.")
        else:
            bot.send_message(message.chat.id, f"المستخدم {user_id_to_remove} ليس في قائمة المصرح لهم أصلاً.")

    except ValueError:
        bot.send_message(message.chat.id, "الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(message.chat.id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(message.from_user.id))

def remove_chat_by_admin(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "عذرًا، هذا الأمر متاح للمشرف الرئيسي فقط.")
        return
    try:
        chat_id_to_remove = int(message.text.strip())
        if remove_user_target_chat_from_db(message.from_user.id, chat_id_to_remove):
            bot.send_message(message.chat.id, f"تمت إزالة الشات {chat_id_to_remove} بنجاح من جميع قوائم الشير.")
        else:
            bot.send_message(message.chat.id, f"الشات {chat_id_to_remove} غير موجود في أي قائمة شير مسجلة.")
    except ValueError:
        bot.send_message(message.chat.id, "الرجاء إدخال ID صحيح (رقم).")
    finally:
        bot.send_message(message.chat.id, "اختر من القائمة الرئيسية:", reply_markup=get_main_keyboard(message.from_user.id))

# --- معالج الرسائل الأساسي (يقوم بالشير) ---
@bot.message_handler(func=lambda message: user_share_mode.get(message.from_user.id, False), 
                     content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def forward_all_messages_to_user_chats(message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت.")
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
            time.sleep(2)
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 403:
                print(f"❌ خطأ 403: البوت محظور أو تم إزالته من الشات ID: {target_chat_id} (المستخدم {user_id} حاول الشير).")
                bot.send_message(message.chat.id, f"❌ فشل الشير إلى {target_chat_id}: يبدو أن البوت محظور أو تم إزالته من هذه القناة/المجموعة. يرجى إعادة إضافته أو إلغاء حظره.")
                failed_shares += 1
                continue

            if e.error_code == 429:
                retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                print(f"⚠️ تجاوز حد الطلبات إلى {target_chat_id} للمستخدم {user_id}. سأنتظر {retry_after} ثوانٍ.")
                bot.send_message(message.chat.id, f"⚠️ تم تجاوز حد الطلبات في Telegram. سأستأنف الشير بعد {retry_after} ثوانٍ.")
                time.sleep(retry_after)
                try:
                    bot.copy_message(target_chat_id, message.chat.id, message.message_id)
                    successful_shares += 1
                    time.sleep(2)
                except Exception as retry_e:
                    failed_shares += 1
                    print(f"❌ فشل الشير مرة أخرى إلى {target_chat_id} للمستخدم {user_id} بعد الانتظار: {retry_e}")
                    if target_chat_id != message.chat.id: 
                        bot.send_message(message.chat.id, f"❌ فشل الشير إلى {target_chat_id} بعد إعادة المحاولة: يرجى التأكد من أن البوت مشرف في هذه القناة/المجموعة ولديه صلاحية النشر.\nالخطأ: {retry_e}")
            else:
                failed_shares += 1
                print(f"❌ فشل الشير إلى {target_chat_id} للمستخدم {user_id}: {e}")
                if target_chat_id != message.chat.id: 
                    bot.send_message(message.chat.id, f"❌ فشل الشير إلى {target_chat_id}: يرجى التأكد من أن البوت مشرف في هذه القناة/المجموعة ولديه صلاحية النشر.\nالخطأ: {e}")
        except Exception as e:
            failed_shares += 1
            print(f"❌ فشل الشير إلى {target_chat_id} للمستخدم {user_id}: {e}")
            if target_chat_id != message.chat.id: 
                bot.send_message(message.chat.id, f"❌ فشل الشير إلى {target_chat_id}: يرجى التأكد من أن البوت مشرف في هذه القناة/المجموعة ولديه صلاحية النشر.\nالخطأ: {e}")

    bot.send_message(message.chat.id, f"✅ تم الشير بنجاح! ({successful_shares} شير ناجح، {failed_shares} شير فاشل).")
    
    if message.text:
        last_shared_message[user_id] = f"رسالة نصية: {message.text[:50]}..."
    elif message.photo:
        last_shared_message[user_id] = f"صورة (ID: {message.photo[-1].file_id})"
    elif message.video:
        last_shared_message[user_id] = f"فيديو (ID: {message.video.file_id})"
    elif message.document:
        last_shared_message[user_id] = f"ملف (الاسم: {message.document.file_name})"
    else:
        last_shared_message[user_id] = f"نوع آخر من المحتوى (ID: {message.message_id})"

# --- معالج الرسائل من المستخدمين المصرح لهم عندما لا يكون وضع الشير مفعلًا ---
@bot.message_handler(func=lambda message: not user_share_mode.get(message.from_user.id, False) and is_authorized(message.from_user.id), content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker', 'animation', 'contact', 'location', 'venue', 'game', 'video_note', 'poll', 'dice'])
def handle_other_authorized_messages(message):
    bot.send_message(
        message.chat.id,
        "لم أقم بشير رسالتك لأن وضع الشير غير مفعل. استخدم الأزرار للتحكم.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# --- معالج لأي رسالة من مستخدم غير مصرح به على الإطلاق ---
@bot.message_handler(func=lambda message: not is_authorized(message.from_user.id))
def handle_unauthorized_messages(message):
    markup = telebot.types.InlineKeyboardMarkup()
    # تأكد من أن 'Mo_sc_ow' هو اسم المستخدم (اليوزرنيم) الخاص بك بالضبط في تيليجرام (بدون علامة @)
    markup.add(telebot.types.InlineKeyboardButton("تواصل مع المالك", url="https://t.me/Mo_sc_ow")) 
    bot.send_message(message.chat.id, "عذرًا، أنت غير مصرح لك باستخدام هذا البوت. هذا البوت خاص. إذا كنت ترغب في استخدامه، يرجى التواصل مع المالك.", reply_markup=markup)

# --- معالج عند إضافة البوت لمجموعة/قناة جديدة ---
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_members(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            chat_id = message.chat.id
            user_id = message.from_user.id 

            if add_user_target_chat_to_db(user_id, chat_id):
                print(f"✅ تم إضافة الشات الجديد (ID: {chat_id}, النوع: {message.chat.type}, الاسم: {message.chat.title or message.chat.first_name}) إلى قائمة الشير للمستخدم {user_id}.")
                
                welcome_message = f"شكرًا لإضافتي! أنا هنا لمساعدتك في نشر الرسائل.\n"
                if message.chat.type == 'channel':
                    welcome_message += "⚠️ **ملاحظة هامة للقنوات:** لكي أتمكن من النشر هنا، يرجى التأكد من أنني مشرف في هذه القناة ولدي صلاحية 'نشر الرسائل'."
                
                try:
                    bot.send_message(user_id, f"تم تسجيل هذه المجموعة/القناة (ID: {chat_id}, الاسم: {message.chat.title or message.chat.first_name}) لقائمة الشير الخاصة بك.")
                    time.sleep(1)
                    bot.send_message(chat_id, welcome_message)
                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429:
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                        print(f"⚠️ تجاوز حد الطلبات عند إضافة بوت لشات جديد. سأنتظر {retry_after} ثوانٍ.")
                        time.sleep(retry_after)
                        try:
                            bot.send_message(user_id, f"تم تسجيل هذه المجموعة/القناة (ID: {chat_id}, الاسم: {message.chat.title or message.chat.first_name}) لقائمة الشير الخاصة بك.")
                            time.sleep(1)
                            bot.send_message(chat_id, welcome_message)
                        except Exception as retry_e:
                            print(f"❌ فشل إرسال رسالة الترحيب بعد الانتظار: {retry_e}")
                    else:
                        print(f"❌ فشل إرسال رسالة الترحيب عند إضافة البوت لشات جديد: {e}")
            else:
                print(f"الشات (ID: {chat_id}) موجود بالفعل في قائمة الشير للمستخدم {user_id}.")
                try:
                    bot.send_message(user_id, f"هذه المجموعة/القناة (ID: {chat_id}, الاسم: {message.chat.title or message.chat.first_name}) موجودة بالفعل في قائمة الشير الخاصة بك.")
                except telebot.apihelper.ApiTelegramException as e:
                    if e.error_code == 429:
                        retry_after = e.result_json.get('parameters', {}).get('retry_after', 5)
                        print(f"⚠️ تجاوز حد الطلبات عند إبلاغ مستخدم بشات موجود. سأنتظر {retry_after} ثوانٍ.")
                        time.sleep(retry_after)
                        try:
                            bot.send_message(user_id, f"هذه المجموعة/القناة (ID: {chat_id}, الاسم: {message.chat.title or message.chat.first_name}) موجودة بالفعل في قائمة الشير الخاصة بك.")
                        except Exception as retry_e:
                            print(f"❌ فشل إرسال رسالة التنبيه بعد الانتظار: {retry_e}")
                    else:
                        print(f"❌ فشل إرسال رسالة التنبيه عند إضافة البوت لشات جديد: {e}")
            break

# --- بدء تشغيل البوت ---
print("البوت يعمل الآن...")
# هذه الدالة تبقي البوت قيد التشغيل وتستقبل التحديثات
bot.polling(non_stop=True, interval=5)
