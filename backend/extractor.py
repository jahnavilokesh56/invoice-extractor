"""
extractor.py — Noise-tolerant GST invoice extractor.
Handles garbled PDF text layers (mixed separators, OCR corruption, etc.)
"""

import os
import re
import json
import sys
import argparse
from typing import Any, Dict, List, Optional, Tuple

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


GSTIN_RE  = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}"
PAN_RE    = r"[A-Z]{5}[0-9]{4}[A-Z]"
AMOUNT_RE = r"[\d,]+(?:\.\d+)?"
DATE_RE   = r"\d{1,2}[.\/,\-]\d{1,2}[.\/,\-]\d{2,4}"

# Separator between label and value — flexible: colon, dash, space, dot, pipe
SEP = r"[\s:.\-–|,]*"


def _to_float(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = re.sub(r"[^\d.]", "", raw.replace(",", ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _normalise_date(raw: str) -> str:
    """Normalise date separators to dashes."""
    return re.sub(r"[,./]", "-", raw).strip()


def _clean_text(text: str) -> str:
    text = text.replace("|", " ")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _extract_all_gstins(text: str) -> List[str]:
    """
    GSTINs in PDF text layers often have noise before them:
    'IGSTIN:', 'GSTIN:', 'GSTIN :', etc.
    We search for the 15-char pattern directly.
    """
    return re.findall(GSTIN_RE, text.upper())


def _pan_from_gstin(gstin: str) -> Optional[str]:
    if len(gstin) == 15:
        candidate = gstin[2:12]
        if re.fullmatch(PAN_RE, candidate):
            return candidate
    return None


def _words_to_number(text: str) -> Optional[float]:
    ones = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,
            "seven":7,"eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,
            "thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,
            "eighteen":18,"nineteen":19}
    tens = {"twenty":20,"thirty":30,"forty":40,"fifty":50,
            "sixty":60,"seventy":70,"eighty":80,"ninety":90}
    mults = {"hundred":100,"thousand":1000,"lakh":100000,"crore":10000000}
    words = re.findall(r"[a-z]+", text.lower())
    words = [w for w in words if w not in ("and","only","rupees","paise","rs","inr")]
    total = current = 0
    for word in words:
        if word in ones:     current += ones[word]
        elif word in tens:   current += tens[word]
        elif word == "hundred": current = current * 100 if current else 100
        elif word in mults:
            total += (current if current else 1) * mults[word]
            current = 0
    total += current
    return float(total) if total > 0 else None


# ── Core: find value after a label, tolerating noise ─────────────────────────

def _after(text: str, *patterns: str, multiline=False, max_chars=300) -> Optional[str]:
    """Find first label match and return text after it."""
    for pattern in patterns:
        full = rf"(?i){pattern}{SEP}(.{{1,{max_chars}}})"
        m = re.search(full, text, re.DOTALL if multiline else 0)
        if m:
            val = m.group(1).strip()
            if not multiline:
                val = val.split("\n")[0].strip()
            return val if val else None
    return None


def _number_after(text: str, *patterns: str) -> Optional[float]:
    for pattern in patterns:
        full = rf"(?i){pattern}{SEP}({AMOUNT_RE})"
        m = re.search(full, text)
        if m:
            v = _to_float(m.group(1))
            if v is not None:
                return v
    return None


def _tax_row(text: str, label: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract (rate, amount) for a tax row like 'Integrated tax  5.00%  1,625'"""
    # Pattern: label ... rate% ... amount
    m = re.search(
        rf"(?i){label}[^\d%]*([\d.]+)%[^\d]*({AMOUNT_RE})",
        text
    )
    if m:
        return _to_float(m.group(1)), _to_float(m.group(2))
    return None, None


# ── Invoice number: handle comma/dash confusion ────────────────────────────

def _extract_invoice_number(text: str) -> Optional[str]:
    """
    Matches patterns like:
      K/25-26/064006   K/25,26/064006   MUM-123456-2025
    Also handles label corruption: 'ITax Invoicc No', 'TAX Invoice No', 'Bill no'
    """
    patterns = [
        # Label-driven (label may be corrupted)
        r"(?:I?TAX\s*Invoi[a-z]+\s*No\.?|Invoice\s*No\.?|Bill\s*[Nn]o\.?)" + SEP + r"([A-Z0-9][A-Z0-9/,\-]{4,29})",
        # Direct format match — invoice numbers like K/25-26/064006 or K/25,26/064006
        r"\b(K/\d{2}[,\-]\d{2}/\d{6})\b",
        r"\b([A-Z]{2,5}[/\-]\d{4,6}[/\-]\d{4,6})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", "-").strip()
    return None


def _extract_date(text: str) -> Optional[str]:
    patterns = [
        r"Tax\s*Invoi[a-z]+\s*Date" + SEP + rf"({DATE_RE})",
        r"Bill\s*Date" + SEP + rf"({DATE_RE})",
        r"Invoice\s*Date" + SEP + rf"({DATE_RE})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return _normalise_date(m.group(1))
    return None


def _extract_vendor_name(text: str) -> Optional[str]:
    """Find M/S ... line or first recognisable company line."""
    m = re.search(r"M[/\\]S[^\n]{2,80}", text, re.IGNORECASE)
    if m:
        name = re.sub(r"(?i)M[/\\]S\s*", "", m.group(0)).strip()
        return name if len(name) > 3 else None
    return None


def _extract_vendor_address(text: str) -> Optional[str]:
    """Grab lines between vendor name and GSTIN."""
    m = re.search(
        r"(?:Near|Address|Regd\.?\s*Office)[^\n]{0,200}",
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        block = m.group(0).split("\n")[0]
        return re.sub(r"\s+", " ", block).strip()
    return None


def _extract_customer_name(text: str) -> Optional[str]:
    patterns = [
        # "Name - Reliance ..." or "Name : Reliance ..."
        r"(?:Service\s*Recipient[^\n]*\n\s*)?Name" + SEP + r"((?:Reliance|[\w])[^\n]{5,80})",
        r"(?:Consignee|Bill\s*To|Customer|Buyer)\s*Name" + SEP + r"([^\n]{5,80})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            # Exclude generic strings
            if val and not re.match(r"(?i)^as\s*per", val):
                return val
    return None


def _extract_customer_address(text: str) -> Optional[str]:
    m = re.search(
        r"(?:Flat\s*[Nn]o\.?|Plot\s*[Nn]o\.?)" + SEP + r"(.+?)(?:GSTIN|PAN|State\s*Name|\n\n)",
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _extract_place_of_supply(text: str) -> Optional[str]:
    m = re.search(
        r"Place\s+of\s+[Ss]upply(?:\s+of\s+[Ss]ervice)?" + SEP + r"([A-Za-z][A-Za-z\s]{2,40})",
        text
    )
    if m:
        val = m.group(1).strip()
        return re.split(r"[\d\n]|Code\b|Name\b|PIN\b", val)[0].strip()
    return None


def _extract_sac(text: str) -> Optional[str]:
    patterns = [
        r"SAC" + SEP + r"(?:C[o0]d[ce]|Cdc)" + SEP + r"(?:\+)?\s*(?:Category)?" + SEP + r"(\d{6})",
        r"SAC" + SEP + r"(\d{6})",
        r"\b(99\d{4})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_subtotal(text: str, line_items: list) -> Optional[float]:
    # 1. Freight (in amount) label
    v = _number_after(text,
        r"Freight\s*\(\s*in\s*amount\s*\)",
        r"Freight\s+Amount",
        r"Basic\s+Freight",
    )
    if v and v > 100:
        return v

    # 2. Amount in words → number
    m = re.search(
        r"(?:Freight\s*\(\s*in\s*words?\s*\)|Amount\s+in\s+words?)" + SEP + r"([A-Za-z\s]+?)(?:Only|$|\n)",
        text, re.IGNORECASE
    )
    if m:
        v = _words_to_number(m.group(1))
        if v and v > 100:
            return v

    # 3. Sum line items
    if line_items:
        col = "total_amount" if "total_amount" in line_items[0] else "amount"
        vals = [item.get(col) for item in line_items if item.get(col)]
        if vals:
            return round(sum(vals), 2)

    # 4. Largest comma-formatted number in doc
    candidates = [_to_float(n) for n in re.findall(r"\b\d{1,3},\d{3}(?:\.\d+)?\b", text)]
    valid = [c for c in candidates if c and c > 1000]
    return max(valid) if valid else None


def _extract_igst(text: str, subtotal: Optional[float]) -> Tuple[Optional[str], Optional[float]]:
    rate, amount = _tax_row(text, r"Integrated\s*[Tt]ax|IGST")
    rate_str = f"{rate}%" if rate is not None else None

    if amount is None and rate and subtotal:
        amount = round(subtotal * rate / 100, 2)

    if rate_str is None:
        m = re.search(r"Integrated\s*[Tt]ax[^\d]*([\d.]+)%", text, re.IGNORECASE)
        if m:
            rate_str = m.group(1) + "%"
            if amount is None and subtotal:
                amount = round(subtotal * float(m.group(1)) / 100, 2)

    # Default for interstate GTA
    if rate_str is None:
        rate_str = "5%"
        if subtotal:
            amount = round(subtotal * 0.05, 2)

    return rate_str, amount


def _extract_total_gst(text: str) -> Optional[float]:
    return _number_after(text,
        r"Total\s+GST\s+to\s+be\s+paid[^0-9]*",
        r"Total\s+GST",
        r"Total\s+Tax",
    )


def _extract_grand_total(text: str, subtotal: Optional[float], igst: Optional[float]) -> Optional[float]:
    for label in [
        r"Grand\s+Total",
        r"Total\s+Amount\s+(?:in\s+Rs\.?|Payable)",
        r"Amount\s+Payable",
        r"Invoice\s+Value",
    ]:
        v = _number_after(text, label)
        if v and v > 100:
            return v
    if subtotal and igst:
        return round(subtotal + igst, 2)
    return subtotal


def _parse_line_items(text: str) -> list:
    items = []
    # RC-number anchored pattern — tolerant of varying column counts
    for m in re.finditer(
        r"(RC\d{7,15})"                                 # TCN number
        r"\s+(\d{1,2}[-/]\w{2,3}[-/]\d{2,4})"         # TCN date
        r"\s+(\d{4,12})"                                # indent no
        r".{0,300}?"                                    # flexible middle
        r"([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})"             # vehicle number
        r"\s+(\d{5,8})"                                 # LR no
        r"\s+(\d{1,2}[-/]\w{2,3}[-/]\d{2,4})"         # LR date
        r".{0,50}?"
        r"([\d,]{4,8})\s+"                              # freight
        r"([\d,]{4,8})\s+"                              # detention
        r"([\d,]{4,8})",                                # total
        text, re.IGNORECASE | re.DOTALL
    ):
        try:
            items.append({
                "tcn_number":        m.group(1),
                "tcn_date":          m.group(2),
                "indent_no":         m.group(3),
                "vehicle_number":    m.group(4),
                "lr_number":         m.group(5),
                "lr_date":           m.group(6),
                "freight":           _to_float(m.group(7)),
                "detention_charges": _to_float(m.group(8)),
                "total_amount":      _to_float(m.group(9)),
            })
        except Exception:
            continue

    # Fallback: RC number + final amount
    if not items:
        for m in re.finditer(r"(RC\d{7,15}).{0,200}?([\d,]{4,8})\s*$", text, re.MULTILINE):
            try:
                items.append({
                    "tcn_number":   m.group(1),
                    "total_amount": _to_float(m.group(2)),
                })
            except Exception:
                continue

    return items


# ── PDF / image I/O ───────────────────────────────────────────────────────────

def _pdf_text(path: str) -> str:
    if not PYPDF2_AVAILABLE:
        return ""
    try:
        text = ""
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        return text
    except Exception:
        return ""


def _preprocess(img):
    if not PIL_AVAILABLE:
        return img
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.SHARPEN)
    if OPENCV_AVAILABLE:
        arr = np.array(gray)
        arr = cv2.fastNlMeansDenoising(arr, h=10)
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)
        return Image.fromarray(arr)
    return gray


def _ocr(img) -> str:
    if not (TESSERACT_AVAILABLE and PIL_AVAILABLE):
        return ""
    try:
        return pytesseract.image_to_string(img, config="--oem 3 --psm 6")
    except Exception:
        return ""


def _get_text(file_path: str) -> Tuple[str, str]:
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == ".pdf":
        text = _pdf_text(file_path)
    if len(text.strip()) >= 80:
        return text, "pdf_text_layer"

    images = []
    if ext == ".pdf" and PDF2IMAGE_AVAILABLE:
        try:
            images = convert_from_path(file_path, dpi=300)
        except Exception:
            pass
    elif PIL_AVAILABLE and ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        try:
            images = [Image.open(file_path)]
        except Exception:
            pass

    for img in images:
        text += _ocr(_preprocess(img)) + "\n"

    return text, "ocr"


# ── Public API ────────────────────────────────────────────────────────────────

class InvoiceExtractor:

    def extract(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        raw, source = _get_text(file_path)
        raw = _clean_text(raw)

        gstins = _extract_all_gstins(raw)
        vendor_gstin   = gstins[0] if gstins else None
        customer_gstin = gstins[1] if len(gstins) >= 2 else None

        line_items = _parse_line_items(raw)
        subtotal   = _extract_subtotal(raw, line_items)
        igst_rate, igst_amount = _extract_igst(raw, subtotal)
        cgst_rate, cgst_amount = _tax_row(raw, r"Central\s+Tax|CGST")
        sgst_rate, sgst_amount = _tax_row(raw, r"State\s+Tax|SGST")
        total_gst  = _extract_total_gst(raw) or igst_amount or (
            (cgst_amount or 0) + (sgst_amount or 0)) or None
        grand_total = _extract_grand_total(raw, subtotal, igst_amount)

        vendor_pan = (
            _after(raw, r"\bPAN\b") or
            (_pan_from_gstin(vendor_gstin) if vendor_gstin else None)
        )
        if vendor_pan:
            m = re.search(PAN_RE, vendor_pan.upper())
            vendor_pan = m.group(0) if m else None

        data = {
            "invoice_number":   _extract_invoice_number(raw),
            "invoice_date":     _extract_date(raw),
            "vendor_name":      _extract_vendor_name(raw),
            "vendor_gstin":     vendor_gstin,
            "vendor_pan":       vendor_pan,
            "vendor_address":   _extract_vendor_address(raw),
            "customer_name":    _extract_customer_name(raw),
            "customer_gstin":   customer_gstin,
            "customer_address": _extract_customer_address(raw),
            "place_of_supply":  _extract_place_of_supply(raw),
            "sac_code":         _extract_sac(raw),
            "mode_of_transport": _after(raw, r"Mode\s+of\s+Transport"),
            "freight_amount":   subtotal,
            "freight_in_words": _after(raw, r"Freight\s*\(\s*in\s*words?\s*\)", r"Amount\s+in\s+words?"),
            "central_tax_rate":   f"{cgst_rate}%" if cgst_rate is not None else None,
            "central_tax_amount": cgst_amount,
            "state_tax_rate":     f"{sgst_rate}%" if sgst_rate is not None else None,
            "state_tax_amount":   sgst_amount,
            "igst_rate":          igst_rate,
            "igst_amount":        igst_amount,
            "total_gst":          total_gst,
            "grand_total":        grand_total,
            "line_items":         line_items,
            "source":             source,
            "raw_text_preview":   raw[:500].strip(),
        }

        return {k: (v if v is not None else "") for k, v in data.items()}

    def flatten_for_csv(self, data: Dict[str, Any]) -> List[List[str]]:
        rows = []
        for key, value in data.items():
            if key == "line_items" and isinstance(value, list):
                for i, item in enumerate(value, 1):
                    if isinstance(item, dict):
                        for k, v in item.items():
                            rows.append([f"line_item_{i}_{k}", str(v) if v is not None else ""])
            else:
                rows.append([key, str(value) if value is not None else ""])
        return rows


def main():
    parser = argparse.ArgumentParser(description="GST invoice extractor")
    parser.add_argument("file")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()
    data = InvoiceExtractor().extract(args.file)
    out = json.dumps(data, indent=2, ensure_ascii=False)
    print(out)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)


if __name__ == "__main__":
    main()