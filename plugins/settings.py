import os
import sys
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from helper.database import codeflixbots as db
from helper.auth import auth_chats
from helper.permissions import is_admin as _perm_is_admin
from config import Config

logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

def is_admin(user_id):
    return user_id == Config.OWNER_ID or _perm_is_admin(user_id)

settings_state = {}


# ================= MAIN MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼️ Thumbnail", callback_data="stg|thumb_menu"),
            InlineKeyboardButton("🏷️ Metadata", callback_data="stg|meta_menu"),
        ],
        [
            InlineKeyboardButton("📦 Upload Type", callback_data="stg|upload_menu"),
            InlineKeyboardButton("📝 Caption", callback_data="stg|caption_menu"),
        ],
        [
            InlineKeyboardButton("📼 Video Ext", callback_data="stg|video_extension_menu"),
            InlineKeyboardButton("🎬 Encode", callback_data="stg|encode_menu"),
        ],
        [
            InlineKeyboardButton("💧 Watermark", callback_data="stg|watermark_menu"),
            InlineKeyboardButton("📑 Subtitles", callback_data="stg|subtitle_menu"),
        ],
        [InlineKeyboardButton("❌ Close", callback_data="stg|close")],
    ])


# ================= THUMBNAIL =================

async def thumb_menu(user_id):
    thumb = await db.get_thumbnail(user_id)
    buttons = []
    if thumb:
        buttons.append([
            InlineKeyboardButton("👁️ View", callback_data="stg|thumb_view"),
            InlineKeyboardButton("🗑️ Delete", callback_data="stg|thumb_del"),
        ])
    buttons.append([InlineKeyboardButton("📸 Upload New", callback_data="stg|thumb_set")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|back")])
    return InlineKeyboardMarkup(buttons)


# ================= METADATA =================

async def meta_menu(user_id):
    title = await db.get_title(user_id)
    author = await db.get_author(user_id)
    artist = await db.get_artist(user_id)
    buttons = []
    if title or author or artist:
        buttons.append([
            InlineKeyboardButton("👁️ View", callback_data="stg|meta_view"),
            InlineKeyboardButton("🗑️ Delete", callback_data="stg|meta_del"),
        ])
    buttons.append([InlineKeyboardButton("✏️ Set Metadata", callback_data="stg|meta_set")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|back")])
    return InlineKeyboardMarkup(buttons)


# ================= UPLOAD TYPE =================

async def upload_menu(user_id):
    media_type = await db.get_media_preference(user_id)
    opts = [
        ("📄 Document", "document"), ("🎬 Video", "video"),
        ("🎵 Music", "music"), ("🧩 Original", "original"),
    ]
    buttons = []
    for label, val in opts:
        check = " ✅" if media_type == val else ""
        buttons.append([InlineKeyboardButton(f"{label}{check}", callback_data=f"stg|upload_{val}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|back")])
    return InlineKeyboardMarkup(buttons)


# ================= CAPTION =================

async def caption_menu(user_id):
    fmt = await db.get_caption_format(user_id)
    fmt_label = "📋 As Original" if fmt == "as_original" else "✏️ Custom"
    buttons = [
        [InlineKeyboardButton("🎨 Caption Style", callback_data="stg|caption_style_menu")],
        [InlineKeyboardButton("✏️ Set Caption Text", callback_data="stg|caption_text_set")],
        [InlineKeyboardButton("🗑️ Reset Caption Text", callback_data="stg|caption_reset")],
        [InlineKeyboardButton(f"📋 Format: {fmt_label}", callback_data="stg|caption_format_toggle")],
        [InlineKeyboardButton("🔙 Back", callback_data="stg|back")],
    ]
    return InlineKeyboardMarkup(buttons)


async def caption_style_menu(user_id):
    current = await db.get_caption_style(user_id)
    styles = [
        ("original", "Same as Original"),
        ("regular", "Regular"),
        ("bold", "𝐁𝐨𝐥𝐝"),
        ("italic", "𝘐𝘵𝘢𝘭𝘪𝘤"),
        ("underline", "U̲n̲d̲e̲r̲l̲i̲n̲e̲"),
        ("monospace", "𝙼𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎"),
        ("strike", "S̶t̶r̶i̶k̶e̶"),
    ]
    buttons = []
    for key, label in styles:
        check = " ✅" if current == key else ""
        buttons.append([InlineKeyboardButton(f"{label}{check}", callback_data=f"stg|caption_style_{key}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|caption_menu")])
    return InlineKeyboardMarkup(buttons)


# ================= VIDEO EXTENSION =================

async def video_extension_menu(user_id):
    current = await db.get_video_extension(user_id)
    exts = ["mkv", "mp4", "avi"]
    buttons = []
    for ext in exts:
        check = " ✅" if current == ext else ""
        buttons.append([InlineKeyboardButton(f"📼 {ext.upper()}{check}", callback_data=f"stg|ext_{ext}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|back")])
    return InlineKeyboardMarkup(buttons)


# ================= ENCODE SETTINGS =================

async def encode_menu(user_id):
    codec = await db.get_encode_codec(user_id)
    res = await db.get_encode_resolution(user_id)
    preset = await db.get_encode_preset(user_id)
    crf = await db.get_encode_crf(user_id)
    ten_bit = await db.get_encode_10bit(user_id)
    a_codec = await db.get_encode_audio_codec(user_id)
    a_bitrate = await db.get_encode_audio_bitrate(user_id)
    a_channels = await db.get_encode_audio_channels(user_id)
    compress = await db.get_encode_compress(user_id)

    def fmt(val):
        return "🔄 Ask" if val == "ask" else str(val).upper()

    buttons = [
        [InlineKeyboardButton(f"🎬 Codec: {fmt(codec)}", callback_data="stg|enc_codec")],
        [InlineKeyboardButton(f"📐 Resolution: {fmt(res)}", callback_data="stg|enc_resolution")],
        [InlineKeyboardButton(f"⚡ Preset: {fmt(preset)}", callback_data="stg|enc_preset")],
        [InlineKeyboardButton(f"🎚️ CRF: {fmt(crf)}", callback_data="stg|enc_crf")],
        [InlineKeyboardButton(f"{'✅' if ten_bit else '❌'} 10-bit Encoding", callback_data="stg|enc_10bit_toggle")],
        [InlineKeyboardButton(f"🔊 Audio Codec: {fmt(a_codec)}", callback_data="stg|enc_audio_codec")],
        [InlineKeyboardButton(f"🔈 Audio Bitrate: {a_bitrate}", callback_data="stg|enc_audio_bitrate")],
        [InlineKeyboardButton(f"🎧 Channels: {fmt(a_channels)}", callback_data="stg|enc_audio_channels")],
        [InlineKeyboardButton(f"🗜️ Compress: {fmt(compress)}", callback_data="stg|enc_compress")],
        [
            InlineKeyboardButton("🔄 Reset All", callback_data="stg|enc_reset"),
            InlineKeyboardButton("🔙 Back", callback_data="stg|back"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


# ================= WATERMARK SETTINGS =================

async def watermark_menu(user_id):
    wm_text = await db.get_watermark_text(user_id)
    wm_image = await db.get_watermark_image(user_id)
    wm_pos = await db.get_watermark_position(user_id)
    wm_size = await db.get_watermark_size(user_id)
    wm_opacity = await db.get_watermark_opacity(user_id)
    wm_mode = await db.get_watermark_mode(user_id)

    pos_label = wm_pos.replace("_", " ").title()
    mode_labels = {"text": "Text Only", "image": "Image Only", "both": "Both"}
    mode_label = mode_labels.get(wm_mode, "Text Only")
    size_display = wm_size.title() if not wm_size.endswith("%") else wm_size

    buttons = [
        [InlineKeyboardButton(f"✏️ Text: {wm_text or 'Not Set'}", callback_data="stg|wm_text_set")],
        [InlineKeyboardButton(f"🖼️ Image: {'Set ✅' if wm_image else 'Not Set'}", callback_data="stg|wm_image_set")],
        [InlineKeyboardButton(f"🔀 Mode: {mode_label}", callback_data="stg|wm_mode")],
        [InlineKeyboardButton(f"📍 Position: {pos_label}", callback_data="stg|wm_position")],
        [InlineKeyboardButton(f"📏 Size: {size_display}", callback_data="stg|wm_size")],
        [InlineKeyboardButton(f"🔆 Opacity: {wm_opacity}", callback_data="stg|wm_opacity")],
        [
            InlineKeyboardButton("🗑️ Clear All", callback_data="stg|wm_clear"),
            InlineKeyboardButton("🔙 Back", callback_data="stg|back"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


# ================= SUBTITLE SETTINGS =================

async def subtitle_menu(user_id):
    mode = await db.get_subtitle_mode(user_id)
    modes = [
        ("copy", "📋 Copy (Soft subs)"),
        ("hardsub", "🔥 Hardsub (Burn in)"),
        ("none", "❌ No Subtitles"),
    ]
    buttons = []
    for key, label in modes:
        check = " ✅" if mode == key else ""
        buttons.append([InlineKeyboardButton(f"{label}{check}", callback_data=f"stg|sub_{key}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|back")])
    return InlineKeyboardMarkup(buttons)


# ================= COMMAND =================

@Client.on_message(filters.command("settings") & (filters.private | filters.group))
async def settings_cmd(client, message):
    await message.reply_text(
        "⚙️ **Settings Menu**\n━━━━━━━━━━━━━━━━━━━━",
        reply_markup=main_menu()
    )


# ================= MAIN CALLBACK ROUTER =================

@Client.on_callback_query(filters.regex(r"^stg\|"))
async def settings_callback(client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data.split("|", 1)[1]

    try:
        # ---- NAVIGATION ----
        if data == "back":
            await query.message.edit_text("⚙️ **Settings Menu**\n━━━━━━━━━━━━━━━━━━━━", reply_markup=main_menu())

        elif data == "close":
            await query.message.delete()

        # ---- THUMBNAIL ----
        elif data == "thumb_menu":
            await query.message.edit_text("🖼️ **Thumbnail Settings**", reply_markup=await thumb_menu(user_id))

        elif data == "thumb_view":
            thumb = await db.get_thumbnail(user_id)
            if thumb:
                await client.send_photo(user_id, thumb, caption="🖼️ Your current thumbnail")
                await query.answer("Thumbnail sent!")
            else:
                await query.answer("No thumbnail set.", show_alert=True)

        elif data == "thumb_del":
            await db.set_thumbnail(user_id, None)
            await query.answer("✅ Thumbnail deleted")
            await query.message.edit_text("🖼️ **Thumbnail Settings**", reply_markup=await thumb_menu(user_id))

        elif data == "thumb_set":
            settings_state[user_id] = "thumb"
            await query.message.edit_text("📸 **Send me a photo** to set as thumbnail.")

        # ---- METADATA ----
        elif data == "meta_menu":
            await query.message.edit_text("🏷️ **Metadata Settings**", reply_markup=await meta_menu(user_id))

        elif data == "meta_view":
            title = await db.get_title(user_id)
            author = await db.get_author(user_id)
            artist = await db.get_artist(user_id)
            text = f"🏷️ **Metadata**\n\n📌 Title: `{title}`\n✍️ Author: `{author}`\n🎨 Artist: `{artist}`"
            await query.answer()
            await query.message.edit_text(text, reply_markup=await meta_menu(user_id))

        elif data == "meta_del":
            await db.set_title(user_id, "")
            await db.set_author(user_id, "")
            await db.set_artist(user_id, "")
            await query.answer("✅ Metadata cleared")
            await query.message.edit_text("🏷️ **Metadata Settings**", reply_markup=await meta_menu(user_id))

        elif data == "meta_set":
            settings_state[user_id] = "meta"
            await query.message.edit_text(
                "✏️ **Send metadata** in this format:\n\n"
                "`Title | Author | Artist`\n\n"
                "Example: `My Video | @Channel | Creator`"
            )

        # ---- UPLOAD TYPE ----
        elif data == "upload_menu":
            await query.message.edit_text("📦 **Upload Type**", reply_markup=await upload_menu(user_id))

        elif data.startswith("upload_"):
            media_type = data.replace("upload_", "")
            await db.set_media_preference(user_id, media_type)
            await query.answer(f"✅ Upload type: {media_type}")
            await query.message.edit_text("📦 **Upload Type**", reply_markup=await upload_menu(user_id))

        # ---- CAPTION ----
        elif data == "caption_menu":
            await query.message.edit_text("📝 **Caption Settings**", reply_markup=await caption_menu(user_id))

        elif data == "caption_style_menu":
            await query.message.edit_text("🎨 **Caption Style**", reply_markup=await caption_style_menu(user_id))

        elif data.startswith("caption_style_"):
            style = data.replace("caption_style_", "")
            await db.set_caption_style(user_id, style)
            await query.answer(f"✅ Style: {style}")
            await query.message.edit_text("🎨 **Caption Style**", reply_markup=await caption_style_menu(user_id))

        elif data == "caption_text_set":
            settings_state[user_id] = "caption_text"
            await query.message.edit_text("✏️ **Send your caption text.**\n\nVariables: `{filename}`, `{filesize}`, `{duration}`")

        elif data == "caption_reset":
            await db.set_caption(user_id, None)
            await query.answer("✅ Caption reset")
            await query.message.edit_text("📝 **Caption Settings**", reply_markup=await caption_menu(user_id))

        elif data == "caption_format_toggle":
            current = await db.get_caption_format(user_id)
            new_fmt = "as_original" if current != "as_original" else "custom"
            await db.set_caption_format(user_id, new_fmt)
            label = "As Original File" if new_fmt == "as_original" else "Custom"
            await query.answer(f"✅ Caption format: {label}")
            await query.message.edit_text("📝 **Caption Settings**", reply_markup=await caption_menu(user_id))

        # ---- VIDEO EXTENSION ----
        elif data == "video_extension_menu":
            await query.message.edit_text("📼 **Video Extension**", reply_markup=await video_extension_menu(user_id))

        elif data.startswith("ext_"):
            ext = data.replace("ext_", "")
            await db.set_video_extension(user_id, ext)
            await query.answer(f"✅ Extension: .{ext}")
            await query.message.edit_text("📼 **Video Extension**", reply_markup=await video_extension_menu(user_id))

        # ---- ENCODE SETTINGS ----
        elif data == "encode_menu":
            await query.message.edit_text("🎬 **Encode Settings**\n\n💡 Set defaults or choose 'Ask Each Time'", reply_markup=await encode_menu(user_id))

        elif data == "enc_codec":
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Ask Each Time", callback_data="stg|enc_codec_set|ask")],
                [InlineKeyboardButton("🎬 H.265 (HEVC)", callback_data="stg|enc_codec_set|h265")],
                [InlineKeyboardButton("📺 H.264 (AVC)", callback_data="stg|enc_codec_set|h264")],
                [InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")],
            ])
            await query.message.edit_text("🎬 **Default Codec**", reply_markup=buttons)

        elif data.startswith("enc_codec_set|"):
            val = data.split("|")[1]
            await db.set_encode_codec(user_id, val)
            await query.answer(f"✅ Codec: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_resolution":
            res_list = ["ask", "360p", "480p", "540p", "720p", "1080p", "4k", "original"]
            buttons = []
            for r in res_list:
                label = "🔄 Ask Each Time" if r == "ask" else f"📐 {r}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"stg|enc_res_set|{r}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")])
            await query.message.edit_text("📐 **Default Resolution**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("enc_res_set|"):
            val = data.split("|")[1]
            await db.set_encode_resolution(user_id, val)
            await query.answer(f"✅ Resolution: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_preset":
            presets = ["ask", "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
            buttons = []
            for p in presets:
                label = "🔄 Ask Each Time" if p == "ask" else f"⚡ {p}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"stg|enc_preset_set|{p}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")])
            await query.message.edit_text("⚡ **Default Preset**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("enc_preset_set|"):
            val = data.split("|")[1]
            await db.set_encode_preset(user_id, val)
            await query.answer(f"✅ Preset: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_crf":
            settings_state[user_id] = "enc_crf"
            await query.message.edit_text(
                "🎚️ **Set Custom CRF**\n\n"
                "Send a number (0-51) or `ask` for prompt each time.\n"
                "Lower = better quality, bigger file.\n"
                "Recommended: 18-28"
            )

        elif data == "enc_10bit_toggle":
            current = await db.get_encode_10bit(user_id)
            await db.set_encode_10bit(user_id, not current)
            status = "Enabled" if not current else "Disabled"
            await query.answer(f"✅ 10-bit: {status}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_audio_codec":
            codecs = ["ask", "aac", "ac3", "opus", "mp3", "copy"]
            buttons = []
            for c in codecs:
                label = "🔄 Ask Each Time" if c == "ask" else f"🔊 {c.upper()}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"stg|enc_acodec_set|{c}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")])
            await query.message.edit_text("🔊 **Default Audio Codec**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("enc_acodec_set|"):
            val = data.split("|")[1]
            await db.set_encode_audio_codec(user_id, val)
            await query.answer(f"✅ Audio Codec: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_audio_bitrate":
            bitrates = ["64k", "96k", "128k", "192k", "256k", "320k"]
            buttons = []
            for b in bitrates:
                buttons.append([InlineKeyboardButton(f"🔈 {b}", callback_data=f"stg|enc_abitrate_set|{b}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")])
            await query.message.edit_text("🔈 **Audio Bitrate**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("enc_abitrate_set|"):
            val = data.split("|")[1]
            await db.set_encode_audio_bitrate(user_id, val)
            await query.answer(f"✅ Audio Bitrate: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_audio_channels":
            channels = ["ask", "stereo", "mono", "5.1", "original"]
            buttons = []
            for ch in channels:
                label = "🔄 Ask Each Time" if ch == "ask" else f"🎧 {ch}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"stg|enc_achan_set|{ch}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")])
            await query.message.edit_text("🎧 **Audio Channels**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("enc_achan_set|"):
            val = data.split("|")[1]
            await db.set_encode_audio_channels(user_id, val)
            await query.answer(f"✅ Channels: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_compress":
            levels = ["ask", "low", "medium", "high", "best", "skip"]
            buttons = []
            for lv in levels:
                label = "🔄 Ask Each Time" if lv == "ask" else f"🗜️ {lv.title()}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"stg|enc_cmp_set|{lv}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|encode_menu")])
            await query.message.edit_text("🗜️ **Default Compression**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("enc_cmp_set|"):
            val = data.split("|")[1]
            await db.set_encode_compress(user_id, val)
            await query.answer(f"✅ Compress: {val}")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        elif data == "enc_reset":
            await db.reset_encode_settings(user_id)
            await query.answer("✅ All encode settings reset to defaults")
            await query.message.edit_text("🎬 **Encode Settings**", reply_markup=await encode_menu(user_id))

        # ---- WATERMARK ----
        elif data == "watermark_menu":
            await query.message.edit_text("💧 **Watermark Settings**", reply_markup=await watermark_menu(user_id))

        elif data == "wm_text_set":
            settings_state[user_id] = "wm_text"
            await query.message.edit_text("✏️ **Send watermark text**\nExample: `@MyChannel`")

        elif data == "wm_image_set":
            settings_state[user_id] = "wm_image"
            await query.message.edit_text(
                "🖼️ **Send a PNG image as document** for watermark overlay.\n\n"
                "📌 **How to send:**\n"
                "1. Tap 📎 (attach)\n"
                "2. Choose **File** (send as document)\n"
                "3. Select your PNG image\n\n"
                "💡 Use **PNG with transparent background** for best results!\n"
                "⚠️ Do NOT send as photo — it loses transparency."
            )

        # ---- WATERMARK MODE (NEW) ----
        elif data == "wm_mode":
            current = await db.get_watermark_mode(user_id)
            modes = [("text", "✏️ Text Only"), ("image", "🖼️ Image Only"), ("both", "🔀 Both (Text + Image)")]
            buttons = []
            for val, label in modes:
                check = " ✅" if current == val else ""
                buttons.append([InlineKeyboardButton(f"{label}{check}", callback_data=f"stg|wm_mode_set|{val}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|watermark_menu")])
            await query.message.edit_text(
                "🔀 **Watermark Mode**\n\n💡 Choose what to apply when both text & image are set:",
                reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("wm_mode_set|"):
            val = data.split("|")[1]
            await db.set_watermark_mode(user_id, val)
            mode_names = {"text": "Text Only", "image": "Image Only", "both": "Both"}
            await query.answer(f"✅ Mode: {mode_names.get(val, val)}")
            await query.message.edit_text("💧 **Watermark Settings**", reply_markup=await watermark_menu(user_id))

        elif data == "wm_position":
            positions = ["top_left", "top_right", "bottom_left", "bottom_right", "center"]
            buttons = []
            for pos in positions:
                label = pos.replace("_", " ").title()
                buttons.append([InlineKeyboardButton(f"📍 {label}", callback_data=f"stg|wm_pos_set|{pos}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|watermark_menu")])
            await query.message.edit_text("📍 **Watermark Position**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("wm_pos_set|"):
            val = data.split("|")[1]
            await db.set_watermark_position(user_id, val)
            await query.answer(f"✅ Position: {val.replace('_', ' ').title()}")
            await query.message.edit_text("💧 **Watermark Settings**", reply_markup=await watermark_menu(user_id))

        elif data == "wm_size":
            current = await db.get_watermark_size(user_id)
            presets = [("small", "📏 Small"), ("medium", "📏 Medium"), ("large", "📏 Large")]
            percentages = ["5%", "7%", "10%", "15%", "20%", "25%", "30%", "40%", "50%", "60%", "70%", "80%"]
            buttons = []
            preset_row = []
            for val, label in presets:
                check = " ✅" if current == val else ""
                preset_row.append(InlineKeyboardButton(f"{label}{check}", callback_data=f"stg|wm_size_set|{val}"))
            buttons.append(preset_row)
            for i in range(0, len(percentages), 3):
                row = []
                for pct in percentages[i:i+3]:
                    check = " ✅" if current == pct else ""
                    row.append(InlineKeyboardButton(f"📐 {pct}{check}", callback_data=f"stg|wm_size_set|{pct}"))
                buttons.append(row)
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|watermark_menu")])
            await query.message.edit_text(
                "📏 **Watermark Size**\n\n💡 Choose a preset OR exact percentage (only one active):",
                reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("wm_size_set|"):
            val = data.split("|")[1]
            await db.set_watermark_size(user_id, val)
            display = val.title() if not val.endswith("%") else val
            await query.answer(f"✅ Size: {display}")
            await query.message.edit_text("💧 **Watermark Settings**", reply_markup=await watermark_menu(user_id))

        elif data == "wm_opacity":
            opacities = [0.3, 0.5, 0.7, 0.9, 1.0]
            buttons = []
            for o in opacities:
                buttons.append([InlineKeyboardButton(f"🔆 {o}", callback_data=f"stg|wm_opacity_set|{o}")])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="stg|watermark_menu")])
            await query.message.edit_text("🔆 **Watermark Opacity**", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("wm_opacity_set|"):
            val = float(data.split("|")[1])
            await db.set_watermark_opacity(user_id, val)
            await query.answer(f"✅ Opacity: {val}")
            await query.message.edit_text("💧 **Watermark Settings**", reply_markup=await watermark_menu(user_id))

        elif data == "wm_clear":
            await db.set_watermark_text(user_id, None)
            await db.set_watermark_image(user_id, None)
            await db.set_watermark_mode(user_id, "text")
            await query.answer("✅ Watermark cleared")
            await query.message.edit_text("💧 **Watermark Settings**", reply_markup=await watermark_menu(user_id))

        # ---- SUBTITLES ----
        elif data == "subtitle_menu":
            await query.message.edit_text("📑 **Subtitle Settings**", reply_markup=await subtitle_menu(user_id))

        elif data.startswith("sub_"):
            mode = data.replace("sub_", "")
            await db.set_subtitle_mode(user_id, mode)
            await query.answer(f"✅ Subtitle mode: {mode}")
            await query.message.edit_text("📑 **Subtitle Settings**", reply_markup=await subtitle_menu(user_id))

        else:
            await query.answer("Unknown option")

    except Exception as e:
        logger.error(f"Settings callback error: {e}", exc_info=True)
        await query.answer("⚠️ Error occurred", show_alert=True)


# ================= TEXT INPUT HANDLER =================

@Client.on_message(
    filters.private & filters.text & ~filters.command(["settings", "start", "help"]),
    group=5
)
async def settings_text_handler(client, message):
    user_id = message.from_user.id
    state = settings_state.pop(user_id, None)
    if not state:
        return

    if state == "thumb":
        # Will be handled by photo handler below
        settings_state[user_id] = "thumb"  # Re-add
        return

    elif state == "meta":
        parts = message.text.split("|")
        if len(parts) >= 3:
            await db.set_title(user_id, parts[0].strip())
            await db.set_author(user_id, parts[1].strip())
            await db.set_artist(user_id, parts[2].strip())
            await message.reply_text("✅ Metadata set!", reply_markup=main_menu())
        else:
            await message.reply_text("❌ Format: `Title | Author | Artist`")
            settings_state[user_id] = "meta"

    elif state == "caption_text":
        await db.set_caption(user_id, message.text)
        await message.reply_text("✅ Caption set!", reply_markup=main_menu())

    elif state == "enc_crf":
        text = message.text.strip().lower()
        if text == "ask":
            await db.set_encode_crf(user_id, "ask")
            await message.reply_text("✅ CRF: Ask each time", reply_markup=main_menu())
        elif text.isdigit() and 0 <= int(text) <= 51:
            await db.set_encode_crf(user_id, int(text))
            await message.reply_text(f"✅ CRF: {text}", reply_markup=main_menu())
        else:
            await message.reply_text("❌ Send 0-51 or `ask`")
            settings_state[user_id] = "enc_crf"

    elif state == "wm_text":
        await db.set_watermark_text(user_id, message.text)
        await message.reply_text("✅ Watermark text set!", reply_markup=main_menu())


# ================= PHOTO HANDLER (Thumbnail + Watermark Image) =================

@Client.on_message(filters.private & filters.photo, group=6)
async def settings_photo_handler(client, message):
    user_id = message.from_user.id
    state = settings_state.pop(user_id, None)
    if not state:
        return

    if state == "thumb":
        file_id = message.photo.file_id
        await db.set_thumbnail(user_id, file_id)
        await message.reply_text("✅ Thumbnail set!", reply_markup=main_menu())

    elif state == "wm_image":
        # Reject photo — must send as document for transparency
        settings_state[user_id] = "wm_image"  # Re-add state
        await message.reply_text(
            "⚠️ Please send as **document** (📎), not as photo.\n\n"
            "**Why?** Photos lose transparency when compressed by Telegram.\n"
            "📌 Tap 📎 → **File** → Select your PNG image.")


# ================= DOCUMENT HANDLER (Watermark Image) =================

@Client.on_message(filters.private & filters.document, group=7)
async def settings_document_handler(client, message):
    user_id = message.from_user.id
    state = settings_state.pop(user_id, None)
    if not state:
        return
    if state == "wm_image":
        doc = message.document
        mime = doc.mime_type or ""
        fname = (doc.file_name or "").lower()
        if not (mime.startswith("image/") or fname.endswith((".png", ".jpg", ".jpeg", ".webp"))):
            settings_state[user_id] = "wm_image"
            await message.reply_text(
                "❌ Please send an **image file** (PNG, JPG, or WEBP).\n"
                "Send as **document** (📎 attach as file).\n\n"
                "💡 PNG with transparent background recommended!")
            return
        file_id = doc.file_id
        await db.set_watermark_image(user_id, file_id)
        fmt = "PNG ✨" if "png" in mime or fname.endswith(".png") else "Image"
        await message.reply_text(
            f"✅ Watermark image set! ({fmt})\n📎 Saved as document — transparency preserved!",
            reply_markup=main_menu())
    else:
        settings_state[user_id] = state
