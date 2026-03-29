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
from helper.database import codeflixbots
from helper.permissions import is_admin as _perm_is_admin
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

# ================= MERGE QUALITY =================

MERGE_QUALITY = {
    "copy": {
        "label": "⚡ Fast Copy",
        "desc": "No re-encode · fastest · same quality",
        "encode": False,
    },
    "low": {
        "label": "🟢 Low Compress",
        "desc": "~10% smaller · best quality",
        "encode": True,
        "crf": 26,
    },
    "medium": {
        "label": "🟡 Medium Compress",
        "desc": "~30% smaller · good quality",
        "encode": True,
        "crf": 28,
    },
    "high": {
        "label": "🟠 High Compress",
        "desc": "~50% smaller · decent quality",
        "encode": True,
        "crf": 31,
    },
    "best": {
        "label": "🔴 Best Compress",
        "desc": "~70% smaller · max compression",
        "encode": True,
        "crf": 35,
    },
}

# Encode quality options (resolution + CRF)
ENCODE_QUALITY = {
    "480p":  {"scale": "854:480",   "crf": 26, "label": "🎬 480p"},
    "720p":  {"scale": "1280:720",  "crf": 24, "label": "📺 720p"},
    "1080p": {"scale": "1920:1080", "crf": 22, "label": "🔥 1080p"},
    "4k":    {"scale": "3840:2160", "crf": 20, "label": "💎 4K"},
}

# Funny jokes for progress bar
MERGE_JOKES = [
    "☕ Server chai pi raha hai, thoda ruko...",
    "🐢 FFmpeg ka kachua race mein hai...",
    "🔧 Bits aur bytes ko suljha rahe hain...",
    "🎭 CPU ko motivational speech de rahe hain...",
    "🍕 Files merge ho rahi hain, pizza order karo...",
    "🧩 Video ke tukde jod rahe hain, patience raho...",
    "🚀 Rocket ki speed se process ho raha hai... (nahi)...",
    "😅 Bot thaka nahi hai, bas slow hai...",
    "🎪 Data circus mein juggling ho rahi hai...",
    "⏳ Ek minute mein ho jayega... (shayad)...",
    "🤖 AI mehnat kar raha hai, chai de do...",
    "🌀 Files ka chakravyuh tod rahe hain...",
]

# ================= STATE =================

merge_sessions = {}   # user_id -> {"files": [], "msg_ids": []}
merge_pending = {}    # user_id -> task (waiting for rename/encode input)
merge_queue = asyncio.Queue()
queue_list = deque()
active_tasks = {}
workers_started = False
cancel_tasks = {}
_upload_edit_times = {}  # upload progress throttle

# ================= WORKER =================

async def start_workers(client):
    global workers_started
    if workers_started:
        return
    workers_started = True
    asyncio.create_task(worker(client))


async def worker(client):
    while True:
        task = await merge_queue.get()
        active_tasks[task["id"]] = task
        try:
            await run_merge(client, task)
        except Exception as e:
            logger.error(f"Merge worker error: {e}")
        active_tasks.pop(task["id"], None)
        try:
            queue_list.remove(task)
        except:
            pass
        merge_queue.task_done()


