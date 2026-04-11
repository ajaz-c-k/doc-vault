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
WAITING_DELETE = 2


# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to DocVault!\n\n"
        "Store and retrieve your important documents anytime, anywhere.\n\n"
        "📤 Send any document or photo to store it\n"
        "💡 Add a caption while sending to auto-label\n"
        "🔍 /find <name> — search your documents\n"
        "📋 /list — see all stored documents\n"
        "🗑️ /delete — remove a document\n"
        "❓ /help — show commands\n\n"
        "Built by Ajaz "
    )


# ---------------- HELP ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 DocVault Commands\n\n"
        "📤 Send file/photo — store a document\n"
        "💡 Send with caption — auto-labels it\n"
        "🔍 /find <text> — search your docs\n"
        "📋 /list — show all your documents\n"
        "🗑️ /delete — pick from list to delete\n"
        "🗑️ /delete <name> — delete by name\n\n"
        "Built by Ajaz "
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

    try:
        os.unlink(file_path)
    except Exception:
        pass
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
    tmp.close()
    await file.download_to_drive(tmp.name, read_timeout=60)

    context.user_data["file_path"] = tmp.name
    context.user_data["file_type"] = file_type

    if msg.caption and msg.caption.strip():
        label = msg.caption.strip()
        await update.message.reply_text("⏳ Processing...")
        await process_and_save(update, context, label)
        return ConversationHandler.END

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
        await update.message.reply_text("No documents stored yet. Send a file to get started!")
        return

    lines = [f"📄 {d['label']}" for d in result.data]
    await update.message.reply_text(
        f"📋 Your Documents ({len(lines)} total)\n\n" + "\n".join(lines)
    )


# ---------------- DELETE ----------------
async def delete_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if context.args:
        label = " ".join(context.args)
        result = supabase.table("documents")\
            .select("id, label")\
            .eq("user_id", user_id)\
            .ilike("label", f"%{label}%")\
            .execute()

        if not result.data:
            await update.message.reply_text(f"❌ No document found matching '{label}'")
            return ConversationHandler.END

        doc = result.data[0]
        supabase.table("documents").delete().eq("id", doc["id"]).execute()
        await update.message.reply_text(f"🗑️ '{doc['label']}' deleted successfully!")
        return ConversationHandler.END

    result = supabase.table("documents")\
        .select("id, label")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .execute()

    if not result.data:
        await update.message.reply_text("No documents to delete.")
        return ConversationHandler.END

    context.user_data["delete_list"] = result.data
    lines = [f"{i+1}. {d['label']}" for i, d in enumerate(result.data)]
    await update.message.reply_text(
        "🗑️ Which document to delete?\nReply with the number:\n\n" + "\n".join(lines)
    )
    return WAITING_DELETE


# ---------------- CONFIRM DELETE ----------------
async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = int(update.message.text.strip()) - 1
        docs = context.user_data.get("delete_list", [])

        if index < 0 or index >= len(docs):
            await update.message.reply_text("❌ Invalid number. Try /delete again.")
            return ConversationHandler.END

        doc = docs[index]
        supabase.table("documents").delete().eq("id", doc["id"]).execute()
        await update.message.reply_text(f"🗑️ '{doc['label']}' deleted successfully!")

    except ValueError:
        await update.message.reply_text("❌ Please send a valid number. Try /delete again.")

    return ConversationHandler.END


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
            MessageHandler(filters.PHOTO | filters.Document.ALL, receive_file),
            CommandHandler("delete", delete_doc),
        ],
        states={
            WAITING_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_label)
            ],
            WAITING_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)
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