import os
import tempfile
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
from telegram.request import HTTPXRequest

# Custom modules
from ocr import extract_text
from storage import upload_file, save_document, supabase
from embeddings import embed, search_documents

# Load env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

WAITING_LABEL = 1


# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to DocVault!\n\n"
        "📤 Send any document or image\n"
        "💡 Add a caption to auto-label it\n"
        "🔍 Use /find <query>\n"
        "📋 Use /list"
    )


# ---------------- HELP ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Start bot\n"
        "/find <text> - Search docs\n"
        "/list - Show all docs\n"
        "Send file/photo to store\n"
        "Tip: Add a caption to skip labeling!"
    )


# ---------------- SHARED SAVE LOGIC ----------------
async def process_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    file_path = context.user_data["file_path"]
    file_type = context.user_data["file_type"]
    user_id = str(update.effective_user.id)

    ocr_text = extract_text(file_path, file_type)
    file_url = upload_file(file_path, user_id, label)
    embedding = embed(label + " " + ocr_text)
    save_document(user_id, label, file_url, file_type, ocr_text, embedding)

    os.unlink(file_path)
    await update.message.reply_text(f"✅ '{label}' stored successfully!")


# ---------------- RECEIVE FILE ----------------
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.photo:
        file = await context.bot.get_file(
            msg.photo[-1].file_id,
            read_timeout=60,
            write_timeout=60
        )
        file_type = "image"
        suffix = ".jpg"

    elif msg.document:
        file = await context.bot.get_file(
            msg.document.file_id,
            read_timeout=60,
            write_timeout=60
        )
        file_type = "pdf" if msg.document.mime_type == "application/pdf" else "file"
        suffix = ".pdf" if file_type == "pdf" else ".jpg"

    else:
        return

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    await file.download_to_drive(tmp.name, read_timeout=60)

    context.user_data["file_path"] = tmp.name
    context.user_data["file_type"] = file_type

    # CHANGED — if caption exists, use it as label directly, skip asking
    if msg.caption and msg.caption.strip():
        label = msg.caption.strip()
        await update.message.reply_text("⏳ Processing...")
        await process_and_save(update, context, label)
        return ConversationHandler.END  # CHANGED — skip label step entirely

    await update.message.reply_text("✅ Got it! What should I label this file?")
    return WAITING_LABEL


# ---------------- RECEIVE LABEL ----------------
async def receive_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = update.message.text.strip()
    await update.message.reply_text("⏳ Processing...")
    await process_and_save(update, context, label)
    return ConversationHandler.END


# ---------------- FIND ----------------
async def find_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage: /find <what you're looking for>")
        return

    results = search_documents(str(update.effective_user.id), query)

    if not results:
        await update.message.reply_text("❌ Nothing found.")
        return

    for doc in results:
        await update.message.reply_text(
            f"📄 {doc['label']}\n🔗 {doc['file_url']}"
        )


# ---------------- LIST ----------------
async def list_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = supabase.table("documents")\
        .select("label, created_at")\
        .eq("user_id", str(update.effective_user.id))\
        .order("created_at", desc=True)\
        .execute()

    if not result.data:
        await update.message.reply_text("No documents stored yet.")
        return

    lines = [f"📄 {d['label']}" for d in result.data]
    await update.message.reply_text("\n".join(lines))


# ---------------- MAIN ----------------
def main():
    request = HTTPXRequest(
        read_timeout=60,
        write_timeout=60,
        connect_timeout=60
    )

    app = ApplicationBuilder().token(TOKEN).request(request).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO | filters.Document.ALL, receive_file)
        ],
        states={
            WAITING_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_label)
            ],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("find", find_doc))
    app.add_handler(CommandHandler("list", list_docs))
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()