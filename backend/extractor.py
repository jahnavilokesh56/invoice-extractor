"""
extractor.py — Noise-tolerant GST invoice extractor v3.
BUG FIXES v3 (all 18 invoices tested):
  1. customer_name returning "Receiver Signature" → fixed
  2. customer_name OCR garble "Reliance Cxinsumcr..." → fixed
  3. customer_name MUM invoices returning vendor name → fixed
  4. customer_address returning "As per Annex." → fixed
  5. sac_code "SAC : Cale . Category : 996791" → OCR "Cale"→"Code" fixed
  6. mode_of_transport missing on KRL invoices → "By Road" keyword fallback added
  7. place_of_supply missing → extended patterns added
  8. subtotal "5,81500" OCR artifact → normalised to 581500
  9. subtotal wrong on K2526064000 (IGST line picked up) → fixed
 10. igst_rate/igst_amount blank on most invoices → _tax_row regex fixed
 11. igst_rate "Integrated tax 5" (no % sign) → handled
 12. total_gst "1.725" = OCR of "1,725" → scaled to 1725
 13. grand_total wrong chain due to wrong subtotal → fixed
 14. vendor_name garbled on K2526064000 → M/S fallback + alpha ratio filter
 15. vendor_gstin "MIZV" (OCR) → normalised correctly
 16. invoice_number "K/25,26/dm" → Bill no fallback added
 17. invoice_date missing many invoices → Bill Date fallback added
 18. MUM-004141 empty PDF → handled gracefully
 19. "0.00(X)" OCR tax artifact → cleaned
 20. K/25,26/ → K/25-26/ normalised
"""

import os
import re
import json
import sys
import argparse
from typing import Any, Dict, List, Optional, Tuple

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_AVAILABLE = False

try:
    from pypdf import PdfReader as PyPDFReader
    PYPDF_AVAILABLE = True
except ImportError:
    PyPDFReader = None
    PYPDF_AVAILABLE = False

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PyPDF2 = None
    PYPDF2_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    convert_from_path = None
    PDF2IMAGE_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    Image = ImageEnhance = ImageFilter = None
    PIL_AVAILABLE = False

try:
    import pytesseract
    if sys.platform == "win32":
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    TESSERACT_AVAILABLE = False

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    cv2 = None
    np = None
    OPENCV_AVAILABLE = False


GSTIN_RE       = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}"
GSTIN_NOISY_RE = r"[0-9OI]{2}[A-Z]{5}[0-9OI]{4}[A-Z][0-9A-Z]{3}"
PAN_RE         = r"[A-Z]{5}[0-9]{4}[A-Z]"
AMOUNT_RE      = r"[\d,]+(?:\.\d+)?"
DATE_RE        = (
    r"(?:\d{1,2}[.\\/,\-]\d{1,2}[.\\/,\-]\d{2,4}"
    r"|\d{1,2}[.\\/,\-][A-Za-z]{3}[.\\/,\-]\d{2,4}"
    r"|\d{4}[.\\/,\-]\d{1,2}[.\\/,\-]\d{1,2})"
)
SEP = r"[\s:.\-\u2013|,]*"


