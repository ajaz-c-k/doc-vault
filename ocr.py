import pytesseract
from PIL import Image
import pdfplumber

def extract_text(file_path: str, file_type: str) -> str:
    try:
        if file_type == "pdf":
            with pdfplumber.open(file_path) as pdf:
                return " ".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        else:
            return pytesseract.image_to_string(Image.open(file_path))
    except Exception:
        return ""  # OCR failed, still save the doc