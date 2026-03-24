#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wb_rolls_cli.py – West Bengal voter roll downloader + OCR search tool.
Now exits immediately after showing matches (no summary block).
"""

import os
import re
import sys
import base64
import subprocess
import shutil
import argparse
import pdfplumber
import pytesseract
from bs4 import BeautifulSoup
from PIL import Image, ImageFilter, ImageOps, ImageEnhance

# ---- Config ----
BASE = "https://ceowestbengal.wb.gov.in"
ROLL_DIST_URL = f"{BASE}/roll_dist"
ROLL_AC_URL = f"{BASE}/Roll_ac"
ROLL_PS_URL = f"{BASE}/Roll_ps"
GETDRAFT_URL = f"{BASE}/RollPDF/GetDraft"

OUT_DIR = "wb_rolls_downloads"
HTML_DIR = "wb_html_cache"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)

"""
KEYWORDS = [
    "রথীন দে", "রথীন কুমার দে", "বীণাপাণি দে",
    "Rathin Dey", "Rathin Kumar Dey", "Binapani Dey"
]"""

KEYWORDS = [
    "সঙ্গীতা দাস","সঙ্গীতা দে (দাস)" ,
    "Sangita Das", "Sangita Dey (Das)"
]


OCR_LANG = "ben+eng"
TESSERACT_PSM = ["3", "6", "11"]
TESSERACT_OEM = "3"

# ---- Network (curl to bypass legacy TLS) ----
def fetch_html_with_curl(url: str) -> str:
    try:
        proc = subprocess.run(
            ["curl", "-k", "-L", "-s", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
            timeout=60
        )
        return proc.stdout
    except Exception as e:
        print(f"❌ curl failed to fetch {url}: {e}")
        return ""

# ---- OCR helpers ----
def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()

def preprocess_variants(pil_img):
    imgs = []
    img = pil_img.convert("L")
    base_w = max(1200, img.width)
    ratio = base_w / img.width
    img = img.resize((base_w, int(img.height * ratio)), Image.LANCZOS)
    imgs.append(img)
    enh = ImageEnhance.Contrast(img).enhance(1.8)
    enh = ImageEnhance.Sharpness(enh).enhance(1.2)
    imgs.append(enh)
    mf = ImageOps.autocontrast(img).filter(ImageFilter.MedianFilter(3))
    imgs.append(mf)
    for thresh in (150, 140, 120):
        bin_img = img.point(lambda p: 255 if p > thresh else 0)
        imgs.append(bin_img)
    inv = ImageOps.invert(img)
    imgs.append(inv)
    imgs.append(ImageOps.autocontrast(inv))
    return imgs

def ocr_try(img):
    results = []
    for psm in TESSERACT_PSM:
        cfg = f"--oem {TESSERACT_OEM} --psm {psm}"
        try:
            txt = pytesseract.image_to_string(img, lang=OCR_LANG, config=cfg)
        except Exception:
            txt = ""
        if txt and txt.strip():
            for ln in txt.splitlines():
                s = normalize_line(ln)
                if s:
                    results.append(s)
    return results

def full_page_ocr(pil_img):
    lines = []
    for var in preprocess_variants(pil_img):
        lines.extend(ocr_try(var))
    return [ln for ln in lines if ln.strip()]

# ---- HTML helpers ----
def parse_districts_from_html(html_text: str):
    soup = BeautifulSoup(html_text, "html.parser")
    pairs = []
    for a in soup.find_all("a", href=True):
        href = a["href"].replace("\\", "/")
        if "Roll_ac" in href:
            name = a.get_text(" ", strip=True)
            pairs.append((name, href))
    seen = set(); out=[]
    for n,h in pairs:
        if n and n not in seen:
            out.append((n,h)); seen.add(n)
    return out

def parse_ac_list_from_html(html_text: str):
    soup = BeautifulSoup(html_text, "html.parser")
    pairs = []
    for a in soup.find_all("a", href=True):
        href = a["href"].replace("\\", "/")
        if "Roll_ps" in href:
            name = a.get_text(" ", strip=True)
            pairs.append((name, href))
    seen = set(); out=[]
    for n,h in pairs:
        if n and n not in seen:
            out.append((n,h)); seen.add(n)
    return out

def extract_part_filenames_and_rowtext(html_text: str):
    mapping = {}
    soup = BeautifulSoup(html_text, "html.parser")
    for a in soup.find_all("a", onclick=True):
        onclick = a["onclick"]
        m = re.search(r"(AC0?\d+PART\d+\.pdf)", onclick, re.IGNORECASE)
        if m:
            fn = m.group(1)
            parent = a.find_parent(['tr','li','p','div'])
            row_text = parent.get_text(" ", strip=True) if parent else a.get_text(" ", strip=True)
            mapping[fn] = re.sub(r"\s+", " ", row_text)
    for m in re.finditer(r'(AC0?\d+PART\d+\.pdf)', html_text, re.IGNORECASE):
        fn = m.group(1)
        if fn not in mapping:
            mapping[fn] = fn
    return mapping

# ---- Interactive flow ----
def interactive_flow():
    print(f"🌐 Fetching district list: {ROLL_DIST_URL}")
    dist_html = fetch_html_with_curl(ROLL_DIST_URL)
    if not dist_html:
        sys.exit("❌ Could not fetch district list.")

    districts = parse_districts_from_html(dist_html)
    if not districts:
        sys.exit("❌ No districts parsed from HTML.")

    print("\nAvailable districts:")
    for name, href in districts[:200]:
        print(" -", name)

    district_input = input("\nEnter District name (exact or partial): ").strip()
    matches = [(n, h) for (n, h) in districts if district_input.lower() in n.lower()]
    if not matches:
        sys.exit("❌ District not found.")
    district_name, district_href = matches[0]
    print(f"Selected District: {district_name}")

    m = re.search(r"/Roll_ac/(\d+)", district_href)
    district_id = m.group(1) if m else input("Enter district id: ").strip()
    ac_html = fetch_html_with_curl(f"{ROLL_AC_URL}/{district_id}")
    acs = parse_ac_list_from_html(ac_html)
    if not acs:
        sys.exit("❌ No ACs found.")
    print("\nAvailable ACs:")
    for n, _ in acs[:200]:
        print(" -", n)

    ac_input = input("\nEnter Assembly Constituency: ").strip()
    ac_matches = [(n, h) for (n, h) in acs if ac_input.lower() in n.lower()]
    if not ac_matches:
        sys.exit("❌ AC not found.")
    ac_name, ac_href = ac_matches[0]
    print(f"Selected AC: {ac_name}")

    m2 = re.search(r"/Roll_ps/(\d+)", ac_href)
    ac_id = m2.group(1) if m2 else input("Enter AC id: ").strip()

    roll_html = fetch_html_with_curl(f"{ROLL_PS_URL}/{ac_id}")
    parts = extract_part_filenames_and_rowtext(roll_html)
    if not parts:
        sys.exit("⚠️ No parts found.")

    print("\nSearch mode:")
    print("1) By Part number")
    print("2) By Booth name")
    mode = input("Enter 1 or 2: ").strip()

    if mode == "1":
        p = input("Enter part number: ").strip()
        targets = [fn for fn in parts if re.search(rf"{re.escape(p)}", fn, re.IGNORECASE)]
    else:
        q = input("Enter booth name text: ").strip().lower()
        targets = [fn for fn, row in parts.items() if q in row.lower()]

    if not targets:
        sys.exit("No matching part number found.")

    print(f"\nFound {len(targets)} matching file(s). Will download and search these.")

    for fname in sorted(set(targets)):
        key = base64.b64encode(fname.encode("utf-8")).decode("ascii")
        url = f"{GETDRAFT_URL}?acId={ac_id}&key={key}"
        outpath = os.path.join(OUT_DIR, fname)
        print(f"\n⬇️ Downloading {fname}")
        subprocess.run(["curl", "-k", "-L", "-s", url, "-o", outpath], check=False)

        matched_any = False
        try:
            with pdfplumber.open(outpath) as pdf:
                total = len(pdf.pages)
                for i, page in enumerate(pdf.pages, 1):
                    print(f"  🔍 Scanning page {i}/{total} of {fname} ...")
                    try:
                        selectable = page.extract_text() or ""
                    except Exception:
                        selectable = ""
                    lines = [normalize_line(l) for l in selectable.splitlines() if l.strip()]
                    img = page.to_image(resolution=300).original
                    lines += full_page_ocr(img)
                    for line in lines:
                        for kw in KEYWORDS:
                            if kw.lower() in line.lower():
                                print(f"✅ [{kw}] {fname} (p{i}): {line}")
                                matched_any = True
                    if matched_any:
                        break
            if matched_any:
                print("\n✅ Matches found. Exiting.\n")
                sys.exit(0)
            else:
                os.remove(outpath)
                print(f"🧹 Deleted {fname} (no matches)")
        except Exception as e:
            print("⚠️ Error reading PDF:", e)
            continue

    print("\n❌ No matches found in selected parts.")
    sys.exit(0)

# ---- Entry ----
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    args = parser.parse_args()
    if args.interactive:
        interactive_flow()
    else:
        print("Usage: python3 wb_rolls_cli.py --interactive")

if __name__ == "__main__":
    main()

