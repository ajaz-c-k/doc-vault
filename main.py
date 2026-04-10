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

# Import custom modules
from ocr import extract_text
from storage import upload_file, save_document, supabase
from embeddings import embed, search_documents

# Load env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Conversation state
WAITING_LABEL = 1


# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to DocVault!\n\n"
        "📤 Send any document or image\n"
        "🔍 Use /find <query>\n"
        "📋 Use /list"
    )


# ---------------- HELP ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Start bot\n"
        "/find <text> - Search docs\n"
        "/list - Show all docs\n"
        "Send file/photo to store"
    )


# ---------------- RECEIVE FILE ----------------
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.photo:
        file = await msg.photo[-1].get_file()
        file_type = "image"
    elif msg.document:
        file = await msg.document.get_file()
        file_type = "pdf" if msg.document.mime_type == "application/pdf" else "file"
    else:
        return

    suffix = ".pdf" if file_type == "pdf" else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)

    await file.download_to_drive(tmp.name)

    context.user_data["file_path"] = tmp.name
    context.user_data["file_type"] = file_type

    await update.message.reply_text("✅ Got it! Send label for this file:")
    return WAITING_LABEL


# ---------------- RECEIVE LABEL ----------------
async def receive_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = update.message.text.strip()
    file_path = context.user_data["file_path"]
    file_type = context.user_data["file_type"]
    user_id = str(update.effective_user.id)

    await update.message.reply_text("⏳ Processing...")

    # OCR
    ocr_text = extract_text(file_path, file_type)

    # Upload
    file_url = upload_file(file_path, user_id, label)

    # Embedding
    embedding = embed(label + " " + ocr_text)

    # Save to DB
    save_document(user_id, label, file_url, file_type, ocr_text, embedding)

    # Delete temp file
    os.unlink(file_path)

    await update.message.reply_text(f"✅ '{label}' stored successfully!")
    return ConversationHandler.END


# ---------------- FIND ----------------
async def find_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage: /find <query>")
        return

    results = search_documents(str(update.effective_user.id), query)

    if not results:
        await update.message.reply_text("❌ Nothing found.")
        return

    for doc in results:
        await update.message.reply_text(
            f"📄 *{doc['label']}*\n🔗 {doc['file_url']}",
            parse_mode="Markdown"
        )


# ---------------- LIST ----------------
async def list_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = supabase.table("documents")\
        .select("label")\
        .eq("user_id", str(update.effective_user.id))\
        .execute()

    if not result.data:
        await update.message.reply_text("No documents stored yet.")
        return

    lines = [f"📄 {d['label']}" for d in result.data]
    await update.message.reply_text("\n".join(lines))


# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Conversation flow
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

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("find", find_doc))
    app.add_handler(CommandHandler("list", list_docs))
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()