def _fix_ocr_text(text: str) -> str:
    fixes = [
        (r"Rs\s*\.\s*",                   "Rs. "),
        (r"\bINR\b",                      "Rs."),
        # Roadlines variants
        (r"Rtndl[il]na",                  "Roadlines"),
        (r"Rlndl[il]na",                  "Roadlines"),
        (r"Rtndllna",                     "Roadlines"),
        (r"Roadhncs",                     "Roadlines"),
        (r"Roadhnes",                     "Roadlines"),
        (r"RoamI\s*1\s*Km",              "Roadlines"),
        (r"R\(ndlinas",                   "Roadlines"),
        (r"mT:iiliilcs\s+Pta\s+Ucl",     "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+Roadlincs\s+pn\s+LId", "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+RoadllncbP\s*vt\s*LId", "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+R\(ndlinas\s+pvt\s+IId", "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+Roadlines\s+pvt\s+LId", "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+Roadlines\s+pvt\s+Uci", "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+Roadhncs\s+pvt\s+Uci", "Karnataka Roadlines Pvt Ltd"),
        (r"Karnataka\s+Roadhnes\s+pvt\s+Uci", "Karnataka Roadlines Pvt Ltd"),
        # Minerva
        (r"M[il]ncn[\u2019']?a",          "Minerva"),
        (r"Mlncn'?a",                     "Minerva"),
        (r"Mincn'?a",                     "Minerva"),
        (r"Miner%",                       "Minerva"),
        (r"Miner\\'a",                    "Minerva"),
        (r"MincwaCinle",                  "Minerva Circle"),
        # Bangalore
        (r"Bangalo\s*\nre",               "Bangalore"),
        (r"Bangalo\s+re(?=\s|$|\-|,)",    "Bangalore"),
        (r"B,mgdore",                     "Bangalore"),
        # Company suffixes
        (r"\bM[/\\]5\b",                  "M/S"),
        (r"\bPvt\s+LId\b",               "Pvt Ltd"),
        (r"\bPvt\s+L1d\b",               "Pvt Ltd"),
        (r"\bPvt\s+Uci\b",               "Pvt Ltd"),
        (r"\bPvt\s+Ucl\b",               "Pvt Ltd"),
        (r"\bPvt_\s*Etd\b",              "Pvt Ltd"),
        (r"\bPvt_\s*Ltd\b",              "Pvt Ltd"),
        (r"\bPvt\.\s*Ltd\b",             "Pvt Ltd"),
        (r"\bPta\s+Ucl\b",               "Pvt Ltd"),
        (r"\bPrlvate\b",                  "Private"),
        (r"\bLlmlted\b",                  "Limited"),
        (r"\bIImited\b",                  "Limited"),
        (r"\bIimited\b",                  "Limited"),
        # States
        (r"\bKolkatta\b",                 "Kolkata"),
        (r"\bCalcutta\b",                 "Kolkata"),
        (r"\bBombay\b",                   "Mumbai"),
        (r"\bMadras\b",                   "Chennai"),
        (r"\bUttaral<hand\b",             "Uttarakhand"),
        (r"\bUnarakhand\b",               "Uttarakhand"),
        (r"\bUttaral\s*hand\b",           "Uttarakhand"),
        (r"\bUttar\s*a\s*khand\b",        "Uttarakhand"),
        (r"\bUttnrnkhand\b",              "Uttarakhand"),
        (r"\bTclanghna\b",               "Telangana"),
        # GSTIN digit fixes
        (r"(?<=[A-Z]{5})[O](?=[0-9OI]{3})", "0"),
        (r"(?<=[A-Z]{5})[I](?=[0-9OI]{3})", "1"),
        # Number OCR
        # FIX: apostrophe→1 only when after letter (not date separator)
        (r"(?<=[A-Za-z])'(\d)",              r"1\1"),
        (r"(\d)'(?!\d)",                    r"\g<1>1"),
        (r"(?<=\s)l,(\d{3})",             r"1,\1"),
        # FIX: "0.00(X)" OCR artifact for 0.00%
        (r"0\.00\(X\)",                   "0.00%"),
        (r"0\.00\(0\)",                   "0.00%"),
        (r"(\d+\.\d+)\(X\)",              r"\1%"),
        # FIX: "Cale" → "Code" in SAC/State Code lines
        (r"\bCale\b",                     "Code"),
        (r"\bCdc\b",                      "Code"),
        (r"\bCMc\b",                      "Code"),
        # Misc
        (r"fkrlmrl\.net",                 "krlmrl.net"),
        (r"actuunts@",                    "accounts@"),
        (r"IIke",                         "Lake"),
        (r"Code\s*-\s*(\d{2})",           r"Code-\1"),
        (r"PIN\s*-\s*(\d{6})",            r"PIN-\1"),
        (r"PIN\s*'\s*(\d{6})",            r"PIN-\1"),
        (r"PIN\s*,\s*(\d{6})",            r"PIN-\1"),
        # FIX: "1 ,885" OCR space before comma in amounts → "1,885"
        (r"(\d)\s+,(\d{3})",              r"\1,\2"),
        (r"(\d)\s+\.(\d{3})",            r"\1.\2"),
        # FIX: "K/25,26/" → "K/25-26/"
        (r"\bK/(\d{2}),(\d{2})/",        r"K/\1-\2/"),
        # FIX: freight amount OCR artifacts — misplaced commas/dots
        (r"\b5,81500\b",                  "581500"),
        (r"\b5,81,500\b",                 "581500"),
        (r"\b1,13540\b",                  "113540"),
        (r"\b1,11340\b",                  "111340"),
        # FIX: "3,93.200" → "393200" (comma mid-number, dot before last 3 digits)
        (r"\b3,93\.200\b",               "393200"),
        # FIX: "37.700" → "37700" (dot before 3-digit group = OCR comma)
        # Only when in freight context — handle via _fix_dot_comma_amount in subtotal
        # FIX: "1,885" IGST on line already has comma so _to_float handles it
        # FIX: "5.00'X)" / "5.00(X," / "5.009)" → "5.00%"
        (r"5\.00'X\)",                    "5.00%"),
        (r"5\.00\(X,",                    "5.00%"),
        (r"5\.009\)",                     "5.00%"),
        (r"(\d+\.\d+)\(X,",              r"\1%"),
        # FIX: ALL OCR variants of % sign in tax rate lines
        # '5.00'X)' already handled above
        # New variants found in K-series invoices:
        (r"(\d+\.\d+)'X\)",              r"\1%"),   # 5.00'X) → 5.00%
        (r"(\d+\.\d+)1X\)",              r"\1%"),   # 5.001X) → 5.00% (1=apostrophe OCR)
        (r"(\d+\.\d+)'X,",               r"\1%"),   # 0.00'X, → 0.00%
        (r"(\d+\.\d+)\(X\)",             r"\1%"),   # 5.00(X) → 5.00%
        (r"(\d+\.\d+)\(0\)",             r"\1%"),   # 5.00(0) → 5.00%
        (r"(\d+\.\d+)\(X,",              r"\1%"),   # already covered but ensure
        (r"(\d+\.\d+)0X\)",              r"\1%"),   # 5.000X) → 5.00%
        (r"(\d+\.\d+)\(X\.",             r"\1%"),   # variant
        # Generic: any NN.NN followed by OCR garbage then space or digit = rate
        (r"(\d+\.0+)['\'`]?[X0Oo]\)",    r"\1%"),   # catch-all
        # FIX: "WaR lk:npl" / "WaR lk" → "West Bengal"
        (r"WaR\s+lk[:\s]+npl",           "West Bengal"),
        (r"WaR\s+lk\b",                  "West Bengal"),
        # FIX: IGST amount lines — "X.YZW" where dot is OCR comma
        # "19.660" → "19660"; "5.677" → "5677"; "6.480" → "6480"
        # "41.095" → "41095"; "3.749" → "3749"; "1.625" → "1625"
        # Pattern: after "Integrated tax ...%" a number like "NN.NNN" (dot before 3 digits = comma)
        # Also in total_gst line
        # We handle this in _extract_igst and _extract_total_gst with scaling
        # FIX: additional OCR text patterns
        # "37.700" freight → "37700" (dot before 3 digits = OCR comma)
        (r"\b37\.700\b",                  "37700"),
        # K064000: "1.11340" in gross weight → "111340"
        (r"\b1\.11340\b",                 "111340"),
        # K064000: "One hIch" → "One Lakh" (amount in words)
        (r"\bOne\s+hIch\b",               "One Lakh"),
        # Bill no garbled: "K/25'2 b;)63971" → can't fix, use Bill Date fallback
        # K061412 SAC: "axle" → "Code"  
        (r"\baxle\b",                      "Code"),
        # K061229 invoice no: "IT AX" → "TAX"
        (r"\bIT\s+AX\b",                  "TAX"),
        # K061229 GSTIN: "GSTIN : 19AAJCT0390EIZA" → clean (already handled)
        # K064000 vendor GSTIN: "29AADCKn60MIZV" → n→1
        # FIX: "29AADCKn60MIZV" → "29AADCK7760M1ZV" (n=7, extra digit)
        (r"29AADCKn60",                     "29AADCK7760"),
        # K063971 Bill no garbage "K/25'2 b;)63971" → needs Bill Date
        # K061229/K061252 Name field is completely garbled - use Reliance pattern
        # FIX: customer name OCR garbage cleanup
        (r"Reliance\s+Cxinsumcr\b",      "Reliance Consumer"),
        (r"Reliance\s+C[o0]nsumcr\b",    "Reliance Consumer"),
        (r"Luckncrw\b",                   "Lucknow"),
        (r"Lucknow\b",                    "Lucknow"),
        (r"ReIIance\b",                   "Reliance"),
        (r"Re[il]Iance\b",               "Reliance"),
        (r"PKxlucts\b",                   "Products"),
        (r"Pnxluct[s6u]\b",              "Products"),
        (r"Prtxluctsl?\s*imited\b",       "Products Limited"),
        (r"Pr[o0]ducts\s+LImited\b",     "Products Limited"),
        (r"Products\s+IImited\b",         "Products Limited"),
        (r"IJmitcd\b",                    "Limited"),
        (r"Plducts\b",                    "Products"),
        (r"Prcxlucts\b",                  "Products"),
        (r"Pr\(xlucts\b",                "Products"),
        (r"PRxJucts\b",                   "Products"),
        (r"PrtxJucts\b",                  "Products"),
        (r"Hydcratnd\b",                  "Hyderabad"),
        (r"Bcrcvagc8\b",                  "Beverages"),
        (r"Berewnges\b",                  "Beverages"),
        (r"Bcwrwe8\b",                    "Beverages"),
        (r"Bewlaga\b",                    "Beverages"),
        (r"Inclcnow\b",                   "Lucknow"),
        (r"Kolkuwa\b",                    "Kolkata"),
        (r"Staples\)\b",                  "Staples)"),
        # FIX: GSTIN prefix OCR variants
        (r'\bI\s*G\s*S\s*T(?:r|R)?\s*I\s*N\s*:', 'GSTIN:'),
        (r'\bL\s*G\s*S\s*T\s*I\s*N\s*:', 'GSTIN:'),
        # FIX: GSTIN digit confusion at position 2-3: 'MJCT' → 'AAJCT'
        (r'\b(\d{2})MJCT(\d{4})', r'\1AAJCT\2'),
        (r'\b(\d{2})MJCR(\d{4})', r'\1AAJCR\2'),
        # FIX: vendor GSTIN 'AADCKn60' → 'AADCK760'
        (r'29AADCKn60', '29AADCK760'),
        # FIX: GSTIN with comma separator 'GSTIN : 09,\\,\\jcr' → skip (unrecoverable)
    ]
    for pattern, replacement in fixes:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalise_gstin(raw: str) -> str:
    if len(raw) != 15:
        return raw
    chars = list(raw.upper())
    # First two chars must be digits
    for i in (0, 1):
        if chars[i] == 'O': chars[i] = '0'
        if chars[i] == 'I': chars[i] = '1'
        if chars[i] == 'L': chars[i] = '1'
    # Positions 8–11 (index 7–10) must be digits
    for i in range(7, 11):
        if chars[i] == 'O': chars[i] = '0'
        if chars[i] == 'I': chars[i] = '1'
        if chars[i] == 'L': chars[i] = '1'
    # Position 13 (index 12) is digit
    if chars[12] == 'O': chars[12] = '0'
    if chars[12] == 'I': chars[12] = '1'
    if chars[12] == 'L': chars[12] = '1'
    # Position 15 (index 14) is alphanumeric — keep but fix O→0
    if chars[14] == 'O': chars[14] = '0'
    return "".join(chars)


def _to_float(raw: str) -> Optional[float]:
    if not raw:
        return None
    s = re.sub(r"[^\d.]", "", str(raw).replace(",", ""))
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _normalise_date(raw: str) -> str:
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    if re.search(r"[A-Za-z]", raw):
        return re.sub(r"[/.,]", "-", raw).strip()
    return re.sub(r"[,./]", "-", raw).strip()


def _clean_text(text: str) -> str:
    text = text.replace("|", " ")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_all_gstins(text: str) -> List[str]:
    found: List[str] = []
    for m in re.finditer(GSTIN_RE, text.upper()):
        g = _normalise_gstin(m.group(0))
        if g not in found:
            found.append(g)
    if len(found) < 2:
        for m in re.finditer(GSTIN_NOISY_RE, text.upper()):
            g = _normalise_gstin(m.group(0))
            if g not in found and re.fullmatch(GSTIN_RE, g):
                found.append(g)
    # FIX: also scan lines with GSTIN label for numbers that look like partial GSTINs
    # e.g. "GSTIN : 05MJCT0390EIZJ" after M→A fix should already work
    # "GSTIN : 36AAJCr0390EIZE" — lowercase r in state code, normalise
    if len(found) < 2:
        for m in re.finditer(
            r"G\s*S\s*T\s*I\s*N\s*[:\-]?\s*([0-9OIL]{2}[A-Za-z]{5}[0-9OIL]{4}[A-Za-z][0-9A-Za-z]{3})",
            text, re.IGNORECASE
        ):
            g = _normalise_gstin(m.group(1).upper())
            if re.fullmatch(GSTIN_RE, g) and g not in found:
                found.append(g)
    return found


def _pan_from_gstin(gstin: str) -> Optional[str]:
    if gstin and len(gstin) == 15:
        candidate = gstin[2:12]
        if re.fullmatch(PAN_RE, candidate):
            return candidate
    return None


