import os
import re
import time
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

print("🔥 PROFESSIONAL RENAME BOT RUNNING")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing")

if not API_ID:
    raise ValueError("API_ID missing")

if not API_HASH:
    raise ValueError("API_HASH missing")

if not MONGO_URI:
    raise ValueError("MONGO_URI missing")

API_ID = int(API_ID)

ADMIN_IDS = [
    int(x.strip())
    for x in ADMIN_IDS_RAW.split(",")
    if x.strip().isdigit()
]

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

mongo = MongoClient(MONGO_URI)
mongo.admin.command("ping")
print("✅ MongoDB connected")

db = mongo["rename_bot"]
users_col = db["users"]
files_col = db["files"]

bot = Client(
    "rename_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

waiting = {}
batch_files = {}
cooldown = {}

FREE_LIMIT = 500 * 1024 * 1024
PREMIUM_LIMIT = 2 * 1024 * 1024 * 1024


def get_user(user_id):
    user = users_col.find_one({"user_id": user_id})

    if not user:
        user = {
            "user_id": user_id,
            "premium": False,
            "caption": None,
            "prefix": "",
            "suffix": "",
            "auto_format": None,
            "thumbnail": None,
            "files_renamed": 0,
            "joined_at": datetime.utcnow()
        }
        users_col.insert_one(user)

    return user


def update_user(user_id, data):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": data},
        upsert=True
    )


def is_admin(user_id):
    return user_id in ADMIN_IDS


def clean_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()


def format_size(size):
    if not size:
        return "Unknown"

    size = float(size)

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size:.2f} PB"


def get_media(message):
    return message.document or message.video or message.audio


def get_media_info(message):
    media = get_media(message)

    file_name = getattr(media, "file_name", None) or "Unknown"
    file_size = getattr(media, "file_size", 0)
    mime_type = getattr(media, "mime_type", None) or "Unknown"
    dc_id = getattr(media, "dc_id", None) or "Unknown"

    ext = os.path.splitext(file_name)[1].replace(".", "")
    if not ext:
        ext = "Unknown"

    return file_name, file_size, ext, mime_type, dc_id


def extract_quality(filename):
    match = re.search(r"(480p|720p|1080p|2160p|4K)", filename, re.I)
    return match.group(1) if match else "HD"


def extract_title(filename):
    name = os.path.splitext(filename)[0]
    name = re.sub(r"(480p|720p|1080p|2160p|4K)", "", name, flags=re.I)
    name = name.replace(".", " ").replace("_", " ").replace("-", " ")
    return " ".join(name.split()).title()


def apply_auto_format(template, old_name):
    title = extract_title(old_name)
    quality = extract_quality(old_name)
    ext = os.path.splitext(old_name)[1]

    new_name = template.replace("{title}", title)
    new_name = new_name.replace("{quality}", quality)

    if ext and not new_name.endswith(ext):
        new_name += ext

    return clean_filename(new_name)


def main_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Rename File", callback_data="rename"),
            InlineKeyboardButton("📦 Batch Rename", callback_data="batch")
        ],
        [
            InlineKeyboardButton("🖼 Thumbnail", callback_data="thumbnail"),
            InlineKeyboardButton("⚙ Settings", callback_data="settings")
        ],
        [
            InlineKeyboardButton("📊 My Plan", callback_data="myplan"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ],
        [
            InlineKeyboardButton("💎 Premium", callback_data="premium"),
            InlineKeyboardButton("❤️ Donate", callback_data="donate")
        ]
    ])


def settings_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Set Caption", callback_data="set_caption"),
            InlineKeyboardButton("👀 See Caption", callback_data="see_caption")
        ],
        [
            InlineKeyboardButton("🗑 Delete Caption", callback_data="del_caption"),
            InlineKeyboardButton("➕ Prefix", callback_data="prefix")
        ],
        [
            InlineKeyboardButton("➖ Suffix", callback_data="suffix"),
            InlineKeyboardButton("🔁 Auto Rename", callback_data="auto")
        ],
        [
            InlineKeyboardButton("👀 View Thumb", callback_data="viewthumb"),
            InlineKeyboardButton("🗑 Delete Thumb", callback_data="delthumb")
        ],
        [
            InlineKeyboardButton("🗑 Reset All", callback_data="reset"),
            InlineKeyboardButton("⬅ Back", callback_data="back")
        ]
    ])


