"""
Leaderboard system — tracks all bot activities.
Multi-category: rename, encode, compress, merge, upscale.
"""
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait
from helper.database import codeflixbots
from config import Config
import asyncio

CATEGORIES = {
    "all": {"emoji": "🏆", "label": "Overall"},
    "rename": {"emoji": "✏️", "label": "Rename"},
    "encode": {"emoji": "🎬", "label": "Encode"},
    "compress": {"emoji": "🗜️", "label": "Compress"},
    "merge": {"emoji": "🔀", "label": "Merge"},
    "upscale": {"emoji": "🔍", "label": "Upscale"},
}

MEDALS = ["🥇", "🥈", "🥉"]


def _build_leaderboard_text(top_users, category="all", caller_rank=None):
    cat = CATEGORIES.get(category, CATEGORIES["all"])
    text = f"{cat['emoji']} **{cat['label']} Leaderboard**\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if not top_users:
        text += "📭 _No activity yet!_\n"
    else:
        for i, user in enumerate(top_users):
            uid = user["_id"]
            username = user.get("username", None)
            
            if category == "all":
                count = user.get("total_tasks", 0)
            else:
                count = user.get("task_counts", {}).get(category, 0)
            
            medal = MEDALS[i] if i < 3 else f"  {i+1}."
            name = f"@{username}" if username else f"`{uid}`"
            text += f"{medal} {name} — **{count}** tasks\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━"
    
    if caller_rank:
        text += f"\n📍 **Your Rank:** #{caller_rank}"
    
    text += "\n💡 Keep processing to climb the ranks!"
    
    return text


def _build_category_buttons(current="all", user_id=None):
    uid = user_id or 0
    buttons = []
    row1 = []
    row2 = []
    
    for key, cat in CATEGORIES.items():
        if key == current:
            label = f"• {cat['emoji']} {cat['label']} •"
        else:
            label = f"{cat['emoji']} {cat['label']}"
        
        btn = InlineKeyboardButton(label, callback_data=f"lb|{key}|{uid}")
        
        if key in ["all", "rename", "encode"]:
            row1.append(btn)
        else:
            row2.append(btn)
    
    buttons = [row1, row2]
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"lb|{current}|{uid}")])
    
    return InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command(["leaderboard", "top", "lb"]))
async def leaderboard_cmd(client, message):
    user_id = message.from_user.id
    top_users = await codeflixbots.get_leaderboard(limit=10)
    caller_rank = await codeflixbots.get_user_rank(user_id)
    
    text = _build_leaderboard_text(top_users, "all", caller_rank)
    buttons = _build_category_buttons("all", user_id)
    
    if Config.LEADERBOARD_PIC:
        await message.reply_photo(
            photo=Config.LEADERBOARD_PIC,
            caption=text,
            reply_markup=buttons
        )
    else:
        await message.reply_text(text, reply_markup=buttons)


@Client.on_callback_query(filters.regex(r"^lb\|"))
async def leaderboard_callback(client, query: CallbackQuery):
    parts = query.data.split("|")
    if len(parts) != 3:
        return await query.answer("Invalid data", show_alert=True)
    
    _, category, owner_id = parts
    caller_id = query.from_user.id
    
    if category == "all":
        top_users = await codeflixbots.get_leaderboard(limit=10)
    else:
        top_users = await codeflixbots.get_leaderboard(limit=10, task_type=category)
    
    caller_rank = await codeflixbots.get_user_rank(caller_id)
    text = _build_leaderboard_text(top_users, category, caller_rank)
    buttons = _build_category_buttons(category, caller_id)
    
    try:
        await query.message.edit_text(text, reply_markup=buttons)
        await query.answer(f"📊 {CATEGORIES[category]['label']}")
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        await query.answer("ℹ️ No changes.", show_alert=False)


@Client.on_message(filters.command(["myrank", "mystats"]))
async def my_rank_cmd(client, message):
    user_id = message.from_user.id
    counts = await codeflixbots.get_task_counts(user_id)
    rank = await codeflixbots.get_user_rank(user_id)
    
    rename = counts.get("rename", 0)
    encode = counts.get("encode", 0)
    compress = counts.get("compress", 0)
    merge = counts.get("merge", 0)
    upscale = counts.get("upscale", 0)
    total = rename + encode + compress + merge + upscale
    
    rank_text = f"#{rank}" if rank else "Unranked"
    
    text = (
        f"📊 **Your Stats**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📍 **Rank:** {rank_text}\n"
        f"📦 **Total:** `{total}` tasks\n\n"
        f"  ✏️ Rename:   `{rename}`\n"
        f"  🎬 Encode:   `{encode}`\n"
        f"  🗜️ Compress: `{compress}`\n"
        f"  🔀 Merge:    `{merge}`\n"
        f"  🔍 Upscale:  `{upscale}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Use /leaderboard to see top users!"
    )
    
    await message.reply_text(text)
