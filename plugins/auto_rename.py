from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait
from helper.database import codeflixbots
from helper.auth import auth_chats
from helper.permissions import is_authorized_chat
import asyncio


# ================= AUTORENAME =================

@Client.on_message((filters.private | filters.group) & filters.command("autorename"))
async def auto_rename_command(client, message):

    # Group authorization check
    if message.chat.type in ["group", "supergroup"]:
        if not is_authorized_chat(message.chat.id):
            return await message.reply_text(
                "❌ **This group is not authorized.**\n"
                "Use `/auth` first."
            )

    user_id = message.from_user.id

    # Extract command argument
    command_parts = message.text.split(maxsplit=1)

    if len(command_parts) < 2 or not command_parts[1].strip():
        return await message.reply_text(
            "**✏️ A U T O  R E N A M E**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ **Please provide a rename format.**\n\n"
            "💡 **Example:**\n"
            "`/autorename Overflow [S{season}E{episode}] - [Dual] {quality}`\n\n"
            "📝 **Available Placeholders:**\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "  `{season}`   → Season number (e.g., `01`)\n"
            "  `{episode}`  → Episode number (e.g., `05`)\n"
            "  `{quality}`  → Quality (e.g., `1080p`, `720p`)\n"
            "  `{codec}`    → Codec info (e.g., `HEVC x265`)\n"
            "  `{audio}`    → Audio language (e.g., `Dual Audio`)\n"
            "  `{year}`     → Year (e.g., `2024`)\n"
            "  `{filename}` → Original filename (without ext)\n\n"
            "🔍 **Auto-detected patterns:**\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "  `S01E01` · `Season 1 Episode 5`\n"
            "  `1x05` · `Ep05` · `Episode 3`\n"
            "  `[S01E01]` · `S01-E05`\n"
            "  `- 03` (anime) · `Part 2`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    format_template = command_parts[1].strip()

    # Save template
    await codeflixbots.set_format_template(user_id, format_template)

    await message.reply_text(
        "✅ **Rename Template Saved!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 **Template:**\n`{format_template}`\n\n"
        "📦 Now send files to rename.\n"
        "Use `/select 1-12` to set episode range."
    )