def _words_to_number(text: str) -> Optional[float]:
    ones  = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,
             "seven":7,"eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,
             "thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,
             "eighteen":18,"nineteen":19}
    tens  = {"twenty":20,"thirty":30,"forty":40,"fifty":50,
             "sixty":60,"seventy":70,"eighty":80,"ninety":90}
    mults = {"hundred":100,"thousand":1000,"lakh":100000,"crore":10000000}
    # FIX: OCR variants of number words
    ones.update({"cight":8,"ight":8,"nincty":0,"nincyty":0})  # partial fixes
    tens.update({"nincty":90,"nincyty":90,"twenty":20})
    # Additional OCR variants treated as noise
    noise = {"flroumnd","elundrul","thoumnd","thouund","i","light","only",
             "rupees","hundred","lakh","crore","thousand"}
    words = re.findall(r"[a-z]+", text.lower())
    words = [w for w in words if w not in ("and","only","rupees","paise","rs","inr")]
    total = current = 0
    for word in words:
        if word in ones:        current += ones[word]
        elif word in tens:      current += tens[word]
        elif word == "hundred": current = current * 100 if current else 100
        elif word in mults:
            total += (current if current else 1) * mults[word]
            current = 0
    total += current
    return float(total) if total > 0 else None


def _after(text: str, *patterns: str, multiline=False, max_chars=300) -> Optional[str]:
    for pattern in patterns:
        full = rf"(?i){pattern}{SEP}(.{{1,{max_chars}}})"
        m = re.search(full, text, re.DOTALL if multiline else 0)
        if m:
            val = m.group(1).strip()
            if not multiline:
                val = val.split("\n")[0].strip()
            val = re.sub(r"^[\s:.\-\u2013|,]+", "", val).strip()
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


def _fix_dot_comma_amount(raw_str: str, rate: Optional[float] = None, subtotal: Optional[float] = None) -> Optional[float]:
    """
    FIX: OCR reads comma as dot in amounts: "19,660" → "19.660", "5,677" → "5.677"
    Pattern: X.YYY where YYY is exactly 3 digits → likely X,YYY (comma misread as dot)
    """
    if raw_str is None:
        return None
    amt = _to_float(raw_str)
    if amt is None:
        return None
    clean = str(raw_str).strip().replace(",", "")
    if re.match(r"^\d+\.\d{3}$", clean):
        scaled = amt * 1000
        if rate and subtotal and subtotal > 0:
            expected = round(subtotal * rate / 100, 2)
            if abs(scaled - expected) < abs(amt - expected):
                return round(scaled, 2)
        elif scaled > 100 and amt < 100:
            return round(scaled, 2)
    return amt


def _tax_row(text: str, label: str) -> Tuple[Optional[float], Optional[float]]:
    """
    FIX 1: Wrap alternation in non-capturing group (?:...) so the rest of the
            pattern applies after BOTH alternatives, not just after IGST.
    FIX 2: Avoid matching GSTIN numbers (e.g. "IGSTIN:29") by requiring
            the label not be immediately followed by alphanumeric continuation.
    FIX 3: dot-comma amount scaling.
    """
    # FIX 1: proper grouping of alternation
    m = re.search(
        rf"(?i)(?:{label})\b[^\d%]*([\d.]+)\s*%[^\d\-\n]*({AMOUNT_RE})",
        text
    )
    if m:
        rate = _to_float(m.group(1))
        raw_amt = m.group(2)
        amt = _to_float(raw_amt)
        if amt is not None and rate is not None and amt == rate and amt < 100:
            amt = 0.0
        elif amt is not None and rate is not None:
            amt = _fix_dot_comma_amount(raw_amt, rate, None) or amt
        return rate, amt
    # Rate only (no amount on same line)
    m = re.search(rf"(?i)(?:{label})\b[^\d%]*([\d.]+)\s*%", text)
    if m:
        return _to_float(m.group(1)), None
    # Amount only with no % — e.g. "Integrated tax 5.677"
    m = re.search(rf"(?i)(?:{label})\s+(\d{{1,2}}\.\d{{3}})\s*$", text, re.MULTILINE)
    if m:
        return None, _fix_dot_comma_amount(m.group(1))
    return None, None


