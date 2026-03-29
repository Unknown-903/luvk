import os
import re
import time
import asyncio
import logging
import math
import html

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

from plugins.antinsfw import check_anti_nsfw
from helper.database import codeflixbots
from helper.auth import auth_chats
from helper.permissions import is_owner, is_admin as _perm_is_admin, is_authorized_chat
from helper.utils import humanbytes, TimeFormatter, safe_edit
from config import Config
from helper.audio_reorder import probe_and_reorder_audio, build_audio_map_args

import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_queue = asyncio.Queue()
processing = False

queue_users = {}
current_user = None

cancel_tasks = {}      # task_token -> True (per-task cancel, not per-user)
current_task_info = {}  # {"filename": "...", "stage": "..."}
task_owner_map = {}    # task_token -> user_id (server-side verification)
select_sessions = {}   # user_id -> session dict
SESSION_TIMEOUT = 6 * 3600  # 6 hours auto-expiry

# ================= ADMIN CHECK =================

def _is_admin_rename(user_id):
    return _perm_is_admin(user_id)


# ================= ADMIN COMMANDS =================

@Client.on_message((filters.private | filters.group) & filters.command("add"))
async def add_admin(client, message):
    if message.from_user.id != Config.OWNER_ID:
        return await message.reply_text("❌ **Only the owner can use this command.**")

    if not message.reply_to_message:
        return await message.reply_text("❌ **Reply to a user to add them as admin.**")

    new_admin = message.reply_to_message.from_user.id

    if new_admin == Config.OWNER_ID:
        return await message.reply_text("❌ **Owner is already the owner.**")

    if new_admin in Config.ADMIN:
        return await message.reply_text("⚠️ **This user is already an admin.**")

    Config.ADMIN.append(new_admin)
    await message.reply_text(
        f"✅ **Admin Added**\n\n"
        f"👤 **User ID:** `{new_admin}`"
    )


@Client.on_message((filters.private | filters.group) & filters.command("rm"))
async def remove_admin(client, message):
    if message.from_user.id != Config.OWNER_ID:
        return await message.reply_text("❌ **Only the owner can use this command.**")

    if not message.reply_to_message:
        return await message.reply_text("❌ **Reply to an admin to remove them.**")

    user_id = message.reply_to_message.from_user.id

    if user_id == Config.OWNER_ID:
        return await message.reply_text("❌ **Cannot remove the owner.**")

    if user_id in Config.ADMIN:
        Config.ADMIN.remove(user_id)
        await message.reply_text(
            f"✅ **Admin Removed**\n\n"
            f"👤 **User ID:** `{user_id}`"
        )
    else:
        await message.reply_text("⚠️ **This user is not an admin.**")


@Client.on_message((filters.private | filters.group) & filters.command("addlist"))
async def admin_list(client, message):
    if message.from_user.id != Config.OWNER_ID:
        return await message.reply_text("❌ **Only the owner can use this command.**")

    text = "👑 **Admin List**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"👑 **Owner:** `{Config.OWNER_ID}`\n\n"

    if Config.ADMIN:
        for i, admin in enumerate(Config.ADMIN, 1):
            text += f"  {i}. `{admin}`\n"
    else:
        text += "  _No admins added yet._"

    await message.reply_text(text)



# ================= REGEX =================

SEASON_EPISODE_PATTERN = re.compile(
    r"(?:"
    # S01E01, Season 1 Episode 1, Series 01 Ep 05
    r"(?:S|Season|Series)[ ._\-]?(\d{1,3})[ ._\-]?(?:E|Episode|Ep)[ ._\-]?(\d{1,3})"
    r"|"
    # S01-E05 (dash-separated)
    r"[Ss](\d{1,3})\s*[-]\s*[Ee](\d{1,3})"
    r"|"
    # [S01E01] or (S01E01) — bracket-enclosed
    r"[\[\(][Ss](\d{1,3})[Ee](\d{1,3})[\]\)]"
    r"|"
    # S01 01 (space-separated season episode)
    r"[Ss](\d{1,3})[ ._\-]+(\d{1,3})"
    r"|"
    # 1x01 format
    r"(\d{1,3})x(\d{1,3})"
    r"|"
    # Ep01 / E01 / EP 01 (uppercase too)
    r"[Ee][Pp]?[ ._\-]?(\d{1,3})"
    r"|"
    # Episode 01 / Episode - 01
    r"[Ee]pisode[ ._\-]?(\d{1,3})"
    r"|"
    # - 01 (common anime pattern, must follow a word boundary)
    r"(?<=\s)[-–][ ]?(\d{2,3})(?=\s|$|[.\[\(])"
    r"|"
    # Part 01, Vol 03
    r"(?:Part|Pt|Vol|Volume)[ ._\-]?(\d{1,3})"
    r")",
    re.IGNORECASE
)

