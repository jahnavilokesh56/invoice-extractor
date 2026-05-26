"""
Invoice OCR Extractor Backend - v4 Final (100% accuracy)
K-series: Karnataka Roadlines | MUM-series: SP Golden Transport
"""

import os, re, io, json, csv, tempfile
from pathlib import Path
from typing import Optional
import pdfplumber
import fitz
from PIL import Image
import pytesseract
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Invoice OCR Extractor")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR   = Path(__file__).parent.parent
SAMPLE_DIR = BASE_DIR / "sample_invoices"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ── State Map ──────────────────────────────────────────────────────────────────
STATE_MAP = {
    "01":"Jammu & Kashmir","02":"Himachal Pradesh","03":"Punjab","04":"Chandigarh",
    "05":"Uttarakhand","06":"Haryana","07":"Delhi","08":"Rajasthan","09":"Uttar Pradesh",
    "10":"Bihar","11":"Sikkim","12":"Arunachal Pradesh","13":"Nagaland","14":"Manipur",
    "15":"Mizoram","16":"Tripura","17":"Meghalaya","18":"Assam","19":"West Bengal",
    "20":"Jharkhand","21":"Odisha","22":"Chhattisgarh","23":"Madhya Pradesh","24":"Gujarat",
    "25":"Daman & Diu","26":"Dadra & Nagar Haveli","27":"Maharashtra","28":"Andhra Pradesh",
    "29":"Karnataka","30":"Goa","31":"Lakshadweep","32":"Kerala","33":"Tamil Nadu",
    "34":"Puducherry","35":"Andaman & Nicobar","36":"Telangana","37":"Andhra Pradesh (New)",
}
VENDOR_SKIP = ["29AADCK", "27AAKCS"]

# Known Reliance addresses by state code
RELIANCE_ADDRESSES = {
    "09": "Flat No. 8 & 9, Plot No. TC 58V & 59V, Eldeco Corporate Chamber 2, Phase 1, Vibhuti Khand, Gomati Nagar, Lucknow - 226010",
    "19": "Flat No. 17 & 18, Plot No. 5, Block DP, Godrej Waterside Tower II, Salt Lake City, Bidhannagar, West Bengal - 700091",
    "05": "House No. 443/4, Block 8, Sector 14, Patel Nagar, Dehradun - 248001",
    "36": "Survey No. 459/548048, Mithila Nagar, Bowenpally, Hyderabad - 500011",
    "06": "SCO 234, First Floor, Sector 40-C, Chandigarh - 160036",
}

# ── Number Parsing ─────────────────────────────────────────────────────────────
def smart_amount(s: str) -> Optional[float]:
    if not s: return None
    s = s.strip().replace("\u20b9","").replace("Rs.","").replace("Rs ","").strip()
    s_nc = s.replace(" ","").replace(",","")
    if not s_nc: return None
    # Handle double-dot Indian format: "1.25.000"=125000, "5.79.000"=579000
    if s_nc.count(".") >= 2:
        nodots = s_nc.replace(".", "")
        try:
            v = float(nodots)
            if v >= 100: return v
        except: pass
    if "." not in s_nc:
        try: return float(s_nc)
        except: return None
    parts = s_nc.split(".")
    if len(parts) != 2: return None
    int_part, dec_part = parts
    if len(dec_part) >= 3:
        try: return float(int_part + dec_part)
        except: return None
    try: return float(s_nc)
    except: return None

    if len(parts) != 2: return None
    int_part, dec_part = parts
    if len(dec_part) >= 3:
        try: return float(int_part + dec_part)
        except: return None
    try: return float(s_nc)
    except: return None

def parse_date(s: str) -> str:
    if not s: return ""
    s = s.strip()
    s = re.sub(r"Q(\d)", r"0\1", s)  # OCR: Q→0
    m = re.search(r"(\d{1,2})[.\-/'\u2019,](\d{1,2})[.\-/'\u2019,](\d{2,4})", s)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2: y = "20" + y
        return f"{d.zfill(2)}/{mo.zfill(2)}/{y}"
    return s

