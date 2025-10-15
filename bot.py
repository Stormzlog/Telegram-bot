from telegram import (
    Update,
    LabeledPrice,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
)
from translate import Translator
import datetime
import os

# === Config ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", "-1002780760786"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "6472207061"))

USD_PER_STAR = 0.0251
MAX_STARS_ALLOWED = 15000

# === Subscription Plans ===
PLANS = {
    "1_month": {"name": "1 Month", "price_usd": 100},
    "3_months": {"name": "3 Months", "price_usd": 250},
    "6_months": {"name": "6 Months", "price_usd": 350},
    "1_year": {"name": "1 Year", "price_usd": 400},
}

# === In-memory storage ===
PENDING_APPROVALS = {}
USER_LANGUAGES = {}

# === Translator setup ===
def get_translator(lang="en"):
    return Translator(to_lang=lang)

# === Helper functions ===
def usd_to_stars(usd):
    stars = round(usd / USD_PER_STAR)
    return min(stars, MAX_STARS_ALLOWED)

def flag_for(lang):
    flags = {
        "en": "🇺🇸", "ru": "🇷🇺", "de": "🇩🇪", "fr": "🇫🇷", "es": "🇪🇸",
        "zh-cn": "🇨🇳", "it": "🇮🇹", "pt": "🇵🇹", "ar": "🇸🇦", "ja": "🇯🇵"
    }
    return flags.get(lang, "🌍")

async def t_send(chat, text, user_id):
    lang = USER_LANGUAGES.get(user_id, "en")
    if lang != "en":
        try:
            translator = get_translator(lang)
            text = f"{flag_for(lang)} {translator.translate(text)}"
        except Exception:
            pass
    await chat.reply_text(text)

# === /start command ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    USER_LANGUAGES[user.id] = "en"

    keyboard = [
        [InlineKeyboardButton("💫 Pay via Stars", callback_data="pay_stars")],
        [InlineKeyboardButton("🧾 Pay via Gift Card", callback_data="pay_giftcard")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome to the Premium Channel Access Bot 💎\n\nChoose your payment method:", reply_markup=reply_markup)

# === Handle main menu selection ===
async def main_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "pay_stars":
        keyboard = []
        for key, plan in PLANS.items():
            stars = usd_to_stars(plan["price_usd"])
            label = f"{plan['name']} - ${plan['price_usd']} (~{stars}⭐)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"star_{key}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("💫 Choose a plan to pay with Stars:", reply_markup=reply_markup)

    elif query.data == "pay_giftcard":
        keyboard = [[InlineKeyboardButton("Upload Gift Card & Receipt", callback_data="manual_payment")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("🧾 Upload your Gift Card & Receipt:", reply_markup=reply_markup)

# === Handle Star plan selection ===
async def star_plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_key = query.data.replace("star_", "")
    plan = PLANS[plan_key]
    stars = usd_to_stars(plan["price_usd"])

    await query.message.reply_invoice(
        title=f"{plan['name']} Subscription",
        description=f"Access to the private channel for {plan['name']}.",
        payload=plan_key,
        provider_token="",  # Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(f"{plan['name']} Plan", stars)],
    )

# === Pre-checkout ===
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

# === Payment success ===
async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plan = update.message.successful_payment.invoice_payload
    plan_name = PLANS[plan]["name"]
    user_id = update.message.from_user.id

    await t_send(update.message, f"✅ Payment for {plan_name} successful! Generating your invite link...", user_id)
    invite = await context.bot.create_chat_invite_link(chat_id=GROUP_ID, member_limit=1)
    await t_send(update.message, f"🎉 Here’s your private access link:\n{invite.invite_link}", user_id)

# === Manual payment prompt ===
async def manual_payment_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await t_send(query.message,
        "📸 Please upload your GIFT CARD & PAYMENT RECEIPT image/file below.\n\nOnce received, it will be sent to the admin for verification.", user_id)

# === Forward receipts to admin ===
async def forward_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    caption = (
        f"🧾 New Payment Receipt:\n"
        f"👤 Name: {user.first_name} {user.last_name or ''}\n"
        f"🔗 Username: @{user.username or 'N/A'}\n"
        f"🆔 User ID: {user.id}\n"
        f"🕒 Time: {now}\n\n"
        f"To approve: /approve {user.id}\n"
        f"To disapprove: /disapprove {user.id}"
    )

    await context.bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=update.message.chat_id,
        message_id=update.message.message_id,
    )

    PENDING_APPROVALS[user.id] = {"status": "pending", "time": now}
    await context.bot.send_message(chat_id=ADMIN_ID, text=caption)
    await t_send(update.message, "✅ Your receipt has been sent for review. Please wait for admin approval.", user.id)

# === Admin approval/disapproval ===
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve <user_id>")
        return
    user_id = int(context.args[0])
    if user_id not in PENDING_APPROVALS:
        await update.message.reply_text("❌ No pending approval found.")
        return
    invite = await context.bot.create_chat_invite_link(chat_id=GROUP_ID, member_limit=1)
    await context.bot.send_message(chat_id=user_id, text=f"🎉 Your payment has been verified!\nHere’s your private channel link:\n{invite.invite_link}")
    PENDING_APPROVALS[user_id]["status"] = "approved"
    await update.message.reply_text(f"✅ Approved user {user_id} ✅")

async def disapprove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /disapprove <user_id>")
        return
    user_id = int(context.args[0])
    if user_id not in PENDING_APPROVALS:
        await update.message.reply_text("❌ No pending approval found.")
        return
    await context.bot.send_message(chat_id=user_id, text="❌ Your payment was not approved. Please check your details and try again.")
    PENDING_APPROVALS[user_id]["status"] = "disapproved"
    await update.message.reply_text(f"🚫 Disapproved user {user_id}.")

# === Tracker command ===
async def tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ Unauthorized.")
    if not PENDING_APPROVALS:
        return await update.message.reply_text("No gift card confirmations yet.")
    text = "📊 Gift Card Confirmation Tracker:\n\n"
    for uid, info in PENDING_APPROVALS.items():
        text += f"👤 {uid} — {info['status'].upper()} ({info['time']})\n"
    await update.message.reply_text(text)

# === Run bot ===
def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set in environment variables.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Main commands
    app.add_handler(CommandHandler("start", start))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(main_menu_selection, pattern="^(pay_stars|pay_giftcard)$"))
    app.add_handler(CallbackQueryHandler(star_plan_selected, pattern="^star_"))

    # Payment handlers
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # Receipt upload
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, forward_receipt))

    # Admin commands
    app.add_handler(CommandHandler("approve", approve_user))
    app.add_handler(CommandHandler("disapprove", disapprove_user))
    app.add_handler(CommandHandler("tracker", tracker))

    app.run_polling()

if __name__ == "__main__":
    print("Bot is running...")
    application.run_polling()
