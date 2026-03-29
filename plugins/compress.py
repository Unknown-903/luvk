import os
import sys
import time
import asyncio
import logging
from collections import deque

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

from helper.utils import progress_for_pyrogram
from helper.auth import auth_chats
from helper.database import codeflixbots
from helper.permissions import is_owner, is_admin as _perm_is_admin
from config import Config
from helper.audio_reorder import probe_and_reorder_audio, build_audio_map_args

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= ADMIN CHECK =================

def is_admin(user_id):
    return user_id == Config.OWNER_ID or _perm_is_admin(user_id)

# ================= COMPRESS LEVELS =================

COMPRESS_LEVELS = {
    "low": {
        "label": "🟢 Low",
        "ratio": 0.75,   # original size ka 75% — ~25% smaller
        "desc": "~25% smaller · best quality"
    },
    "medium": {
        "label": "🟡 Medium",
        "ratio": 0.55,   # ~45% smaller
        "desc": "~45% smaller · good quality"
    },
    "high": {
        "label": "🟠 High",
        "ratio": 0.38,   # ~62% smaller
        "desc": "~60% smaller · decent quality"
    },
    "best": {
        "label": "🔴 Best",
        "ratio": 0.25,   # ~75% smaller
        "desc": "~75% smaller · max compression"
    },
}


def get_video_duration(file_path):
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             file_path],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except:
        return None


def get_video_resolution(file_path):
    """Video resolution detect karo — bitrate floor ke liye"""
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0",
             file_path],
            capture_output=True, text=True, timeout=30
        )
        parts = result.stdout.strip().split(",")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except:
        pass
    return None, None


def get_resolution_floor(width, height):
    """Resolution se minimum bitrate floor nikalo"""
    if height is None:
        return 300
    if height <= 480:
        return 350
    elif height <= 720:
        return 700
    elif height <= 1080:
        return 1400
    else:
        return 3000


def calc_compress_bitrate(file_size_bytes, duration_sec, ratio, width=None, height=None, audio_kbps=128):
    """Original file size aur ratio se target bitrate nikalo — floor enforce karo"""
    target_bytes = file_size_bytes * ratio
    target_bits = target_bytes * 8
    total_kbps = (target_bits / duration_sec) / 1000
    video_kbps = int(total_kbps - audio_kbps)

    # Resolution-aware floor
    floor = get_resolution_floor(width, height)
    video_kbps = max(video_kbps, floor)

    # maxrate hamesha target se 40% zyada — kabhi target se kam nahi
    max_kbps = int(video_kbps * 1.4)
    return video_kbps, max_kbps

# ================= QUEUE =================

compress_queue = asyncio.Queue()
queue_list = deque()
active_tasks = {}
workers_started = False
cancel_tasks = {}
compress_wait = {}  # user_id -> {"msg": message}

# ================= WORKER =================

async def start_workers(client):
    global workers_started
    if workers_started:
        return
    workers_started = True
    asyncio.create_task(worker(client))


async def worker(client):
    while True:
        task = await compress_queue.get()
        active_tasks[task["id"]] = task
        try:
            await run_compress(client, task)
        except Exception as e:
            logger.error(f"Worker error: {e}")
        active_tasks.pop(task["id"], None)
        try:
            queue_list.remove(task)
        except:
            pass
        compress_queue.task_done()


# ================= /compress COMMAND =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.command("compress") &
    filters.reply
)
async def compress_cmd(client, message):
    user_id = message.from_user.id

    # Sirf owner aur admins use kar sakte hain
    if not is_admin(user_id):
        await message.reply_text("❌ Sirf owner aur admins use kar sakte hain")
        return

    # Group mein auth check
    if message.chat.type in ["group", "supergroup"]:
        if message.chat.id not in auth_chats:
            await message.reply_text("❌ This group is not authorized")
            return

    replied = message.reply_to_message

    if not (replied.video or replied.document):
        await message.reply_text("❌ Reply to a video or file")
        return

    is_group = message.chat.type in ["group", "supergroup"]
    compress_wait[user_id] = {"msg": replied, "is_group": is_group}

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Low", callback_data=f"compress_level|{user_id}|low"),
            InlineKeyboardButton("🟡 Medium", callback_data=f"compress_level|{user_id}|medium"),
        ],
        [
            InlineKeyboardButton("🟠 High", callback_data=f"compress_level|{user_id}|high"),
            InlineKeyboardButton("🔴 Best", callback_data=f"compress_level|{user_id}|best"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"compress_cancel_pre|{user_id}"),
        ]
    ])

    dm_note = "\n\n📩 _Result will be sent to your DM_" if is_group else ""

    await message.reply_text(
        "🗜️ **Video Compressor**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🟢 **Low** — ~25% smaller · best quality\n"
        "🟡 **Medium** — ~45% smaller · good quality\n"
        "🟠 **High** — ~60% smaller · decent quality\n"
        "🔴 **Best** — ~75% smaller · max compression\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 **Select compression level:**{dm_note}",
        reply_markup=buttons
    )

    await start_workers(client)


