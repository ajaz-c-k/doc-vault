import os
import mimetypes
from supabase import create_client
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# Encryption
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt_file(file_path: str) -> str:
    """Encrypt file contents and save as .enc file"""
    with open(file_path, "rb") as f:
        encrypted = fernet.encrypt(f.read())
    encrypted_path = file_path + ".enc"
    with open(encrypted_path, "wb") as f:
        f.write(encrypted)
    return encrypted_path


def upload_file(file_path: str, user_id: str, label: str) -> str:
    """Encrypt file then upload — returns storage path not public URL"""
    encrypted_path = encrypt_file(file_path)
    dest = f"{user_id}/{label}_{os.path.basename(file_path)}.enc"

    with open(encrypted_path, "rb") as f:
        supabase.storage.from_("documents").upload(
            dest,
            f,
            file_options={"content-type": "application/octet-stream"}
        )

    try:
        os.unlink(encrypted_path)
    except Exception:
        pass

    return dest  # return storage path, NOT public URL


def get_signed_url(storage_path: str, expires_in: int = 300) -> str:
    """Generate signed URL that expires in 5 minutes"""
    result = supabase.storage.from_("documents").create_signed_url(
        storage_path,
        expires_in
    )
    return result["signedURL"]


def save_document(user_id, label, storage_path, file_type, ocr_text, embedding):
    """Save metadata to DB — stores storage path not public URL"""
    supabase.table("documents").insert({
        "user_id": user_id,
        "label": label,
        "file_url": storage_path,
        "file_type": file_type,
        "ocr_text": ocr_text,
    }).execute()