import os
import logging
import heroku3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler, ContextTypes
)

# --- Logging setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_HEROKU_API_KEY = os.getenv("HEROKU_API_KEY")

# Store user API keys in memory (you can replace with DB later)
user_api_keys = {}

# Conversation states
GET_API_KEY = 1


# --- Helpers ---
def get_heroku_conn(api_key: str = None):
    """Return a Heroku connection using provided key or default env key."""
    key = api_key or DEFAULT_HEROKU_API_KEY
    if not key:
        return None
    return heroku3.from_key(key)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text="Choose an option:"):
    """Send the main menu with buttons."""
    keyboard = [
        [InlineKeyboardButton("List Apps", callback_data="list_apps")],
        [InlineKeyboardButton("Login", callback_data="login")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context, "👋 Welcome to the Heroku Bot!")


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "🔑 Please send me your Heroku API key.\n\n"
        "➡️ You can find it at https://dashboard.heroku.com/account"
    )
    return GET_API_KEY


async def get_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    api_key = update.message.text.strip()

    # Try deleting the message for safety
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete API key message: {e}")

    await update.message.reply_text("⏳ Authenticating...")
    heroku_conn = get_heroku_conn(api_key)

    try:
        # Validate by listing apps
        _ = heroku_conn.apps()
        user_api_keys[user_id] = api_key
        await update.message.reply_text("✅ Login successful! You can now manage your apps.")
        await show_main_menu(update, context, "What would you like to do next?")
    except Exception as e:
        logger.error(f"Heroku authentication failed: {e}")
        await update.message.reply_text(
            "❌ Authentication failed! Your API key seems invalid or unauthorized."
        )
        await show_main_menu(update, context)

    return ConversationHandler.END


async def list_apps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    api_key = user_api_keys.get(user_id, None)

    heroku_conn = get_heroku_conn(api_key)
    if not heroku_conn:
        await update.callback_query.message.reply_text(
            "❌ No valid Heroku API key found. Please login first."
        )
        return

    try:
        apps = heroku_conn.apps()
        if not apps:
            await update.callback_query.message.reply_text("⚠️ No apps found on your Heroku account.")
            return

        text = "🚀 Your Heroku Apps:\n\n"
        for app in apps:
            text += f"• {app.name}\n"
        await update.callback_query.message.reply_text(text)

    except Exception as e:
        logger.error(f"Error fetching apps: {e}")
        await update.callback_query.message.reply_text("❌ Failed to fetch apps. Check API key.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "list_apps":
        await list_apps(update, context)
    elif query.data == "login":
        return await login(update, context)


# --- Main ---
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for login
    login_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(login, pattern="^login$")],
        states={
            GET_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_key)],
        },
        fallbacks=[],
        per_message=True,  # ✅ avoid PTB warning
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(login_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
