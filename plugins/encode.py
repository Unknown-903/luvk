import os
import time
import json
import asyncio
import logging
import subprocess
from collections import deque

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

from helper.utils import progress_for_pyrogram
from helper.auth import auth_chats
from helper.database import codeflixbots
from helper.permissions import is_owner, is_admin as _perm_is_admin, is_authorized_chat
from config import Config

import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ================= ADMIN CHECK =================

def _is_admin_encode(user_id):
    return _perm_is_admin(user_id)

# ================= CONSTANTS =================

CODECS = {
    "h265": {"lib": "libx265", "tag": "hvc1", "label": "🎬 H.265 (HEVC)"},
    "h264": {"lib": "libx264", "tag": "avc1", "label": "📺 H.264 (AVC)"},
}

RESOLUTIONS = {
    "original": None, "360p": "640:360", "480p": "854:480", "540p": "960:540",
    "720p": "1280:720", "1080p": "1920:1080", "4k": "3840:2160",
}

RESOLUTION_WIDTHS = {
    "360p": 640, "480p": 854, "540p": 960, "720p": 1280, "1080p": 1920, "4k": 3840,
}

DEFAULT_CRF = {
    "360p": 30, "480p": 28, "540p": 27, "720p": 26,
    "1080p": 24, "4k": 22, "original": 24,
}
MIN_BITRATE = {
    "360p": 200, "480p": 350, "540p": 500, "720p": 700,
    "1080p": 1400, "4k": 3000, "original": 700,
}
MAX_BITRATE = {
    "360p": 800, "480p": 1200, "540p": 1800, "720p": 2500,
    "1080p": 4500, "4k": 9000, "original": 4500,
}
SIZE_PER_MIN = {
    "360p": 1.5, "480p": 2.5, "540p": 3.5, "720p": 5.0,
    "1080p": 8.5, "4k": 20.0, "original": 5.0,
}

PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster",
    "fast", "medium", "slow", "slower", "veryslow",
]

AUDIO_CODECS = {
    "aac": {"lib": "aac", "label": "🔊 AAC"},
    "ac3": {"lib": "ac3", "label": "🔊 AC3"},
    "opus": {"lib": "libopus", "label": "🔊 OPUS"},
    "mp3": {"lib": "libmp3lame", "label": "🔊 MP3"},
    "copy": {"lib": "copy", "label": "📋 Copy Original"},
}

AUDIO_CHANNELS = {
    "stereo": {"val": "2"}, "mono": {"val": "1"},
    "5.1": {"val": "6"}, "original": {"val": None},
}

COMPRESS_LEVELS = {
    "low": {"ratio": 0.85}, "medium": {"ratio": 0.65},
    "high": {"ratio": 0.45}, "best": {"ratio": 0.30}, "skip": {"ratio": 1.0},
}

PATIENCE_MSGS = [
    "☕ Chai pi lo, thoda time lagega...",
    "🍿 Popcorn ready karo, abhi aa raha hai!",
    "🐢 HEVC encoding slow hoti hai, quality ke liye worth it hai!",
    "🔧 FFmpeg mehnat kar raha hai aapke liye...",
    "⚡ Server full speed pe hai, bas thoda sabr karo...",
    "🧘 Patience is a virtue... aur encoding bhi!",
    "🚀 Quality encode ho rahi hai, rush mat karo!",
]

# ================= HELPERS =================

def get_video_duration(file_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except:
        return None

def get_video_width(file_path):
    """Get video width from file using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=30)
        return int(result.stdout.strip())
    except:
        return 1280

def get_audio_streams_info(file_path):
    """Get audio streams with language/title for reorder UI."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index,codec_name,channels:stream_tags=language,title",
             "-of", "json", file_path],
            capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        return data.get("streams", [])
    except:
        return []

def calc_video_bitrate(duration_sec, quality, audio_bitrate_kbps=128):
    minutes = duration_sec / 60
    target_mb = SIZE_PER_MIN.get(quality, 5.0) * minutes
    target_bits = target_mb * 8 * 1024 * 1024
    total_kbps = (target_bits / duration_sec) / 1000
    video_kbps = int(total_kbps - audio_bitrate_kbps)
    video_kbps = max(video_kbps, MIN_BITRATE.get(quality, 350))
    video_kbps = min(video_kbps, MAX_BITRATE.get(quality, 2500))
    return video_kbps

def calc_max_bitrate(duration_sec, quality, audio_bitrate_kbps=128):
    target = calc_video_bitrate(duration_sec, quality, audio_bitrate_kbps)
    return min(int(target * 1.4), int(MAX_BITRATE.get(quality, 2500) * 1.2))