# ================= LEVEL SELECT =================

@Client.on_callback_query(filters.regex("^compress_level"))
async def compress_level_select(client, query):
    _, user_id, level = query.data.split("|")
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    data = compress_wait.pop(user_id, None)
    if not data:
        await query.answer("Session expired. Send /compress again.", show_alert=True)
        return

    level_info = COMPRESS_LEVELS[level]
    task = {
        "id": int(time.time() * 1000),
        "user": user_id,
        "level": level,
        "ratio": level_info["ratio"],
        "label": level_info["label"],
        "msg": data["msg"],
        "name": query.from_user.first_name,
        "is_group": data.get("is_group", False),
    }

    queue_list.append(task)
    cancel_tasks[task["id"]] = False

    pos = compress_queue.qsize() + 1
    await query.message.edit_text(
        f"📥 Added to Queue\n\n"
        f"{level_info['label']} — {level_info['desc']}\n"
        f"📌 Position: {pos}"
    )

    await compress_queue.put(task)


# ================= PRE-CANCEL =================

@Client.on_callback_query(filters.regex("^compress_cancel_pre"))
async def compress_cancel_pre(client, query):
    _, user_id = query.data.split("|")
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    compress_wait.pop(user_id, None)
    await query.message.edit_text("❌ Compress cancelled.")


# ================= CANCEL =================

@Client.on_callback_query(filters.regex("^compress_cancel[|]"))
async def compress_cancel(client, query):
    _, task_id, user_id = query.data.split("|")
    task_id = int(task_id)
    user_id = int(user_id)
    caller_id = query.from_user.id

    # Task owner — cancel kar sakta hai
    if caller_id == user_id:
        pass
    # Owner — kisi ka bhi cancel kar sakta hai
    elif caller_id == Config.OWNER_ID:
        pass
    # Admin — sirf apna cancel kar sakta hai, dusre admin ka nahi
    else:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    cancel_tasks[task_id] = True
    await query.answer("❌ Cancelling...")


# ================= /ctasks COMMAND =================

@Client.on_message(
    (filters.private | filters.group) & filters.command("ctasks")
)
async def compress_tasks_cmd(client, message):
    if not is_admin(message.from_user.id):
        return

    if not active_tasks and compress_queue.empty():
        return await message.reply_text("✅ No active compress tasks")

    text = "🗜️ **Compress Tasks**\n\n"

    for task_id, task in active_tasks.items():
        text += (
            f"⚙️ **Running**\n"
            f"👤 User: `{task['user']}`\n"
            f"📊 Level: {task['label']}\n"
            f"🆔 ID: `{task_id}`\n\n"
        )

    if not compress_queue.empty():
        text += f"📦 Queue: `{compress_queue.qsize()}` pending\n"

    await message.reply_text(text)


# ================= RUN COMPRESS =================

