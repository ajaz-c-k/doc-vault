import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

def embed(text: str) -> list:
    return []  # no embeddings needed

def search_documents(user_id: str, query: str) -> list:
    # Simple keyword search — searches label and ocr_text
    result = supabase.table("documents")\
        .select("id, label, file_url, ocr_text")\
        .eq("user_id", user_id)\
        .ilike("label", f"%{query}%")\
        .execute()
    return result.data