async def progress(current, total, message, start, text):
    now = time.time()

    if now - start < 3:
        return

    try:
        percentage = current * 100 / total
    except:
        percentage = 0

    speed = current / (now - start) if now - start else 0
    filled = min(10, int(percentage / 10))
    bar = "█" * filled + "░" * (10 - filled)

    try:
        await message.edit_text(
            f"{text}\n\n"
            f"[{bar}] {percentage:.1f}%\n"
            f"{format_size(current)} / {format_size(total)}\n"
            f"⚡ Speed: {format_size(speed)}/s"
        )
    except:
        pass


async def set_bot_commands():
    await bot.set_bot_commands([
        BotCommand("start", "✔️ Bot alive checking"),
        BotCommand("premium", "💎 To upgrade your plan"),
        BotCommand("myplan", "❄️ To check your current plan info"),
        BotCommand("metadata", "⚡ To Configure Your Metadata Tags"),
        BotCommand("settings", "⚙️ To Configure Your Settings"),
        BotCommand("viewthumb", "👀 View your thumbnail"),
        BotCommand("delthumb", "🗑 Delete your thumbnail"),
        BotCommand("set_caption", "✏️ Set a custom caption"),
        BotCommand("see_caption", "👀 See your custom caption"),
        BotCommand("del_caption", "🗑 Delete Custom Caption"),
        BotCommand("ping", "🔥 Check Bot Ping"),
        BotCommand("donate", "💗 To Support Developer"),
        BotCommand("task", "✨ Complete Simple Task & Use Me For Free"),
        BotCommand("add_premium", "🎉 Add user to Premium List Admin Only"),
        BotCommand("remove_premium", "🙊 Remove user from Premium List Admin Only"),
        BotCommand("premium_list", "🌸 See all Premium Users Admin Only"),
        BotCommand("admin", "👑 Admin Panel")
    ])


@bot.on_message(filters.command("ping"))
async def ping(_, message):
    start = time.time()
    msg = await message.reply_text("Checking ping...")
    end = time.time()
    ms = round((end - start) * 1000)
    await msg.edit_text(f"🔥 Bot Ping: `{ms} ms`")


@bot.on_message(filters.command("start"))
async def start(_, message):
    user = get_user(message.from_user.id)

    await message.reply_text(
        f"""
✔️ Bot alive checking.

Hello {message.from_user.first_name}

I can rename Telegram files professionally.

Features:
• File rename
• Media info
• Batch rename
• Custom thumbnail
• Custom caption
• Prefix / suffix
• Auto rename
• Premium users
• Admin panel
• MongoDB storage

Plan: {"Premium 💎" if user.get("premium") else "Free"}

Send me any file/video/audio to begin.
""",
        reply_markup=main_buttons()
    )


@bot.on_message(filters.command("premium"))
async def premium(_, message):
    await message.reply_text(
        """
💎 Premium Plan

Premium users get:
• Bigger file limit
• Faster priority access
• Batch rename
• Custom caption
• Thumbnail support

Contact admin to upgrade.
"""
    )


@bot.on_message(filters.command("myplan"))
async def myplan(_, message):
    user = get_user(message.from_user.id)
    limit = PREMIUM_LIMIT if user.get("premium") else FREE_LIMIT

    await message.reply_text(
        f"""
❄️ Your Current Plan

Plan: {"Premium 💎" if user.get("premium") else "Free"}
File Limit: {format_size(limit)}
Files Renamed: {user.get("files_renamed", 0)}
"""
    )


@bot.on_message(filters.command("metadata"))
async def metadata(_, message):
    waiting[message.from_user.id] = "metadata"
    await message.reply_text("⚡ Send your metadata text.")


@bot.on_message(filters.command("settings"))
async def settings(_, message):
    await message.reply_text("⚙️ Settings", reply_markup=settings_buttons())


@bot.on_message(filters.command("viewthumb"))
async def viewthumb(_, message):
    user = get_user(message.from_user.id)
    thumb = user.get("thumbnail")

    if thumb and os.path.exists(thumb):
        await message.reply_photo(thumb, caption="👀 Your current thumbnail.")
    else:
        await message.reply_text("No thumbnail saved.")


@bot.on_message(filters.command("delthumb"))
async def delthumb(_, message):
    user = get_user(message.from_user.id)
    thumb = user.get("thumbnail")

    if thumb and os.path.exists(thumb):
        try:
            os.remove(thumb)
        except:
            pass

    update_user(message.from_user.id, {"thumbnail": None})
    await message.reply_text("🗑 Thumbnail deleted.")


@bot.on_message(filters.command("set_caption"))
async def set_caption(_, message):
    waiting[message.from_user.id] = "caption"
    await message.reply_text("✏️ Send your custom caption.\n\nUse `{filename}` for file name.")


