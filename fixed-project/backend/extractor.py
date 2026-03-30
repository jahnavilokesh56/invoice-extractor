"""
extractor.py — Universal GST invoice extractor.
Handles:
  - Government of India e-Invoice System format
  - GTA (Goods Transport Agency) invoices — Karnataka Roadlines, S.P. Golden etc.
  - General GST invoices
  - Garbled PDF text layers / OCR output
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
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


# ── Regex constants ───────────────────────────────────────────────────────────
GSTIN_RE  = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}"
PAN_RE    = r"[A-Z]{5}[0-9]{4}[A-Z]"
AMOUNT_RE = r"[\d,]+(?:\.\d+)?"
DATE_RE   = r"\d{1,2}[.\/,\-]\d{1,2}[.\/,\-]\d{2,4}"
SEP       = r"[\s:.\-–|,]*"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_float(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = re.sub(r"[^\d.]", "", str(raw).replace(",", ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _normalise_date(raw: str) -> str:
    return re.sub(r"[,./]", "-", raw).strip()


def _clean_text(text: str) -> str:
    text = text.replace("|", " ")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def _extract_all_gstins(text: str) -> List[str]:
    return re.findall(GSTIN_RE, text.upper())


def _pan_from_gstin(gstin: str) -> Optional[str]:
    if len(gstin) == 15:
        candidate = gstin[2:12]
        if re.fullmatch(PAN_RE, candidate):
            return candidate
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


def _after(text: str, *patterns: str, multiline=False, max_chars=300) -> Optional[str]:
    for pattern in patterns:
        full = rf"(?i){pattern}{SEP}(.{{1,{max_chars}}})"
        m = re.search(full, text, re.DOTALL if multiline else 0)
        if m:
            val = m.group(1).strip()
            if not multiline:
                val = val.split("\n")[0].strip()
            return val if val else None
    return None


def _tax_row(text: str, label: str) -> Tuple[Optional[float], Optional[float]]:
    m = re.search(
        rf"(?i){label}[^\d%]*([\d.]+)%[^\d]*({AMOUNT_RE})",
        text
    )
    if m:
        return _to_float(m.group(1)), _to_float(m.group(2))
    return None, None


# ── Field extractors ──────────────────────────────────────────────────────────

def _extract_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r"Document\s*No\.?" + SEP + r"([A-Z0-9][A-Z0-9/,\-]{3,40})",
        r"(?:I?TAX\s*Invoi[a-z]+\s*No\.?|Invoice\s*No\.?|Bill\s*[Nn]o\.?)" + SEP + r"([A-Z0-9][A-Z0-9/,\-]{4,29})",
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
        r"Document\s*Date" + SEP + rf"({DATE_RE})",
        r"Tax\s*Invoi[a-z]+\s*Date" + SEP + rf"({DATE_RE})",
        r"Bill\s*Date" + SEP + rf"({DATE_RE})",
        r"Invoice\s*Date" + SEP + rf"({DATE_RE})",
        r"Ack\.?\s*Date" + SEP + rf"({DATE_RE})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return _normalise_date(m.group(1))
    return None


def _extract_vendor_name(text: str) -> Optional[str]:
    # e-Invoice: "Seller" section
    m = re.search(r"Seller\s*\n\s*(.+)", text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        if len(name) > 3:
            return name

    # GSTIN line followed by company name
    m = re.search(r"GSTIN\s*:?\s*" + GSTIN_RE + r"\s*\n\s*(.+)", text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        if len(name) > 3 and not re.search(r"GSTIN|PAN|Address", name, re.IGNORECASE):
            return name

    # GTA style
    m = re.search(r"M[/\\]S[^\n]{2,80}", text, re.IGNORECASE)
    if m:
        name = re.sub(r"(?i)M[/\\]S\s*", "", m.group(0)).strip()
        return name if len(name) > 3 else None

    return None


def _extract_vendor_address(text: str) -> Optional[str]:
    m = re.search(
        r"(?:Pvt\.?\s*Ltd\.?|Industries|Enterprises|Roadlines)[^\n]*\n([^\n]+\n[^\n]+)",
        text, re.IGNORECASE
    )
    if m:
        addr = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(addr) > 10:
            return addr

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
        r"Purchaser\s*\n\s*(.+)",
        r"(?:Service\s*Recipient[^\n]*\n\s*)?Name" + SEP + r"([A-Z][A-Z\s&]{3,80})",
        r"(?:Consignee|Bill\s*To|Customer|Buyer)\s*Name" + SEP + r"([^\n]{5,80})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and not re.match(r"(?i)^as\s*per", val) and len(val) > 2:
                return val
    return None


def _extract_customer_gstin(text: str, gstins: List[str]) -> Optional[str]:
    m = re.search(r"Purchaser.{0,200}?(" + GSTIN_RE + r")", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1)
    return gstins[1] if len(gstins) >= 2 else None


def _extract_customer_address(text: str) -> Optional[str]:
    m = re.search(
        r"(?:Purchaser|Buyer).{0,400}?" + GSTIN_RE + r"\s*\n(.{10,300}?)(?:Place\s*of\s*Supply|4\.|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        addr = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(addr) > 5:
            return addr

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
    m = re.search(r"HSN\s*(?:Code)?\s*\n?\s*(\d{6,8})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    patterns = [
        r"SAC" + SEP + r"(?:C[o0]d[ce])" + SEP + r"(\d{6})",
        r"SAC" + SEP + r"(\d{6})",
        r"\b(99\d{4})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_subtotal(text: str, line_items: list) -> Optional[float]:
    v = _number_after(text,
        r"Tax['\s]*ble\s*Amt",
        r"Taxable\s*Amount",
        r"Taxable\s*Value",
        r"Total\s+Taxable",
        r"Freight\s*\(\s*in\s*amount\s*\)",
        r"Freight\s+Amount",
        r"Basic\s+Freight",
    )
    if v and v > 10:
        return v

    if line_items:
        for col in ("taxable_amount", "total_amount", "amount"):
            vals = [item.get(col) for item in line_items if item.get(col)]
            if vals:
                return round(sum(vals), 2)

    return None


def _extract_igst(text: str, subtotal: Optional[float]) -> Tuple[Optional[str], Optional[float]]:
    rate, amount = _tax_row(text, r"Integrated\s*[Tt]ax|IGST")
    rate_str = f"{rate}%" if rate is not None else None

    if amount is None:
        m = re.search(r"IGST\s*Amt\s*\n?\s*(" + AMOUNT_RE + r")", text, re.IGNORECASE)
        if m:
            amount = _to_float(m.group(1))

    if amount is None and rate and subtotal:
        amount = round(subtotal * rate / 100, 2)

    if rate_str is None:
        m = re.search(r"Integrated\s*[Tt]ax[^\d]*([\d.]+)%", text, re.IGNORECASE)
        if m:
            rate_str = m.group(1) + "%"
            if amount is None and subtotal:
                amount = round(subtotal * float(m.group(1)) / 100, 2)

    return rate_str, amount


def _extract_total_gst(text: str) -> Optional[float]:
    return _number_after(text,
        r"Total\s+GST\s+to\s+be\s+paid[^0-9]*",
        r"Total\s+GST",
        r"Total\s+Tax",
    )


def _extract_grand_total(text: str, subtotal: Optional[float], igst: Optional[float]) -> Optional[float]:
    for label in [
        r"Total\s+Inv(?:oice)?\.?\s*(?:Inv\.?)?",
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

    # e-Invoice goods table
    for m in re.finditer(
        r"(\d+)\s+"
        r"([A-Z][A-Z\s,()]+?)\s+"
        r"(\d{6,8})\s+"
        r"([\d,]+)\s+"
        r"([A-Z]{2,4})\s+"
        r"([\d,]+\.?\d*)\s+"
        r"([\d,]+\.?\d*)\s+"
        r"([\d,]+\.?\d*)\s+"
        r"([\d.+]+)\s+"
        r"([\d,]+\.?\d*)\s+"
        r"([\d,]+\.?\d*)",
        text, re.IGNORECASE
    ):
        try:
            items.append({
                "sl_no":          m.group(1),
                "description":    m.group(2).strip(),
                "hsn_code":       m.group(3),
                "quantity":       _to_float(m.group(4)),
                "unit":           m.group(5),
                "unit_price":     _to_float(m.group(6)),
                "discount":       _to_float(m.group(7)),
                "taxable_amount": _to_float(m.group(8)),
                "tax_rate":       m.group(9),
                "other_charges":  _to_float(m.group(10)),
                "total":          _to_float(m.group(11)),
            })
        except Exception:
            continue

    if items:
        return items

    # GTA RC-number pattern
    for m in re.finditer(
        r"(RC\d{7,15})"
        r"\s+(\d{1,2}[-/]\w{2,3}[-/]\d{2,4})"
        r"\s+(\d{4,12})"
        r".{0,300}?"
        r"([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})"
        r"\s+(\d{5,8})"
        r"\s+(\d{1,2}[-/]\w{2,3}[-/]\d{2,4})"
        r".{0,50}?"
        r"([\d,]{4,8})\s+"
        r"([\d,]{4,8})\s+"
        r"([\d,]{4,8})",
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
    w, h = img.size
    if w < 1200:
        scale = 1200 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    gray = gray.filter(ImageFilter.SHARPEN)
    if OPENCV_AVAILABLE:
        arr = np.array(gray)
        arr = cv2.fastNlMeansDenoising(arr, h=10)
        arr = cv2.adaptiveThreshold(
            arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
        )
        return Image.fromarray(arr)
    return gray


def _ocr(img) -> str:
    if not (TESSERACT_AVAILABLE and PIL_AVAILABLE):
        return ""
    try:
        return pytesseract.image_to_string(img, config="--oem 3 --psm 6")
    except Exception as e:
        print(f"Tesseract failed: {e}")
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
        except Exception as e:
            print(f"pdf2image failed: {e}")
    elif PIL_AVAILABLE and ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        try:
            images = [Image.open(file_path)]
        except Exception as e:
            print(f"Image open failed: {e}")

    if not images:
        print("WARNING: No images to OCR. Check Tesseract and Poppler installation.")
        return "", "ocr_failed"

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

        # Debug output — visible in your uvicorn terminal
        print(f"\n[extractor] source={source}, text_len={len(raw)}")
        print(f"[extractor] preview:\n{raw[:300]}\n")

        gstins         = _extract_all_gstins(raw)
        vendor_gstin   = gstins[0] if gstins else None
        customer_gstin = _extract_customer_gstin(raw, gstins)

        line_items  = _parse_line_items(raw)
        subtotal    = _extract_subtotal(raw, line_items)
        igst_rate, igst_amount = _extract_igst(raw, subtotal)
        cgst_rate, cgst_amount = _tax_row(raw, r"Central\s+Tax|CGST")
        sgst_rate, sgst_amount = _tax_row(raw, r"State\s+Tax|SGST")
        total_gst   = _extract_total_gst(raw) or igst_amount or (
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
            "invoice_number":     _extract_invoice_number(raw),
            "invoice_date":       _extract_date(raw),
            "vendor_name":        _extract_vendor_name(raw),
            "vendor_gstin":       vendor_gstin,
            "vendor_pan":         vendor_pan,
            "vendor_address":     _extract_vendor_address(raw),
            "customer_name":      _extract_customer_name(raw),
            "customer_gstin":     customer_gstin,
            "customer_address":   _extract_customer_address(raw),
            "place_of_supply":    _extract_place_of_supply(raw),
            "sac_code":           _extract_sac(raw),
            "mode_of_transport":  _after(raw, r"Mode\s+of\s+Transport"),
            "subtotal":           subtotal,
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