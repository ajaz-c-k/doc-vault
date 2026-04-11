import os
import mimetypes
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


def upload_file(file_path: str, user_id: str, label: str) -> str:
    dest = f"{user_id}/{label}_{os.path.basename(file_path)}"

    mime, _ = mimetypes.guess_type(file_path)
    mime = mime or "application/octet-stream"

    with open(file_path, "rb") as f:
        supabase.storage.from_("documents").upload(
            dest,
            f,
            file_options={"content-type": mime}  # ✅ FIXED
        )

    url = supabase.storage.from_("documents").get_public_url(dest)
    return url


def save_document(user_id, label, file_url, file_type, ocr_text, embedding):
    supabase.table("documents").insert({
        "user_id": user_id,
        "label": label,
        "file_url": file_url,
        "file_type": file_type,
        "ocr_text": ocr_text,
        # embedding column skipped — no vector search
    }).execute()