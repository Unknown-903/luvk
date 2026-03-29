import asyncio
import sys
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from config import Config
from helper.permissions import is_admin as _perm_is_admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= ADMIN CHECK =================

def is_admin(user_id):
    return user_id == Config.OWNER_ID or _perm_is_admin(user_id)

# ================= SAFE IMPORTS =================

def get_encode_tasks():
    try:
        from plugins.encode import active_tasks, encode_queue
        return active_tasks, encode_queue.qsize()
    except Exception:
        return {}, 0

def get_compress_tasks():
    try:
        from plugins.compress import active_tasks, compress_queue
        return active_tasks, compress_queue.qsize()
    except Exception:
        return {}, 0

def get_merge_tasks():
    try:
        from plugins.merge import active_tasks, merge_queue, merge_sessions
        return active_tasks, merge_queue.qsize(), merge_sessions
    except Exception:
        return {}, 0, {}

def get_upscale_tasks():
    try:
        from plugins.upscale import cancel_upscale, upscale_wait
        active = {k: v for k, v in cancel_upscale.items() if v is False}
        return active, upscale_wait
    except Exception:
        return {}, {}

def get_rename_queue():
    try:
        from plugins.file_rename import file_queue, current_user, queue_users
        return file_queue.qsize(), current_user, queue_users
    except Exception:
        return 0, None, {}

# ================= BUILD STATUS TEXT =================

def _build_status_text():
    """Build status text — reused by both /status and refresh callback."""
    encode_tasks, encode_queue_size = get_encode_tasks()
    compress_tasks, compress_queue_size = get_compress_tasks()
    merge_tasks, merge_queue_size, merge_sessions = get_merge_tasks()
    upscale_active, upscale_wait = get_upscale_tasks()
    rename_size, rename_current, rename_users = get_rename_queue()

    total_active = (
        len(encode_tasks) +
        len(compress_tasks) +
        len(merge_tasks) +
        len(upscale_active) +
        (1 if rename_current else 0)
    )

    lines = []
    lines.append("**🤖 B O T  S T A T U S**")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # -------- ENCODE --------
    lines.append("🎬 **ENCODE**")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if encode_tasks:
        for tid, task in encode_tasks.items():
            lines.append(
                f"  ⚙️ **Running**\n"
                f"  👤 `{task.get('name', task.get('user', '?'))}`\n"
                f"  📊 `{task.get('quality','?')}` · `{task.get('preset','?')}` · CRF `{task.get('crf','?')}`"
            )
    else:
        lines.append("  ✅ _No active tasks_")
    if encode_queue_size:
        lines.append(f"  📦 Queue: `{encode_queue_size}` pending")
    lines.append("")

    # -------- COMPRESS --------
    lines.append("🗜️ **COMPRESS**")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if compress_tasks:
        for tid, task in compress_tasks.items():
            lines.append(
                f"  ⚙️ **Running**\n"
                f"  👤 `{task.get('name', task.get('user', '?'))}`\n"
                f"  📊 `{task.get('label', task.get('level','?'))}` · CRF `{task.get('crf','?')}`"
            )
    else:
        lines.append("  ✅ _No active tasks_")
    if compress_queue_size:
        lines.append(f"  📦 Queue: `{compress_queue_size}` pending")
    lines.append("")

    # -------- MERGE --------
    lines.append("🔀 **MERGE**")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if merge_tasks:
        for tid, task in merge_tasks.items():
            lines.append(
                f"  ⚙️ **Running**\n"
                f"  👤 `{task.get('name', task.get('user', '?'))}`\n"
                f"  📦 Files: `{len(task.get('files',[]))}`\n"
                f"  📊 `{task.get('quality_info',{}).get('label','?')}`"
            )
    else:
        lines.append("  ✅ _No active tasks_")
    if merge_sessions:
        lines.append(f"  🕐 Sessions: `{len(merge_sessions)}` collecting files")
    if merge_queue_size:
        lines.append(f"  📦 Queue: `{merge_queue_size}` pending")
    lines.append("")

    # -------- UPSCALE --------
    lines.append("🔍 **UPSCALE**")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if upscale_active:
        lines.append(f"  ⚙️ Running: `{len(upscale_active)}` task(s)")
    else:
        lines.append("  ✅ _No active tasks_")
    if upscale_wait:
        lines.append(f"  🕐 Waiting: `{len(upscale_wait)}` user(s)")
    lines.append("")

    # -------- RENAME --------
    lines.append("✏️ **RENAME**")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if rename_current:
        lines.append(f"  ⚙️ Processing: `{rename_current}`")
    if rename_users:
        for user, count in rename_users.items():
            lines.append(f"  👤 `{user}` — **{count}** file(s)")
    if rename_size:
        lines.append(f"  📦 Queue: `{rename_size}` pending")
    if not rename_current and not rename_users:
        lines.append("  ✅ _No active tasks_")
    lines.append("")

    # -------- SUMMARY --------
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    if total_active == 0:
        lines.append("💤 **Bot is idle — no active tasks.**")
    else:
        lines.append(f"📊 **Total active: `{total_active}` task(s)**")

    # Timestamp
    from datetime import datetime
    from pytz import timezone
    now = datetime.now(timezone("Asia/Kolkata"))
    lines.append(f"\n🕐 _Updated: {now.strftime('%I:%M:%S %p')}_")

    return "\n".join(lines)

# ================= /status COMMAND =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.command("status")
)
async def status_cmd(client, message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.reply_text("❌ **Only owner and admins can use this.**")
        return

    text = _build_status_text()

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"status_refresh|{user_id}")]
    ])

    await message.reply_text(text, reply_markup=buttons)


# ================= REFRESH BUTTON =================

@Client.on_callback_query(filters.regex("^status_refresh"))
async def status_refresh(client, query):
    _, user_id = query.data.split("|")
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ This is not your status panel!", show_alert=True)
        return

    text = _build_status_text()

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"status_refresh|{user_id}")]
    ])

    try:
        await query.message.edit_text(text, reply_markup=buttons)
        await query.answer("✅ Refreshed!")
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit_text(text, reply_markup=buttons)
    except Exception:
        await query.answer("ℹ️ No changes.", show_alert=False)