def _get_size_ratio(wm_size):
    """Convert size setting to a ratio (0.0-1.0)."""
    preset_ratios = {"small": 0.08, "medium": 0.15, "large": 0.25}
    if wm_size in preset_ratios: return preset_ratios[wm_size]
    if wm_size.endswith("%"):
        try: return int(wm_size.rstrip("%")) / 100
        except ValueError: pass
    return 0.15

def build_watermark_filter(wm_text, wm_position, wm_size, wm_opacity):
    preset_sizes = {"small": "16", "medium": "24", "large": "36"}
    if wm_size in preset_sizes:
        fontsize_expr = preset_sizes[wm_size]
    elif wm_size.endswith("%"):
        try:
            pct = int(wm_size.rstrip("%")) / 100
            fontsize_expr = f"h*{pct}"
        except ValueError:
            fontsize_expr = "24"
    else:
        fontsize_expr = "24"
    positions = {
        "top_left": "x=10:y=10", "top_right": "x=w-tw-10:y=10",
        "bottom_left": "x=10:y=h-th-10", "bottom_right": "x=w-tw-10:y=h-th-10",
        "center": "x=(w-tw)/2:y=(h-th)/2",
    }
    pos = positions.get(wm_position, "x=w-tw-10:y=10")
    safe_text = wm_text.replace("'", "\\'").replace(":", "\\:")
    alpha = max(0.1, min(1.0, wm_opacity))
    return f"drawtext=text='{safe_text}':fontsize={fontsize_expr}:{pos}:fontcolor=white@{alpha}:borderw=1:bordercolor=black@{alpha}"

def get_overlay_position(wm_position):
    """Get FFmpeg overlay position string (uses W,H for main, w,h for overlay)."""
    positions = {
        "top_left": "x=10:y=10", "top_right": "x=W-w-10:y=10",
        "bottom_left": "x=10:y=H-h-10", "bottom_right": "x=W-w-10:y=H-h-10",
        "center": "x=(W-w)/2:y=(H-h)/2",
    }
    return positions.get(wm_position, "x=W-w-10:y=10")

def _build_audio_order_text(streams, order):
    """Build numbered text list for audio streams."""
    text = "🎛 **Audio Track Order**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, idx in enumerate(order):
        s = streams[idx]
        tags = s.get("tags", {})
        lang = tags.get("language", "und").title()
        title = tags.get("title", "")
        codec = s.get("codec_name", "?").upper()
        ch = s.get("channels", "?")
        label = f"{title} ({lang})" if title else lang
        prefix = "🔊 **DEFAULT** →" if i == 0 else f"  {i+1}."
        text += f"{prefix} {label} | {codec} | {ch}ch\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━\n"
    text += "💡 Tap track → moves to #1 (default)\n"
    return text

def _build_audio_order_buttons(streams, order, task_id, user_id):
    buttons = []
    for i, idx in enumerate(order):
        s = streams[idx]
        tags = s.get("tags", {})
        lang = tags.get("language", "und").title()
        title = tags.get("title", "")
        label = f"{'🔊 ' if i==0 else ''}{title or lang}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"enc_aorder|{task_id}|{idx}")])
    buttons.append([
        InlineKeyboardButton("✅ Continue Encoding", callback_data=f"enc_aorder_done|{task_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{task_id}|{user_id}"),
    ])
    return InlineKeyboardMarkup(buttons)

# ================= QUEUE =================

encode_queue = asyncio.Queue()
queue_list = deque()
active_tasks = {}
workers_started = False
encode_state = {}
cancel_tasks = {}

# Audio reorder events: task_id -> asyncio.Event
audio_order_events = {}
# Audio reorder data: task_id -> list (order)
audio_order_data = {}

# ================= WORKER =================

async def start_workers(client):
    global workers_started
    if workers_started:
        return
    workers_started = True
    asyncio.create_task(worker(client))

async def worker(client):
    while True:
        task = await encode_queue.get()
        active_tasks[task["id"]] = task
        try:
            await start_encode(client, task)
        except asyncio.CancelledError:
            logger.warning(f"[{task['id']}] Worker task cancelled")
        except Exception as e:
            logger.error(f"Encode error: {e}", exc_info=True)
        finally:
            active_tasks.pop(task["id"], None)
            cancel_tasks.pop(task["id"], None)
            audio_order_events.pop(task["id"], None)
            audio_order_data.pop(task["id"], None)
            try:
                queue_list.remove(task)
            except:
                pass
            encode_queue.task_done()

# ================= ENCODE COMMAND =================