# ================= /merge COMMAND =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.command("merge")
)
async def merge_cmd(client, message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.reply_text("❌ Sirf owner aur admins use kar sakte hain")
        return

    if user_id in merge_sessions:
        count = len(merge_sessions[user_id]["files"])
        await message.reply_text(
            f"⚠️ Already in merge session!\n\n"
            f"📦 Files collected: `{count}`\n\n"
            f"Send more files or /done to merge\n"
            f"Use /mergecancel to cancel session"
        )
        return

    merge_sessions[user_id] = {
        "files": [],
        "chat_id": message.chat.id,
        "is_group": message.chat.type in ["group", "supergroup"],
    }

    await message.reply_text(
        "🎬 **Merge Session Started**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📤 Ab apni video files bhejo ek ek karke\n"
        "✅ Sab files bhejne ke baad `/done` bhejo\n"
        "❌ Cancel karne ke liye `/mergecancel` bhejo\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ _Files same format/resolution mein honi chahiye_"
    )
    await start_workers(client)


# ================= COLLECT FILES =================

@Client.on_message(
    (filters.private | filters.group) &
    (filters.video | filters.document),
    group=2
)
async def collect_merge_files(client, message):
    user_id = message.from_user.id

    if user_id not in merge_sessions:
        return

    if not is_admin(user_id):
        return

    file = message.video or message.document
    if not file:
        return

    # Document ho toh check karo video/audio file hai
    if message.document:
        name = message.document.file_name or ""
        if not any(name.lower().endswith(ext) for ext in
                   [".mkv", ".mp4", ".avi", ".mov", ".flv", ".ts", ".m4v",
                    ".mp3", ".aac", ".m4a", ".opus", ".flac", ".ogg"]):
            return

    session = merge_sessions[user_id]
    session["files"].append(message)
    count = len(session["files"])

    await message.reply_text(
        f"✅ File `{count}` added\n\n"
        f"📦 Total: `{count}` file(s)\n"
        f"Send more or /done to merge"
    )


# ================= /done COMMAND =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.command("done")
)
async def merge_done(client, message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    if user_id not in merge_sessions:
        await message.reply_text("❌ No active merge session\nSend /merge to start")
        return

    session = merge_sessions[user_id]
    files = session["files"]

    if len(files) < 2:
        await message.reply_text(
            f"❌ Kam se kam 2 files chahiye merge ke liye\n\n"
            f"Abhi sirf `{len(files)}` file hai"
        )
        return

    # Quality select karo
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Fast Copy", callback_data=f"merge_quality|{user_id}|copy"),
        ],
        [
            InlineKeyboardButton("🟢 Low", callback_data=f"merge_quality|{user_id}|low"),
            InlineKeyboardButton("🟡 Medium", callback_data=f"merge_quality|{user_id}|medium"),
        ],
        [
            InlineKeyboardButton("🟠 High", callback_data=f"merge_quality|{user_id}|high"),
            InlineKeyboardButton("🔴 Best", callback_data=f"merge_quality|{user_id}|best"),
        ],
        [
            InlineKeyboardButton("🎬 Encode 480p", callback_data=f"merge_quality|{user_id}|enc_480p"),
            InlineKeyboardButton("📺 Encode 720p", callback_data=f"merge_quality|{user_id}|enc_720p"),
        ],
        [
            InlineKeyboardButton("🔥 Encode 1080p", callback_data=f"merge_quality|{user_id}|enc_1080p"),
            InlineKeyboardButton("💎 Encode 4K", callback_data=f"merge_quality|{user_id}|enc_4k"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"merge_cancel_pre|{user_id}"),
        ]
    ])

    await message.reply_text(
        f"🎬 **Ready to Merge**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Files: `{len(files)}`\n\n"
        f"⚡ **Fast Copy** — No re-encode · fastest\n"
        f"🟢 **Low** — ~10% smaller · best quality\n"
        f"🟡 **Medium** — ~30% smaller · good quality\n"
        f"🟠 **High** — ~50% smaller · decent quality\n"
        f"🔴 **Best** — ~70% smaller · max compression\n"
        f"🎬 **Encode** — Re-encode to selected resolution\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 **Select quality:**",
        reply_markup=buttons
    )



# ================= /mergecancel COMMAND =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.command("mergecancel")
)
async def merge_cancel_cmd(client, message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        return

    if user_id not in merge_sessions:
        await message.reply_text("❌ No active merge session")
        return

    session = merge_sessions.pop(user_id)
    count = len(session["files"])
    await message.reply_text(
        f"❌ Merge session cancelled\n"
        f"📦 `{count}` file(s) discarded"
    )


# ================= QUALITY SELECT =================

@Client.on_callback_query(filters.regex("^merge_quality"))
async def merge_quality_select(client, query):
    _, user_id, quality = query.data.split("|")
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    session = merge_sessions.pop(user_id, None)
    if not session:
        await query.answer("Session expired. Send /merge again.", show_alert=True)
        return

    # Encode option handle karo
    if quality.startswith("enc_"):
        res = quality.replace("enc_", "")  # "480p", "720p" etc
        eq = ENCODE_QUALITY[res]
        quality_info = {
            "label": f"🎬 Encode {res.upper()}",
            "desc": f"Re-encode to {res}",
            "encode": True,
            "crf": eq["crf"],
            "scale": eq["scale"],
            "is_encode": True,
        }
    else:
        quality_info = MERGE_QUALITY[quality]
        quality_info["is_encode"] = False

    task = {
        "id": int(time.time() * 1000),
        "user": user_id,
        "files": session["files"],
        "quality": quality,
        "quality_info": quality_info,
        "is_group": session.get("is_group", False),
        "rename": None,
    }

    # Step 1: Rename puchho
    merge_pending[user_id] = task

    await query.message.edit_text(
        f"✏️ **Rename Merged File?**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Files: `{len(task['files'])}`\n"
        f"🎬 Quality: {quality_info['label']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️  Rename", callback_data=f"merge_rename|{user_id}|yes"),
                InlineKeyboardButton("⏭️  Skip", callback_data=f"merge_rename|{user_id}|skip"),
            ],
            [InlineKeyboardButton("❌  Cancel", callback_data=f"merge_cancel_pre|{user_id}")]
        ])
    )


