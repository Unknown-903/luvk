import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pyrogram.errors import FloodWait

from helper.database import codeflixbots
from config import Config


class Txt(object):

    START_TXT = """<b>⚡ G O A T  U I ⚡

━━━━━━━━━━━━━━━━━━━━
Hey {}! 👋

🤖 Advanced Media Processing Bot
━━━━━━━━━━━━━━━━━━━━

🎞 Encode　　•　🗜 Compress
🔀 Merge　　　•　🔬 Upscale
✏️ Rename　　•　⚙️ Settings
🎛 Audio　　　•　🚀 Speedtest

━━━━━━━━━━━━━━━━━━━━
Use /help to see all commands.</b>
"""

    HELP_TXT = """<b>📋 C O M M A N D S
━━━━━━━━━━━━━━━━━━━━

🎞 ENCODE
</b><code>/encode</code> — Reply to video → encode
    ‣ H.264 / H.265 codec selection
    ‣ 360p–4K + Original resolution
    ‣ 10-bit, custom CRF, presets
    ‣ Audio: AAC, AC3, OPUS, MP3
<code>/queue</code> — View encode queue

<b>🎛 AUDIO
</b><code>/af</code> — Reply to video → reorder audio tracks
    ‣ Set default audio stream
    ‣ Interactive inline buttons

<b>🗜 COMPRESS
</b><code>/compress</code> — Reply to video → compress
<code>/ctasks</code> — View active compress tasks

<b>🔀 MERGE
</b><code>/merge</code> — Start merge session
<code>/done</code> — Merge all files
<code>/mergecancel</code> — Cancel session
<code>/mtasks</code> — View active merge tasks

<b>🔬 UPSCALE
</b><code>/upscale</code> — Reply to image → upscale

<b>✏️ RENAME
</b><code>/autorename</code> — Set rename format
<code>/select 1-12</code> — Set episode range
<code>/clearselect</code> — Clear active selection

<b>📊 STATUS & TOOLS
</b><code>/status</code> — CPU, RAM, Disk, active tasks
<code>/speedtest</code> — Server internet speed test
<code>/leaderboard</code> — User activity rankings
<code>/logs</code> — View recent logs
<code>/logs stream</code> — Live log streaming

<b>⚙️ SETTINGS
</b><code>/settings</code> — Full settings menu:
    ‣ 🖼 Thumbnail　‣ 🏷 Metadata
    ‣ 📦 Upload Type　‣ 📝 Caption
    ‣ 📼 Video Ext (MKV/MP4/AVI)
    ‣ 🎬 Encode defaults
    ‣ 💧 Watermark (text/image)
    ‣ 📑 Subtitles (copy/hardsub)

<b>🔐 AUTH & ADMIN
</b><code>/auth</code> — Authorize user
<code>/rauth</code> — Remove authorization
<code>/authlist</code> — List authorized
<code>/add</code> — Add admin (reply)
<code>/rm</code> — Remove admin (reply)
<code>/addlist</code> — List admins
<code>/restart</code> — Restart bot

<b>ℹ️ GENERAL
</b><code>/start</code> — Start the bot
<code>/help</code> — Show this help
━━━━━━━━━━━━━━━━━━━━</b>
"""

    FILE_NAME_TXT = """<b>✏️ A U T O  R E N A M E
━━━━━━━━━━━━━━━━━━━━
Set your format:
<code>/autorename Anime S{{season}}E{{episode}} {{quality}}</code>

Placeholders:
‣ <code>{{season}}</code>  — Season number
‣ <code>{{episode}}</code> — Episode number
‣ <code>{{quality}}</code> — Quality (1080p etc)
‣ <code>{{codec}}</code>   — Codec (HEVC, x265 etc)
‣ <code>{{audio}}</code>   — Audio language
‣ <code>{{year}}</code>    — Year
‣ <code>{{filename}}</code> — Original filename

━━━━━━━━━━━━━━━━━━━━
Current Format: {format_template}</b>
"""

    PROGRESS_BAR = """
<b>» Size</b>  : {1} | {2}
<b>» Done</b>  : {0}%
<b>» Speed</b> : {3}/s
<b>» ETA</b>   : {4}
"""

    SEND_METADATA = """<b>🏷 M E T A D A T A
━━━━━━━━━━━━━━━━━━━━
Use /settings → 🏷 Metadata
to set Title, Author and Artist tags.</b>
"""

    THUMBNAIL_TXT = """<b>🖼 S E T T I N G S  I N F O
━━━━━━━━━━━━━━━━━━━━
Use /settings to manage:
‣ 🖼 Thumbnail — upload custom thumb
‣ 🏷 Metadata — set title, author, artist
‣ 📝 Caption — style, text, "As Original"
‣ 📦 Upload Type — document / video / music
‣ 📼 Video Ext — MKV / MP4 / AVI
‣ 🎬 Encode — codec, preset, CRF, audio
‣ 💧 Watermark — text / image overlay
‣ 📑 Subtitles — copy / hardsub / none</b>
"""

    DONATE_TXT = """<b>💝 S U P P O R T
━━━━━━━━━━━━━━━━━━━━
Enjoying the bot? Support us! ❤️

Every contribution keeps it running 🚀</b>
"""

    SOURCE_TXT = """<b>📦 S O U R C E
━━━━━━━━━━━━━━━━━━━━
This bot is a private project.

For support, contact the owner directly.</b>
"""

    ABOUT_TXT = """<b>ℹ️ A B O U T  B O T
━━━━━━━━━━━━━━━━━━━━

⚡ Goat UI — Advanced Media Bot

🎯 Features:
‣ 🎞 H.264 + H.265 Video Encoding
‣ 🗜 Smart Compression
‣ 🔀 Multi-file Merging
‣ 🔬 AI Image Upscaling
‣ ✏️ Auto File Renaming
‣ 🎛 Audio Stream Rearrangement
‣ 💧 Watermark (Text & Image)
‣ 📑 Subtitle Handling
‣ ⚙️ Full Settings & Metadata
‣ 🚀 Speedtest
‣ 📊 Leaderboard & Rankings

━━━━━━━━━━━━━━━━━━━━
👨‍💻 Dev : @cosmic_freak
📢 Updates : @Codeflix_Bots</b>
"""

    CAPTION_TXT = ""