@Client.on_message((filters.private | filters.group) & filters.command("encode") & filters.reply)
async def encode_cmd(client, message):
    user_id = message.from_user.id
    if not _is_admin_encode(user_id):
        return await message.reply_text("❌ Only owner/admin can use this.")
    if message.chat.type in ["group", "supergroup"]:
        if not is_authorized_chat(message.chat.id):
            return await message.reply_text("❌ This group is not authorized.")
    if not message.reply_to_message:
        return await message.reply_text("❌ Reply to a video or file")
    if not (message.reply_to_message.video or message.reply_to_message.document):
        return await message.reply_text("❌ Reply to a downloadable media file")

    encode_state[user_id] = {"msg": message.reply_to_message, "step": "codec"}
    await start_workers(client)

    saved_codec = await codeflixbots.get_encode_codec(user_id)
    if saved_codec != "ask":
        encode_state[user_id]["codec"] = saved_codec
        return await _ask_resolution(client, message, user_id)

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 H.265 (HEVC)", callback_data="enc_codec|h265"),
         InlineKeyboardButton("📺 H.264 (AVC)", callback_data="enc_codec|h264")]
    ])
    await message.reply_text("**🎬 Select Video Codec**", reply_markup=buttons)

async def _ask_resolution(client, msg_or_q, uid):
    saved = await codeflixbots.get_encode_resolution(uid)
    if saved != "ask":
        encode_state[uid]["quality"] = saved
        return await _ask_preset(client, msg_or_q, uid)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 360p", callback_data="enc_res|360p"),
         InlineKeyboardButton("🎬 480p", callback_data="enc_res|480p"),
         InlineKeyboardButton("📺 540p", callback_data="enc_res|540p")],
        [InlineKeyboardButton("🖥️ 720p", callback_data="enc_res|720p"),
         InlineKeyboardButton("🔥 1080p", callback_data="enc_res|1080p"),
         InlineKeyboardButton("💎 4K", callback_data="enc_res|4k")],
        [InlineKeyboardButton("🎯 Original", callback_data="enc_res|original")],
    ])
    text = "**📐 Select Resolution**"
    if hasattr(msg_or_q, 'edit_text'): await msg_or_q.edit_text(text, reply_markup=buttons)
    else: await msg_or_q.reply_text(text, reply_markup=buttons)

async def _ask_preset(client, msg_or_q, uid):
    saved = await codeflixbots.get_encode_preset(uid)
    if saved != "ask":
        encode_state[uid]["preset"] = saved
        return await _ask_compress(client, msg_or_q, uid)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ ultrafast", callback_data="enc_pre|ultrafast"),
         InlineKeyboardButton("🚀 superfast", callback_data="enc_pre|superfast")],
        [InlineKeyboardButton("🔥 veryfast", callback_data="enc_pre|veryfast"),
         InlineKeyboardButton("💨 faster", callback_data="enc_pre|faster")],
        [InlineKeyboardButton("⚙️ fast", callback_data="enc_pre|fast"),
         InlineKeyboardButton("🎯 medium", callback_data="enc_pre|medium")],
        [InlineKeyboardButton("🐢 slow", callback_data="enc_pre|slow"),
         InlineKeyboardButton("🐌 slower", callback_data="enc_pre|slower")],
        [InlineKeyboardButton("🧊 veryslow", callback_data="enc_pre|veryslow")],
    ])
    if hasattr(msg_or_q, 'edit_text'): await msg_or_q.edit_text("**⚡ Select Encoding Speed**", reply_markup=buttons)
    else: await msg_or_q.reply_text("**⚡ Select Encoding Speed**", reply_markup=buttons)

async def _ask_compress(client, msg_or_q, uid):
    saved = await codeflixbots.get_encode_compress(uid)
    if saved != "ask":
        encode_state[uid]["compress_level"] = saved
        return await _ask_audio_codec(client, msg_or_q, uid)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Low", callback_data="enc_cmp|low"),
         InlineKeyboardButton("🟡 Medium", callback_data="enc_cmp|medium")],
        [InlineKeyboardButton("🟠 High", callback_data="enc_cmp|high"),
         InlineKeyboardButton("🔴 Best", callback_data="enc_cmp|best")],
        [InlineKeyboardButton("⏭️ Skip", callback_data="enc_cmp|skip")],
    ])
    if hasattr(msg_or_q, 'edit_text'): await msg_or_q.edit_text("**🗜️ Compression Level**", reply_markup=buttons)
    else: await msg_or_q.reply_text("**🗜️ Compression Level**", reply_markup=buttons)

