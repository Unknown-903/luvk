"""
Speedtest Plugin (/speedtest)
Check server internet speed and display graphical report.
"""
import os
import sys
import logging
import asyncio
import time

from pyrogram import Client, filters
from pyrogram.errors import FloodWait

from helper.permissions import is_admin as _perm_is_admin
from config import Config

logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)


@Client.on_message(filters.command("speedtest") & (filters.private | filters.group))
async def speedtest_cmd(client, message):
    user_id = message.from_user.id
    if not _perm_is_admin(user_id):
        return await message.reply_text("❌ Only owner/admin can use this.")

    status_msg = await message.reply_text("🚀 **Running Speedtest...**\n⏳ This may take 30-60 seconds...")

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-m", "speedtest", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            logger.error(f"Speedtest error: {stderr.decode()}")
            return await status_msg.edit(f"❌ Speedtest failed!\n`{stderr.decode()[:200]}`")

        import json
        data = json.loads(stdout.decode())

        download = data["download"] / 1_000_000  # bits to Mbps
        upload = data["upload"] / 1_000_000
        ping = data["ping"]
        server = data.get("server", {})
        server_name = server.get("name", "Unknown")
        server_country = server.get("country", "")
        isp = data.get("client", {}).get("isp", "Unknown")

        text = (
            "🚀 **Speedtest Results**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📥 **Download:** `{download:.2f} Mbps`\n"
            f"📤 **Upload:** `{upload:.2f} Mbps`\n"
            f"🏓 **Ping:** `{ping:.1f} ms`\n\n"
            f"🌍 **Server:** {server_name}, {server_country}\n"
            f"🏢 **ISP:** {isp}\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

        # Try to get graphical report
        try:
            proc2 = await asyncio.create_subprocess_exec(
                "python3", "-m", "speedtest", "--share",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=120)
            output = stdout2.decode()
            # Extract share URL
            for line in output.split("\n"):
                if "Share results:" in line:
                    share_url = line.split("Share results:")[-1].strip()
                    if share_url:
                        await status_msg.delete()
                        await message.reply_photo(
                            photo=share_url,
                            caption=text
                        )
                        return
        except:
            pass

        await status_msg.edit(text)

    except asyncio.TimeoutError:
        await status_msg.edit("❌ Speedtest timed out (>120s)")
    except Exception as e:
        logger.error(f"Speedtest error: {e}")
        await status_msg.edit(f"❌ Speedtest error: `{str(e)[:200]}`")