async def run_compress(client, task):
    msg = task["msg"]
    user_id = task["user"]
    ratio = task["ratio"]
    label = task["label"]
    task_id = task["id"]
    ext = await codeflixbots.get_video_extension(user_id) or "mkv"
    ext = f".{ext.lstrip('.')}"

    cancel_btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data=f"compress_cancel|{task_id}|{user_id}")]]
    )

    os.makedirs("downloads", exist_ok=True)
    download = f"downloads/comp_in_{task_id}.mkv"
    output = f"downloads/comp_out_{task_id}{ext}"
    file_path = None
    thumb = None

    try:
        # ---------------- DOWNLOAD ----------------
        progress_msg = await msg.reply_text(
            "📥 Downloading...",
            reply_markup=cancel_btn
        )

        start_time = time.time()
        logger.info(f"[{task_id}] Compress download started | user={user_id}")

        file_path = await client.download_media(
            msg,
            file_name=download,
            progress=progress_for_pyrogram,
            progress_args=("📥 Downloading...", progress_msg, start_time)
        )

        logger.info(f"[{task_id}] Download complete: {file_path}")

        if cancel_tasks.get(task_id):
            await progress_msg.edit("❌ Download Cancelled")
            return


        # ---------------- AUDIO REORDER ----------------
        streams, order = await probe_and_reorder_audio(
            client, file_path, user_id, task_id, progress_msg, timeout=300
        )
        if order is None:  # User cancelled
            return

        # ---------------- SIZE + DURATION + RESOLUTION ----------------
        orig_size = os.path.getsize(file_path)
        duration = get_video_duration(file_path)
        width, height = get_video_resolution(file_path)
        logger.info(f"[{task_id}] Resolution={width}x{height} | orig={round(orig_size/1024/1024,1)}MB")

        if duration and duration > 0:
            video_kbps, max_kbps = calc_compress_bitrate(orig_size, duration, ratio, width, height)
            logger.info(f"[{task_id}] Duration={duration:.1f}s | bitrate={video_kbps}k | max={max_kbps}k")
            use_bitrate = True
        else:
            logger.warning(f"[{task_id}] Duration detect nahi hui, CRF fallback")
            crf_map = {"low": 26, "medium": 28, "high": 31, "best": 35}
            fallback_crf = crf_map.get(task["level"], 28)
            use_bitrate = False

        # ---------------- COMPRESS ----------------
        await progress_msg.edit(
            f"🗜️ Compressing... {label}\n\n⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡ 0%",
            reply_markup=cancel_btn
        )

        # Compress level ke hisaab se scale — high/best pe resolution bhi ghataao speed ke liye
        # Audio map from reorder
        audio_args = build_audio_map_args(streams, order) if streams else ["-map", "0:a?"]

        scale_map = {
            "low":    None,          # original resolution rakho
            "medium": None,          # original resolution rakho
            "high":   "1280:720",    # 720p pe le aao
            "best":   "854:480",     # 480p pe le aao
        }
        scale = scale_map.get(task["level"], None)
        vf_filter = f"scale={scale}:flags=bilinear" if scale else None

        def build_cmd(extra_video_args):
            base = [
                "ffmpeg",
                "-nostdin",
                "-threads", "4",
                "-i", file_path,
                "-map", "0:v",
            ] + audio_args + [
                "-map", "0:s?",
            ]
            if vf_filter:
                base += ["-vf", vf_filter]
            base += [
                "-c:v", "libx265",
                "-preset", "ultrafast",
            ]
            base += extra_video_args
            base += [
                "-x265-params", "log-level=error:aq-mode=0:no-sao=1:no-deblock=1",
                "-c:a", "aac",
                "-b:a", "128k",
                "-c:s", "copy",
                "-stats",
                "-y",
                output
            ]
            return base

        if use_bitrate:
            cmd = build_cmd([
                "-b:v", f"{video_kbps}k",
                "-maxrate", f"{max_kbps}k",
                "-bufsize", f"{max_kbps * 2}k",
            ])
        else:
            cmd = build_cmd(["-crf", str(fallback_crf)])

        logger.info(f"[{task_id}] Compress started | level={task['level']}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )

        duration_sec = duration if duration and duration > 0 else 0
        last_edit = 0
        comp_progress = 0
        _editing = False

        async def safe_edit(text):
            nonlocal _editing, last_edit
            if _editing:
                return
            _editing = True
            try:
                await progress_msg.edit(text, reply_markup=cancel_btn)
                last_edit = time.time()
            except FloodWait as e:
                last_edit = time.time() + e.value
            except:
                pass
            finally:
                _editing = False

        import re as _re
        time_pattern = _re.compile(r"time=\s*(\d+):(\d+):(\d+)\.(\d+)")

        while True:
            if cancel_tasks.get(task_id):
                process.kill()
                await progress_msg.edit("❌ Compress Cancelled")
                return

            try:
                line = await asyncio.wait_for(process.stderr.readline(), timeout=60)
            except asyncio.TimeoutError:
                break

            if not line:
                break

            text = line.decode("utf-8", errors="ignore")

            # stderr se time= parse karo — har ffmpeg version pe kaam karta hai
            m = time_pattern.search(text)
            if m and duration_sec > 0:
                h, mi, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                elapsed_sec = h * 3600 + mi * 60 + s + cs / 100
                comp_progress = min(int(elapsed_sec * 100 / duration_sec), 99)

                now = time.time()
                if now - last_edit >= 8:
                    last_edit = now
                    filled = "⬢" * (comp_progress // 10)
                    empty = "⬡" * (10 - comp_progress // 10)
                    asyncio.create_task(safe_edit(
                        f"🗜️ Compressing... {label}\n\n{filled}{empty} {comp_progress}%"
                    ))

        try:
            await asyncio.wait_for(process.wait(), timeout=120)
        except asyncio.TimeoutError:
            process.kill()

        logger.info(f"[{task_id}] Compress complete")

        try:
            await progress_msg.edit(f"🗜️ Compressing... {label}\n\n⬢⬢⬢⬢⬢⬢⬢⬢⬢⬢ 100% ✅")
        except:
            pass

        if not os.path.exists(output):
            await progress_msg.edit("❌ Compress failed — output not found")
            return

        new_size = os.path.getsize(output)
        saved = orig_size - new_size
        saved_pct = round((saved / orig_size) * 100, 1) if orig_size else 0

        # Agar compressed bada ho gaya toh original use karo
        if new_size >= orig_size:
            logger.warning(f"[{task_id}] Compressed ({new_size}) >= original ({orig_size}) — original use kar raha hoon")
            os.remove(output)
            # Original ko hi output maano
            output = file_path
            new_size = orig_size
            saved = 0
            saved_pct = 0
            already_compressed_note = "\n⚠️ _File already compressed — original bheja gaya_"
        else:
            already_compressed_note = ""

        # ---------------- RENAME ----------------
        if msg.document and msg.document.file_name:
            name = msg.document.file_name
        elif msg.video and msg.video.file_name:
            name = msg.video.file_name
        else:
            name = f"compressed_{task_id}{ext}"

        name = os.path.splitext(name)[0] + ext

        # ---------------- METADATA ----------------
        title = await codeflixbots.get_title(user_id) or ""
        author = await codeflixbots.get_author(user_id) or ""
        artist = await codeflixbots.get_artist(user_id) or ""

        meta_file = f"downloads/meta_{task_id}{ext}"
        meta_cmd = [
            "ffmpeg",
            "-i", output,
            "-map", "0",
            "-c", "copy",
            "-metadata", f"title={title}",
            "-metadata", f"author={author}",
            "-metadata", f"artist={artist}",
            "-y", meta_file
        ]

        await progress_msg.edit("🏷️ Applying metadata...")
        meta_proc = await asyncio.create_subprocess_exec(
            *meta_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        try:
            await asyncio.wait_for(meta_proc.wait(), timeout=120)
        except asyncio.TimeoutError:
            meta_proc.kill()

        if os.path.exists(meta_file) and os.path.getsize(meta_file) > 0:
            if output != file_path:  # original delete mat karo
                os.remove(output)
            output_final = meta_file
        else:
            output_final = output

        # ---------------- THUMB ----------------
        thumb_id = await codeflixbots.get_thumbnail(user_id)
        if thumb_id:
            try:
                thumb = await client.download_media(
                    thumb_id,
                    file_name=f"downloads/thumb_{task_id}.jpg"
                )
            except:
                thumb = None

        # ---------------- UPLOAD ----------------
        caption = (
            f"🗜️ **Compressed** — {label}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Original: `{round(orig_size/1024/1024, 2)} MB`\n"
            f"📦 Compressed: `{round(new_size/1024/1024, 2)} MB`\n"
            f"✅ Saved: `{round(saved/1024/1024, 2)} MB ({saved_pct}%)`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 `{name}`"
            f"{already_compressed_note}"
        )

        await progress_msg.edit("📤 Uploading...", reply_markup=cancel_btn)
        start_time = time.time()
        logger.info(f"[{task_id}] Upload started")

        while True:
            if cancel_tasks.get(task_id):
                await progress_msg.edit("❌ Upload Cancelled")
                return
            try:
                await client.send_document(
                    chat_id=user_id,
                    document=output_final,
                    file_name=name,
                    caption=caption,
                    thumb=thumb if thumb else None,
                    progress=progress_for_pyrogram,
                    progress_args=("📤 Uploading...", progress_msg, start_time)
                )
                break
            except FloodWait as e:
                await asyncio.sleep(e.value)

        logger.info(f"[{task_id}] Task complete | saved={saved_pct}%")
        await codeflixbots.increment_task_count(user_id, "compress")
        await progress_msg.delete()

    except Exception as e:
        logger.error(f"[{task_id}] Error: {e}")
        try:
            await progress_msg.edit(f"❌ Error: {str(e)[:200]}")
        except:
            pass

    finally:
        cancel_tasks.pop(task_id, None)
        for f in [file_path, output, f"downloads/meta_{task_id}{ext}", thumb]:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except:
                pass