# ================= RENAME STEP =================

@Client.on_callback_query(filters.regex("^merge_rename"))
async def merge_rename_cb(client, query):
    parts = query.data.split("|")
    _, user_id, action = parts
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    task = merge_pending.get(user_id)
    if not task:
        await query.answer("Session expired.", show_alert=True)
        return

    if action == "yes":
        # Rename input wait
        task["waiting_rename"] = True
        merge_pending[user_id] = task
        await query.message.edit_text(
            "✏️ **Enter New File Name**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📝 Naya naam bhejo\n"
            "Example: `My Merged Video`\n\n"
            "_(Extension automatically .mkv hogi)_\n"
            "━━━━━━━━━━━━━━━━━━━━",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭️  Skip Rename", callback_data=f"merge_rename|{user_id}|skip")]
            ])
        )
    else:
        # Skip rename — go to encode step
        task["waiting_rename"] = False
        task["rename"] = None
        merge_pending[user_id] = task
        await show_encode_step(query, user_id, task)


async def show_encode_step(query, user_id, task):
    quality_info = task["quality_info"]
    await query.message.edit_text(
        f"🎬 **Encode After Merge?**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Files: `{len(task['files'])}`\n"
        f"🗜️ Quality: {quality_info['label']}\n"
        f"✏️ Rename: `{task.get('rename') or 'Skip'}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎬  480p", callback_data=f"merge_encode|{user_id}|enc_480p"),
                InlineKeyboardButton("📺  720p", callback_data=f"merge_encode|{user_id}|enc_720p"),
            ],
            [
                InlineKeyboardButton("🔥  1080p", callback_data=f"merge_encode|{user_id}|enc_1080p"),
                InlineKeyboardButton("💎  4K",    callback_data=f"merge_encode|{user_id}|enc_4k"),
            ],
            [
                InlineKeyboardButton("⏭️  Skip Encode", callback_data=f"merge_encode|{user_id}|skip"),
            ],
            [InlineKeyboardButton("❌  Cancel", callback_data=f"merge_cancel_pre|{user_id}")]
        ])
    )


@Client.on_callback_query(filters.regex("^merge_encode"))
async def merge_encode_cb(client, query):
    parts = query.data.split("|")
    _, user_id, enc = parts
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    task = merge_pending.pop(user_id, None)
    if not task:
        await query.answer("Session expired.", show_alert=True)
        return

    # Apply encode quality if selected
    if enc != "skip" and enc.startswith("enc_"):
        res = enc.replace("enc_", "")
        eq = ENCODE_QUALITY[res]
        task["quality_info"] = {
            "label": f"🎬 Encode {res.upper()}",
            "desc": f"Re-encode to {res}",
            "encode": True,
            "crf": eq["crf"],
            "scale": eq["scale"],
            "is_encode": True,
        }
        task["quality"] = enc

    queue_list.append(task)
    cancel_tasks[task["id"]] = False

    pos = merge_queue.qsize() + 1
    rename_str = f"`{task.get('rename')}`" if task.get('rename') else "Default"
    enc_str = task["quality_info"]["label"]

    await query.message.edit_text(
        f"📥 **Added to Merge Queue**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Files: `{len(task['files'])}`\n"
        f"🎬 Quality: {enc_str}\n"
        f"✏️ Rename: {rename_str}\n"
        f"📌 Position: `{pos}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await merge_queue.put(task)


# ================= GET RENAME TEXT =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.text &
    ~filters.command(["merge", "done", "mergecancel", "encode", "compress",
                      "upscale", "select", "queue", "logs", "restart",
                      "status", "settings", "start", "help"]),
    group=3
)
async def merge_rename_input(client, message):
    user_id = message.from_user.id
    task = merge_pending.get(user_id)
    if not task or not task.get("waiting_rename"):
        return

    rename = message.text.strip()
    if not rename:
        await message.reply_text("❌ Empty naam — phir bhejo")
        return

    task["rename"] = rename
    task["waiting_rename"] = False
    merge_pending[user_id] = task

    # Show encode step via fake query-like edit
    await message.reply_text(
        f"✅ Rename set: `{rename}`\n\n"
        f"Ab encode option select karo 👇",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎬  480p", callback_data=f"merge_encode|{user_id}|enc_480p"),
                InlineKeyboardButton("📺  720p", callback_data=f"merge_encode|{user_id}|enc_720p"),
            ],
            [
                InlineKeyboardButton("🔥  1080p", callback_data=f"merge_encode|{user_id}|enc_1080p"),
                InlineKeyboardButton("💎  4K",    callback_data=f"merge_encode|{user_id}|enc_4k"),
            ],
            [
                InlineKeyboardButton("⏭️  Skip Encode", callback_data=f"merge_encode|{user_id}|skip"),
            ],
            [InlineKeyboardButton("❌  Cancel", callback_data=f"merge_cancel_pre|{user_id}")]
        ])
    )