@bot.on_message(filters.command("see_caption"))
async def see_caption(_, message):
    user = get_user(message.from_user.id)
    caption = user.get("caption")

    if caption:
        await message.reply_text(f"👀 Your caption:\n\n{caption}")
    else:
        await message.reply_text("No custom caption saved.")


@bot.on_message(filters.command("del_caption"))
async def del_caption(_, message):
    update_user(message.from_user.id, {"caption": None})
    await message.reply_text("🗑 Custom caption deleted.")


@bot.on_message(filters.command("donate"))
async def donate(_, message):
    await message.reply_text(
        """
💗 Support Developer

Thank you for using this bot.
You can support the developer by sharing the bot with others.
"""
    )


@bot.on_message(filters.command("task"))
async def task(_, message):
    await message.reply_text(
        """
✨ Complete Simple Task & Use Me For Free

Currently no task is available.
Please check again later.
"""
    )


@bot.on_callback_query()
async def callback_handler(_, query):
    user_id = query.from_user.id
    data = query.data

    if data == "rename":
        waiting[user_id] = "rename"
        await query.message.edit_text("📁 Send file/video/audio to rename.")

    elif data == "batch":
        waiting[user_id] = "batch"
        batch_files[user_id] = []
        await query.message.edit_text(
            "📦 Batch Rename Mode\n\n"
            "Send multiple files one by one.\n"
            "When finished, send /done"
        )

    elif data == "thumbnail":
        waiting[user_id] = "thumbnail"
        await query.message.edit_text("🖼 Send an image to save as thumbnail.")

    elif data == "settings":
        await query.message.edit_text("⚙ Settings", reply_markup=settings_buttons())

    elif data == "set_caption":
        waiting[user_id] = "caption"
        await query.message.edit_text("✏️ Send caption.\n\nUse {filename} for renamed file name.")

    elif data == "see_caption":
        user = get_user(user_id)
        await query.message.edit_text(
            f"👀 Your caption:\n\n{user.get('caption') or 'No caption saved.'}",
            reply_markup=settings_buttons()
        )

    elif data == "del_caption":
        update_user(user_id, {"caption": None})
        await query.message.edit_text("🗑 Caption deleted.", reply_markup=settings_buttons())

    elif data == "prefix":
        waiting[user_id] = "prefix"
        await query.message.edit_text("➕ Send prefix text.")

    elif data == "suffix":
        waiting[user_id] = "suffix"
        await query.message.edit_text("➖ Send suffix text.")

    elif data == "auto":
        waiting[user_id] = "auto"
        await query.message.edit_text(
            "🔁 Send auto rename format.\n\nExample:\n{title} - {quality} - @YourChannel"
        )

    elif data == "viewthumb":
        user = get_user(user_id)
        thumb = user.get("thumbnail")

        if thumb and os.path.exists(thumb):
            await query.message.reply_photo(thumb, caption="👀 Your current thumbnail.")
        else:
            await query.message.edit_text("No thumbnail saved.", reply_markup=settings_buttons())

    elif data == "delthumb":
        user = get_user(user_id)
        thumb = user.get("thumbnail")

        if thumb and os.path.exists(thumb):
            try:
                os.remove(thumb)
            except:
                pass

        update_user(user_id, {"thumbnail": None})
        await query.message.edit_text("🗑 Thumbnail deleted.", reply_markup=settings_buttons())

    elif data == "myplan":
        user = get_user(user_id)
        limit = PREMIUM_LIMIT if user.get("premium") else FREE_LIMIT
        await query.message.edit_text(
            f"""
❄️ Your Current Plan

Plan: {"Premium 💎" if user.get("premium") else "Free"}
File Limit: {format_size(limit)}
Files Renamed: {user.get("files_renamed", 0)}
""",
            reply_markup=main_buttons()
        )

    elif data == "premium":
        await query.message.edit_text(
            "💎 Premium gives bigger limits and priority access.\n\nContact admin to upgrade.",
            reply_markup=main_buttons()
        )

    elif data == "donate":
        await query.message.edit_text(
            "💗 Thank you for supporting developer.\n\nShare the bot with others.",
            reply_markup=main_buttons()
        )

    elif data == "help":
        await query.message.edit_text(
            """
❓ Help

1. Send any file/video/audio.
2. Bot shows media info.
3. Send new filename.
4. Bot sends renamed file.

Batch:
Click Batch Rename → send files → /done → send format.

Example:
Episode {number}.mkv
""",
            reply_markup=main_buttons()
        )

    elif data == "reset":
        update_user(user_id, {
            "caption": None,
            "prefix": "",
            "suffix": "",
            "auto_format": None,
            "thumbnail": None
        })
        await query.message.edit_text("Settings reset.", reply_markup=main_buttons())

    elif data == "back":
        await query.message.edit_text("Main Menu", reply_markup=main_buttons())

    await query.answer()


