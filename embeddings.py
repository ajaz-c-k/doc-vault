from sentence_transformers import SentenceTransformer
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
model = SentenceTransformer('all-MiniLM-L6-v2')  # downloads once, ~80MB
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

def embed(text: str) -> list:
    return model.encode(text).tolist()

def search_documents(user_id: str, query: str) -> list:
    query_embedding = embed(query)
    result = supabase.rpc("match_documents", {
        "query_embedding": query_embedding,
        "user_id_input": user_id,
        "match_count": 3
    }).execute()
    
    # CHANGED — only return results above similarity threshold
    filtered = [r for r in result.data if r["similarity"] > 0.3]
    return filtered