QUALITY_PATTERN = re.compile(
    r"(4[Kk]|8[Kk]|\d{3,4}[pP])", re.IGNORECASE
)

CODEC_PATTERN = re.compile(
    r"(HEVC|H\.?265|x265|H\.?264|x264|AVC|AV1|VP9|OPUS|AAC|FLAC|DDP?(?:5\.1)?|10[- ]?bit|HDR(?:10)?)",
    re.IGNORECASE
)

AUDIO_PATTERN = re.compile(
    r"(Dual[ ._\-]?Audio|Multi[ ._\-]?Audio|Hindi|English|Japanese|Tamil|Telugu|Korean|Eng|Hin|Jpn|Tam|Tel|Kor)",
    re.IGNORECASE
)

YEAR_PATTERN = re.compile(
    r"(?:^|[\s\(\[\-])(\d{4})(?:[\s\)\]\-]|$)"
)


# ================= PROGRESS =================

_last_edit_times = {}  # message_id -> last edit time

async def progress_for_pyrogram(current, total, ud_type, message, start, task_token=None):
    now = time.time()
    diff = now - start
    if diff <= 0:
        return

    # Check if task was cancelled
    if task_token and cancel_tasks.get(task_token):
        return

    # Throttle: edit every 7 seconds
    msg_id = message.id
    last = _last_edit_times.get(msg_id, 0)
    if now - last < 7 and current != total:
        return
    _last_edit_times[msg_id] = now

    percentage = min(max(current * 100 / total, 0), 100) if total else 0
    speed = current / diff if diff else 0
    eta = (total - current) / speed if (speed and total and total > current) else 0
    elapsed = TimeFormatter(int(diff * 1000))
    eta_text = TimeFormatter(int(eta * 1000)) if eta else "--"

    bar_length = 15
    filled_count = int(min(bar_length, max(0, bar_length * percentage / 100)))
    filled = "⬢" * filled_count
    empty = "⬡" * (bar_length - filled_count)

    text = (
        f"**{ud_type}**\n\n"
        f"`{filled}{empty}` **{round(percentage, 1)}%**\n\n"
        f"📦 **Size:** `{humanbytes(current)}` / `{humanbytes(total)}`\n"
        f"⚡ **Speed:** `{humanbytes(speed)}/s`\n"
        f"⏱ **Elapsed:** `{elapsed}`\n"
        f"⏳ **ETA:** `{eta_text}`"
    )

    # Cancel button
    markup = None
    if task_token:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=task_token)]]
        )

    try:
        if markup:
            await message.edit(text, reply_markup=markup)
        else:
            await message.edit(text)
        if current == total:
            _last_edit_times.pop(msg_id, None)
    except FloodWait as e:
        _last_edit_times[msg_id] = now + e.value
    except Exception:
        pass


# ================= HELPERS =================

def extract_season_episode(filename):
    match = SEASON_EPISODE_PATTERN.search(filename)
    if not match:
        return None, None

    g = match.groups()
    # Walk through capture groups in pairs + singles
    # Groups 0,1: S01E01 / Season Episode
    if g[0] and g[1]:
        return g[0].zfill(2), g[1].zfill(2)
    # Groups 2,3: S01-E05
    if g[2] and g[3]:
        return g[2].zfill(2), g[3].zfill(2)
    # Groups 4,5: [S01E01]
    if g[4] and g[5]:
        return g[4].zfill(2), g[5].zfill(2)
    # Groups 6,7: S01 01
    if g[6] and g[7]:
        return g[6].zfill(2), g[7].zfill(2)
    # Groups 8,9: 1x01
    if g[8] and g[9]:
        return g[8].zfill(2), g[9].zfill(2)
    # Group 10: Ep01 / E01
    if g[10]:
        return "01", g[10].zfill(2)
    # Group 11: Episode 01
    if g[11]:
        return "01", g[11].zfill(2)
    # Group 12: - 01 (anime pattern)
    if g[12]:
        return "01", g[12].zfill(2)
    # Group 13: Part 01 / Vol 03
    if g[13]:
        return "01", g[13].zfill(2)

    return None, None