async def _ask_audio_codec(client, msg_or_q, uid):
    saved = await codeflixbots.get_encode_audio_codec(uid)
    if saved != "ask":
        encode_state[uid]["audio_codec"] = saved
        return await _ask_rename(client, msg_or_q, uid)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊 AAC", callback_data="enc_acodec|aac"),
         InlineKeyboardButton("🔊 AC3", callback_data="enc_acodec|ac3")],
        [InlineKeyboardButton("🔊 OPUS", callback_data="enc_acodec|opus"),
         InlineKeyboardButton("🔊 MP3", callback_data="enc_acodec|mp3")],
        [InlineKeyboardButton("📋 Copy Original", callback_data="enc_acodec|copy")],
    ])
    if hasattr(msg_or_q, 'edit_text'): await msg_or_q.edit_text("**🔊 Select Audio Codec**", reply_markup=buttons)
    else: await msg_or_q.reply_text("**🔊 Select Audio Codec**", reply_markup=buttons)

async def _ask_rename(client, msg_or_q, uid):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Rename", callback_data="enc_rename|yes"),
         InlineKeyboardButton("📋 Keep Original", callback_data="enc_rename|no")]
    ])
    if hasattr(msg_or_q, 'edit_text'): await msg_or_q.edit_text("**✏️ Rename output file?**", reply_markup=buttons)
    else: await msg_or_q.reply_text("**✏️ Rename output file?**", reply_markup=buttons)

async def _finalize_task(client, uid, rename=None):
    state = encode_state.pop(uid, {})
    if not state or "msg" not in state:
        return None
    quality = state.get("quality", "720p")
    task = {
        "id": int(time.time() * 1000), "user": uid,
        "codec": state.get("codec", "h265"), "quality": quality,
        "preset": state.get("preset", "veryfast"),
        "compress_level": state.get("compress_level", "skip"),
        "audio_codec": state.get("audio_codec", "aac"),
        "rename": rename, "crf": DEFAULT_CRF.get(quality, 24),
        "msg": state["msg"], "name": state.get("user_name", "User"),
    }
    queue_list.append(task)
    await encode_queue.put(task)
    codec_label = CODECS.get(task["codec"], {}).get("label", task["codec"])
    return (f"📥 **Added to Encode Queue**\n\n🎬 {codec_label}\n"
            f"📐 {task['quality']} | ⚡ {task['preset']}\n"
            f"🗜️ {task['compress_level'].title()} | 🔊 {task['audio_codec'].upper()}\n"
            f"📍 Position: {len(queue_list)}")

# ================= CALLBACKS =================

@Client.on_callback_query(filters.regex("^enc_codec"))
async def enc_codec_cb(client, q):
    uid = q.from_user.id; _, codec = q.data.split("|")
    if uid not in encode_state: return await q.answer("Session expired.", show_alert=True)
    encode_state[uid]["codec"] = codec; encode_state[uid]["user_name"] = q.from_user.first_name
    await _ask_resolution(client, q.message, uid)

@Client.on_callback_query(filters.regex("^enc_res"))
async def enc_res_cb(client, q):
    uid = q.from_user.id; _, val = q.data.split("|")
    if uid not in encode_state: return await q.answer("Session expired.", show_alert=True)
    encode_state[uid]["quality"] = val; encode_state[uid]["user_name"] = q.from_user.first_name
    await _ask_preset(client, q.message, uid)

@Client.on_callback_query(filters.regex("^enc_pre"))
async def enc_preset_cb(client, q):
    uid = q.from_user.id; _, val = q.data.split("|")
    if uid not in encode_state: return await q.answer("Session expired.", show_alert=True)
    encode_state[uid]["preset"] = val
    await _ask_compress(client, q.message, uid)

@Client.on_callback_query(filters.regex("^enc_cmp"))
async def enc_compress_cb(client, q):
    uid = q.from_user.id; _, val = q.data.split("|")
    if uid not in encode_state: return await q.answer("Session expired.", show_alert=True)
    encode_state[uid]["compress_level"] = val
    await _ask_audio_codec(client, q.message, uid)

@Client.on_callback_query(filters.regex("^enc_acodec"))
async def enc_audio_cb(client, q):
    uid = q.from_user.id; _, val = q.data.split("|")
    if uid not in encode_state: return await q.answer("Session expired.", show_alert=True)
    encode_state[uid]["audio_codec"] = val
    await _ask_rename(client, q.message, uid)

@Client.on_callback_query(filters.regex("^enc_rename"))
async def enc_rename_cb(client, q):
    uid = q.from_user.id; _, choice = q.data.split("|")
    if uid not in encode_state: return await q.answer("Session expired.", show_alert=True)
    if choice == "yes":
        encode_state[uid]["waiting_rename"] = True
        await q.message.edit_text("✏️ **Send new file name**\nExample: `Episode 10`")
    else:
        text = await _finalize_task(client, uid, rename=None)
        if text: await q.message.edit_text(text)

