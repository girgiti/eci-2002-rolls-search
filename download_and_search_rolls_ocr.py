#!/usr/bin/env python3
# download_and_search_rolls_ocr.py
# Downloads voter roll PDFs & OCR scans for Bengali/English name matches.

import re
import os
import base64
import subprocess
import pdfplumber
import pytesseract
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from difflib import SequenceMatcher
import shutil

# --- Configuration ---
ROLL_URL = "https://ceowestbengal.wb.gov.in/Roll_ps/25"
HTML_FILE = "roll_page.html"
AC_ID = "25"
BASE_DOWNLOAD = "https://ceowestbengal.wb.gov.in/RollPDF/GetDraft"
OUT_DIR = "wb_rolls_downloads"

KEYWORDS = [
    "রথীন দে", "রথীন কুমার দে", "বীণাপাণি দে",
    "Rathin Dey", "Rathin Kumar Dey", "Binapani Dey"
]

OCR_LANG = "ben+eng+hin"
TESSERACT_PSM = ["3", "6", "11"]
TESSERACT_OEM = "3"

# --- OCR Utilities ---
def normalize_line(line):
    line = re.sub(r"[^0-9A-Za-z\u0980-\u09FF ]+", "", line)
    return re.sub(r"\s+", " ", line.strip())

def is_similar(a, b, threshold=0.85):
    return SequenceMatcher(None, a, b).ratio() >= threshold

def fuzzy_dedup(lines):
    unique = []
    for line in lines:
        if not any(is_similar(line, u) for u in unique):
            unique.append(line)
    return unique

def preprocess_variants(pil_img):
    imgs = []
    img = pil_img.convert("L")
    base_w = max(1200, img.width)
    ratio = base_w / img.width
    img = img.resize((base_w, int(img.height * ratio)), Image.LANCZOS)
    imgs.append(img)

    # Contrast & sharpening
    enh = ImageEnhance.Contrast(img).enhance(1.8)
    enh = ImageEnhance.Sharpness(enh).enhance(1.2)
    imgs.append(enh)

    # Median filter & autocontrast
    mf = ImageOps.autocontrast(img).filter(ImageFilter.MedianFilter(3))
    imgs.append(mf)

    # Binary thresholds
    for thresh in (150, 140, 120):
        bin_img = img.point(lambda p: 255 if p > thresh else 0)
        imgs.append(bin_img)

    # Inverted
    inv = ImageOps.invert(img)
    imgs.append(inv)
    imgs.append(ImageOps.autocontrast(inv))
    return imgs

def ocr_try(img):
    lines_out = []
    seen = set()
    for psm in TESSERACT_PSM:
        cfg = f"--oem {TESSERACT_OEM} --psm {psm}"
        try:
            txt = pytesseract.image_to_string(img, lang=OCR_LANG, config=cfg)
        except Exception:
            txt = ""
        if not txt:
            continue
        for ln in txt.splitlines():
            s = normalize_line(ln)
            if s and s not in seen:
                seen.add(s)
                lines_out.append(s)
    return lines_out

def full_page_ocr(pil_img):
    lines = []
    seen = set()
    for var in preprocess_variants(pil_img):
        for ln in ocr_try(var):
            if ln not in seen:
                seen.add(ln)
                lines.append(ln)
    return fuzzy_dedup(lines)

# --- Step 1: Download roll_page.html ---
print(f"🌐 Fetching roll list HTML from {ROLL_URL} ...")
try:
    subprocess.run(["curl", "-k", "-L", "-s", ROLL_URL, "-o", HTML_FILE], check=True)
    print(f"✅ Saved HTML to {HTML_FILE}")
except subprocess.CalledProcessError:
    print("❌ Failed to fetch roll_page.html. Check your internet connection.")
    raise SystemExit(1)

# --- Step 2: Parse HTML for filenames ---
os.makedirs(OUT_DIR, exist_ok=True)
with open(HTML_FILE, "r", encoding="utf-8", errors="ignore") as f:
    html = f.read()

filenames = sorted(set(re.findall(r"AC0?\d+PART\d+\.pdf", html)))
print(f"📄 Found {len(filenames)} PDF filenames in HTML (example: {filenames[:3]})")

if not filenames:
    print("❌ No filenames found. The site may have changed its structure.")
    raise SystemExit(1)

matches = []
processed = []

# --- Step 3: Download and OCR each PDF ---
for name in filenames:
    key = base64.b64encode(name.encode("utf-8")).decode("ascii")
    url = f"{BASE_DOWNLOAD}?acId={AC_ID}&key={key}"
    outpath = os.path.join(OUT_DIR, name)

    print(f"\n⬇️  Downloading {name}")
    cmd = ["curl", "-k", "-L", "-s", url, "-o", outpath]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        print("⚠️ Download failed, skipping.")
        continue

    found_in_this_pdf = False
    print(f"🔍 Scanning {name} for keywords...")

    try:
        with pdfplumber.open(outpath) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                pil_img = page.to_image(resolution=300).original
                lines = full_page_ocr(pil_img)

                for line in lines:
                    for kw in KEYWORDS:
                        if kw.lower() in line.lower():
                            print(f"✅ [{kw}] Page {page_num}: {line}")
                            matches.append((name, page_num, kw, line))
                            found_in_this_pdf = True
    except Exception as e:
        print(f"⚠️ Error scanning {name}: {e}")

    processed.append(outpath)

    # Auto-delete PDFs with no matches
    if not found_in_this_pdf:
        try:
            os.remove(outpath)
            print(f"🧹 No matches → deleted {name}")
        except Exception as e:
            print(f"⚠️ Could not delete {name}: {e}")

# --- Step 4: Summary ---
if matches:
    print("\n=== SUMMARY OF MATCHES ===")
    for name, page, kw, line in matches:
        print(f"{name} (Page {page}) [{kw}] → {line}")
else:
    print("\n❌ No matches found across all PDFs.")

# --- Optional: Clean empty folder ---
if not matches:
    try:
        shutil.rmtree(OUT_DIR)
        print("🧽 Deleted empty downloads directory.")
    except Exception:
        pass

