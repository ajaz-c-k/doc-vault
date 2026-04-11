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

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY.encode())


def encrypt_file(file_path: str) -> str:
    """Encrypt file and return path to encrypted version"""
    with open(file_path, "rb") as f:
        encrypted = fernet.encrypt(f.read())
    encrypted_path = file_path + ".enc"
    with open(encrypted_path, "wb") as f:
        f.write(encrypted)
    return encrypted_path


def decrypt_bytes(encrypted_bytes: bytes) -> bytes:
    """Decrypt raw bytes back to original file bytes"""
    return fernet.decrypt(encrypted_bytes)


def upload_file(file_path: str, user_id: str, label: str) -> str:
    """Encrypt then upload — returns storage path"""
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

    return dest  # storage path only


def download_and_decrypt(storage_path: str, output_path: str):
    """Download encrypted file from storage, decrypt, save to output_path"""
    encrypted_bytes = supabase.storage.from_("documents").download(storage_path)
    decrypted_bytes = decrypt_bytes(encrypted_bytes)
    with open(output_path, "wb") as f:
        f.write(decrypted_bytes)


def save_document(user_id, label, storage_path, file_type, ocr_text, embedding):
    supabase.table("documents").insert({
        "user_id": user_id,
        "label": label,
        "file_url": storage_path,
        "file_type": file_type,
        "ocr_text": ocr_text,
    }).execute()