# ================= SAFE EDIT =================

async def _safe_edit(msg, text, **kwargs):
    """Edit message with FloodWait retry."""
    try:
        await msg.edit_text(text, **kwargs)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await msg.edit_text(text, **kwargs)
        except Exception:
            pass
    except Exception:
        pass


# ================= START =================

@Client.on_message(filters.command("start"))
async def start(client, message: Message):

    if message.chat.type in ["group", "supergroup"]:
        return await message.reply_text(
            "👋 **Hello!**\n\n"
            "Use me in **private chat** to rename files.\n\n"
            f"👉 https://t.me/{(await client.get_me()).username}"
        )

    user = message.from_user
    await codeflixbots.add_user(client, message)

    # Quick welcome animation
    m = await message.reply_text("⚡")
    await asyncio.sleep(0.5)
    await _safe_edit(m, "⚡ **Goat UI Loading...**")
    await asyncio.sleep(0.4)

    try:
        await m.delete()
    except Exception:
        pass

    try:
        await message.reply_sticker(
            "CAACAgUAAxkBAAECroBmQKMAAQ-Gw4nibWoj_pJou2vP1a4AAlQIAAIzDxlVkNBkTEb1Lc4eBA"
        )
    except Exception:
        pass

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Commands", callback_data="help")],
        [
            InlineKeyboardButton("📢 Updates", url="https://t.me/Codeflix_Bots"),
            InlineKeyboardButton("💬 Support", url="https://t.me/CodeflixSupport")
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
            InlineKeyboardButton("📦 Source", callback_data="source")
        ]
    ])

    if Config.START_PIC:
        await message.reply_photo(
            Config.START_PIC,
            caption=Txt.START_TXT.format(user.mention),
            reply_markup=buttons
        )
    else:
        await message.reply_text(
            Txt.START_TXT.format(user.mention),
            reply_markup=buttons
        )


# ================= HELP COMMAND =================

@Client.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    """Standalone /help command — works in both private and group."""
    bot = await client.get_me()

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Auto Rename Format", callback_data="file_names")],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_info"),
            InlineKeyboardButton("💝 Donate", callback_data="donate")
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="home")]
    ])

    await message.reply_text(
        Txt.HELP_TXT.format(bot.mention),
        reply_markup=buttons
    )


# ================= CALLBACK HANDLER =================

@Client.on_callback_query(filters.regex(r"^(home|help|settings_info|file_names|donate|about|source|close)$"))
async def cb_handler(client, query: CallbackQuery):

    data = query.data
    user_id = query.from_user.id

    if data == "home":
        await _safe_edit(
            query.message,
            Txt.START_TXT.format(query.from_user.mention),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Commands", callback_data="help")],
                [
                    InlineKeyboardButton("📢 Updates", url="https://t.me/Codeflix_Bots"),
                    InlineKeyboardButton("💬 Support", url="https://t.me/CodeflixSupport")
                ],
                [
                    InlineKeyboardButton("ℹ️ About", callback_data="about"),
                    InlineKeyboardButton("📦 Source", callback_data="source")
                ]
            ])
        )

    elif data == "help":
        bot = await client.get_me()
        await _safe_edit(
            query.message,
            Txt.HELP_TXT.format(bot.mention),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Auto Rename Format", callback_data="file_names")],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings_info"),
                    InlineKeyboardButton("💝 Donate", callback_data="donate")
                ],
                [InlineKeyboardButton("🏠 Home", callback_data="home")]
            ])
        )

    elif data == "settings_info":
        await _safe_edit(
            query.message,
            Txt.THUMBNAIL_TXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="help")]
            ])
        )

    elif data == "file_names":
        format_template = await codeflixbots.get_format_template(user_id)
        await _safe_edit(
            query.message,
            Txt.FILE_NAME_TXT.format(format_template=format_template or "<i>Not set</i>"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="help")]
            ])
        )

    elif data == "donate":
        await _safe_edit(
            query.message,
            Txt.DONATE_TXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 Back", callback_data="help"),
                    InlineKeyboardButton("👤 Owner", url="https://t.me/sewxiy")
                ]
            ])
        )

    elif data == "about":
        await _safe_edit(
            query.message,
            Txt.ABOUT_TXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💬 Support", url="https://t.me/CodeflixSupport"),
                    InlineKeyboardButton("📋 Commands", callback_data="help")
                ],
                [
                    InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/cosmic_freak"),
                    InlineKeyboardButton("🌐 Network", url="https://t.me/otakuflix_network")
                ],
                [InlineKeyboardButton("🏠 Home", callback_data="home")]
            ])
        )

    elif data == "source":
        await _safe_edit(
            query.message,
            Txt.SOURCE_TXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Home", callback_data="home")]
            ])
        )

    elif data == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