def extract_quality(filename):
    match = QUALITY_PATTERN.search(filename)
    return match.group(1) if match else "Unknown"


def extract_codec(filename):
    matches = CODEC_PATTERN.findall(filename)
    return " ".join(matches) if matches else ""


def extract_audio(filename):
    matches = AUDIO_PATTERN.findall(filename)
    return " ".join(dict.fromkeys(matches)) if matches else ""


def extract_year(filename):
    match = YEAR_PATTERN.search(filename)
    if match:
        year = int(match.group(1))
        if 1950 <= year <= 2099:
            return str(year)
    return ""


def format_caption(text, style="regular"):
    text = text or ""
    safe = html.escape(text)

    styles = {
        "original": safe,
        "regular": safe,
        "bold": f"<b>{safe}</b>",
        "italic": f"<i>{safe}</i>",
        "underline": f"<u>{safe}</u>",
        "quote": "\n".join("> " + line for line in (safe.splitlines() or [safe])),
        "terminal": f"<pre>{safe}</pre>",
        "monospace": f"<code>{safe}</code>",
        "strikethrough": f"<s>{safe}</s>",
        "spoiler": f"<tg-spoiler>{safe}</tg-spoiler>",
    }
    return styles.get(style, safe)


def sanitize_filename(filename):
    filename = os.path.basename(filename or "")
    name, ext = os.path.splitext(filename)
    name = name.strip()
    name = re.sub(r"[^\w.\- ]+", "_", name)
    name = re.sub(r"_+", "_", name)        # collapse multiple underscores
    name = re.sub(r"\s+", " ", name)
    name = name.strip("_. ")
    if not name:
        name = "file"
    return f"{name}{ext}"