@bot.on_message(filters.photo)
async def photo_handler(_, message):
    user_id = message.from_user.id

    if waiting.get(user_id) != "thumbnail":
        return await message.reply_text("Click 🖼 Thumbnail first.")

    path = await message.download(file_name=f"{DOWNLOAD_DIR}/thumb_{user_id}.jpg")

    update_user(user_id, {"thumbnail": path})
    waiting[user_id] = None

    await message.reply_text("Thumbnail saved.")


@bot.on_message(filters.document | filters.video | filters.audio)
async def file_handler(client, message):
    user_id = message.from_user.id
    user = get_user(user_id)
    media = get_media(message)

    if not media:
        return

    if user_id in cooldown and time.time() - cooldown[user_id] < 3:
        return await message.reply_text("Slow down. Try again in a few seconds.")

    cooldown[user_id] = time.time()

    file_size = getattr(media, "file_size", 0)
    limit = PREMIUM_LIMIT if user.get("premium") else FREE_LIMIT

    if file_size > limit:
        return await message.reply_text(
            f"File too large.\n\nYour limit: {format_size(limit)}"
        )

    if waiting.get(user_id) == "batch":
        batch_files.setdefault(user_id, []).append(message)
        return await message.reply_text(
            f"Added to batch: {len(batch_files[user_id])}\n\n"
            "Send more files or send /done."
        )

    file_name, size, ext, mime, dc = get_media_info(message)

    if user.get("auto_format"):
        new_name = apply_auto_format(user.get("auto_format"), file_name)
        return await rename_file(client, message, new_name)

    waiting[user_id] = {
        "type": "rename_name",
        "message": message
    }

    await message.reply_text(
        f"""
🗂️ Media Info :

◈ File Name : {file_name}
◈ File Size : {format_size(size)}
◈ File Extension : {ext}
◈ Mime Type : {mime}
◈ DC ID : {dc}

Please Enter The New Filename.
"""
    )


@bot.on_message(filters.command("done"))
async def done_handler(_, message):
    user_id = message.from_user.id

    if not batch_files.get(user_id):
        return await message.reply_text("No batch files found.")

    waiting[user_id] = "batch_template"

    await message.reply_text(
        f"""
📦 Batch files received: {len(batch_files[user_id])}

Send rename template.

Example:
Episode {{number}}.mkv
"""
    )


@bot.on_message(filters.text & ~filters.command([
    "start", "ping", "done", "admin", "stats", "add_premium",
    "remove_premium", "broadcast", "premium", "myplan", "metadata",
    "settings", "viewthumb", "delthumb", "set_caption", "see_caption",
    "del_caption", "donate", "task", "premium_list"
]))
async def text_handler(client, message):
    user_id = message.from_user.id
    state = waiting.get(user_id)

    if state == "caption":
        update_user(user_id, {"caption": message.text})
        waiting[user_id] = None
        return await message.reply_text("Caption saved.")

    if state == "prefix":
        update_user(user_id, {"prefix": message.text})
        waiting[user_id] = None
        return await message.reply_text("Prefix saved.")

    if state == "suffix":
        update_user(user_id, {"suffix": message.text})
        waiting[user_id] = None
        return await message.reply_text("Suffix saved.")

    if state == "auto":
        update_user(user_id, {"auto_format": message.text})
        waiting[user_id] = None
        return await message.reply_text("Auto rename saved.")

    if state == "metadata":
        update_user(user_id, {"metadata": message.text})
        waiting[user_id] = None
        return await message.reply_text("Metadata saved.")

    if state == "batch_template":
        template = message.text
        files = batch_files.get(user_id, [])

        await message.reply_text(f"📦 Batch rename started.\nFiles: {len(files)}")

        for index, file_msg in enumerate(files, start=1):
            new_name = template.replace("{number}", str(index).zfill(2))
            await rename_file(client, file_msg, new_name)

        batch_files[user_id] = []
        waiting[user_id] = None

        return await message.reply_text("Batch completed.")

    if isinstance(state, dict) and state.get("type") == "rename_name":
        file_msg = state["message"]
        new_name = clean_filename(message.text)

        waiting[user_id] = None
        return await rename_file(client, file_msg, new_name)

    await message.reply_text("Send me a file/video/audio to rename.", reply_markup=main_buttons())


