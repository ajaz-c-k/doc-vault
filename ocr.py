import logging

import pytesseract
from PIL import Image
import pdfplumber

logger = logging.getLogger(__name__)

def extract_text(file_path: str, file_type: str) -> str:
    try:
        if file_type == "pdf":
            with pdfplumber.open(file_path) as pdf:
                return " ".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        else:
            # OCR a downscaled copy to avoid spending minutes on high-resolution
            # phone images. The original file remains untouched for storage.
            with Image.open(file_path) as image:
                image.thumbnail((2000, 2000))
                logger.info("Starting image OCR with input size %sx%s", *image.size)
                return pytesseract.image_to_string(image, timeout=20)
    except Exception:
        logger.exception("OCR failed; continuing without extracted text")
        return ""  # OCR failed, still save the doc
