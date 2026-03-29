import re
import os
import time

id_pattern = re.compile(r'^.\d+$')


class Config(object):

    # ================= BOT CONFIG =================
    API_ID    = int(os.environ.get("API_ID", 29776284))
    API_HASH  = os.environ.get("API_HASH", "aa9d8ca9cf83f30aa897effa6296493a")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "7439562089:AAGT15FwH89QRyfn0n84RM9MHESAW-3XaqY")

    # ================= OWNER =================
    OWNER_ID = int(os.environ.get("OWNER_ID", "6066102279"))

    # ================= DATABASE =================
    DB_NAME = os.environ.get("DB_NAME", "Yato")
    DB_URL  = os.environ.get(
        "DB_URL",
        "mongodb+srv://Toonpro12:animebash@cluster0.e6hpn8l.mongodb.net/?retryWrites=true&w=majority"
    )

    PORT       = int(os.environ.get("PORT", "8080"))
    BOT_UPTIME = time.time()
    WEBHOOK    = os.environ.get("WEBHOOK", "True").lower() == "true"

    START_PIC = os.environ.get(
        "START_PIC",
        "https://i.ibb.co/jZDxWgmk/dbffcd55fcb3.jpg"
    )

    # ================= ADMINS =================
    ADMIN = [
        int(admin) if id_pattern.search(admin) else admin
        for admin in os.environ.get("ADMIN", "6066102279").split()
    ]

    # ================= CHANNELS =================
    LOG_CHANNEL  = int(os.environ.get("LOG_CHANNEL",  "-1003848503695"))
    DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", "-1002323392635"))

    # ================= NEW FEATURES (from Auto-Rename + ENCODING-BOT) =================

    # Admin contact URL (shown when user is banned)
    ADMIN_URL = os.environ.get("ADMIN_URL", "https://t.me/cosmic_freak")

    # Leaderboard feature
    LEADERBOARD_PIC = os.environ.get("LEADERBOARD_PIC", "")
    LEADERBOARD_DELETE_TIMER = int(os.environ.get("LEADERBOARD_DELETE_TIMER", "30"))

    # Force Subscribe settings
    FSUB_PIC = os.environ.get("FSUB_PIC", "")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

    # Sudo users (separate from admin - can use encode/compress but not owner cmds)
    SUDO_USERS = [
        int(x) for x in os.environ.get("SUDO_USERS", "").split() if x.strip()
    ]

    # Encoding directories
    DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads/")
    ENCODE_DIR   = os.environ.get("ENCODE_DIR", "encodes/")

    # Support chat (for restart notification)
    SUPPORT_CHAT = int(os.environ.get("SUPPORT_CHAT", "-1001953724858"))