async def rename_file(client, file_msg, new_name):
    user_id = file_msg.from_user.id
    user = get_user(user_id)
    media = get_media(file_msg)

    old_name = getattr(media, "file_name", None) or "file"
    old_ext = os.path.splitext(old_name)[1]

    if "." not in new_name and old_ext:
        new_name += old_ext

    final_name = f"{user.get('prefix', '')}{new_name}{user.get('suffix', '')}"
    final_name = clean_filename(final_name)

    status = await file_msg.reply_text("📥 Downloading...")

    download_path = None
    renamed_path = None

    try:
        start = time.time()

        download_path = await file_msg.download(
            file_name=f"{DOWNLOAD_DIR}/{old_name}",
            progress=progress,
            progress_args=(status, start, "📥 Downloading")
        )

        renamed_path = f"{DOWNLOAD_DIR}/{final_name}"

        if os.path.exists(renamed_path):
            os.remove(renamed_path)

        os.rename(download_path, renamed_path)

        caption = user.get("caption")
        caption = caption.replace("{filename}", final_name) if caption else final_name

        thumb = user.get("thumbnail")
        if thumb and not os.path.exists(thumb):
            thumb = None

        await status.edit_text("📤 Uploading...")

        start = time.time()

        await client.send_document(
            chat_id=file_msg.chat.id,
            document=renamed_path,
            caption=caption,
            thumb=thumb,
            progress=progress,
            progress_args=(status, start, "📤 Uploading")
        )

        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"files_renamed": 1}},
            upsert=True
        )

        files_col.insert_one({
            "user_id": user_id,
            "old_name": old_name,
            "new_name": final_name,
            "size": getattr(media, "file_size", 0),
            "date": datetime.utcnow()
        })

        await status.delete()

    except Exception as e:
        await status.edit_text(f"Error:\n{e}")

    finally:
        try:
            if renamed_path and os.path.exists(renamed_path):
                os.remove(renamed_path)
        except:
            pass

        try:
            if download_path and os.path.exists(download_path):
                os.remove(download_path)
        except:
            pass


@bot.on_message(filters.command("admin"))
async def admin_panel(_, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("You are not admin.")

    total_users = users_col.count_documents({})
    premium_users = users_col.count_documents({"premium": True})
    total_files = files_col.count_documents({})

    await message.reply_text(
        f"""
👑 Admin Panel

Total Users: {total_users}
Premium Users: {premium_users}
Files Renamed: {total_files}

Commands:
/add_premium user_id
/remove_premium user_id
/premium_list
/broadcast message
/stats
"""
    )


@bot.on_message(filters.command("stats"))
async def admin_stats(_, message):
    if not is_admin(message.from_user.id):
        return

    total_users = users_col.count_documents({})
    premium_users = users_col.count_documents({"premium": True})
    total_files = files_col.count_documents({})

    await message.reply_text(
        f"""
📊 Bot Stats

Users: {total_users}
Premium Users: {premium_users}
Files Renamed: {total_files}
"""
    )


@bot.on_message(filters.command("add_premium"))
async def add_premium(_, message):
    if not is_admin(message.from_user.id):
        return

    try:
        user_id = int(message.text.split()[1])
        update_user(user_id, {"premium": True})
        await message.reply_text("Premium added.")
    except:
        await message.reply_text("Usage:\n/add_premium user_id")


@bot.on_message(filters.command("remove_premium"))
async def remove_premium(_, message):
    if not is_admin(message.from_user.id):
        return

    try:
        user_id = int(message.text.split()[1])
        update_user(user_id, {"premium": False})
        await message.reply_text("Premium removed.")
    except:
        await message.reply_text("Usage:\n/remove_premium user_id")


@bot.on_message(filters.command("premium_list"))
async def premium_list(_, message):
    if not is_admin(message.from_user.id):
        return

    users = list(users_col.find({"premium": True}))

    if not users:
        return await message.reply_text("No premium users.")

    text = "🌸 Premium Users:\n\n"

    for user in users:
        text += f"• `{user['user_id']}`\n"

    await message.reply_text(text)


@bot.on_message(filters.command("broadcast"))
async def broadcast(client, message):
    if not is_admin(message.from_user.id):
        return

    text = message.text.replace("/broadcast", "").strip()

    if not text:
        return await message.reply_text("Usage:\n/broadcast your message")

    sent = 0
    failed = 0

    for user in users_col.find({}):
        try:
            await client.send_message(user["user_id"], text)
            sent += 1
        except:
            failed += 1

    await message.reply_text(f"Broadcast completed.\nSent: {sent}\nFailed: {failed}")


async def main():
    await bot.start()
    await set_bot_commands()
    print("🚀 Bot started with command menu...")
    await idle()
    await bot.stop()


bot.run(main())