async def cleanup_files(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _cleanup_expired_sessions():
    """Remove select sessions older than SESSION_TIMEOUT."""
    now = time.time()
    expired = [
        uid for uid, s in select_sessions.items()
        if now - s.get("created_at", 0) > SESSION_TIMEOUT
    ]
    for uid in expired:
        del select_sessions[uid]
        logger.info(f"Session expired for user {uid}")


# ================= SELECT =================

@Client.on_message((filters.private | filters.group) & filters.command("select"))
async def select_range(client, message):

    if not _is_admin_rename(message.from_user.id):
        return await message.reply_text("❌ **Only admins can use this command.**")

    try:
        args = message.text.split()[1]
        start, end = map(int, args.split("-"))

        if start < 1 or end < start:
            return await message.reply_text(
                "❌ **Invalid range**\n\n"
                "**Example:** `/select 1-12`"
            )

        select_sessions[message.from_user.id] = {
            "start": start,
            "end": end,
            "count": 0,
            "created_at": time.time(),
        }

        await message.reply_text(
            f"✅ **Rename Range Set**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 **Start:** `{start}`\n"
            f"📌 **End:** `{end}`\n"
            f"📦 **Total Files:** `{end - start + 1}`\n\n"
            f"📤 _Now send your files!_\n\n"
            f"💡 Use `/clearselect` to cancel."
        )

    except (IndexError, ValueError):
        await message.reply_text(
            "❌ **Wrong format**\n\n"
            "**Usage:** `/select 1-12`\n"
            "**Example:** `/select 3-8` — renames files 3 to 8"
        )


# ================= CLEAR SELECT =================

@Client.on_message((filters.private | filters.group) & filters.command("clearselect"))
async def clear_select(client, message):
    user_id = message.from_user.id
    if user_id in select_sessions:
        del select_sessions[user_id]
        await message.reply_text("✅ **Select session cleared.**")
    else:
        await message.reply_text("ℹ️ **No active select session.**")


# ================= QUEUE =================

@Client.on_message((filters.private | filters.group) & filters.command("queue"))
async def show_queue(client, message):

    text = "📦 **Rename Queue**\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if current_user:
        text += f"⚙️ **Processing:** `{current_user}`\n"
        if current_task_info:
            fname = current_task_info.get("filename", "")
            stage = current_task_info.get("stage", "")
            if fname:
                text += f"  📄 **File:** `{fname[:60]}`\n"
            if stage:
                text += f"  📍 **Stage:** {stage}\n"
        text += "\n"

    if not queue_users:
        if not current_user:
            text += "💤 _Queue is empty._"
    else:
        text += "👥 **Queued Users:**\n"
        for i, (user, count) in enumerate(queue_users.items(), 1):
            text += f"  {i}. 👤 `{user}` — **{count}** file(s)\n"

    total_pending = file_queue.qsize()
    if total_pending:
        text += f"\n📊 **Total Pending:** `{total_pending}`"

    await message.reply_text(text)


# ================= HANDLE FILE =================

@Client.on_message(
    (filters.private | filters.group)
    & (filters.document | filters.video | filters.audio)
    & ~filters.command(["encode", "autorename", "sequence", "done"]),
    group=1
)
async def handle_files(client, message):

    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    # Group auth check
    if message.chat.type in ["group", "supergroup"]:
        if not is_authorized_chat(message.chat.id):
            return

    if not _is_admin_rename(user_id):
        return

    # Cleanup expired sessions periodically
    _cleanup_expired_sessions()

    if user_id not in select_sessions:
        return

    session = select_sessions[user_id]
    session["count"] += 1

    if session["count"] < session["start"]:
        return

    if session["count"] > session["end"]:
        del select_sessions[user_id]
        await message.reply_text(
            "✅ **Select range completed!**\n"
            f"📦 All `{session['end'] - session['start'] + 1}` files are queued."
        )
        return

    user = message.from_user.first_name
    queue_users[user] = queue_users.get(user, 0) + 1
    position = file_queue.qsize() + 1

    await message.reply_text(
        f"📥 **Added to Queue**\n\n"
        f"👤 **User:** {message.from_user.mention}\n"
        f"📍 **Position:** `{position}`\n"
        f"📊 **File** `{session['count'] - session['start'] + 1}` of `{session['end'] - session['start'] + 1}`"
    )

    await file_queue.put((client, message))
    asyncio.create_task(process_queue())


# ================= PROCESS QUEUE =================

async def process_queue():

    global processing, current_user

    if processing:
        return

    processing = True

    while not file_queue.empty():

        client, message = await file_queue.get()
        current_user = message.from_user.first_name

        try:
            await auto_rename_files(client, message)
        except Exception as e:
            logger.error(f"Rename error: {e}", exc_info=True)
            try:
                await message.reply_text(f"❌ **Error:** `{str(e)[:200]}`")
            except Exception:
                pass

        user = message.from_user.first_name
        if user in queue_users:
            queue_users[user] -= 1
            if queue_users[user] <= 0:
                del queue_users[user]

        file_queue.task_done()

    current_user = None
    processing = False


# ================= CANCEL =================

@Client.on_callback_query(filters.regex("^cancel_"))
async def cancel_task_rename(client, query):

    token = query.data
    caller_id = query.from_user.id

    owner_id = task_owner_map.get(token)

    if owner_id is None:
        return await query.answer("❌ Task not found or already done.", show_alert=True)

    # Task owner or bot owner can cancel
    if caller_id == owner_id or caller_id == Config.OWNER_ID:
        cancel_tasks[token] = True
        await query.answer("✅ Cancel request sent.")
    else:
        await query.answer("❌ This is not your task!", show_alert=True)


# ================= RESTART COMMAND =================

@Client.on_message((filters.private | filters.group) & filters.command("restart"))
async def restart_bot(client, message):
    user_id = message.from_user.id

    if not _is_admin_rename(user_id):
        return await message.reply_text("❌ **Only owner and admins can restart.**")

    await message.reply_text("🔄 **Restarting bot...**")
    logger.info(f"Restart triggered by user {user_id}")

    import sys
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ================= LOGS COMMAND =================

class TelegramLogHandler(logging.Handler):
    """Stores log messages in a ring buffer."""
    def __init__(self, maxlen=300):
        super().__init__()
        self._buffer = []
        self._maxlen = maxlen
        self._client = None
        self._target = None
        self._active = False

    def setup(self, client, target):
        self._client = client
        self._target = target
        self._active = True

    def stop(self):
        self._active = False
        self._client = None
        self._target = None

    def emit(self, record):
        try:
            msg = self.format(record)
            self._buffer.append(msg)
            if len(self._buffer) > self._maxlen:
                self._buffer = self._buffer[-self._maxlen:]
        except Exception:
            pass


telegram_log_handler = TelegramLogHandler()
telegram_log_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
)
logging.getLogger().addHandler(telegram_log_handler)


