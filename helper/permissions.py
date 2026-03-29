from helper.auth import auth_chats
from config import Config


def is_owner(user_id):
    return user_id == Config.OWNER_ID


def is_admin(user_id):
    return user_id == Config.OWNER_ID or user_id in Config.ADMIN


def is_authorized_chat(chat_id):
    return chat_id in auth_chats


async def check_permission(message, require_owner=False, require_admin=False, require_auth=False):
    """
    Returns True agar permission hai, False agar nahi.
    Automatically error message bhi bhejta hai.
    """
    user_id = message.from_user.id if message.from_user else None
    chat_id = message.chat.id
    chat_type = message.chat.type

    # Group auth check
    if require_auth and chat_type in ["group", "supergroup"]:
        if chat_id not in auth_chats:
            await message.reply_text("❌ Yeh group authorized nahi hai.\nOwner se /auth karwao.")
            return False

    if user_id is None:
        await message.reply_text("❌ Anonymous users allowed nahi hain.")
        return False

    if require_owner and not is_owner(user_id):
        await message.reply_text("❌ Sirf owner use kar sakta hai.")
        return False

    if require_admin and not is_admin(user_id):
        await message.reply_text("❌ Sirf owner/admin use kar sakta hai.")
        return False

    return True
