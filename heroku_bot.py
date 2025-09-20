import os
import logging
import heroku3
import pymongo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI", "") # MongoDB Change: Get URI from environment

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- MongoDB Connection ---
if not MONGO_URI:
    logger.error("MONGO_URI environment variable not set. Exiting.")
    exit(1)

try:
    client = pymongo.MongoClient(MONGO_URI)
    db = client.get_database("HerokuBotDB")
    user_collection = db.get_collection("users")
    # Test the connection
    client.admin.command('ping')
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"Could not connect to MongoDB: {e}")
    exit(1)

# --- Conversation Handler States ---
ASK_EMAIL, ASK_API_KEY = range(2)

# --- Helper Functions ---
def get_heroku_conn(api_key: str):
    """Establishes a connection to the Heroku API."""
    try:
        return heroku3.from_key(api_key)
    except Exception:
        return None

# --- Main Menu and Start Command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🔐 Login to Heroku", callback_data="login")],
        [InlineKeyboardButton("⚙️ Manage Apps", callback_data="manage_apps")],
        [InlineKeyboardButton("🚪 Logout", callback_data="logout")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to the Heroku Management Bot! 👋\n\n"
        "Please log in to manage your applications.",
        reply_markup=reply_markup,
    )

# --- Login Conversation ---
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please send me your Heroku account email address.\n\n"
        "You can type /cancel to abort."
    )
    return ASK_EMAIL

async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['heroku_email'] = update.message.text.strip()
    await update.message.reply_text(
        "Great. Now, please send me your Heroku API Key.\n\n"
        "⚠️ **Warning**: Your API key grants full access to your account."
    )
    return ASK_API_KEY

async def get_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    api_key = update.message.text.strip()
    
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete API key message: {e}")

    await update.message.reply_text("Authenticating...")
    heroku_conn = get_heroku_conn(api_key)

    if heroku_conn:
        # MongoDB Change: Save the API key to the database
        user_collection.update_one(
            {"_id": user_id},
            {"$set": {"api_key": api_key}},
            upsert=True
        )
        await update.message.reply_text("✅ **Login successful!** Your credentials are now saved.")
        await show_main_menu(update, context, "What would you like to do next?")
    else:
        await update.message.reply_text("❌ **Authentication failed!** The API key seems invalid.")
        await show_main_menu(update, context)
        
    if 'heroku_email' in context.user_data:
        del context.user_data['heroku_email']
        
    return ConversationHandler.END

async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'heroku_email' in context.user_data:
        del context.user_data['heroku_email']
    await update.message.reply_text("Login cancelled.")
    await show_main_menu(update, context)
    return ConversationHandler.END

# --- Button Handler and Actions ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "logout":
        await logout_user(query)
        return
    
    # MongoDB Change: Check if user exists in the database
    if data != "main_menu" and not user_collection.find_one({"_id": user_id}):
        await query.edit_message_text(
            "You are not logged in. Please login first.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Login", callback_data="login")]])
        )
        return
    
    # ... (routing logic remains the same)
    if data == "manage_apps":
        await show_app_management_menu(query)
    # ... etc.

async def logout_user(query: Update.callback_query):
    user_id = query.from_user.id
    # MongoDB Change: Delete the user's document from the database
    result = user_collection.delete_one({"_id": user_id})
    if result.deleted_count > 0:
        text = "✅ You have been successfully logged out."
    else:
        text = "You were not logged in."
    
    # ... (rest of the function is the same)

async def list_apps(query, action_type: str):
    user_id = query.from_user.id
    # MongoDB Change: Retrieve API key from the database
    user_doc = user_collection.find_one({"_id": user_id})
    if not user_doc or "api_key" not in user_doc:
        await query.edit_message_text("Could not find your credentials. Please /logout and login again.")
        return
    api_key = user_doc["api_key"]
    
    # ... (rest of the function is the same)

# Note: All other functions like restart_dyno, scale_dyno, etc., also need to fetch the api_key from the database.
# The following is a sample for restart_dyno. You would apply the same pattern to the others.

async def restart_dyno(query, user_id: int, app_name: str):
    await query.edit_message_text(f"🔄 Restarting dynos for **{app_name}**...", parse_mode="Markdown")
    # MongoDB Change: Retrieve API key from the database
    user_doc = user_collection.find_one({"_id": user_id})
    if not user_doc or "api_key" not in user_doc:
        await query.edit_message_text("Could not find your credentials. Please /logout and login again.")
        return
    api_key = user_doc["api_key"]
    
    heroku_conn = get_heroku_conn(api_key)
    # ... (rest of the function is the same)

# --- (The rest of your functions like show_main_menu, confirm_restart, scale_dyno, etc., need to be included here) ---
# --- (Make sure to apply the same MongoDB logic to fetch the API key in all functions that need it) ---

# --- Main Application Setup ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    login_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_start, pattern="^login$")],
        states={
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            ASK_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel_login)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(login_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