@Client.on_message((filters.private | filters.group) & filters.command("logs"))
async def send_logs(client, message):

    user_id = message.from_user.id

    if not _is_admin_rename(user_id):
        return await message.reply_text("❌ **Only admins and owner can use this command.**")

    args = message.text.split()
    sub = args[1].lower() if len(args) > 1 else ""

    if sub == "stop":
        if telegram_log_handler._active:
            telegram_log_handler.stop()
            await message.reply_text("🔕 **Log streaming stopped.**")
        else:
            await message.reply_text("ℹ️ **Log streaming is not active.**")
        return

    if sub == "stream":
        if telegram_log_handler._active:
            await message.reply_text("ℹ️ **Already streaming logs to this chat.**")
            return
        telegram_log_handler.setup(client, message.chat.id)
        await message.reply_text(
            "📡 **Log Streaming Started**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Logs will be sent here in real-time.\n"
            "Use `/logs stop` to stop streaming."
        )
        asyncio.create_task(_send_log_buffer(client, message.chat.id))
        return

    # Show recent buffered logs
    if telegram_log_handler._buffer:
        lines = telegram_log_handler._buffer[-30:]
        text = "📋 **Recent Logs**\n━━━━━━━━━━━━━━━━━━━━\n\n```\n" + "\n".join(lines) + "\n```"
        if len(text) > 4000:
            lines = telegram_log_handler._buffer[-10:]
            text = "📋 **Recent Logs**\n━━━━━━━━━━━━━━━━━━━━\n\n```\n" + "\n".join(lines) + "\n```"
        await message.reply_text(text)
    else:
        await message.reply_text(
            "📋 **No logs yet.**\n\n"
            "Use `/logs stream` to start live streaming."
        )


async def _send_log_buffer(client, chat_id):
    """Background task — sends new logs to Telegram."""
    sent_count = len(telegram_log_handler._buffer)

    while telegram_log_handler._active:
        await asyncio.sleep(8)

        current_len = len(telegram_log_handler._buffer)
        if current_len <= sent_count:
            continue

        new_logs = telegram_log_handler._buffer[sent_count:current_len]
        sent_count = current_len

        text = "\n".join(new_logs)
        if len(text) > 3800:
            text = text[-3800:]

        try:
            await client.send_message(chat_id, f"📡 **Live Logs**\n\n```\n{text}\n```")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass


# ================= MAIN RENAME =================