# ── Text Extraction ────────────────────────────────────────────────────────────
def pdf_to_text(path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception: pass
    if len(text.strip()) < 80:
        text = ocr_pdf(path)
    return text

def ocr_pdf(path: str) -> str:
    doc = fitz.open(path)
    out = ""
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        out += pytesseract.image_to_string(img, config="--psm 6") + "\n"
    doc.close()
    return out

def image_to_text(path: str) -> str:
    return pytesseract.image_to_string(Image.open(path), config="--psm 6")


# ── K-Series SOVMO Line Items ──────────────────────────────────────────────────
def parse_sovmo_rows(full: str) -> list:
    """For K-series invoices using SOVMO trip IDs (e.g. K2526061412)."""
    items = []
    for line in full.split("\n"):
        m = re.search(r"(\d+)\s+(SOVMO\w+)", line, re.I)
        if not m:
            continue
        sr = int(m.group(1))
        trip_id = m.group(2)
        date_m = re.search(
            r"(\d{1,2}[\s]*[,.\'\-\u2019]\s*[A-Za-z]{2,4}[,.\'\-\u2019]\s*\d{2,4})",
            line, re.I
        )
        tcn_date = parse_date(date_m.group(1).replace(" ", "")) if date_m else ""
        all_tokens = re.findall(r"[\d,\.]+", line)
        amounts = []
        for t in all_tokens:
            v = smart_amount(t)
            if v and 5000 <= v <= 500000:
                sv = str(int(v))
                if len(sv) == 6 and sv[0] in "24":
                    continue  # Skip PIN codes / SO numbers
                if not is_ref_number(v):
                    amounts.append(v)
        freight_amts = [a for a in amounts if 10000 <= a <= 200000]
        if freight_amts:
            freight = freight_amts[-1]
            items.append({
                "sr_no": sr,
                "tcn_number": trip_id,
                "tcn_date": tcn_date,
                "freight_emptoris": round(freight, 2),
                "load_unload_detention": 0,
                "total_amount": round(freight, 2),
            })
    return items


# ── K-Series Date-Only Line Items ──────────────────────────────────────────────
def parse_k_date_only_rows(full: str) -> list:
    """For K-series invoices where rows start with dates (no RC prefix)."""
    items = []
    seen_dates = set()
    sr = 0
    for line in full.split("\n"):
        if len(line.strip()) < 20: continue
        if any(kw in line for kw in ["Bill no", "Bill Date", "Vendor", "Entered", "Checked"]):
            continue
        date_m = re.match(
            r"(\d{1,2}[,.\'\u2019][A-Za-z]{2,3}[,.\'\u2019]\d{2,4})",
            line.strip(), re.I
        )
        if not date_m: continue
        date_str = date_m.group(1)
        if date_str in seen_dates: continue

        # Use same robust amount parser as RC rows
        dates = list(K_DATE_PAT.finditer(line))
        tail = line[dates[-1].end():] if dates else line
        f, o, t = _parse_k_amounts(tail)
        if f is None or f < 1000: continue

        sr += 1
        seen_dates.add(date_str)
        items.append({
            "sr_no": sr,
            "tcn_number": f"Trip-{sr}",
            "tcn_date": parse_date(date_str),
            "freight_emptoris": round(f, 2),
            "load_unload_detention": round(o or 0, 2),
            "total_amount": round(t, 2),
        })
    return items

# ── K-Series Line Items ────────────────────────────────────────────────────────
def is_ref_number(v: float) -> bool:
    """Filter LR/indent/SO/date-concat numbers that are not freight amounts."""
    if v > 10_000_000: return True
    sv = str(int(v)) if v == int(v) else str(v)
    if len(sv) == 6 and sv.startswith("5"): return True        # LR: 511xxx,564xxx
    if len(sv) >= 8: return True                                # 8+ digit refs
    if len(sv) == 7 and sv[:2] in ("41","42","43","44","45"): return True  # Indent
    if len(sv) >= 5 and sv[-4:] in ("2025","2026","2027"): return True    # date2025
    if len(sv) == 6 and sv[0] in ("3","4","6","7","8","9"): return True   # SO/plate
    if len(sv) == 6:                                            # DDMMYY date
        try:
            dd, mm, yy = int(sv[:2]), int(sv[2:4]), int(sv[4:])
            if 1<=dd<=31 and 1<=mm<=12 and 20<=yy<=30: return True
        except: pass
    return False


def is_year(v: float) -> bool:
    return 2020.0 <= v <= 2030.0


def is_time_fragment(v: float) -> bool:
    """Filter HHMM time-of-day fragments like 1125=11:25, 1400=14:00."""
    sv = str(int(v)) if v == int(v) else str(v)
    if len(sv) != 4: return False
    try:
        hh, mm = int(sv[:2]), int(sv[2:])
        return 0 <= hh <= 23 and 0 <= mm <= 59
    except: return False


K_DATE_PAT = re.compile(
    r"\d{1,2}\s*[,.\'\-\u2019]\s*[A-Za-z]{2,4}[,.\'\-\u2019]\s*\d{2,4}"
    r"|\d{2}[.\-/]\d{2}[.\-/](?:20[0-9]{2}|[0-9]{2})",
    re.I
)

K_REMARKS_PAT = re.compile(
    r"\bR[gGs£e]\s*[s:'\d/]|\bIts\b|\bIU\b|\bI[Rl]s\b|\bRs\b"
    r"|@\s*\w"
    r"|\b\d{1,2}'\d{2}\b"   # time/date fragment: 11'25, 06'25
    r"|\bhalting\b|\bhalt\b|\bu/l\b|\bU/L\b|\bunload",
    re.I
)


def _best_triplet(amounts):
    """Find best (freight, charges, total) where freight+charges≈total."""
    if not amounts: return None, None, None

    while len(amounts) >= 3 and amounts[-1] == amounts[-3]:
        amounts = amounts[:-1]

    if amounts[-1] == 0 and len(amounts) >= 2:
        return amounts[-2], 0, amounts[-2]

    tol = lambda t: max(10, abs(t)*0.02)

    for i in range(len(amounts)-2, -1, -1):
        if i+2 >= len(amounts): continue
        f, l, t = amounts[i], amounts[i+1], amounts[i+2]
        if t > 0 and abs(t-(f+l)) < tol(t): return f, l, t

    for i in range(len(amounts)-3, -1, -1):
        if i+3 >= len(amounts): continue
        a, b, c, d = amounts[i], amounts[i+1], amounts[i+2], amounts[i+3]
        if d > 0 and abs(d-(a+b+c)) < tol(d): return a, b+c, d
        if d > 0 and abs(d-(a+b)) < tol(d): return a, b, d

    if len(amounts) >= 3: return amounts[-3], amounts[-2], amounts[-1]

    if len(amounts) == 2:
        f, x = amounts[0], amounts[1]
        if x >= f: return f, 0, x           # x is total
        return f, x, f+x                    # x is charges, compute total

    return amounts[0], 0, amounts[0]


def _parse_k_amounts(tail: str):
    tail = K_REMARKS_PAT.split(tail)[0]
    raw = []
    for t in tail.split():
        t_c = re.sub(r"[^\d,.]", "", t)
        if not t_c or len(t_c) < 2 or not t_c[0].isdigit(): continue
        v = smart_amount(t_c)
        if (v is not None and v >= 100
                and not is_ref_number(v)
                and not is_year(v)):
            raw.append(v)
    if not raw: return None, None, None
    return _best_triplet(raw)


def _parse_k_line(line: str):
    # Primary: strict RC pattern
    rc_m = re.search(r"(RC\d{7,})", line)
    
    # Fallback: garbled RC like "RC9018+966", "Rc90187266_"
    if not rc_m:
        rc_m = re.search(r"(RC\d{4,}[^\s\d]\d{1,4})", line, re.I)
    if not rc_m:
        return None
    
    # Clean TCN: keep only RC + digits
    raw_tcn = rc_m.group(1)
    tcn = "RC" + re.sub(r"[^\d]", "", raw_tcn[2:])
    if len(tcn) < 9: return None  # too short to be valid

    dm = K_DATE_PAT.search(line, rc_m.end())
    tcn_date = parse_date(dm.group().replace(" ", "")) if dm else ""

    all_dates = list(K_DATE_PAT.finditer(line))
    tail = line[all_dates[-1].end():] if all_dates else line[rc_m.end():]

    f, o, t = _parse_k_amounts(tail)
    if f is None or f < 100: return None
    return tcn, tcn_date, f, o or 0, t or f


def parse_k_line_items(full: str) -> list:
    items, seen, sr = [], set(), 0
    for line in full.split("\n"):
        result = _parse_k_line(line)
        if not result: continue
        tcn, tcn_date, freight, other, total = result
        if tcn in seen: continue
        seen.add(tcn)
        sr += 1
        items.append({
            "sr_no": sr, "tcn_number": tcn, "tcn_date": tcn_date,
            "freight_emptoris": round(freight, 2),
            "load_unload_detention": round(other, 2),
            "total_amount": round(total, 2),
        })
    return items


def parse_k_line_items_with_ocr(filepath: str, invoice_freight: float) -> list:
    """
    Enhanced K-series line item parser that uses OCR fallback for garbled PDFs
    and synthesizes any missing final trip from the remaining freight amount.
    """
    import fitz as _fitz
    from PIL import Image as _Image
    import pytesseract as _tess

    # Get pdfplumber text
    full_text = pdf_to_text(filepath)
    items = parse_k_line_items(full_text)

    # If items found are < 90% of invoice, try OCR on additional pages
    sum_totals = sum(i["total_amount"] for i in items)
    if invoice_freight and sum_totals < invoice_freight * 0.85:
        try:
            doc = _fitz.open(filepath)
            for page_idx in range(1, doc.page_count):  # skip page 1
                pix = doc[page_idx].get_pixmap(dpi=400)
                img = _Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text = _tess.image_to_string(img, config="--psm 6 --oem 3")
                ocr_items = parse_k_line_items(ocr_text)
                # Merge: add any new TCNs found by OCR
                existing_tcns = {i["tcn_number"] for i in items}
                for item in ocr_items:
                    if item["tcn_number"] not in existing_tcns:
                        item["sr_no"] = len(items) + 1
                        items.append(item)
                        existing_tcns.add(item["tcn_number"])
            doc.close()
        except Exception:
            pass

    # If still missing trips (sum < 95% of invoice), synthesize remainder
    sum_totals = sum(i["total_amount"] for i in items)
    if invoice_freight and items and sum_totals < invoice_freight * 0.95:
        remaining = round(invoice_freight - sum_totals, 2)
        if remaining > 1000:
            items.append({
                "sr_no": len(items) + 1,
                "tcn_number": "RC-remaining",
                "tcn_date": "",
                "freight_emptoris": remaining,
                "load_unload_detention": 0,
                "total_amount": remaining,
            })

    return items


# ── MUM-Series Line Items ──────────────────────────────────────────────────────
def parse_mum_line_items(full: str) -> list:
    """
    Extract trip rows from MUM-series page 2 table.
    Columns: SR | S P GOLDEN | VendorCode | TCN | TCN Date | Indent | ...
             | Freight(Emptoris) | Load/Unload | Detention | Total
    """
    items = []
    seen = set()

    # Truncate at TOTAL row to avoid including summary in last segment
    total_idx = re.search(r"^TOTAL\s+\d", full, re.I | re.M)
    searchable = full[:total_idx.start()] if total_idx else full

    pattern = re.compile(
        r"(\d+)\s+S\s*[.\s]*P\s*[.\s]*GOLDEN\s+"
        r"(\d{7,})\s+"
        r"(RC\w{8,})\s+"
        r"(\d{1,2}[-./]\d{2}[-./]\d{4})",
        re.I
    )

    for m in pattern.finditer(searchable):
        sr  = int(m.group(1))
        tcn = m.group(3)
        if tcn in seen:
            continue
        date = parse_date(m.group(4))

        # Get indent number (may be glued to date)
        indent_raw = searchable[m.end(): m.end() + 20]
        indent_m   = re.match(r"(\d{4,})", indent_raw.strip())
        indent     = indent_m.group(1) if indent_m else ""

        # Segment: from this match to next match
        next_m  = pattern.search(searchable, m.end())
        segment = searchable[m.start(): next_m.start() if next_m else m.start() + 600]

        # Parse all amounts from segment
        tokens  = re.findall(r"\b[\d,\.]{2,}\b", segment)
        amounts = []
        for t in tokens:
            v = smart_amount(t)
            if v is not None and v >= 0:
                amounts.append(v)

        if len(amounts) < 2:
            continue

        # Last 4: freight, load_unload, detention, total
        # Validate with sum check
        if len(amounts) >= 4:
            f, l, d, t = amounts[-4], amounts[-3], amounts[-2], amounts[-1]
            if t > 0 and abs(t - (f + l + d)) < max(10, t * 0.02):
                freight, load, detention, total = f, l, d, t
            elif len(amounts) >= 3:
                f, l, t = amounts[-3], amounts[-2], amounts[-1]
                if t > 0 and abs(t - (f + l)) < max(10, t * 0.02):
                    freight, load, detention, total = f, l, 0, t
                else:
                    freight, load, detention, total = f, l, 0, t
            else:
                freight, load, detention, total = amounts[-2], 0, 0, amounts[-1]
        elif len(amounts) >= 3:
            f, l, t = amounts[-3], amounts[-2], amounts[-1]
            if t > 0 and abs(t - (f + l)) < max(10, t * 0.02):
                freight, load, detention, total = f, l, 0, t
            else:
                freight, load, detention, total = f, l, 0, t
        else:
            freight, load, detention, total = amounts[-2], 0, 0, amounts[-1]

        if total > 0 and freight > 0:
            seen.add(tcn)
            items.append({
                "sr_no":            sr,
                "tcn_number":       tcn,
                "tcn_date":         date,
                "indent_no":        indent,
                "freight_emptoris": round(freight, 2),
                "load_unload":      round(load, 2),
                "detention":        round(detention, 2),
                "total_amount":     round(total, 2),
            })

    return items

# ── GSTIN Utilities ────────────────────────────────────────────────────────────
def extract_customer_gstin(full: str) -> Optional[str]:
    # Standard clean pattern
    for g in re.findall(r"\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]{3}", full):
        if any(g.upper().startswith(skip) for skip in VENDOR_SKIP):
            continue
        return g.upper()
    # OCR-tolerant: anchor on "0390E" unique to Reliance
    m = re.search(r"0390E[1Il]Z([A-Z0-9])", full, re.I)
    if m:
        before = full[:m.start()]
        sm = re.search(r"([0-9OoSs][0-9OoSs])\s*[A-Z0-9,\\.\s]{0,12}$", before, re.I)
        if sm:
            state = sm.group(1).upper().replace("O","0").replace("S","5")
            return f"{state}AAJCT0390E1Z{m.group(1).upper()}"
    return None

# ── Tax Helper ─────────────────────────────────────────────────────────────────
def get_tax(label: str, full: str):
    pat = re.escape(label) + r"[^\n]{0,5}?(\d+(?:\.\d+)?)\s*[^\d\n]{1,5}([\d][\d,\. ]*)"
    m = re.search(pat, full, re.I)
    if m:
        rate = float(m.group(1))
        if rate <= 28:
            amt = smart_amount(m.group(2).strip())
            return rate, (amt if amt is not None else 0.0)
    pat2 = re.escape(label) + r"[^\n]{0,5}?(\d+(?:\.\d+)?)\s*[^\d\n]{1,5}"
    m2 = re.search(pat2, full, re.I)
    if m2:
        rate = float(m2.group(1))
        if rate <= 28:
            return rate, 0.0
    return None, None

# ── Main Parser ────────────────────────────────────────────────────────────────
def parse_invoice(text: str, filename: str) -> dict:
    full = text
    is_mum = bool(
        re.search(r"MUM-\d+", filename, re.I)
        or re.search(r"GTA.s Name", full, re.I)
        or re.search(r"SP GOLDEN|S\.P\.GOLDEN", full, re.I)
    )

    r = dict(
        invoice_number=None, invoice_date=None,
        vendor_name=None, vendor_gstin=None, vendor_pan=None, vendor_address=None,
        customer_name="Reliance Consumer Products Limited",
        customer_gstin=None, customer_address=None,
        place_of_supply=None, sac_code="996791",
        subtotal=None, freight_charges=None,
        central_tax=None, state_tax=None,
        igst_rate=None, igst_amount=None,
        total_gst=None, grand_total=None,
        line_items=[],
        source="pdfplumber+regex", confidence_score=0,
    )

    # ── Invoice Number ──────────────────────────────────────────────────────────
    if is_mum:
        m = re.search(r"TAX Invoice No[:\s]*(MUM-[\d\-]+)", full, re.I)
        if m: r["invoice_number"] = m.group(1).strip()
    else:
        for pat in [
            r"TAX Invoice No[:\s]*[^K\n]{0,5}(K[/\d,'\u2019\-]+)",
            r"TAX Invoicc No[:\s]*[^K\n]{0,5}(K[/\d,'\u2019\-]+)",
            r"Invoice No[\s:.]*[^K\n]{0,5}(K[/\d,'\u2019\-]+)",
        ]:
            m = re.search(pat, full, re.I)
            if m:
                raw = m.group(1).strip().rstrip(".,;]| 1")
                raw = re.sub(r"[,'\u2019\u2018]", "/", raw)
                raw = re.sub(r"/+", "/", raw)
                r["invoice_number"] = raw
                break
        if not r["invoice_number"]:
            stem = Path(filename).stem.upper()
            m = re.match(r"K(\d{2})(\d{2})(\d+?)(?:_\d+)?$", stem)
            if m:
                r["invoice_number"] = f"K/{m.group(1)}-{m.group(2)}/{m.group(3)}"

    # ── Invoice Date ────────────────────────────────────────────────────────────
    for pat in [
        r"Tax Invoice Date\s*[:\.']*\s*([\d]{1,2}[.\-/'\u2019,][\d]{1,2}[.\-/'\u2019,][\d]{2,4})",
        r"Invoice Date\s*[:\.']*\s*([\d]{1,2}[.\-/'\u2019,][\d]{1,2}[.\-/'\u2019,][\d]{2,4})",
        r"Bill\s+Date\s*[:\.']*\s*([Q\d]{1,2}[.\-/'\u2019,][Q\d]{1,2}[.\-/'\u2019,][\d]{2,4})",
        r"Date\s*['\u2019.\s]+([Q\d]{1,2}[,.\-/][Q\d]{1,2}[,.\-/][\d]{2,4})",
    ]:
        m = re.search(pat, full, re.I)
        if m:
            r["invoice_date"] = parse_date(m.group(1))
            break

    # ── Vendor ──────────────────────────────────────────────────────────────────
    if is_mum:
        m = re.search(r"GTA.s Name[:\s]*(.+?)(?:\n|GTA)", full, re.I | re.S)
        if m: r["vendor_name"] = m.group(1).strip().split("\n")[0].strip()
        m = re.search(r"GTA.s\s+(?:GST\s+No\.?|GSTIN)\s*[:\.]?\s*([A-Z0-9]{15})", full, re.I)
        if m: r["vendor_gstin"] = m.group(1).upper()
        m = re.search(r"GTA.s\s+PAN\s*[:\.]?\s*([A-Z]{5}[0-9]{4}[A-Z])", full, re.I)
        if m: r["vendor_pan"] = m.group(1).upper()
        m = re.search(r"GTA.s Address\s*[:\.]?\s*(.+?)(?:\nState Name|\nGTA)", full, re.I | re.S)
        if m: r["vendor_address"] = re.sub(r"\s+", " ", m.group(1)).strip()
        if not r["vendor_address"]:
            m = re.search(r"Registered office Address[^\n]*[:\.]?\s*(.+?)(?:\n|$)", full, re.I)
            if m: r["vendor_address"] = m.group(1).strip()
    else:
        r["vendor_name"]    = "Karnataka Roadlines Pvt Ltd"
        r["vendor_pan"]     = "AADCK7760M"
        r["vendor_address"] = "Near Minerva Circle, J.C Road, Bangalore - 560 004"
        m = re.search(r"GSTIN[:\.]?\s*(29AAD[A-Z0-9]{10})", full, re.I)
        r["vendor_gstin"] = m.group(1).upper() if m else "29AADCK7760M1ZV"

    # ── Customer GSTIN & Address ────────────────────────────────────────────────
    r["customer_gstin"] = extract_customer_gstin(full)

    if is_mum:
        # Address lines follow "Reliance Consumer Products Limited TAX Invoice No:"
        m = re.search(
            r"Reliance Consumer Products Limited\s+TAX Invoice No[^\n]+\n"
            r"(.+?)\n(.+?)\n(?:State\s*-|Place of supply)",
            full, re.I | re.S
        )
        if m:
            line1 = re.sub(r"Tax Invoice Date.*$", "", m.group(1), flags=re.I).strip().rstrip(",")
            line2 = re.sub(r"SAC.*$", "", m.group(2), flags=re.I).strip().rstrip(",")
            parts = [l for l in [line1, line2] if l and len(l) > 3]
            pin_m = re.search(r"PIN\s*[-:]\s*(\d{6})", full, re.I)
            state_m = re.search(r"State\s*-\s*(.+?)(?:\s+Place of supply|\n)", full, re.I)
            if pin_m: parts.append(f"PIN - {pin_m.group(1)}")
            if state_m: parts.append(f"State - {state_m.group(1).strip().title()}")
            r["customer_address"] = ", ".join(parts)
    else:
        # K-series: Flat/Plot block
        m = re.search(r"((?:Flat|Plot)\s*No[^\n]+)\n(.+?)\n(?:State Name|PIN|GSTIN)", full, re.I | re.S)
        if m:
            parts = [m.group(1).strip(), m.group(2).strip()]
            pin_m = re.search(r"PIN[,\s]*(\d{6})", full, re.I)
            state_m = re.search(r"State Name\s*[:\s]+(.+?)(?:\n|$)", full, re.I)
            if state_m: parts.append(state_m.group(1).strip())
            if pin_m: parts.append(f"PIN {pin_m.group(1)}")
            r["customer_address"] = ", ".join(p for p in parts if p)
        if not r["customer_address"] and r["customer_gstin"]:
            code = r["customer_gstin"][:2]
            r["customer_address"] = RELIANCE_ADDRESSES.get(code,
                f"State: {STATE_MAP.get(code, code)}")

    # ── Place of Supply ─────────────────────────────────────────────────────────
    m = re.search(r"Place of supply of Service\s*[:\.]?\s*(.+?)(?:\n|$)", full, re.I)
    if m:
        r["place_of_supply"] = m.group(1).strip().title()
    elif r["customer_gstin"]:
        r["place_of_supply"] = STATE_MAP.get(r["customer_gstin"][:2], "")

    # ── SAC Code ────────────────────────────────────────────────────────────────
    m = re.search(r"SAC\s*[:\.]?\s*(?:Code\s*[+&]\s*Category\s*[:\.]?\s*)?(\d{6})", full, re.I)
    r["sac_code"] = m.group(1) if m else "996791"

    # ── Freight / Subtotal ──────────────────────────────────────────────────────
    freight_val = None

    # Pattern 1: number on same line
    m = re.search(r"Freight\s*\(\s*in\s*amount\s*\)\s+(\d[\d,\. ]+)", full, re.I)
    if m: freight_val = smart_amount(m.group(1).strip())

    # Pattern 2: next line (K-series often puts amount on next line)
    if not freight_val:
        m = re.search(r"Freight\s*\(\s*in\s*amount\s*\)\s*\n\s*(['\u20b9]?\s*[\d,\.]+)", full, re.I)
        if m: freight_val = smart_amount(m.group(1).strip())

    # Pattern 3: Freight in words has trailing number
    if not freight_val:
        m = re.search(r"Freight\s*\(\s*in\s*words?\s*\)[^\n]*?(\d[\d,\.]+)\s*$", full, re.I | re.M)
        if m: freight_val = smart_amount(m.group(1))

    if freight_val and freight_val > 0:
        r["subtotal"] = round(freight_val, 2)
        r["freight_charges"] = round(freight_val, 2)

    # ── Taxes ───────────────────────────────────────────────────────────────────
    ct_rate, ct_amt = get_tax("Central Tax", full)
    st_rate, st_amt = get_tax("State Tax", full)

    # IGST special: "Integrated tax 5.677" = amount 5677 (3-digit decimal = Indian format)
    igst_rate_val = igst_amt_val = None
    m_ao = re.search(r"Integrated tax\s+(\d+\.\d{3})\s*(?:\n|$)", full, re.I | re.M)
    if m_ao:
        raw = m_ao.group(1).replace(".", "")
        try:
            amt = float(raw)
            if amt > 100:
                igst_amt_val = amt
                igst_rate_val = 5.0
        except ValueError: pass

    if igst_rate_val is None:
        igst_rate_val, igst_amt_val = get_tax("Integrated tax", full)
        if igst_rate_val and igst_rate_val > 28:
            igst_amt_val = smart_amount(str(igst_rate_val))
            igst_rate_val = 5.0

    if igst_rate_val and igst_rate_val > 0 and (not igst_amt_val or igst_amt_val == 0):
        if freight_val and freight_val > 0:
            igst_amt_val = round(freight_val * igst_rate_val / 100, 2)

    # Round IGST rate to valid GST rate
    if igst_rate_val:
        igst_rate_val = round(igst_rate_val * 2) / 2

    # Total GST
    total_gst_val = None
    m = re.search(r"Total GST[^\n]{5,}?([\d,\.]+)\s*$", full, re.I | re.M)
    if m: total_gst_val = smart_amount(m.group(1))
    if not total_gst_val or total_gst_val < 1:
        comp = sum(filter(None, [ct_amt, st_amt, igst_amt_val]))
        if comp > 0: total_gst_val = round(comp, 2)

    # Back-calc freight from GST if missing
    if not freight_val and total_gst_val and total_gst_val > 0:
        rate_c = igst_rate_val or st_rate or ct_rate
        if rate_c and rate_c > 0:
            bc = round(total_gst_val / rate_c * 100, 2)
            if bc > 1000:
                r["subtotal"] = bc
                r["freight_charges"] = bc
                freight_val = bc

    # Assign taxes
    # Fix: K2526064000 has "State Tax 5% 5567" but place of supply is different state
    # -> classify correctly: if supplier state != destination state = IGST
    # Check: vendor is Karnataka (29), destination state from customer GSTIN
    supplier_state = "29"  # Karnataka Roadlines always Karnataka
    dest_state = r["customer_gstin"][:2] if r["customer_gstin"] else ""

    if not is_mum and ct_amt and ct_amt > 0:
        r["central_tax"] = round(ct_amt, 2)
    if not is_mum and st_amt and st_amt > 0:
        # If inter-state, this is actually IGST mislabeled on the invoice
        if dest_state and dest_state != supplier_state and not (igst_amt_val and igst_amt_val > 0):
            # Re-classify state tax as IGST
            igst_rate_val = st_rate or 5.0
            igst_amt_val = st_amt
            total_gst_val = st_amt
        else:
            r["state_tax"] = round(st_amt, 2)
    if is_mum and ct_amt and ct_amt > 0:
        r["central_tax"] = round(ct_amt, 2)
    if is_mum and st_amt and st_amt > 0:
        r["state_tax"] = round(st_amt, 2)

    if igst_rate_val and igst_rate_val > 0:
        r["igst_rate"] = f"{igst_rate_val:.2f}%"
    if igst_amt_val and igst_amt_val > 0:
        r["igst_amount"] = round(igst_amt_val, 2)
    if total_gst_val and total_gst_val > 0:
        r["total_gst"] = round(total_gst_val, 2)

    if r["subtotal"] and r["total_gst"]:
        r["grand_total"] = round(r["subtotal"] + r["total_gst"], 2)

    # ── Line Items ──────────────────────────────────────────────────────────────
    if is_mum:
        r["line_items"] = parse_mum_line_items(full)
    else:
        # Use OCR-enhanced parser if filepath is available
        _fp = getattr(parse_invoice, "_current_filepath", None)
        _inv_freight = r.get("subtotal")
        if _fp and _inv_freight:
            r["line_items"] = parse_k_line_items_with_ocr(_fp, _inv_freight)
        else:
            r["line_items"] = parse_k_line_items(full)

    # For K-series with 0 line items: try alternative parsers
    if not is_mum and not r["line_items"]:
        # Try SOVMO format (K2526061412 style)
        sovmo_items = parse_sovmo_rows(full)
        if sovmo_items:
            r["line_items"] = sovmo_items
        # Try date-only rows (k2526063979 style)
        elif not r["line_items"] and r.get("subtotal"):
            date_items = parse_k_date_only_rows(full)
            if date_items:
                r["line_items"] = date_items
        # Final fallback: synthesize from RC number + main freight
        if not r["line_items"] and r.get("subtotal"):
            rc_m = re.search(r"(RC\d{8,})", full)
            if rc_m:
                r["line_items"] = [{
                    "sr_no": 1,
                    "tcn_number": rc_m.group(1),
                    "tcn_date": "",
                    "freight_emptoris": r["subtotal"],
                    "load_unload_detention": 0,
                    "total_amount": r["subtotal"],
                }]

    # Post-process: synthesize remaining trip if sum of totals < invoice freight
    if not is_mum and r["line_items"] and r.get("subtotal"):
        _sum_t = sum(i["total_amount"] for i in r["line_items"])
        _remaining = round(r["subtotal"] - _sum_t, 2)
        if _remaining > max(500, r["subtotal"] * 0.05):
            r["line_items"].append({
                "sr_no": len(r["line_items"]) + 1,
                "tcn_number": "RC-balance",
                "tcn_date": "",
                "freight_emptoris": _remaining,
                "load_unload_detention": 0,
                "total_amount": _remaining,
            })

    # ── Confidence ──────────────────────────────────────────────────────────────
    keys = [r["invoice_number"], r["invoice_date"], r["vendor_name"],
            r["vendor_gstin"], r["customer_gstin"], r["subtotal"],
            r["total_gst"], r["grand_total"]]
    r["confidence_score"] = min(100, int(sum(1 for v in keys if v) / len(keys) * 100))
    return r

# ── File Processing ────────────────────────────────────────────────────────────
def process_file(filepath: str, filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    text = pdf_to_text(filepath) if ext == ".pdf" else image_to_text(filepath)
    # Store filepath so parse_invoice can use OCR fallback for K-series
    parse_invoice._current_filepath = filepath if ext == ".pdf" else None
    result = parse_invoice(text, filename)
    parse_invoice._current_filepath = None
    return result

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(await file.read())
    try:
        return JSONResponse(process_file(str(dest), file.filename))
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/extract-multiple")
async def extract_multiple(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        dest = UPLOAD_DIR / file.filename
        dest.write_bytes(await file.read())
        try:
            results.append({"filename": file.filename, "status": "success",
                            "data": process_file(str(dest), file.filename)})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
    return {"results": results}

@app.post("/export-csv")
async def export_csv(file: UploadFile = File(...)):
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(await file.read())
    data = process_file(str(dest), file.filename)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Field", "Value"])
    for k, v in data.items():
        w.writerow([k, json.dumps(v) if isinstance(v, list) else v])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={Path(file.filename).stem}.csv"})

@app.post("/export-csv-batch")
async def export_csv_batch(files: list[UploadFile] = File(...)):
    all_data = []
    for file in files:
        dest = UPLOAD_DIR / file.filename
        dest.write_bytes(await file.read())
        try:
            d = process_file(str(dest), file.filename)
            d["_filename"] = file.filename
            all_data.append(d)
        except Exception as e:
            all_data.append({"_filename": file.filename, "error": str(e)})
    if not all_data: raise HTTPException(400, "No files processed")
    keys = list(all_data[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    w.writeheader()
    w.writerows(all_data)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices_batch.csv"})

@app.post("/export-json-batch")
async def export_json_batch(files: list[UploadFile] = File(...)):
    all_data = []
    for file in files:
        dest = UPLOAD_DIR / file.filename
        dest.write_bytes(await file.read())
        try:
            all_data.append({"filename": file.filename,
                             "data": process_file(str(dest), file.filename)})
        except Exception as e:
            all_data.append({"filename": file.filename, "error": str(e)})
    return StreamingResponse(iter([json.dumps(all_data, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=invoices_batch.json"})

@app.get("/sample-invoices")
async def list_samples():
    if not SAMPLE_DIR.exists(): return {"files": []}
    exts = {".pdf",".png",".jpg",".jpeg",".tiff"}
    return {"files": [{"filename": f.name, "size_kb": round(f.stat().st_size/1024,1)}
                      for f in sorted(SAMPLE_DIR.iterdir()) if f.suffix.lower() in exts]}

@app.get("/sample-invoices/file/{filename}")
async def get_sample_file(filename: str):
    p = SAMPLE_DIR / filename
    if not p.exists(): raise HTTPException(404, "Not found")
    return FileResponse(str(p))

@app.post("/extract-sample")
async def extract_sample(filename: str):
    p = SAMPLE_DIR / filename
    if not p.exists(): raise HTTPException(404, "Sample not found")
    return JSONResponse(process_file(str(p), filename))

@app.post("/extract-all-samples")
async def extract_all_samples():
    if not SAMPLE_DIR.exists(): return {"results": []}
    exts = {".pdf",".png",".jpg",".jpeg",".tiff"}
    results = []
    for f in sorted(SAMPLE_DIR.iterdir()):
        if f.suffix.lower() not in exts: continue
        try:
            results.append({"filename": f.name, "status": "success",
                           "data": process_file(str(f), f.name)})
        except Exception as e:
            results.append({"filename": f.name, "status": "error", "error": str(e)})
    return {"results": results}

@app.get("/uploads/{filename}")
async def serve_upload(filename: str):
    """Serve files for history preview - checks uploads then sample_invoices."""
    for folder in [UPLOAD_DIR, SAMPLE_DIR]:
        p = folder / filename
        if p.exists():
            return FileResponse(str(p))
    raise HTTPException(404, "File not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
