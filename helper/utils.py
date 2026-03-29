import time
import re
import asyncio
from datetime import datetime
from pytz import timezone
from config import Config
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait

# ================= PROGRESS BAR =================

last_edit_times = {}  # message_id -> last edit timestamp

async def progress_for_pyrogram(current, total, ud_type, message, start, cancel_data=None):
    now = time.time()
    diff = now - start
    if diff <= 0:
        return

    # Throttle updates to 7s to avoid FloodWait and edit storms.
    msg_id = message.id
    last = last_edit_times.get(msg_id, 0)
    if now - last < 7 and current != total:
        return
    last_edit_times[msg_id] = now

    percentage = 0.0
    if total and total > 0:
        percentage = min(max(current * 100 / total, 0.0), 100.0)

    speed = current / diff if diff > 0 else 0
    eta_seconds = 0
    if total and total > current and speed > 0:
        eta_seconds = int((total - current) / speed)

    elapsed_text = TimeFormatter(int(diff * 1000))
    eta_text = TimeFormatter(eta_seconds * 1000) if eta_seconds else "--"

    bar_length = 15
    filled_count = int(bar_length * (percentage / 100))
    filled = "⬢" * filled_count
    empty = "⬡" * (bar_length - filled_count)

    text = (
        f"**{ud_type}**\n\n"
        f"`{filled}{empty}` **{round(percentage, 1)}%**\n\n"
        f"📦 **Size:** `{humanbytes(current)}` / `{humanbytes(total if total else 0)}`\n"
        f"⚡ **Speed:** `{humanbytes(speed)}/s`\n"
        f"⏱ **Elapsed:** `{elapsed_text}`\n"
        f"⏳ **ETA:** `{eta_text}`"
    )

    if cancel_data:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=cancel_data)]]
        )
    else:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="close")]]
        )

    try:
        await message.edit_text(text, reply_markup=markup)
        if current == total:
            last_edit_times.pop(msg_id, None)
    except FloodWait as e:
        # Set next allowed edit time to now + wait duration
        last_edit_times[msg_id] = time.time() + e.value
    except Exception:
        pass

# ================= HUMAN BYTES =================

def humanbytes(size):
    if not size or size == 0:
        return "0 B"
    if size < 0:
        return f"-{humanbytes(-size)}"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    power = 1024
    n = 0
    while size >= power and n < len(units) - 1:
        size /= power
        n += 1
    return f"{round(size, 2)} {units[n]}"

# ================= TIME FORMAT =================

def TimeFormatter(milliseconds: int) -> str:
    if milliseconds <= 0:
        return "0s"
    seconds, _ = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)

# ================= TIME CONVERTER =================

def convert(seconds):
    seconds = seconds % (24 * 3600)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return "%d:%02d:%02d" % (hour, minutes, seconds)

# ================= LOG NEW USER =================

async def send_log(b, u):
    if Config.LOG_CHANNEL is None:
        return
    curr = datetime.now(timezone("Asia/Kolkata"))
    date = curr.strftime("%d %B, %Y")
    time_ = curr.strftime("%I:%M:%S %p")
    try:
        await b.send_message(
            Config.LOG_CHANNEL,
            f"**━━ New User Started Bot ━━**\n\n"
            f"👤 **User:** {u.mention}\n"
            f"🆔 **ID:** `{u.id}`\n"
            f"📛 **Username:** @{u.username}\n\n"
            f"📅 **Date:** `{date}`\n"
            f"🕐 **Time:** `{time_}`\n\n"
            f"🤖 **By:** {b.mention}",
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await send_log(b, u)
    except Exception:
        pass

# ================= PREFIX SUFFIX =================

def add_prefix_suffix(input_string, prefix="", suffix=""):
    pattern = r"(?P<filename>.*?)(\.\w+)?$"
    match = re.search(pattern, input_string)
    if not match:
        return input_string
    filename = match.group("filename")
    extension = match.group(2) or ""
    if prefix:
        filename = f"{prefix}{filename}"
    if suffix:
        filename = f"{filename} {suffix}"
    return f"{filename}{extension}"

# ================= SAFE MESSAGE EDIT =================

async def safe_edit(message, text, reply_markup=None):
    """Edit message with FloodWait protection."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except Exception:
            pass
    except Exception:
        pass

async def safe_send(client, chat_id, text, **kwargs):
    """Send message with FloodWait protection."""
    try:
        return await client.send_message(chat_id, text, **kwargs)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await client.send_message(chat_id, text, **kwargs)