# ================= PRE-CANCEL =================

@Client.on_callback_query(filters.regex("^merge_cancel_pre"))
async def merge_cancel_pre(client, query):
    _, user_id = query.data.split("|")
    user_id = int(user_id)

    if query.from_user.id != user_id:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    merge_sessions.pop(user_id, None)
    await query.message.edit_text("❌ Merge cancelled.")


# ================= TASK CANCEL =================

@Client.on_callback_query(filters.regex("^merge_cancel[|]"))
async def merge_cancel_task(client, query):
    _, task_id, user_id = query.data.split("|")
    task_id = int(task_id)
    user_id = int(user_id)
    caller_id = query.from_user.id

    # Task owner cancel kar sakta hai
    if caller_id == user_id:
        pass
    # Owner kisi ka bhi cancel kar sakta hai
    elif caller_id == Config.OWNER_ID:
        pass
    # Admin sirf apna cancel kar sakta hai
    else:
        await query.answer("❌ Ye tumhara task nahi hai!", show_alert=True)
        return

    cancel_tasks[task_id] = True
    await query.answer("❌ Cancelling...")


# ================= /mtasks COMMAND =================

@Client.on_message(
    (filters.private | filters.group) &
    filters.command("mtasks")
)
async def merge_tasks_cmd(client, message):
    if not is_admin(message.from_user.id):
        return

    if not active_tasks and merge_queue.empty():
        return await message.reply_text("✅ No active merge tasks")

    text = "🎬 **Merge Tasks**\n\n"
    for task_id, task in active_tasks.items():
        text += (
            f"⚙️ **Running**\n"
            f"👤 User: `{task['user']}`\n"
            f"📦 Files: `{len(task['files'])}`\n"
            f"🎬 Quality: {task['quality_info']['label']}\n"
            f"🆔 ID: `{task_id}`\n\n"
        )

    if not merge_queue.empty():
        text += f"📦 Queue: `{merge_queue.qsize()}` pending\n"

    await message.reply_text(text)


# ================= RUN MERGE =================

