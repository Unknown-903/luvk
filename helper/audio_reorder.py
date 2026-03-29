"""
Shared audio reorder utility.
Import and use in encode.py, compress.py, merge.py, file_rename.py.

Usage:
    from helper.audio_reorder import probe_and_reorder_audio

    # In your process function, after downloading the file:
    audio_map, file_path = await probe_and_reorder_audio(
        client, file_path, user_id, task_id, progress_msg, timeout=300
    )
    # audio_map = list of original stream indices in user's chosen order
    # Use audio_map to build ffmpeg -map commands
"""
import os
import json
import asyncio
import subprocess
import logging

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait

logger = logging.getLogger(__name__)

# Global state for audio reorder across all plugins
_reorder_events = {}   # key -> asyncio.Event
_reorder_data = {}     # key -> {"streams": [...], "order": [...]}
_reorder_cancelled = {}


def _get_audio_streams(file_path):
    """Probe audio streams from file."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index,codec_name,channels:stream_tags=language,title",
             "-of", "json", file_path],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        return data.get("streams", [])
    except:
        return []


def _build_text(streams, order):
    """Build numbered audio track display."""
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
    text += "💡 Tap track → moves to #1 (default)"
    return text


def _build_buttons(streams, order, key, user_id):
    """Build inline buttons for reordering."""
    buttons = []
    for i, idx in enumerate(order):
        s = streams[idx]
        tags = s.get("tags", {})
        lang = tags.get("language", "und").title()
        title = tags.get("title", "")
        label = f"{'🔊 ' if i==0 else ''}{title or lang}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"areorder|{key}|{idx}")])
    buttons.append([
        InlineKeyboardButton("✅ Continue", callback_data=f"areorder_done|{key}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"areorder_cancel|{key}|{user_id}"),
    ])
    return InlineKeyboardMarkup(buttons)


def build_audio_map_args(streams, order):
    """Convert reorder result into ffmpeg -map arguments.
    Returns list like ["-map", "0:1", "-map", "0:2", "-map", "0:3"]
    """
    args = []
    for idx in order:
        if idx < len(streams):
            original_index = streams[idx]["index"]
            args += ["-map", f"0:{original_index}"]
    return args


async def probe_and_reorder_audio(client, file_path, user_id, task_id, progress_msg, timeout=300):
    """
    Probe audio streams. If >1, show reorder UI and wait.
    Returns (streams, order) tuple.
    - streams: list of stream dicts from ffprobe
    - order: list of indices in user's chosen order
    
    If only 1 or 0 streams, returns immediately with default order.
    """
    streams = _get_audio_streams(file_path)
    order = list(range(len(streams)))

    if len(streams) <= 1:
        return streams, order

    key = str(task_id)
    _reorder_data[key] = {"streams": streams, "order": order}
    _reorder_events[key] = asyncio.Event()
    _reorder_cancelled[key] = False

    text = _build_text(streams, order)
    buttons = _build_buttons(streams, order, key, user_id)

    try:
        await progress_msg.edit(text, reply_markup=buttons)
    except:
        pass

    # Wait for user action
    try:
        await asyncio.wait_for(_reorder_events[key].wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            await progress_msg.edit("⏰ Audio reorder timed out. Using default order.")
        except:
            pass

    final_order = _reorder_data.get(key, {}).get("order", order)
    cancelled = _reorder_cancelled.get(key, False)

    # Cleanup
    _reorder_data.pop(key, None)
    _reorder_events.pop(key, None)
    _reorder_cancelled.pop(key, None)

    if cancelled:
        return streams, None  # None signals cancellation

    return streams, final_order


def handle_reorder_move(key, stream_idx):
    """Called by callback handler when user taps a track."""
    data = _reorder_data.get(key)
    if not data:
        return None, None
    order = data["order"]
    streams = data["streams"]
    if stream_idx in order:
        order.remove(stream_idx)
        order.insert(0, stream_idx)
    text = _build_text(streams, order)
    buttons = _build_buttons(streams, order, key, data.get("user_id", 0))
    return text, buttons


def handle_reorder_done(key):
    """Called by callback handler when user clicks Continue."""
    event = _reorder_events.get(key)
    if event:
        event.set()


def handle_reorder_cancel(key):
    """Called by callback handler when user clicks Cancel."""
    _reorder_cancelled[key] = True
    event = _reorder_events.get(key)
    if event:
        event.set()


# ================= PYROGRAM CALLBACK HANDLERS =================
# These must be registered by importing this module in a plugin file
# that uses @Client.on_callback_query

from pyrogram import Client, filters

@Client.on_callback_query(filters.regex(r"^areorder\|"))
async def _areorder_move_cb(client, query):
    parts = query.data.split("|")
    key = parts[1]
    stream_idx = int(parts[2])
    data = _reorder_data.get(key)
    if not data:
        return await query.answer("Session expired.", show_alert=True)
    order = data["order"]
    streams = data["streams"]
    if stream_idx in order:
        order.remove(stream_idx)
        order.insert(0, stream_idx)
    text = _build_text(streams, order)
    buttons = _build_buttons(streams, order, key, 0)
    try:
        await query.message.edit_text(text, reply_markup=buttons)
        await query.answer("🔊 Moved to #1")
    except:
        pass


@Client.on_callback_query(filters.regex(r"^areorder_done\|"))
async def _areorder_done_cb(client, query):
    key = query.data.split("|")[1]
    handle_reorder_done(key)
    await query.answer("✅ Continuing...")


@Client.on_callback_query(filters.regex(r"^areorder_cancel\|"))
async def _areorder_cancel_cb(client, query):
    parts = query.data.split("|")
    key = parts[1]
    handle_reorder_cancel(key)
    await query.answer("❌ Cancelled")