# Audio reorder callback (during encoding, after download)
@Client.on_callback_query(filters.regex(r"^enc_aorder\|"))
async def enc_aorder_cb(client, q):
    parts = q.data.split("|")
    task_id = int(parts[1]); stream_idx = int(parts[2])
    order = audio_order_data.get(task_id)
    if not order: return await q.answer("Session expired.", show_alert=True)
    task = active_tasks.get(task_id)
    if not task: return await q.answer("Task not found.", show_alert=True)
    # Move selected to #1
    if stream_idx in order:
        order.remove(stream_idx)
        order.insert(0, stream_idx)
    streams = task.get("_audio_streams", [])
    text = _build_audio_order_text(streams, order)
    buttons = _build_audio_order_buttons(streams, order, task_id, task["user"])
    try:
        await q.message.edit_text(text, reply_markup=buttons)
        await q.answer("🔊 Moved to #1")
    except: pass

@Client.on_callback_query(filters.regex(r"^enc_aorder_done\|"))
async def enc_aorder_done_cb(client, q):
    task_id = int(q.data.split("|")[1])
    event = audio_order_events.get(task_id)
    if event: event.set()
    await q.answer("✅ Continuing encode...")

# ================= RENAME TEXT HANDLER =================

@Client.on_message(
    (filters.private | filters.group) & filters.text &
    ~filters.command(["encode","start","help","settings","queue","cancel",
                      "setthumb","delthumb","viewthumb","setcaption","delcaption",
                      "seecaption","metadata","delmetadata","addadmin","removeadmin",
                      "adminlist","authgroup","unauthgroup","authlist","rename","logs",
                      "batch","cancelbatch","speedtest","status","leaderboard","top","lb",
                      "af","broadcast","add","rm","addlist","clearselect"]),
    group=2)
async def get_encode_rename(client, message):
    uid = message.from_user.id
    if uid not in encode_state: return
    data = encode_state.get(uid)
    if not data or not data.get("waiting_rename"): return
    text = await _finalize_task(client, uid, rename=message.text)
    if text: await message.reply_text(text)

# ================= QUEUE COMMAND =================

@Client.on_message(filters.command(["queue"]) & (filters.private | filters.group))
async def queue_cmd(client, message):
    uid = message.from_user.id
    if not _is_admin_encode(uid): return await message.reply_text("❌ **Only admins.**")
    if not queue_list and not active_tasks:
        return await message.reply_text("📭 Queue is empty.")
    text = "📋 **Encode Queue**\n\n"
    if active_tasks:
        text += f"🔄 **Active ({len(active_tasks)}):**\n"
        for tid, t in active_tasks.items():
            text += f"  ▶️ `{t['name']}` — {t['quality']} | {t.get('codec','?')}\n"
        text += "\n"
    waiting = [t for t in queue_list if t['id'] not in active_tasks]
    if waiting:
        text += f"⏳ **Waiting ({len(waiting)}):**\n"
        for i, t in enumerate(waiting, 1):
            text += f"  {i}. `{t['name']}` — {t['quality']} | {t.get('codec','?')}\n"
    await message.reply_text(text)

# ================= CANCEL =================

@Client.on_callback_query(filters.regex(r"^cancel\|"))
async def cancel_task_encode(client, q):
    parts = q.data.split("|")
    if len(parts) != 3: return await q.answer("Invalid", show_alert=True)
    _, task_id, owner_id = parts; task_id = int(task_id); owner_id = int(owner_id)
    caller = q.from_user.id
    if caller == owner_id or caller == Config.OWNER_ID:
        cancel_tasks[task_id] = True
        # Also unblock audio reorder wait if pending
        event = audio_order_events.get(task_id)
        if event: event.set()
        await q.answer("✅ Cancel request sent")
    else:
        await q.answer("❌ Not your task!", show_alert=True)

# ================= ENCODING ENGINE =================