async def run_merge(client, task):
    user_id = task["user"]
    files = task["files"]
    task_id = task["id"]
    quality = task["quality"]
    quality_info = task["quality_info"]

    cancel_btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data=f"merge_cancel|{task_id}|{user_id}")]]
    )

    os.makedirs("downloads", exist_ok=True)
    downloaded = []
    progress_msg = None

    try:
        # ---------------- DOWNLOAD ALL FILES ----------------
        progress_msg = await files[0].reply_text(
            f"📥 Downloading files...\n\n0 / {len(files)} done",
            reply_markup=cancel_btn
        )

        for i, msg in enumerate(files):
            if cancel_tasks.get(task_id):
                await progress_msg.edit("❌ Cancelled")
                return

            dl_path = f"downloads/merge_{task_id}_{i}.mkv"
            start_time = time.time()

            try:
                await progress_msg.edit(
                    f"📥 Downloading file {i+1} / {len(files)}...",
                    reply_markup=cancel_btn
                )
            except:
                pass

            file_path = await client.download_media(
                msg,
                file_name=dl_path,
                progress=progress_for_pyrogram,
                progress_args=(f"📥 File {i+1}/{len(files)}", progress_msg, start_time)
            )

            if not file_path or not os.path.exists(file_path):
                await progress_msg.edit(f"❌ Download failed for file {i+1}")
                return

            downloaded.append(file_path)
            logger.info(f"[{task_id}] Downloaded {i+1}/{len(files)}: {file_path}")

        if cancel_tasks.get(task_id):
            await progress_msg.edit("❌ Cancelled")
            return

        logger.info(f"[{task_id}] All {len(downloaded)} files downloaded")

        # ---------------- CREATE CONCAT LIST ----------------
        concat_file = f"downloads/concat_{task_id}.txt"
        with open(concat_file, "w") as f:
            for path in downloaded:
                f.write(f"file '{os.path.abspath(path)}'\n")

        output = f"downloads/merged_{task_id}.mkv"

        # ---------------- MERGE ----------------
        await progress_msg.edit(
            f"🎬 Merging {len(files)} files...\n\n⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡ 0%",
            reply_markup=cancel_btn
        )

        if quality_info["encode"]:
            # Encode with H.265 — with or without scale
            vf_args = []
            if quality_info.get("is_encode") and "scale" in quality_info:
                vf_args = ["-vf", f"scale={quality_info['scale']}:flags=lanczos"]

            cmd = [
                "ffmpeg",
                "-progress", "pipe:1",
                "-nostats",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-map", "0",
            ] + vf_args + [
                "-c:v", "libx265",
                "-preset", "veryfast",
                "-crf", str(quality_info["crf"]),
                "-x265-params", "log-level=error",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ac", "2",
                "-c:s", "copy",
                "-y",
                output
            ]
        else:
            # Fast copy — no re-encode
            cmd = [
                "ffmpeg",
                "-progress", "pipe:1",
                "-nostats",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-map", "0",
                "-c", "copy",
                "-y",
                output
            ]

        logger.info(f"[{task_id}] Merge started | quality={quality}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        progress = 0
        last_edit = 0
        joke_idx = 0
        import random
        jokes = MERGE_JOKES.copy()
        random.shuffle(jokes)

        while True:
            if cancel_tasks.get(task_id):
                process.kill()
                await progress_msg.edit("❌ Merge Cancelled")
                return

            line = await process.stdout.readline()
            if not line:
                break

            text = line.decode("utf-8")
            if "out_time=" in text:
                progress = min(progress + 2, 100)
                now = time.time()
                if now - last_edit >= 8:
                    last_edit = now
                    filled = "⬢" * (progress // 10)
                    empty = "⬡" * (10 - progress // 10)
                    joke = jokes[joke_idx % len(jokes)]
                    joke_idx += 1
                    try:
                        await progress_msg.edit(
                            f"🎬 Merging... {quality_info['label']}\n\n"
                            f"{filled}{empty} {progress}%\n\n"
                            f"_{joke}_",
                            reply_markup=cancel_btn
                        )
                    except FloodWait as e:
                        last_edit = time.time() + e.value
                    except:
                        pass

        await process.wait()


        if not os.path.exists(output):
            await progress_msg.edit("❌ Merge failed — output not found")
            return

        logger.info(f"[{task_id}] Merge complete")

        try:
            await progress_msg.edit(
                f"🎬 Merging...\n\n⬢⬢⬢⬢⬢⬢⬢⬢⬢⬢ 100% ✅"
            )
        except:
            pass


        # ---------------- AUDIO REORDER ----------------
        streams, order = await probe_and_reorder_audio(
            client, output, user_id, task_id, progress_msg, timeout=300
        )
        if order is None:  # User cancelled
            return

        audio_args = build_audio_map_args(streams, order) if streams else ["-map", "0:a?"]

        # ---------------- METADATA ----------------
        title = await codeflixbots.get_title(user_id) or ""
        author = await codeflixbots.get_author(user_id) or ""
        artist = await codeflixbots.get_artist(user_id) or ""

        meta_file = f"downloads/meta_{task_id}.mkv"
        meta_cmd = [
            "ffmpeg",
            "-i", output,
            "-map", "0:v",
            ] + audio_args + [
            "-map", "0:s?",
            "-c", "copy",
            "-metadata", f"title={title}",
            "-metadata", f"author={author}",
            "-metadata", f"artist={artist}",
            "-metadata", "encoder=SharkToonsIndia",
            "-y", meta_file
        ]

        await progress_msg.edit("🗜️ Adding metadata...")
        meta_proc = await asyncio.create_subprocess_exec(
            *meta_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await meta_proc.wait()

        output_final = meta_file if os.path.exists(meta_file) else output

        # ---------------- THUMB ----------------
        thumb = None
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
        total_size = sum(os.path.getsize(f) for f in downloaded)
        merged_size = os.path.getsize(output_final)
        # Use rename if set
        rename = task.get("rename")
        if rename:
            name = rename.strip()
            if not name.lower().endswith(".mkv"):
                name = name + ".mkv"
        else:
            name = f"merged_{task_id}.mkv"

        caption = (
            f"🎬 **Merged** — {quality_info['label']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Files merged: `{len(files)}`\n"
            f"📦 Total input: `{round(total_size/1024/1024, 2)} MB`\n"
            f"📦 Output: `{round(merged_size/1024/1024, 2)} MB`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 `{name}`"
        )

        await progress_msg.edit(
            "📤 Uploading...",
            reply_markup=cancel_btn
        )

        start_time = time.time()
        logger.info(f"[{task_id}] Upload started")

        async def upload_progress(current, total, ud_type, message, start):
            """Upload progress with cancel button always visible"""
            now = time.time()
            diff = now - start
            if diff <= 0:
                return
            if current == total:
                return

            # Throttle — har 5 sec mein edit
            msg_id = message.id
            last = _upload_edit_times.get(msg_id, 0)
            if now - last < 5:
                return
            _upload_edit_times[msg_id] = now

            percentage = current * 100 / total if total else 0
            speed = current / diff if diff else 0
            eta = (total - current) / speed if speed else 0
            filled = "⬢" * int(percentage / 10)
            empty = "⬡" * (10 - int(percentage / 10))

            def fmt(size):
                for unit in ["B","KB","MB","GB"]:
                    if size < 1024:
                        return f"{round(size,2)} {unit}"
                    size /= 1024
                return f"{round(size,2)} TB"

            def tfmt(ms):
                s = int(ms/1000)
                m, s = divmod(s, 60)
                h, m = divmod(m, 60)
                return f"{h}h {m}m {s}s" if h else f"{m}m {s}s" if m else f"{s}s"

            text = (
                f"📤 Uploading...\n\n"
                f"{filled}{empty} {round(percentage,2)}%\n\n"
                f"📦 {fmt(current)} / {fmt(total)}\n"
                f"⚡ {fmt(speed)}/s\n"
                f"⏳ {tfmt(eta*1000)}"
            )
            try:
                await message.edit(
                    text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("❌ Cancel", callback_data=f"merge_cancel|{task_id}|{user_id}")]]
                    )
                )
            except FloodWait as e:
                _upload_edit_times[msg_id] = now + e.value
            except:
                pass

        while True:
            if cancel_tasks.get(task_id):
                await progress_msg.edit("❌ Upload Cancelled")
                return
            try:
                await client.send_document(
                    chat_id=user_id,  # hamesha DM
                    document=output_final,
                    file_name=name,
                    caption=caption,
                    thumb=thumb if thumb else None,
                    progress=upload_progress,
                    progress_args=("📤 Uploading...", progress_msg, start_time)
                )
                break
            except FloodWait as e:
                await asyncio.sleep(e.value)

        logger.info(f"[{task_id}] Merge task complete")
        await codeflixbots.increment_task_count(user_id, "merge")
        await progress_msg.delete()

    except Exception as e:
        logger.error(f"[{task_id}] Error: {e}")
        try:
            await progress_msg.edit(f"❌ Error: {str(e)[:200]}")
        except:
            pass

    finally:
        cancel_tasks.pop(task_id, None)
        # Cleanup all files
        all_files = downloaded + [
            f"downloads/concat_{task_id}.txt",
            f"downloads/merged_{task_id}.mkv",
            f"downloads/meta_{task_id}.mkv",
            f"downloads/thumb_{task_id}.jpg",
        ]
        for f in all_files:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except:
                pass
