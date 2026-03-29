import aiohttp, asyncio, warnings, pytz
from datetime import datetime, timedelta
from pytz import timezone
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from pyrogram.errors import FloodWait
from config import Config
from aiohttp import web
from route import web_server
import pyrogram.utils
import pyromod
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import time

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

SUPPORT_CHAT = int(os.environ.get("SUPPORT_CHAT", "-1001953724858"))
PORT = Config.PORT


class Bot(Client):
    def __init__(self):
        super().__init__(
            name="codeflixbots",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=200,
            plugins={"root": "plugins"},
            sleep_threshold=15,
        )
        self.start_time = time.time()

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)
        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username
        self.uptime = Config.BOT_UPTIME
        if Config.WEBHOOK:
            app = web.AppRunner(await web_server())
            await app.setup()
            await web.TCPSite(app, "0.0.0.0", PORT).start()
        print(f"{me.first_name} Is Started.....✨️")

        uptime_seconds = int(time.time() - self.start_time)
        uptime_string = str(timedelta(seconds=uptime_seconds))

        for chat_id in [Config.LOG_CHANNEL, SUPPORT_CHAT]:
            try:
                curr = datetime.now(timezone("Asia/Kolkata"))
                date = curr.strftime('%d %B, %Y')
                time_str = curr.strftime('%I:%M:%S %p')

                await self.send_photo(
                    chat_id=chat_id,
                    photo=Config.START_PIC,
                    caption=(
                        "**⚡ Bot Restarted!**\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🕐 **Uptime:** `{uptime_string}`\n"
                        f"📅 **Date:** `{date}`\n"
                        f"🕐 **Time:** `{time_str}`"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("📢 Updates", url="https://t.me/codeflix_bots")]]
                    )
                )

            except FloodWait as e:
                await asyncio.sleep(e.value)
                try:
                    await self.send_photo(
                        chat_id=chat_id,
                        photo=Config.START_PIC,
                        caption=f"**⚡ Bot Restarted!**\nUptime: `{uptime_string}`",
                    )
                except Exception:
                    pass

            except Exception as e:
                print(f"Failed to send message in chat {chat_id}: {e}")

    async def stop(self, *args):
        await super().stop()
        print("🛑 Bot stopped!")


Bot().run()
