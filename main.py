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
from storage import upload_file, save_document, download_and_decrypt, supabase
from embeddings import embed, search_documents

# Load env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

WAITING_LABEL = 1
WAITING_DELETE = 2
WAITING_FIND_NUMBER = 3


# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to DocVault!\n\n"
        "Store and retrieve your important documents anytime, anywhere.\n\n"
        "📤 Send any document or photo to store it\n"
        "💡 Add a caption while sending to auto-label\n"
        "🔍 /find — list all docs, pick by number\n"
        "🔍 /find <n> — search directly by name\n"
        "📋 /list — see all stored documents\n"
        "🗑️ /delete — remove a document\n"
        "❓ /help — show commands\n\n"
        "🔒 Your files are encrypted at rest.\n\n"
        "Built by Ajaz ⚡"
    )


# ---------------- HELP ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 DocVault Commands\n\n"
        "📤 Send file/photo — store a document\n"
        "💡 Send with caption — auto-labels it\n"
        "🔍 /find — shows numbered list, reply with number\n"
        "🔍 /find <text> — search directly by name\n"
        "📋 /list — show all your documents\n"
        "🗑️ /delete — pick from list to delete\n"
        "🗑️ /delete <n> — delete by name\n\n"
        "Built by Ajaz ⚡"
    )


# ---------------- SHARED SAVE LOGIC ----------------
async def process_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    file_path = context.user_data["file_path"]
    file_type = context.user_data["file_type"]
    user_id = str(update.effective_user.id)

    ocr_text = extract_text(file_path, file_type)
    storage_path = upload_file(file_path, user_id, label)
    embedding = embed(label + " " + ocr_text)
    save_document(user_id, label, storage_path, file_type, ocr_text, embedding)

    try:
        os.unlink(file_path)
    except Exception:
        pass

    await update.message.reply_text(f"✅ '{label}' stored successfully! 🔒")


# ---------------- SEND FILE TO USER ----------------
async def send_decrypted_file(update: Update, doc: dict):
    """Download, decrypt and send actual file back to user"""
    storage_path = doc["file_url"]
    file_type = doc.get("file_type", "file")
    label = doc["label"]

    # Determine suffix from storage path
    if storage_path.endswith(".pdf.enc"):
        suffix = ".pdf"
    else:
        suffix = ".jpg"

    # Download and decrypt to temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()

    await update.message.reply_text(f"⏳ Retrieving '{label}'...")

    try:
        download_and_decrypt(storage_path, tmp.name)

        # Send actual file back to user
        with open(tmp.name, "rb") as f:
            if suffix == ".pdf":
                await update.message.reply_document(
                    document=f,
                    filename=f"{label}.pdf",
                    caption=f"📄 {label}"
                )
            else:
                await update.message.reply_photo(
                    photo=f,
                    caption=f"📄 {label}"
                )
    except Exception as e:
        await update.message.reply_text(f"❌ Could not retrieve '{label}'. Try again.")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


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
        await update.message.reply_text("⏳ Encrypting and storing...")
        await process_and_save(update, context, label)
        return ConversationHandler.END

    await update.message.reply_text("✅ Got it! What should I label this file?")
    return WAITING_LABEL


# ---------------- RECEIVE LABEL ----------------
async def receive_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = update.message.text.strip()
    await update.message.reply_text("⏳ Encrypting and storing...")
    await process_and_save(update, context, label)
    return ConversationHandler.END


# ---------------- FIND ----------------
async def find_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    query = " ".join(context.args)

    # /find <name> — search directly
    if query:
        results = search_documents(user_id, query)
        if not results:
            await update.message.reply_text("❌ Nothing found.")
            return ConversationHandler.END

        for doc in results:
            await send_decrypted_file(update, doc)
        return ConversationHandler.END

    # /find only — show numbered list
    result = supabase.table("documents")\
        .select("id, label, file_url, file_type")\
        .eq("user_id", user_id)\
        .order("label", desc=False)\
        .execute()

    if not result.data:
        await update.message.reply_text("No documents stored yet. Send a file to get started!")
        return ConversationHandler.END

    context.user_data["find_list"] = result.data
    lines = [f"{i+1}. {d['label']}" for i, d in enumerate(result.data)]
    await update.message.reply_text(
        f"📋 Your Documents ({len(lines)} total)\n"
        f"Reply with a number to retrieve:\n\n" +
        "\n".join(lines)
    )
    return WAITING_FIND_NUMBER


# ---------------- FIND BY NUMBER ----------------
async def find_by_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = int(update.message.text.strip()) - 1
        docs = context.user_data.get("find_list", [])

        if index < 0 or index >= len(docs):
            await update.message.reply_text("❌ Invalid number. Try /find again.")
            return ConversationHandler.END

        doc = docs[index]
        await send_decrypted_file(update, doc)

    except ValueError:
        await update.message.reply_text("❌ Please send a valid number. Try /find again.")

    return ConversationHandler.END


# ---------------- LIST ----------------
async def list_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = supabase.table("documents")\
        .select("label, created_at")\
        .eq("user_id", str(update.effective_user.id))\
        .order("label", desc=False)\
        .execute()

    if not result.data:
        await update.message.reply_text("No documents stored yet. Send a file to get started!")
        return

    lines = [f"{i+1}. {d['label']}" for i, d in enumerate(result.data)]
    await update.message.reply_text(
        f"📋 Your Documents ({len(lines)} total)\n\n" + "\n".join(lines)
    )


# ---------------- DELETE ----------------
async def delete_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if context.args:
        label = " ".join(context.args)
        result = supabase.table("documents")\
            .select("id, label, file_url")\
            .eq("user_id", user_id)\
            .ilike("label", f"%{label}%")\
            .execute()

        if not result.data:
            await update.message.reply_text(f"❌ No document found matching '{label}'")
            return ConversationHandler.END

        doc = result.data[0]
        try:
            supabase.storage.from_("documents").remove([doc["file_url"]])
        except Exception:
            pass
        supabase.table("documents").delete().eq("id", doc["id"]).execute()
        await update.message.reply_text(f"🗑️ '{doc['label']}' deleted successfully!")
        return ConversationHandler.END

    result = supabase.table("documents")\
        .select("id, label, file_url")\
        .eq("user_id", user_id)\
        .order("label", desc=False)\
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
        try:
            supabase.storage.from_("documents").remove([doc["file_url"]])
        except Exception:
            pass
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
            CommandHandler("find", find_doc),
        ],
        states={
            WAITING_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_label)
            ],
            WAITING_DELETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)
            ],
            WAITING_FIND_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, find_by_number)
            ],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_docs))
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()