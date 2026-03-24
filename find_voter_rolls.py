import pdfplumber
import pytesseract
from PIL import Image
import re

PDF_FILE = "part333-2002-SIR-SLG.pdf"

KEYWORDS = [
    "রথীন দে", "রথীন কুমার দে", "বীণাপাণি দে",
    "Rathin Dey", "Rathin Kumar Dey", "Binapani Dey"
]

print(f"🔍 Running full OCR scan on {PDF_FILE}...")

matches = []

with pdfplumber.open(PDF_FILE) as pdf:
    for i, page in enumerate(pdf.pages, start=1):
        img = page.to_image(resolution=300).original
        text = pytesseract.image_to_string(img, lang="ben+eng")
        for kw in KEYWORDS:
            for line in text.splitlines():
                if kw in line:
                    print(f"✅ Page {i}: Found '{kw}' → {line.strip()[:200]}")
                    matches.append((i, kw, line.strip()))

if not matches:
    print("❌ No matches found.")
else:
    print("\n=== MATCH SUMMARY ===")
    for page, kw, line in matches:
        print(f"Page {page}: {kw} → {line}")