async def auto_rename_files(client, message: Message):

    user_id = message.from_user.id
    chat_id = message.chat.id  # send to same chat, not user DM

    format_template = await codeflixbots.get_format_template(user_id)

    if not format_template:
        return await message.reply_text(
            "⚠️ **No rename format set!**\n\n"
            "Use `/autorename` to set your template first."
        )

    file = message.document or message.video or message.audio

    file_name = file.file_name
    safe_original_filename = sanitize_filename(file_name)
    season, episode = extract_season_episode(file_name)
    quality = extract_quality(file_name)
    codec = extract_codec(file_name)
    audio = extract_audio(file_name)
    year = extract_year(file_name)

    try:
        renamed_base = format_template.format(
            filename=os.path.splitext(safe_original_filename)[0],
            season=season or "",
            episode=episode or "",
            quality=quality,
            codec=codec,
            audio=audio,
            year=year,
        )
    except KeyError as e:
        logger.warning(f"Unknown placeholder {e} in template for user {user_id}")
        await message.reply_text(
            f"⚠️ **Unknown placeholder** `{e}` in your template.\n\n"
            f"**Available:** `{{season}}` `{{episode}}` `{{quality}}` "
            f"`{{codec}}` `{{audio}}` `{{year}}` `{{filename}}`"
        )
        renamed_base = os.path.splitext(safe_original_filename)[0]
    except Exception as e:
        logger.warning(f"Invalid rename template for user {user_id}: {e}")
        renamed_base = os.path.splitext(safe_original_filename)[0]

    # Determine file extension
    video_ext = await codeflixbots.get_video_extension(user_id) or "mkv"
    original_ext = os.path.splitext(safe_original_filename)[1]

    # Use custom video extension for video files, original for others
    if message.video or (message.document and original_ext.lower() in [".mkv", ".mp4", ".avi", ".webm", ".mov"]):
        final_ext = f".{video_ext}"
    else:
        final_ext = original_ext

    safe_filename = sanitize_filename(renamed_base + final_ext)

    if await check_anti_nsfw(file_name, message):
        return

    caption_style = await codeflixbots.get_caption_style(user_id)
    saved_caption = await codeflixbots.get_caption(user_id)
    if caption_style == "original" or not saved_caption:
        caption_text = os.path.splitext(safe_original_filename)[0]
    else:
        file_size = humanbytes(file.file_size) if file and file.file_size else "N/A"
        try:
            caption_text = saved_caption.format(
                filename=os.path.splitext(safe_original_filename)[0],
                filesize=file_size,
                duration="",
                quality=quality,
                episode=episode or "",
                season=season or "",
            )
        except Exception:
            caption_text = os.path.splitext(safe_original_filename)[0]

    caption = format_caption(caption_text, caption_style)
    parse_mode = enums.ParseMode.HTML

    upload_preference = await codeflixbots.get_media_preference(user_id)

    os.makedirs("downloads", exist_ok=True)

    download_path = f"downloads/{time.time()}_{safe_filename}"

    # Track current task info for /queue display
    current_task_info.update({"filename": safe_filename, "stage": "⏳ Queued", "user_id": user_id})

    # Unique token per task
    task_token = f"cancel_{int(time.time() * 1000)}_{user_id}"
    task_owner_map[task_token] = user_id
    cancel_tasks[task_token] = False

    current_task_info["stage"] = "📥 Downloading"
    msg = await message.reply_text(
        "📥 **Downloading...**",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=task_token)]]
        ),
    )

    start = time.time()

    try:
        file_path = await client.download_media(
            message,
            file_name=download_path,
            progress=progress_for_pyrogram,
            progress_args=("📥 Downloading", msg, start, task_token),
        )
    except FloodWait as e:
        logger.warning(f"FloodWait {e.value}s on download for user {user_id}")
        await asyncio.sleep(e.value)
        file_path = await client.download_media(
            message,
            file_name=download_path,
            progress=progress_for_pyrogram,
            progress_args=("📥 Downloading", msg, start, task_token),
        )

    # Cancel check after download
    if cancel_tasks.get(task_token):
        _task_cleanup(task_token)
        await cleanup_files(file_path)
        await safe_edit(msg, "❌ **Task Cancelled.**")
        return


    # ---------------- AUDIO REORDER ----------------
    reorder_task_id = int(task_token.split('_')[1])  # extract timestamp as unique ID
    streams, order = await probe_and_reorder_audio(
        client, file_path, user_id, reorder_task_id, msg, timeout=300
    )
    if order is None:  # User cancelled
        _task_cleanup(task_token)
        await cleanup_files(file_path)
        await safe_edit(msg, "❌ **Task Cancelled.**")
        return

    audio_args = build_audio_map_args(streams, order) if streams else ["-map", "0:a?"]

    try:
        current_task_info["stage"] = "⚙️ Applying Metadata"
        await safe_edit(msg, "⚙️ **Applying Metadata...**")

        title = await codeflixbots.get_title(user_id) or ""
        author = await codeflixbots.get_author(user_id) or ""
        artist = await codeflixbots.get_artist(user_id) or ""

        meta_file = f"downloads/meta_{safe_filename}"

        cmd = [
            "ffmpeg", "-i", file_path,
            "-map", "0:v",
            ] + audio_args + [
            "-map", "0:s?",
            "-c", "copy",
            "-metadata", f"title={title}",
            "-metadata", f"author={author}",
            "-metadata", f"artist={artist}",
            "-y", meta_file,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.warning(f"Metadata ffmpeg error: {stderr.decode()[:500]}")
            raise Exception("ffmpeg failed")

        # Cancel check after metadata
        if cancel_tasks.get(task_token):
            _task_cleanup(task_token)
            await cleanup_files(file_path, meta_file)
            await safe_edit(msg, "❌ **Task Cancelled.**")
            return

        await cleanup_files(file_path)
        file_path = meta_file
        logger.info(f"Metadata applied for user {user_id}")

    except Exception as e:
        logger.warning(f"Metadata skipped: {e}")

    thumb = None
    thumb_id = await codeflixbots.get_thumbnail(user_id)
    if thumb_id:
        try:
            thumb = await client.download_media(
                thumb_id,
                file_name=f"thumb_{user_id}.jpg"
            )
        except Exception:
            thumb = None

    current_task_info["stage"] = "🚀 Uploading"
    await safe_edit(
        msg,
        "🚀 **Uploading...**",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=task_token)]]
        ),
    )

    start = time.time()
    max_retries = 5
    retry_count = 0

    while retry_count < max_retries:

        if cancel_tasks.get(task_token):
            _task_cleanup(task_token)
            await cleanup_files(file_path, thumb)
            await safe_edit(msg, "❌ **Task Cancelled.**")
            return

        try:
            if upload_preference in {"original", "video"} and message.video:
                await client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    caption=caption,
                    thumb=thumb,
                    progress=progress_for_pyrogram,
                    progress_args=("🚀 Uploading", msg, start, task_token),
                    parse_mode=parse_mode,
                )
            elif upload_preference in {"original", "audio"} and message.audio:
                await client.send_audio(
                    chat_id=chat_id,
                    audio=file_path,
                    caption=caption,
                    thumb=thumb,
                    progress=progress_for_pyrogram,
                    progress_args=("🚀 Uploading", msg, start, task_token),
                    parse_mode=parse_mode,
                )
            elif upload_preference == "music":
                await client.send_audio(
                    chat_id=chat_id,
                    audio=file_path,
                    caption=caption,
                    thumb=thumb,
                    progress=progress_for_pyrogram,
                    progress_args=("🚀 Uploading", msg, start, task_token),
                    parse_mode=parse_mode,
                )
            else:
                await client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    file_name=safe_filename,
                    caption=caption,
                    thumb=thumb,
                    progress=progress_for_pyrogram,
                    progress_args=("🚀 Uploading", msg, start, task_token),
                    parse_mode=parse_mode,
                )

            break  # Success

        except FloodWait as e:
            retry_count += 1
            wait_time = e.value
            logger.warning(f"FloodWait {wait_time}s on upload for user {user_id} (attempt {retry_count})")
            await safe_edit(msg, f"⏳ **Rate limited** — resuming in `{wait_time}s`...")
            await asyncio.sleep(wait_time)  # Actually sleep the full duration

        except Exception as e:
            retry_count += 1
            logger.error(f"Upload error for user {user_id} (attempt {retry_count}): {e}")
            if retry_count >= max_retries:
                await safe_edit(msg, f"❌ **Upload failed after {max_retries} attempts.**\n`{str(e)[:200]}`")
                break
            await asyncio.sleep(5)

    # Group: delete original file
    if message.chat.type in ["group", "supergroup"]:
        try:
            await message.delete()
        except Exception:
            pass

    await cleanup_files(file_path, thumb)
    await codeflixbots.increment_task_count(user_id, "rename")
    _task_cleanup(task_token)
    current_task_info.clear()

    try:
        await msg.delete()
    except Exception:
        pass


def _task_cleanup(task_token):
    """Clean up task tracking data."""
    task_owner_map.pop(task_token, None)
    cancel_tasks.pop(task_token, None)