async def start_encode(client, task):
    msg = task["msg"]; user_id = task["user"]; quality = task["quality"]
    preset = task.get("preset", "veryfast"); codec_key = task.get("codec", "h265")
    audio_codec_key = task.get("audio_codec", "aac"); rename = task["rename"]
    crf = task["crf"]; codec_info = CODECS.get(codec_key, CODECS["h265"])
    scale = RESOLUTIONS.get(quality)
    ext = await codeflixbots.get_video_extension(user_id) or "mkv"
    ext = f".{ext.lstrip('.')}"
    download = f"temp_{task['id']}.mkv"; encoded = f"enc_{task['id']}.mkv"
    cancel_tasks[task['id']] = False

    # ---- DOWNLOAD ----
    progress_msg = await msg.reply_text("📥 Downloading...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{task['id']}|{user_id}")]]))
    start_time = time.time()
    file_path = await client.download_media(msg, file_name=download,
        progress=progress_for_pyrogram,
        progress_args=("📥 Downloading...", progress_msg, start_time, f"cancel|{task['id']}|{user_id}"))
    if cancel_tasks.get(task['id']):
        await progress_msg.edit("❌ Cancelled"); _cleanup_files([file_path]); return

    # ---- AUDIO REORDER STEP ----
    audio_streams = get_audio_streams_info(file_path)
    task["_audio_streams"] = audio_streams
    audio_map_order = list(range(len(audio_streams)))  # default order

    if len(audio_streams) > 1:
        # Show reorder UI and wait for user
        audio_order_data[task["id"]] = audio_map_order
        audio_order_events[task["id"]] = asyncio.Event()
        text = _build_audio_order_text(audio_streams, audio_map_order)
        buttons = _build_audio_order_buttons(audio_streams, audio_map_order, task["id"], user_id)
        await progress_msg.edit(text, reply_markup=buttons)
        # Wait for user to click "Continue" or cancel (max 5 min)
        try:
            await asyncio.wait_for(audio_order_events[task["id"]].wait(), timeout=300)
        except asyncio.TimeoutError:
            await progress_msg.edit("⏰ Audio reorder timed out. Using default order.")
        audio_map_order = audio_order_data.get(task["id"], audio_map_order)
        if cancel_tasks.get(task['id']):
            await progress_msg.edit("❌ Cancelled"); _cleanup_files([file_path]); return

    # ---- BUILD FFMPEG COMMAND ----
    duration = get_video_duration(file_path)
    compress_level = task.get("compress_level", "skip")
    ratio = COMPRESS_LEVELS.get(compress_level, COMPRESS_LEVELS["skip"])["ratio"]
    ten_bit = await codeflixbots.get_encode_10bit(user_id)
    pix_fmt = "yuv420p10le" if ten_bit else "yuv420p"
    audio_info = AUDIO_CODECS.get(audio_codec_key, AUDIO_CODECS["aac"])
    audio_bitrate = await codeflixbots.get_encode_audio_bitrate(user_id) or "128k"
    audio_channels_key = await codeflixbots.get_encode_audio_channels(user_id)
    audio_samplerate = await codeflixbots.get_encode_audio_samplerate(user_id)
    wm_text = await codeflixbots.get_watermark_text(user_id)
    wm_image_id = await codeflixbots.get_watermark_image(user_id)
    wm_position = await codeflixbots.get_watermark_position(user_id)
    wm_size = await codeflixbots.get_watermark_size(user_id)
    wm_opacity = await codeflixbots.get_watermark_opacity(user_id)
    wm_mode = await codeflixbots.get_watermark_mode(user_id)
    sub_mode = await codeflixbots.get_subtitle_mode(user_id)

    # ---- DETERMINE WATERMARK TYPES ----
    needs_text_wm = bool(wm_text) and wm_mode in ("text", "both")
    needs_image_wm = bool(wm_image_id) and wm_mode in ("image", "both")

    # ---- DOWNLOAD WATERMARK IMAGE IF NEEDED ----
    wm_image_path = None
    if needs_image_wm:
        try:
            wm_image_path = await client.download_media(wm_image_id, file_name=f"wm_{task['id']}.png")
            if not wm_image_path or not os.path.exists(wm_image_path):
                logger.warning(f"[{task['id']}] Watermark image download failed")
                needs_image_wm = False; wm_image_path = None
        except Exception as e:
            logger.warning(f"[{task['id']}] Watermark image error: {e}")
            needs_image_wm = False; wm_image_path = None

    vf_parts = []
    if scale: vf_parts.append(f"scale={scale}:flags=bilinear")
    if needs_text_wm: vf_parts.append(build_watermark_filter(wm_text, wm_position, wm_size, wm_opacity))

    if duration and duration > 0:
        video_bitrate = int(calc_video_bitrate(duration, quality) * ratio)
        max_bitrate = int(calc_max_bitrate(duration, quality) * ratio)
        video_bitrate = max(video_bitrate, MIN_BITRATE.get(quality, 350))
        max_bitrate = max(max_bitrate, int(video_bitrate * 1.4))
        use_bitrate = True
    else:
        use_bitrate = False

    fast_presets = {"ultrafast", "superfast", "veryfast"}
    if codec_key == "h265":
        codec_params = ["-x265-params", "log-level=error:aq-mode=0:no-sao=1:no-deblock=1"] if preset in fast_presets else ["-x265-params", "log-level=error:aq-mode=1:me=hex:subme=1:ref=1"]
    else:
        codec_params = []

    inputs = ["-i", file_path]
    if needs_image_wm: inputs += ["-i", wm_image_path]
    cmd = ["ffmpeg", "-progress", "pipe:1", "-stats_period", "3", "-nostats", "-threads", "4"] + inputs

    if needs_image_wm:
        # === filter_complex for image watermark ===
        vid_width = RESOLUTION_WIDTHS.get(quality) or get_video_width(file_path)
        wm_ratio = _get_size_ratio(wm_size)
        wm_target_w = max(int(vid_width * wm_ratio), 32)
        if wm_target_w % 2 != 0: wm_target_w += 1
        alpha = max(0.1, min(1.0, wm_opacity))
        overlay_pos = get_overlay_position(wm_position)
        fc_parts = [f"[1:v]scale={wm_target_w}:-1:flags=lanczos,format=rgba,colorchannelmixer=aa={alpha}[wm]"]
        if vf_parts:
            fc_parts.append(f"[0:v]{\',\'.join(vf_parts)}[main]")
            fc_parts.append(f"[main][wm]overlay={overlay_pos}:format=auto[vout]")
        else:
            fc_parts.append(f"[0:v][wm]overlay={overlay_pos}:format=auto[vout]")
        cmd += ["-filter_complex", ";".join(fc_parts), "-map", "[vout]"]
    else:
        cmd += ["-map", "0:v"]

    # Audio mapping — use reordered indices
    for idx in audio_map_order:
        original_index = audio_streams[idx]["index"] if idx < len(audio_streams) else 0
        cmd += ["-map", f"0:{original_index}"]
    if not audio_streams:
        cmd += ["-map", "0:a?"]

    if sub_mode == "copy":
        cmd += ["-map", "0:s?"]
    elif sub_mode == "hardsub":
        vf_parts.insert(0, f"subtitles='{file_path}'")

    vf_str = ",".join(vf_parts) if vf_parts else None
    cmd += ["-c:v", codec_info["lib"], "-preset", preset, "-pix_fmt", pix_fmt]
    if use_bitrate:
        cmd += ["-b:v", f"{video_bitrate}k", "-maxrate", f"{max_bitrate}k", "-bufsize", f"{max_bitrate*2}k"]
    else:
        cmd += ["-crf", str(crf)]
    cmd += codec_params
    if not needs_image_wm and vf_str: cmd += ["-vf", vf_str]
    if audio_info["lib"] == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", audio_info["lib"], "-b:a", audio_bitrate]
        ch = AUDIO_CHANNELS.get(audio_channels_key or "original", AUDIO_CHANNELS["original"])
        if ch["val"]: cmd += ["-ac", ch["val"]]
        if audio_samplerate and audio_samplerate not in ("ask", "original"):
            cmd += ["-ar", audio_samplerate]
    if sub_mode == "copy": cmd += ["-c:s", "copy"]
    cmd += ["-tag:v", codec_info["tag"], "-y", encoded]

    logger.info(f"[{task['id']}] FFmpeg: {' '.join(cmd[:25])}...")
    await progress_msg.edit("⚙️ Encoding...\n\n⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡ 0%",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{task['id']}|{user_id}")]]))

    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stderr_task = asyncio.create_task(_drain(process.stderr))

    last_edit_time = 0; encode_start = time.time(); patience_idx = 0
    duration_us = int(duration * 1_000_000) if duration else 0
    progress = 0; _editing = False

    async def safe_edit(text):
        nonlocal _editing, last_edit_time
        if _editing: return
        _editing = True
        try:
            await progress_msg.edit(text, reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{task['id']}|{user_id}")]]))
            last_edit_time = time.time()
        except FloodWait as e: last_edit_time = time.time() + e.value
        except: pass
        finally: _editing = False

    while True:
        if cancel_tasks.get(task['id']):
            try: process.kill(); await process.wait()
            except: pass
            stderr_task.cancel()
            await progress_msg.edit("❌ Encode Cancelled")
            _cleanup_files([file_path, encoded, wm_image_path]); return
        try: line = await asyncio.wait_for(process.stdout.readline(), timeout=60)
        except asyncio.TimeoutError: break
        if not line: break
        text = line.decode("utf-8").strip()
        if text.startswith("out_time_us="):
            try:
                out_us = int(text.split("=")[1])
                if duration_us > 0: progress = min(int(out_us * 100 / duration_us), 99)
            except: pass
            now = time.time(); elapsed = int(now - encode_start)
            if now - last_edit_time >= 10:
                last_edit_time = now
                filled = "⬢" * (progress // 10); empty = "⬡" * (10 - progress // 10)
                if elapsed > 45:
                    patience = PATIENCE_MSGS[patience_idx % len(PATIENCE_MSGS)]; patience_idx += 1
                    asyncio.create_task(safe_edit(f"⚙️ Encoding...\n\n{filled}{empty} {progress}%\n\n{patience}"))
                else:
                    asyncio.create_task(safe_edit(f"⚙️ Encoding...\n\n{filled}{empty} {progress}%"))

    try: await asyncio.wait_for(process.wait(), timeout=120)
    except asyncio.TimeoutError: process.kill(); await process.wait()
    stderr_task.cancel()

    if cancel_tasks.get(task['id']):
        await progress_msg.edit("❌ Cancelled"); _cleanup_files([file_path, encoded, wm_image_path]); return

    try: await progress_msg.edit("⚙️ Encoding...\n\n⬢⬢⬢⬢⬢⬢⬢⬢⬢⬢ 100% ✅")
    except: pass

    if not os.path.exists(encoded) or os.path.getsize(encoded) == 0:
        await progress_msg.edit("❌ Encoding failed!"); _cleanup_files([file_path, encoded, wm_image_path]); return

    # ---- FILE NAME ----
    if rename: name = f"{rename}.mkv"
    else:
        if msg.document and msg.document.file_name: name = msg.document.file_name
        elif msg.video and msg.video.file_name: name = msg.video.file_name
        else: name = f"encoded_{task['id']}.mkv"
    name = os.path.splitext(name)[0] + ext

    # ---- METADATA (with error handling) ----
    try:
        title = await codeflixbots.get_title(user_id) or ""
        author = await codeflixbots.get_author(user_id) or ""
        artist = await codeflixbots.get_artist(user_id) or ""
        meta_file = f"meta_{task['id']}{ext}"
        await progress_msg.edit("🏷️ Applying Metadata...")
        meta_cmd = ["ffmpeg", "-i", encoded, "-map", "0", "-c", "copy",
                    "-metadata", f"title={title}", "-metadata", f"author={author}",
                    "-metadata", f"artist={artist}", "-y", meta_file]
        mp = await asyncio.create_subprocess_exec(*meta_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, merr = await asyncio.wait_for(mp.communicate(), timeout=120)
        if os.path.exists(meta_file) and os.path.getsize(meta_file) > 0:
            os.remove(encoded); os.rename(meta_file, name)
        else:
            logger.warning(f"[{task['id']}] Metadata failed: {merr.decode()[:200]}"); os.rename(encoded, name)
    except Exception as e:
        logger.error(f"[{task['id']}] Metadata error: {e}")
        if os.path.exists(encoded): os.rename(encoded, name)

    # ---- THUMB ----
    thumb = None; thumb_id = await codeflixbots.get_thumbnail(user_id)
    if thumb_id:
        try: thumb = await client.download_media(thumb_id, file_name=f"thumb_{task['id']}.jpg")
        except: pass

    # ---- CAPTION ----
    caption_format = await codeflixbots.get_caption_format(user_id)
    if caption_format == "as_original": caption = msg.caption or name
    else:
        custom = await codeflixbots.get_caption(user_id)
        caption = custom if custom else name

    # ---- UPLOAD ----
    await progress_msg.edit("📤 Uploading...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{task['id']}|{user_id}")]]))
    while True:
        if cancel_tasks.get(task['id']):
            await progress_msg.edit("❌ Cancelled"); _cleanup_files([file_path, name, thumb, wm_image_path]); return
        try:
            st = time.time(); media_pref = await codeflixbots.get_media_preference(user_id)
            if media_pref == "video":
                await client.send_video(chat_id=user_id, video=name, caption=caption, thumb=thumb,
                    progress=progress_for_pyrogram, progress_args=("📤 Uploading...", progress_msg, st, f"cancel|{task['id']}|{user_id}"))
            else:
                await client.send_document(chat_id=user_id, document=name, caption=caption, thumb=thumb,
                    progress=progress_for_pyrogram, progress_args=("📤 Uploading...", progress_msg, st, f"cancel|{task['id']}|{user_id}"))
            break
        except FloodWait as e: await asyncio.sleep(e.value)

    await codeflixbots.increment_task_count(user_id, "encode")
    await progress_msg.delete()
    _cleanup_files([file_path, name, thumb, wm_image_path])

async def _drain(stream):
    try:
        while True:
            line = await stream.readline()
            if not line: break
    except asyncio.CancelledError: pass
    except: pass

def _cleanup_files(files):
    for f in files:
        try:
            if f and os.path.exists(f): os.remove(f)
        except: pass