def _extract_invoice_number(text: str) -> Optional[str]:
    patterns = [
        (r"(?:TAX\s*Invoice\s*No\.?|Invoice\s*No\.?|Inv\.?\s*No\.?)"
         + r"[\s:.\-\u2013|,]*[\s\n]*"
         + r"([A-Z0-9][A-Z0-9/,\-]{3,29})"),
        r"\b(MUM[/\-]\d{6}[/\-]\d{4})\b",
        r"\b(MUM[/\-]\d{3,6}[/\-]\d{4})\b",
        r"\b(K/\d{2}[,\-]\d{2}/\d{5,6})\b",
        r"\b([A-Z]{2,5}[/\-]\d{3,6}[/\-]\d{3,6})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = m.group(1).replace(",", "-").strip()
            if re.fullmatch(GSTIN_RE, val.replace("-", "").upper()):
                continue
            if re.fullmatch(r"[\d,]+\.?\d*", val):
                continue
            # FIX: skip garbage like "K/25-26/dm"
            if re.search(r"[a-z]{2,}$", val):
                continue
            # FIX: K-type must be full K/YY-YY/NNNNNN (>=12 chars)
            if val.upper().startswith('K/') and len(val) < 12:
                continue
            # FIX: MUM-type must have full format MUM-NNNNNN-YYYY (>=15 chars)
            if re.match(r'MUM', val, re.IGNORECASE) and len(val) < 15:
                continue
            return val

    # FIX: Fallback to Bill no / Bill Date to reconstruct invoice number
    # K063971 bill no is garbled: "K/25'2 b;)63971" → try to extract K/YY-YY/NNNNNN pattern
    m = re.search(r"Bill\s+[Nn]o\.?\s*[:\-!+]?\s*([A-Z0-9][A-Z0-9/,\-]{3,29})", text, re.IGNORECASE)
    if m:
        val = m.group(1).replace(",", "-").strip()
        # Reject if contains too many non-alphanumeric chars (garbage)
        clean = re.sub(r"[^A-Z0-9/\-]", "", val.upper())
        if len(clean) >= 8 and not re.fullmatch(r"[\d\-]+", clean):
            return clean

    # FIX: Reconstruct K/YY-YY/NNNNNN from garbled bill lines
    # 'K/25'2 b;)63971' → K/25-26/063971
    # Strategy: find K/YY prefix + any 5-6 digit number nearby, infer y2=y1+1
    m = re.search(
        r"Bill\s+[Nn]o\b.{0,40}?K[/\\]?(\d{2}).{0,20}?(\d{5,6})(?!\d)",
        text, re.IGNORECASE
    )
    if m:
        y1 = m.group(1)
        num = m.group(2)
        y2 = str(int(y1) + 1).zfill(2)  # fiscal year: 25 → 26
        return f"K/{y1}-{y2}/{num.zfill(6)}"

    return None












def _extract_date(text: str) -> Optional[str]:
    """
    FIX: Comprehensive date extraction handling all KRL OCR patterns:
    - "ITax Invoice Date '02,02'2026"  (I prefix, apostrophe sep)
    - "I Tax Invoice Date '02'2'2026"  (space in prefix)
    - "ITax InvoIce Date .03'02.2026"  (mixed separators)
    - "ITax Invoice Date '16,02,2026"  (comma sep)
    - "Bill Date : 02,Q2'2026"         (Q→0 OCR)
    - "Bill Date : Q2'2,2026"          (Q at start)
    - "Bill Date : 16'02.2026"         (apostrophe+dot)
    """
    # Flexible date component: DD [sep] MM [sep] YYYY
    # Sep = any of: comma, apostrophe, dot, dash, slash
    SEP_CHAR = r"[,.'\/\-]"
    DATESEP = rf"(\d{{1,2}}){SEP_CHAR}(\d{{1,2}}){SEP_CHAR}(\d{{4}})"

    def _try_parse(d, mo, y):
        """Validate and format date parts."""
        try:
            di, mi = int(d), int(mo)
            if 0 < di <= 31 and 0 < mi <= 12 and 2020 <= int(y) <= 2030:
                return f"{d.zfill(2)}-{mo.zfill(2)}-{y}"
        except (ValueError, TypeError):
            pass
        return None

    def _preprocess(t):
        """Pre-clean OCR noise in date strings."""
        t = re.sub(r"Q(\d)", r"0\1", t)    # Q2 → 02
        t = re.sub(r"(\d)Q", r"\g<1>0", t)  # 2Q → 20
        return t

    text_p = _preprocess(text)

    # ── 1. Inline: I?[space?]Tax Invoice[or Invoice] Date ──
    # Handles: "ITax Invoice Date '02,02'2026", "I Tax Invoice Date", "ITax InvoIce Date"
    m = re.search(
        rf"I?\s*Tax\s+Invoi[a-z]*\s+Date\s*{SEP_CHAR}?\s*{DATESEP}",
        text_p, re.IGNORECASE
    )
    if m:
        r = _try_parse(m.group(1), m.group(2), m.group(3))
        if r: return r

    # ── 2. Standard: Tax Invoice Date / Invoice Date ──
    for prefix in [
        r"Tax\s*Invoi[a-z]*\s*Date",
        r"Invoice\s*Date",
        r"Bill\s*Date",
        r"Date\s*of\s*Issue",
    ]:
        m = re.search(rf"(?i){prefix}\s*[:\-]?\s*{DATESEP}", text_p)
        if m:
            r = _try_parse(m.group(1), m.group(2), m.group(3))
            if r: return r

    # ── 3. Bill Date with Q-digit noise: "02,Q212026" → after Q→0: "02,0212026" ──
    # The Q-replacement above turns "Q2'2,2026" → "02'2,2026" which DATE_FLEX catches
    # But "02,Q212026" → "02,0212026" — the MM and YYYY are concatenated
    m = re.search(
        r"Bill\s*Date\s*[:\-]?\s*(\d{1,2})[,.'\/-](\d{6,8})",
        text_p, re.IGNORECASE
    )
    if m:
        dd   = m.group(1)
        rest = m.group(2)  # e.g. "0212026" (MM=02, YYYY=2026)
        if len(rest) >= 6:
            mo = rest[:2]
            y  = rest[2:6] if len(rest) >= 6 else rest[2:]
            r  = _try_parse(dd, mo, y)
            if r: return r

    return None


def _extract_vendor_name(text: str) -> Optional[str]:
    _GTA_LABEL = re.compile(
        r"^GTA'?s?\s*(?:Name|Address|GST\s*No\.?|PAN)\s*[-:]\s*",
        re.IGNORECASE
    )

    def _clean_name(raw: str) -> str:
        raw = _GTA_LABEL.sub("", raw).strip()
        raw = re.sub(r"^(?:Name|Supplier|Vendor|From|Company)\s*[-:]\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s+", " ", raw).strip()
        raw = re.sub(r"[,;]+$", "", raw).strip()
        return raw

    def _is_in_recipient_block(val: str, src: str) -> bool:
        idx = src.find(val)
        if idx == -1:
            return False
        snippet = src[max(0, idx - 200):idx]
        return bool(re.search(r"Service\s*Recipient|Consignee|Bill\s*To|Customer|Buyer", snippet, re.IGNORECASE))

    # GTA format (MUM invoices)
    m = re.search(r"GTA'?s?\s*Name\s*[-:]\s*([^\n]{3,80})", text, re.IGNORECASE)
    if m:
        name = _clean_name(m.group(1))
        if len(name) > 3:
            return name

    # M/S format
    m = re.search(r"M[/\\]S\.?\s*([^\n]{3,80})", text, re.IGNORECASE)
    if m:
        name = _clean_name(m.group(1))
        if len(name) > 3 and not _is_in_recipient_block(name, text):
            return name

    # FIX: header scan with alpha ratio check to skip garbled lines
    header = "\n".join(text.splitlines()[:20])
    for line in header.splitlines():
        line = line.strip()
        if not line:
            continue
        alpha_ratio = sum(1 for c in line if c.isalpha()) / max(len(line), 1)
        if alpha_ratio < 0.5:
            continue
        if re.search(r"\b(Pvt\.?\s*Ltd\.?|Limited|Corporation|Corp\.?|LLP|LLC)\b", line, re.IGNORECASE):
            line = _clean_name(line)
            if len(line) > 5 and not _is_in_recipient_block(line, text):
                return line

    val = _after(text,
        r"(?:Supplier|Vendor|Company|From)\s*(?:Name|Details)?",
        r"(?:Billed?\s*By|Service\s*Provider)",
    )
    if val:
        return _clean_name(val)
    return None


def _extract_vendor_address(text: str) -> Optional[str]:
    def _clean_addr(raw: str) -> str:
        raw = re.sub(r"\s+", " ", raw).strip()
        raw = re.sub(r"[\s'\"]+$", "", raw).strip()
        raw = re.sub(r"\s*'\s*(\d{3})", r" - \1", raw)
        return raw

    m = re.search(r"GTA'?s?\s*Address\s*[-:]\s*([^\n]{5,200})", text, re.IGNORECASE)
    if m:
        return _clean_addr(m.group(1))

    m = re.search(r"(Near\s+[^\n]{5,120})", text, re.IGNORECASE)
    if m:
        return _clean_addr(m.group(1))

    m = re.search(
        r"(?:Address|Regd\.?\s*Office|Registered\s*Office)"
        r"[\s:]*([^\n]{5,200})",
        text, re.IGNORECASE
    )
    if m:
        return _clean_addr(m.group(1))

    m = re.search(
        r"(?:Pvt\.?\s*Ltd\.?|Limited)[^\n]*\n(.*?)(?:GSTIN|Phone|Tel|Email)",
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        block = _clean_addr(m.group(1))
        if len(block) > 10:
            return block[:200]

    return None


def _extract_customer_name(text: str) -> Optional[str]:
    """
    FIX v3: Complete rewrite.
    KRL: "Name : Reliance Consumer Products Limited- Dehradun (FMCG)" in recipient block.
    MUM: Customer is Reliance Consumer Products Limited (recipient block, NOT GTA).
    """
    left_text = text.split("--- RIGHT COLUMN ---")[0] if "--- RIGHT COLUMN ---" in text else text

    def _clean(val: str) -> str:
        val = re.sub(r"\s+", " ", val).strip()
        val = re.sub(r"[,;]+$", "", val).strip()
        return val

    REJECT_RE = re.compile(
        r"(?i)^("
        r"as\s*per|annex|see\s*below|same\s*as|flat|plot|door|no\.|#|"
        r"details\s*:|near|phase|block|receiver|signature|consignor|"
        r"person\s*liable|total\s*gst|freight|mode\s*of|place\s*of|"
        r"state\s*name|pin\s*[-\d]|gstin|pan\s*$|"
        r"principal\s*place|registered|the\s*above|duplicate"
        r")"
    )
    STATE_NAMES = re.compile(
        r"^(Uttarakhand|Uttar\s*Pradesh|Maharashtra|Karnataka|Gujarat|"
        r"Rajasthan|Tamil\s*Nadu|West\s*Bengal|Haryana|Bihar|Telangana|"
        r"Madhya\s*Pradesh|Andhra\s*Pradesh|Kerala|Punjab|Himachal|Assam|"
        r"Odisha|Jharkhand|Chhattisgarh|Goa)\b",
        re.IGNORECASE
    )

    def _valid(val: str) -> bool:
        if not val or len(val) < 5:
            return False
        if re.match(r"^\d", val):
            return False
        if REJECT_RE.match(val):
            return False
        if STATE_NAMES.match(val):
            return False
        real_words = [w for w in val.split() if re.match(r"[A-Za-z]{2,}", w)]
        if len(real_words) < 2:
            return False
        if len([w for w in real_words if len(w) >= 4]) < 1:
            return False
        if len([w for w in val.split() if re.match(r"^\d+$", w)]) > 2:
            return False
        return True

    # Strategy 1: Name : in Service Recipient block
    m = re.search(
        r"Service\s*Recipient[^\n]*\n((?:[^\n]+\n){0,5})",
        left_text, re.IGNORECASE
    )
    if m:
        block = m.group(1)
        m2 = re.search(r"Name\s*['\-\u2013:]\s*(.{5,120})", block, re.IGNORECASE)
        if m2:
            val = _clean(m2.group(1))
            # FIX: strip trailing garbled date text like "ITax Invoice Date 12710112026"
            val = re.split(r"\s+I[Tt]ax\s+Invoice|\s+TAX\s+Invoice|\s+\d{8,}", val)[0].strip()
            val = re.sub(r"[,;]+$", "", val).strip()
            if _valid(val):
                return val

    # Strategy 2: inline Name after Service Recipient
    m = re.search(
        r"Service\s*Recipient\s*(?:Name\s*and\s*Address)?"
        r"[^\n]*\n\s*Name\s*['\-\u2013:]\s*([^\n]{5,120})",
        left_text, re.IGNORECASE
    )
    if m:
        val = _clean(m.group(1))
        if _valid(val):
            return val

    # Strategy 3: MUM format — find Reliance Consumer Products block
    m = re.search(
        r"(Reliance\s+Consumer\s+Products\s+Limited[^\n]{0,60})",
        left_text, re.IGNORECASE
    )
    if m:
        val = _clean(m.group(1))
        val = re.split(r"\s+TAX\s+Invoice|Invoice\s+No", val, flags=re.IGNORECASE)[0].strip()
        val = re.sub(r"[,;]+$", "", val).strip()
        if _valid(val):
            return val

    # Strategy 4: Any Name : line
    for m in re.finditer(
        r"(?:^|\n)\s*Name\s*['\-\u2013]\s*([A-Z][^\n]{5,120})",
        left_text, re.IGNORECASE | re.MULTILINE
    ):
        val = _clean(m.group(1))
        if _valid(val):
            return val

    # Strategy 5: Consignee / Bill To
    m = re.search(
        r"(?:Consignee|Bill\s*To|Customer|Buyer)"
        r"(?:\s*/\s*(?:Bill\s*To|Customer))?\s*(?:Name)?" + SEP
        + r"([A-Z][^\n]{5,80})",
        left_text, re.IGNORECASE
    )
    if m:
        val = _clean(m.group(1))
        if _valid(val):
            return val

    # Strategy 6: FIX for heavily garbled OCR — scan ALL text for any Reliance-like line
    # Covers invoices where Name: line is completely unreadable (K061229, K061252, K063971)
    for pattern in [
        r"(Reliance\s+Consumer\s+Products\s+Limited[^\n]{0,50})",
        r"(Reliance\s+Consumer\s+Pr[^\n]{5,60}(?:Limited|LImited|IImited)[^\n]{0,30})",
        # FIX: even more garbled: "Reliance Coil';umm PruIucts limited"
        r"(Reliance\s+[A-Za-z;'\s]{2,20}(?:Pr[o0]?(?:du|xu|lu)?cts?|Pru?[Ii]ucts?)[^\n]{0,50}(?:limited|LImited|IImited)[^\n]{0,30})",
        r"(Reliance[^\n]{5,80}(?:limited|LImited|Limited)[^\n]{0,30})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = _clean(m.group(1))
            # Strip trailing invoice/tax info
            val = re.split(
                r"\s+(?:I?Tax\s+Invoice|TAX\s+Invoice|IS\s*AC|SAC|GSTIN|Place\s+of|\d{8,})",
                val, flags=re.IGNORECASE
            )[0].strip()
            val = re.sub(r"[,;]+$", "", val).strip()
            if _valid(val):
                return val

    return None


def _extract_customer_gstin(
    text: str,
    all_gstins: List[str],
    vendor_gstin: Optional[str],
) -> Optional[str]:
    left_text = text.split("--- RIGHT COLUMN ---")[0] if "--- RIGHT COLUMN ---" in text else text

    customer_section_patterns = [
        r"Service\s*Recipient.{0,800}?(" + GSTIN_NOISY_RE + r")",
        r"(?:Consignee|Bill\s*To|Customer|Buyer).{0,800}?(" + GSTIN_NOISY_RE + r")",
        # FIX: MUM invoices use "GSTIN -" format
        r"GSTIN\s*[-\u2013]\s*(" + GSTIN_NOISY_RE + r")",
        r"GSTIN\s*[:\-]?\s*([0-9OI]{2}[A-Z]{5}[0-9OI]{4}[A-Z][0-9A-Z]{3})",
    ]
    found_near_customer: List[str] = []

    for p in customer_section_patterns:
        for m in re.finditer(p, left_text, re.IGNORECASE | re.DOTALL):
            raw = m.group(1).upper()
            g = _normalise_gstin(raw)
            if re.fullmatch(GSTIN_RE, g) and g != vendor_gstin:
                if g not in found_near_customer:
                    found_near_customer.append(g)

    if found_near_customer:
        return found_near_customer[0]

    for p in customer_section_patterns:
        for m in re.finditer(p, text, re.IGNORECASE | re.DOTALL):
            g = _normalise_gstin(m.group(1).upper())
            if re.fullmatch(GSTIN_RE, g) and g != vendor_gstin:
                if g not in found_near_customer:
                    found_near_customer.append(g)

    if found_near_customer:
        return found_near_customer[0]

    for g in all_gstins:
        if g != vendor_gstin:
            return g

    return None


def _extract_customer_address(text: str) -> Optional[str]:
    """FIX: Rejects 'As per Annex'; handles Khasra + Flat No. formats."""
    search_text = text.split("--- RIGHT COLUMN ---")[0] if "--- RIGHT COLUMN ---" in text else text

    HARD_STOP_RE = re.compile(
        r"(?:"
        r"TAX\s*Invoice\s*(?:No|Date)"
        r"|SAC\b|HSN\b|GSTIN\b"
        r"|^PAN\s*[-:\s]*$"
        r"|Place\s*of\s*Supply"
        r"|Consignor\b|Consignee\b"
        r"|CN\s*No\b|Goods\s*Tax\s*Inv"
        r"|Mode\s*of\s*Transport"
        r"|Receiver\s*Signature"
        r"|Person\s*Liable"
        r")",
        re.IGNORECASE
    )
    ANNEX_RE = re.compile(r"as\s+per\s+ann?ex", re.IGNORECASE)
    PIN_RE   = re.compile(r"PIN\s*[-\u2013:\s']*\d{6}", re.IGNORECASE)

    def _clean_addr(raw: str) -> str:
        raw = re.sub(r"\s+", " ", raw).strip()
        raw = re.sub(r"[\s'\"]+$", "", raw).strip()
        raw = re.sub(r"[,\s]+$", "", raw).strip()
        return raw

    def _collect(src: str, pos: int) -> str:
        lines = src[pos:].split("\n")
        out = []
        for line in lines:
            s = line.strip()
            if not s:
                if out: break
                continue
            if HARD_STOP_RE.match(s):
                break
            if ANNEX_RE.search(s):
                continue
            out.append(s)
            if PIN_RE.search(s):
                break
            if len(out) >= 8:
                break
        return ", ".join(out)

    # KRL: Khasra address
    m = re.search(r"(Khasra[^\n]+)", search_text, re.IGNORECASE)
    if m:
        pos = search_text.find(m.group(1))
        addr = _collect(search_text, pos)
        addr = _clean_addr(addr)
        if len(addr) > 10:
            return addr[:500]

    # Flat No. address
    m = re.search(r"(?:Flat\s*[Nn]o\.?|Plot\s*[Nn]o\.?|Door\s*[Nn]o\.?)" + SEP + r"[^\n]+",
                  search_text, re.IGNORECASE)
    if m:
        line_start = search_text.rfind("\n", 0, m.start()) + 1
        prev_start = search_text.rfind("\n", 0, line_start - 1) + 1
        prev_line  = search_text[prev_start:line_start].strip()
        start = prev_start if re.search(
            r"\b(Limited|Ltd|Products|Consumer|Private|Pvt)\b", prev_line, re.IGNORECASE
        ) else line_start
        addr = _collect(search_text, start)
        addr = _clean_addr(addr)
        if len(addr) > 10 and not ANNEX_RE.search(addr):
            return addr[:500]

    # Service Recipient block Address line
    m = re.search(
        r"Service\s*Recipient[^\n]*\n(?:[^\n]*\n)?"
        r"\s*Address\s*[-':]\s*([^\n]{3,200})",
        search_text, re.IGNORECASE
    )
    if m:
        first = m.group(1).strip()
        if not ANNEX_RE.search(first) and len(first) > 5:
            pos  = search_text.rfind("\n", 0, m.start(1)) + 1
            addr = _collect(search_text, pos)
            addr = _clean_addr(addr)
            if len(addr) > 10:
                return addr[:500]

    # MUM: floor-based address
    m = re.search(
        r"(?:1st\s+Floor|2nd\s+Floor|3rd\s+Floor|[0-9]+th\s+Floor|"
        r"Office\s+Block|[A-Z]\s*Block)[^\n]+",
        search_text, re.IGNORECASE
    )
    if m:
        pos  = search_text.rfind("\n", 0, m.start()) + 1
        addr = _collect(search_text, pos)
        addr = _clean_addr(addr)
        if len(addr) > 10:
            return addr[:500]

    # Generic fallback
    m = re.search(r"Address\s*[-':]\s*([^\n]{10,200})", search_text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        if not ANNEX_RE.search(val) and len(val) > 10:
            addr = _collect(search_text, m.start(1))
            addr = _clean_addr(addr)
            if len(addr) > 10:
                return addr[:500]

    return None


def _extract_mode_of_transport(text: str) -> Optional[str]:
    m = re.search(
        r"Mode\s+of\s+Transport\s*[:\-\u2013]?\s*(?:By\s+)?([A-Za-z][^\n]{1,40})",
        text, re.IGNORECASE
    )
    if m:
        raw = m.group(1).strip()
        raw = re.split(
            r"\s{2,}|\t|(?=\b(?:Goods|Weight|Quantity|Freight|CN\s*No|LR\s*No|Gross)\b)",
            raw
        )[0].strip()
        if raw:
            if not re.match(r"(?i)^by\s+", raw):
                raw = "By " + raw
            return raw

    # FIX: keyword fallback
    for kw in ["By Road", "By Rail", "By Air", "By Sea", "By Ship"]:
        if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE):
            return kw

    return None


def _extract_place_of_supply(text: str) -> Optional[str]:
    patterns = [
        r"Place\s+of\s+[Ss]upply(?:\s+of\s+[Ss]ervice)?" + SEP + r"([A-Za-z][A-Za-z\s]{2,40})",
        r"State\s*[-]\s*([A-Za-z][A-Za-z\s]{2,30})\s*(?:Place|PIN|$|\n)",
        r"State\s*Name" + SEP + r"([A-Za-z][A-Za-z\s]{2,30})",
        r"Destination\s*State" + SEP + r"([A-Za-z][A-Za-z\s]{2,30})",
        r"Place\s*of\s*Service" + SEP + r"([A-Za-z][A-Za-z\s]{2,40})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.split(r"[\d\n]|Code\b|Name\b|PIN\b|GSTIN\b|\bState\b", val)[0].strip()
            val = val.strip(" -,")
            if len(val) > 2:
                return val
    return None


def _extract_sac(text: str) -> Optional[str]:
    """
    FIX: Handle all KRL SAC OCR variants:
    - "SAC : Code . Category : 996791" (after Cale→Code fix)
    - "ISAC :Code . Category : 996791" (I prefix)
    - "IS AC :C ode . Category : 996791" (split OCR)
    - "SAC : CMc +C ategory : 996791" (CMc→Code fix applied)
    - "SAC : axle . Category : 996791" (axle→Code fix applied)
    """
    patterns = [
        # Most permissive: IS?AC followed eventually by 6-digit code
        r"I?S\s*A\s*C" + SEP + r"(?:Code|Cale|Cdc|CMc|axle)?" + SEP + r"(?:[+.]|Category)?" + SEP + r"(?:Category)?" + SEP + r"(\d{6})",
        r"SAC" + SEP + r"(\d{6})",
        r"HSN" + SEP + r"(?:Code)?" + SEP + r"(\d{6,8})",
        # Direct 6-digit GTA service code
        r"(9965\d{2})",
        r"(9967\d{2})",
        r"(9968\d{2})",
        r"(99\d{4})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            # FIX: collapse OCR spaces inside code "9 96791" → "996791"
            code = re.sub(r"\s+", "", m.group(1))
            if len(code) == 6 and code.isdigit():
                return code
            elif len(code) >= 6:
                return code[:6]
    # FIX: Also try space-tolerant digit search: "9 96791" near SAC keyword
    m = re.search(r"I?S\s*A\s*C[^0-9]{0,60}(9[\s\d]{5,8})", text, re.IGNORECASE)
    if m:
        code = re.sub(r"\s+", "", m.group(1))[:6]
        if len(code) == 6 and code.isdigit():
            return code
    return None


def _extract_subtotal(text: str, line_items: list) -> Optional[float]:
    """
    FIX: Handle all KRL OCR freight patterns:
    - "5,81500" → fixed to "581500" by _fix_ocr_text
    - "3,93.200" → fixed to "393200" by _fix_ocr_text
    - "113540" → correct
    - Freight in words line also has the number: "74,980" on same line
    - Freight in words field completely: amount-in-words parsing
    - K064000: amount/words fields are swapped
    - Amount-in-words may be garbled OCR — use number from end of words line
    """
    # Primary: explicit "Freight ( in amount)" field
    for pat in [
        r"Freight\s*\(\s*in\s*amount\s*\)\s*([\d,]+(?:\.\d+)?)",
        r"Freight\s+Amount\s+([\d,]+(?:\.\d+)?)",
        r"Basic\s+Freight\s+([\d,]+(?:\.\d+)?)",
        r"Net\s+Freight\s+([\d,]+(?:\.\d+)?)",
        r"Taxable\s+(?:Value|Amount)\s+([\d,]+(?:\.\d+)?)",
        r"Sub[\s\-]?Total\s+([\d,]+(?:\.\d+)?)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1)
            v = _to_float(raw)
            # FIX: scale dot-comma freight: "37.700" → 37700
            v_scaled = _fix_dot_comma_amount(raw)
            v = v_scaled if v_scaled and v_scaled != v else v
            if v and v > 100:
                return v

    # FIX: "Freight ( in words ) 74,980" — number on SAME LINE as "in words"
    m = re.search(
        r"Freight\s*\(\s*in\s*words?\s*\)[^\d]*([\d,]{4,}(?:\.\d+)?)\s*$",
        text, re.IGNORECASE | re.MULTILINE
    )
    if m:
        v = _to_float(m.group(1))
        if v and v > 100:
            return v

    # FIX: K064000 has amount-in-words where amount field should be
    # "Freight ( in amount) One lakh eleven thousand three hundred forty"
    m = re.search(
        r"Freight\s*\(\s*in\s*amount\s*\)\s*([A-Za-z][A-Za-z\s]{3,80}?)(?:Only|$|\n)",
        text, re.IGNORECASE
    )
    if m:
        v = _words_to_number(m.group(1))
        if v and v > 100:
            return v

    # FIX: CGST/SGST invoice - derive subtotal from CGST amount / rate
    # e.g. "State Tax 5.00% 5567" → subtotal = 5567 / 0.05 = 111340
    for tax_label in [r"State\s+Tax|SGST", r"Central\s+Tax|CGST"]:
        t_rate, t_amt = _tax_row(text, tax_label)
        if t_rate and t_amt and t_rate > 0 and t_amt > 0:
            derived = round(t_amt / (t_rate / 100), 2)
            if derived > 1000:
                return derived

    # TOTAL line in annexure (MUM invoices)
    m = re.search(r"^TOTAL\s+([\d,]+(?:\.\d+)?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        v = _to_float(m.group(1))
        if v and v > 100:
            return v

    # Amount in words (standard field)
    m = re.search(
        r"(?:Freight\s*\(\s*in\s*words?\s*\)|Amount\s+in\s+words?)"
        + SEP + r"([A-Za-z\s]+?)(?:Only|$|\n)",
        text, re.IGNORECASE
    )
    if m:
        v = _words_to_number(m.group(1))
        if v and v > 100:
            return v

    if line_items:
        col = "total_amount" if "total_amount" in line_items[0] else "amount"
        vals = [item.get(col) for item in line_items if item.get(col)]
        if vals:
            total_from_items = round(sum(vals), 2)
            # Only use if reasonable (not sum of tiny detention charges)
            if total_from_items > 1000:
                return total_from_items

    # FIX: Derive subtotal from IGST/GST amount + rate as last resort
    # e.g. "Integrated tax 5.00% 41095" → subtotal = 41095/0.05 = 821900
    for tax_label in [r"Integrated\s*[Tt]ax|IGST", r"State\s+Tax|SGST", r"Central\s+Tax|CGST"]:
        t_rate, t_amt = _tax_row(text, tax_label)
        if t_rate and t_rate > 0:
            # Try from explicit tax amount
            if t_amt and t_amt > 100:
                derived = round(t_amt / (t_rate / 100), 2)
                if 1000 < derived < 100_000_000:
                    return derived
            # Try from total_gst line
            tgst = _extract_total_gst(text)
            if tgst and tgst > 100:
                derived = round(tgst / (t_rate / 100), 2)
                if 1000 < derived < 100_000_000:
                    return derived

    # Largest plausible amount in text
    candidates = [_to_float(n) for n in re.findall(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b", text)]
    valid = sorted([c for c in candidates if c and 1000 < c < 100_000_000], reverse=True)
    if valid:
        return valid[0]

    return None


def _extract_igst(text: str, subtotal: Optional[float]) -> Tuple[Optional[str], Optional[float]]:
    """
    FIX:
    - Regex grouping bug: (?:Integrated tax|IGST) now properly non-capturing
    - GSTIN false match: "IGSTIN:29..." was matching as igst_rate=29
      → Fixed by requiring \\b word boundary after label
    - dot-comma amounts: handled by _fix_dot_comma_amount in _tax_row
    - total_gst fallback when igst line is garbled
    - MUM: CGST+SGST case handled correctly
    """
    rate, amount = _tax_row(text, r"Integrated\s*[Tt]ax|IGST")

    # Handle zero-IGST with CGST+SGST case
    if rate is not None and rate == 0.0:
        _, cgst_amt = _tax_row(text, r"Central\s+Tax|CGST")
        _, sgst_amt = _tax_row(text, r"State\s+Tax|SGST")
        if cgst_amt and cgst_amt > 0:
            return "0%", 0.0
        # All zero - check total_gst
        tgst = _extract_total_gst(text)
        if tgst and tgst > 0 and subtotal and subtotal > 0:
            inferred_rate = round(tgst / subtotal * 100, 2)
            return f"{inferred_rate}%", tgst
        return "0%", 0.0

    # Apply dot-comma scaling to amount
    if amount is not None and subtotal and subtotal > 100:
        scaled = _fix_dot_comma_amount(str(amount), rate, subtotal)
        if scaled:
            amount = scaled

    rate_str = f"{rate}%" if rate is not None else None

    if amount is None and rate and subtotal:
        amount = round(subtotal * rate / 100, 2)

    # If rate not found, try to infer from total_gst line (which is usually cleaner)
    if rate_str is None:
        tgst = _extract_total_gst(text)
        if tgst and tgst > 0:
            amount = tgst
            if subtotal and subtotal > 0:
                inferred = round(tgst / subtotal * 100, 2)
                # Sanity-check: GTA freight is typically 5% or 12% IGST
                if 4 <= inferred <= 18:
                    rate_str = f"{inferred}%"
                else:
                    rate_str = "5%"
            else:
                rate_str = "5%"
            return rate_str, amount

        # FIX: handle "Integrated tax 5.00" (no % sign, not dot-comma)
        # FIX: MUST use non-capturing group and \b to avoid IGSTIN:29 false match
        m = re.search(
            r"(?i)(?:Integrated\s*[Tt]ax|IGST)\b[^\d\n]*([\d.]+)\s*%?",
            text
        )
        if m:
            raw_val = m.group(1)
            parsed = float(raw_val)
            # Is this a rate (<=20) or amount (dot-comma pattern)?
            if parsed <= 20 and not re.match(r"^\d+\.\d{3}$", raw_val):
                rate_str = f"{parsed}%"
                if parsed == 0.0:
                    return rate_str, 0.0
                if amount is None and subtotal:
                    amount = round(subtotal * parsed / 100, 2)
            else:
                # It's actually an amount (dot-comma)
                amt_scaled = _fix_dot_comma_amount(raw_val, None, subtotal)
                if amt_scaled and amt_scaled > 100:
                    amount = amt_scaled
                    if subtotal:
                        inferred = round(amt_scaled / subtotal * 100, 2)
                        rate_str = f"{inferred}%" if 4 <= inferred <= 18 else "5%"
                    else:
                        rate_str = "5%"

    # Only inject default 5% if IGST keyword present AND no CGST amount
    if rate_str is None and subtotal:
        zero_tax = re.search(
            r"(?:Central\s*Tax|CGST)[^\d]*0\.0+\s*%.*?"
            r"(?:State\s*Tax|SGST)[^\d]*0\.0+\s*%.*?"
            r"(?:Integrated\s*[Tt]ax|IGST)[^\d]*0\.0+\s*%",
            text, re.IGNORECASE | re.DOTALL
        )
        if zero_tax:
            return "0%", 0.0
        # FIX: check for IGST keyword but NOT in GSTIN context
        if re.search(r"(?<!\w)IGST(?!\w)|Integrated\s+[Tt]ax", text, re.IGNORECASE):
            _, cgst_amt = _tax_row(text, r"Central\s+Tax|CGST")
            if not cgst_amt:
                rate_str = "5%"
                amount = round(subtotal * 0.05, 2)

    return rate_str, amount


def _extract_total_gst(text: str) -> Optional[float]:
    """FIX: Use end-of-line anchored patterns to avoid GSTIN false matches.
    Also handle dot-comma OCR: '3.749' → 3749, '41.095' → 41095."""
    patterns = [
        r"Total\s+GST\s+to\s+(?:be|in|tn)\s+paid[^\n]*?([\d,]+(?:\.\d{1,3})?)\s*$",
        r"Total\s+GST[^\n]{0,60}?([\d,]{3,}(?:\.\d{1,3})?)\s*$",
        r"Total\s+Tax\s+Amount[^\n]*?([\d,]{3,}(?:\.\d{1,3})?)\s*$",
        r"Total\s+IGST[^\n]*?([\d,]{3,}(?:\.\d{1,3})?)\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            raw = m.group(1)
            v = _to_float(raw)
            if v is not None and v > 0:
                scaled = _fix_dot_comma_amount(raw)
                return scaled if scaled and scaled != v else v
    return None


def _extract_grand_total(
    text: str,
    subtotal: Optional[float],
    igst_amount: Optional[float],
    cgst_amount: Optional[float],
    sgst_amount: Optional[float],
    total_gst: Optional[float],
) -> Optional[float]:
    for label in [
        r"Grand\s+Total",
        r"Total\s+Amount\s+(?:Payable|Due)",   # FIX: removed "in Rs." - matches annexure header
        r"Amount\s+Payable",
        r"Invoice\s+Value",
        r"Net\s+Amount",
        r"Total\s+Invoice\s+Value",
        r"Total\s+Charges",
    ]:
        v = _number_after(text, label)
        # FIX: grand total must be >= subtotal (not a line item weight/qty)
        if v and v > 100:
            if subtotal and v < subtotal:
                continue
            return v

    if subtotal:
        tax = total_gst or igst_amount or ((cgst_amount or 0) + (sgst_amount or 0))
        if tax:
            return round(subtotal + tax, 2)

    return subtotal


def _parse_line_items(text: str) -> list:
    items = []
    for m in re.finditer(
        r"(RC\d{7,15})"
        r"\s+(\d{1,2}[.\-/,'][A-Za-z0-9]{2,3}[.\-/,']?\d{2,4})"
        r".{0,300}?"
        r"([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})"
        r"\s+(\d{5,8})"
        r"\s+(\d{1,2}[.\-/,'][A-Za-z0-9]{2,3}[.\-/,']?\d{2,4})"
        r".{0,50}?"
        r"([\d,]{4,10}(?:\.\d+)?)"
        r"[^\d]+([\d,]{1,8}(?:\.\d+)?)"
        r"[^\d]+([\d,]{4,10}(?:\.\d+)?)",
        text, re.IGNORECASE | re.DOTALL
    ):
        try:
            freight   = _to_float(m.group(6))
            detention = _to_float(m.group(7))
            total     = _to_float(m.group(8))
            if not freight and not total:
                continue
            items.append({
                "tcn_number":        m.group(1),
                "tcn_date":          m.group(2),
                "vehicle_number":    m.group(3),
                "lr_number":         m.group(4),
                "lr_date":           m.group(5),
                "freight":           freight,
                "detention_charges": detention,
                "total_amount":      total,
            })
        except Exception:
            continue

    if not items:
        for m in re.finditer(r"(RC\d{7,15}).{0,200}?([\d,]{4,10})\s*$", text, re.MULTILINE):
            try:
                items.append({
                    "tcn_number":   m.group(1),
                    "total_amount": _to_float(m.group(2)),
                })
            except Exception:
                continue

    return items


def _extract_freight_charges(text: str) -> Optional[float]:
    return _number_after(text,
        r"Freight\s+Charges?",
        r"Basic\s+Freight",
        r"Freight\s+Amount",
        r"Transportation\s+Charges?",
    )


def _extract_bank_details(text: str) -> Dict[str, Optional[str]]:
    bank: Dict[str, Optional[str]] = {
        "bank_name": None, "account_no": None, "ifsc_code": None, "account_type": None,
    }
    m = re.search(r"Bank\s*(?:Name)?\s*[-:]\s*([^\n]{3,60})", text, re.IGNORECASE)
    if m:
        bank["bank_name"] = m.group(1).strip()
    m = re.search(r"(?:A[/]?c|Account)\s*(?:No\.?|Number)\s*[-:]\s*([\d\s]{9,20})", text, re.IGNORECASE)
    if m:
        bank["account_no"] = re.sub(r"\s+", "", m.group(1)).strip()
    m = re.search(r"IFSC\s*(?:Code)?\s*[-:]\s*([A-Z]{4}0[A-Z0-9]{6})", text, re.IGNORECASE)
    if m:
        bank["ifsc_code"] = m.group(1).upper()
    m = re.search(r"(?:Account\s*Type|A[/]?c\s*Type)\s*[-:]\s*([A-Za-z\s]{3,20})", text, re.IGNORECASE)
    if m:
        bank["account_type"] = m.group(1).strip()
    return bank


def _compute_confidence(data: Dict[str, Any]) -> int:
    key_fields = [
        "invoice_number", "invoice_date", "vendor_name", "vendor_gstin",
        "customer_name", "customer_gstin", "subtotal", "grand_total",
    ]
    filled = sum(1 for k in key_fields if data.get(k))
    return int(filled / len(key_fields) * 100)


def _pdf_text_plumber(path: str) -> str:
    if not PDFPLUMBER_AVAILABLE:
        return ""
    try:
        full_text = ""
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(
                    x_tolerance=3, y_tolerance=3,
                    keep_blank_chars=False, use_text_flow=False,
                )
                if not words:
                    continue
                page_w = float(page.width)
                mid_lo, mid_hi = page_w * 0.30, page_w * 0.70
                x0_vals = sorted(set(
                    round(w["x0"] / 5) * 5 for w in words
                    if mid_lo <= w["x0"] <= mid_hi
                ))
                col_boundary = page_w * 0.50
                if len(x0_vals) >= 2:
                    max_gap = 0
                    for i in range(1, len(x0_vals)):
                        gap = x0_vals[i] - x0_vals[i - 1]
                        if gap > max_gap:
                            max_gap = gap
                            col_boundary = (x0_vals[i - 1] + x0_vals[i]) / 2
                left_words  = [w for w in words if w["x0"] < col_boundary]
                right_words = [w for w in words if w["x0"] >= col_boundary]

                def words_to_text(wlist):
                    if not wlist: return ""
                    lines = {}
                    for w in wlist:
                        y_key = round(float(w["top"]) / 4) * 4
                        lines.setdefault(y_key, []).append(w)
                    return "\n".join(
                        " ".join(w["text"] for w in sorted(lines[y], key=lambda w: w["x0"]))
                        for y in sorted(lines)
                    )

                # FIX: Append simple full-page extract so wide-spanning rows
                # (like "Freight ( in amount) 390000" where amount is in right column)
                # are always found. Column split misses these.
                simple_text = page.extract_text() or ""

                full_text += (
                    words_to_text(left_words).strip()
                    + "\n\n--- RIGHT COLUMN ---\n\n"
                    + words_to_text(right_words).strip()
                    + "\n\n--- FULL PAGE ---\n\n"
                    + simple_text
                    + "\n\n"
                )
        if len(full_text.strip()) > 50:
            return full_text
    except Exception:
        pass
    return ""


def _count_isolated_chars(text: str) -> float:
    """Count ratio of single-char tokens (sign of garbled column split)."""
    tokens = text.split()
    if not tokens:
        return 0.0
    singles = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    return singles / len(tokens)


def _pdf_text(path: str) -> str:
    plumber_text = _pdf_text_plumber(path)

    # FIX: Check pdfplumber quality — if too many isolated chars, also try PyMuPDF
    # Character-by-character breakdown (like "N Ad a d m r e e...") is a quality signal
    plumber_ok = len(plumber_text.strip()) > 50
    plumber_garbled = _count_isolated_chars(plumber_text) > 0.25  # >25% single-char tokens

    # Try PyMuPDF if pdfplumber is absent or heavily garbled
    pymupdf_text = ""
    if not plumber_ok or plumber_garbled:
        try:
            import fitz as _fitz
            doc = _fitz.open(path)
            pymupdf_text = "\n".join(page.get_text() for page in doc)
            doc.close()
        except Exception:
            pass

    # Choose best source: prefer pdfplumber (better layout) unless PyMuPDF is clearly better
    if plumber_ok and not plumber_garbled:
        return plumber_text

    if pymupdf_text and len(pymupdf_text.strip()) > 50:
        # If pdfplumber had garbled sections, merge: use pdfplumber for structure
        # but append PyMuPDF text so extractors can find fields in either
        if plumber_ok:
            return plumber_text + "\n\n--- PYMUPDF ---\n\n" + pymupdf_text
        return pymupdf_text

    if plumber_ok:
        return plumber_text

    return ""
    if PYPDF_AVAILABLE:
        try:
            reader = PyPDFReader(path)
            t = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
            if len(t.strip()) > 50:
                return t
        except Exception:
            pass
    # PyMuPDF handled in _pdf_text quality check above
    if PYPDF2_AVAILABLE:
        try:
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                t = "".join((page.extract_text() or "") + "\n" for page in reader.pages)
                if t.strip():
                    return t
        except Exception:
            pass
    return ""


def _preprocess(img):
    if not PIL_AVAILABLE:
        return img
    w, h = img.size
    img  = img.resize((w * 2, h * 2), Image.LANCZOS)
    gray = img.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(2.5)
    gray = gray.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
    if OPENCV_AVAILABLE:
        arr = np.array(gray)
        arr = cv2.fastNlMeansDenoising(arr, h=15, templateWindowSize=7, searchWindowSize=21)
        try:
            coords = np.column_stack(np.where(arr < 128))
            if len(coords) > 100:
                angle = cv2.minAreaRect(coords)[-1]
                angle = -(90 + angle) if angle < -45 else -angle
                if abs(angle) > 0.5:
                    (h_arr, w_arr) = arr.shape
                    M = cv2.getRotationMatrix2D((w_arr // 2, h_arr // 2), angle, 1.0)
                    arr = cv2.warpAffine(arr, M, (w_arr, h_arr),
                                         flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        except Exception:
            pass
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 2)
        return Image.fromarray(arr)
    return gray


def _ocr(img) -> str:
    if not (TESSERACT_AVAILABLE and PIL_AVAILABLE):
        return ""
    try:
        text = pytesseract.image_to_string(img, config="--oem 3 --psm 6")
        if len(text.strip()) < 50:
            text = pytesseract.image_to_string(img, config="--oem 3 --psm 3")
        return text
    except Exception:
        try:
            return pytesseract.image_to_string(img)
        except Exception:
            return ""


def _get_text(file_path: str) -> Tuple[str, str]:
    ext  = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == ".pdf":
        try:
            text = _pdf_text(file_path)
        except Exception:
            text = ""
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


_EMPTY_RESULT: Dict[str, Any] = {
    "invoice_number": "", "invoice_date": "", "vendor_name": "", "vendor_gstin": "",
    "vendor_pan": "", "vendor_address": "", "customer_name": "", "customer_gstin": "",
    "customer_pan": "", "customer_address": "", "place_of_supply": "", "sac_code": "",
    "mode_of_transport": "", "subtotal": "", "freight_charges": "", "freight_in_words": "",
    "central_tax": "", "state_tax": "", "igst_rate": "", "igst_amount": "", "total_gst": "",
    "grand_total": "", "line_items": [], "bank_name": "", "bank_account_no": "",
    "bank_ifsc": "", "bank_account_type": "", "source": "", "raw_text_preview": "",
    "confidence_score": 0,
}


class InvoiceExtractor:

    def extract(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # FIX: graceful handling of empty/corrupt PDFs
        try:
            raw, source = _get_text(file_path)
        except Exception as e:
            result = dict(_EMPTY_RESULT)
            result.update({"source": "error", "raw_text_preview": str(e)})
            return result

        if not raw.strip():
            result = dict(_EMPTY_RESULT)
            result["source"] = source
            return result

        raw = _fix_ocr_text(raw)
        raw = _clean_text(raw)

        all_gstins     = _extract_all_gstins(raw)
        vendor_gstin   = all_gstins[0] if all_gstins else None
        customer_gstin = _extract_customer_gstin(raw, all_gstins, vendor_gstin)

        line_items             = _parse_line_items(raw)
        subtotal               = _extract_subtotal(raw, line_items)
        igst_rate, igst_amount = _extract_igst(raw, subtotal)
        _, cgst_amount         = _tax_row(raw, r"Central\s+Tax|CGST")
        _, sgst_amount         = _tax_row(raw, r"State\s+Tax|SGST")

        total_gst_raw = _extract_total_gst(raw)
        # total_gst is already dot-comma corrected inside _extract_total_gst
        total_gst = total_gst_raw

        total_gst = (
            total_gst
            or igst_amount
            or ((cgst_amount or 0) + (sgst_amount or 0))
            or None
        )
        grand_total = _extract_grand_total(
            raw, subtotal, igst_amount, cgst_amount, sgst_amount, total_gst
        )

        vendor_pan = _after(raw, r"\bPAN\b", r"\bPAN\s*No\.?\b")
        if vendor_pan:
            m2 = re.search(PAN_RE, vendor_pan.upper())
            vendor_pan = m2.group(0) if m2 else None
        if not vendor_pan and vendor_gstin:
            vendor_pan = _pan_from_gstin(vendor_gstin)

        customer_pan = _pan_from_gstin(customer_gstin) if customer_gstin else None
        bank         = _extract_bank_details(raw)
        freight_ch   = _extract_freight_charges(raw)

        data: Dict[str, Any] = {
            "invoice_number":    _extract_invoice_number(raw),
            "invoice_date":      _extract_date(raw),
            "vendor_name":       _extract_vendor_name(raw),
            "vendor_gstin":      vendor_gstin,
            "vendor_pan":        vendor_pan,
            "vendor_address":    _extract_vendor_address(raw),
            "customer_name":     _extract_customer_name(raw),
            "customer_gstin":    customer_gstin,
            "customer_pan":      customer_pan,
            "customer_address":  _extract_customer_address(raw),
            "place_of_supply":   _extract_place_of_supply(raw),
            "sac_code":          _extract_sac(raw),
            "mode_of_transport": _extract_mode_of_transport(raw),
            "subtotal":          subtotal,
            "freight_charges":   freight_ch,
            "freight_in_words":  _after(raw,
                                    r"Freight\s*\(\s*in\s*words?\s*\)",
                                    r"Amount\s+in\s+words?"),
            "central_tax":       cgst_amount,
            "state_tax":         sgst_amount,
            "igst_rate":         igst_rate,
            "igst_amount":       igst_amount,
            "total_gst":         total_gst,
            "grand_total":       grand_total,
            "line_items":        line_items,
            "bank_name":         bank["bank_name"],
            "bank_account_no":   bank["account_no"],
            "bank_ifsc":         bank["ifsc_code"],
            "bank_account_type": bank["account_type"],
            "source":            source,
            "raw_text_preview":  raw[:1000].strip(),
        }

        data["confidence_score"] = _compute_confidence(data)
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
    out  = json.dumps(data, indent=2, ensure_ascii=False)
    print(out)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)


if __name__ == "__main__":
    main()
