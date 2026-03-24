import os
import re
import json
import tempfile
from typing import Optional, List, Dict, Any

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False


class InvoiceExtractor:
    """
    Main class that handles OCR-based extraction from invoice PDFs or images.
    Tries multiple strategies in order:
      1. PyPDF2 text layer (fastest, works if PDF has embedded text)
      2. Tesseract OCR on preprocessed image
      3. EasyOCR as fallback
    """

    def __init__(self, use_easyocr: bool = False):
        self.use_easyocr = use_easyocr
        self.reader = None
        if use_easyocr and EASYOCR_AVAILABLE:
            self.reader = easyocr.Reader(["en"])

    # ─────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────

    def extract(self, file_path: str) -> Dict[str, Any]:
        ext = os.path.splitext(file_path)[1].lower()

        # Try PDF text layer first
        if ext == ".pdf" and PYPDF2_AVAILABLE:
            text = self._extract_text_from_pdf(file_path)
            if text and len(text.strip()) > 100:
                return self._parse_fields(text, source="pdf_text_layer")

        # Convert to image(s) and OCR
        images = self._load_images(file_path)
        all_text = ""
        for img in images:
            preprocessed = self._preprocess_image(img)
            page_text = self._run_ocr(preprocessed)
            all_text += page_text + "\n"

        return self._parse_fields(all_text, source="ocr")

    def flatten_for_csv(self, data: Dict[str, Any]) -> List[List[str]]:
        """Flatten extracted data for CSV export."""
        rows = []
        for key, value in data.items():
            if key == "line_items" and isinstance(value, list):
                for i, item in enumerate(value, 1):
                    for k, v in item.items():
                        rows.append([f"line_item_{i}_{k}", str(v)])
            else:
                rows.append([key, str(value)])
        return rows

    # ─────────────────────────────────────────────────────────
    # TEXT EXTRACTION
    # ─────────────────────────────────────────────────────────

    def _extract_text_from_pdf(self, path: str) -> str:
        try:
            text = ""
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
            return text
        except Exception:
            return ""

    def _load_images(self, file_path: str) -> List[Any]:
        ext = os.path.splitext(file_path)[1].lower()
        images = []

        if ext == ".pdf":
            if PDF2IMAGE_AVAILABLE:
                try:
                    pil_images = convert_from_path(file_path, dpi=300)
                    images = pil_images
                except Exception as e:
                    print(f"pdf2image failed: {e}")
            if not images and PIL_AVAILABLE:
                try:
                    img = Image.open(file_path)
                    images = [img]
                except Exception:
                    pass
        else:
            if PIL_AVAILABLE:
                img = Image.open(file_path)
                images = [img]

        return images

    def _preprocess_image(self, img: Any) -> Any:
        """
        Apply preprocessing steps to improve OCR accuracy:
        - Convert to grayscale
        - Enhance contrast
        - Denoise
        - Threshold (binarize)
        """
        if not PIL_AVAILABLE:
            return img

        # Convert PIL → grayscale
        gray = img.convert("L")

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.0)

        # Sharpen
        sharpened = enhanced.filter(ImageFilter.SHARPEN)

        if OPENCV_AVAILABLE:
            import numpy as np
            np_img = np.array(sharpened)
            # Denoise
            denoised = cv2.fastNlMeansDenoising(np_img, h=10)
            # Adaptive threshold for cleaner text
            thresh = cv2.adaptiveThreshold(
                denoised, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 2
            )
            return Image.fromarray(thresh)

        return sharpened

    def _run_ocr(self, img: Any) -> str:
        """Run OCR using Tesseract (primary) or EasyOCR (fallback)."""
        text = ""

        if TESSERACT_AVAILABLE and PIL_AVAILABLE:
            try:
                config = "--oem 3 --psm 6"
                text = pytesseract.image_to_string(img, config=config)
                if len(text.strip()) > 50:
                    return text
            except Exception as e:
                print(f"Tesseract failed: {e}")

        if self.use_easyocr and EASYOCR_AVAILABLE and self.reader:
            try:
                import numpy as np
                np_img = np.array(img)
                results = self.reader.readtext(np_img)
                text = " ".join([res[1] for res in results])
            except Exception as e:
                print(f"EasyOCR failed: {e}")

        return text

    # ─────────────────────────────────────────────────────────
    # FIELD PARSING
    # ─────────────────────────────────────────────────────────

    def _parse_fields(self, text: str, source: str = "ocr") -> Dict[str, Any]:
        """
        Parse all invoice fields from extracted text using regex patterns.
        Handles both Karnataka Roadlines / GTA-style and S.P. Golden-style invoices.
        """
        result = {
            "source": source,
            "raw_text_preview": text[:500].strip(),
            "invoice_number": self._extract_invoice_number(text),
            "invoice_date": self._extract_invoice_date(text),
            "vendor_name": self._extract_vendor_name(text),
            "vendor_gstin": self._extract_vendor_gstin(text),
            "vendor_address": self._extract_vendor_address(text),
            "customer_name": self._extract_customer_name(text),
            "customer_gstin": self._extract_customer_gstin(text),
            "customer_address": self._extract_customer_address(text),
            "place_of_supply": self._extract_place_of_supply(text),
            "sac_code": self._extract_sac_code(text),
            "mode_of_transport": self._extract_transport_mode(text),
            "line_items": self._extract_line_items(text),
            "subtotal": self._extract_subtotal(text),
            "central_tax": self._extract_tax(text, "central"),
            "state_tax": self._extract_tax(text, "state"),
            "igst_rate": self._extract_igst_rate(text),
            "igst_amount": self._extract_igst_amount(text),
            "total_gst": self._extract_total_gst(text),
            "grand_total": self._extract_grand_total(text),
            "pan": self._extract_pan(text),
        }

        # Clean up None values to empty strings for cleaner output
        return {k: (v if v is not None else "") for k, v in result.items()}

    # ─────────────────────────────────────────────────────────
    # INDIVIDUAL FIELD EXTRACTORS
    # ─────────────────────────────────────────────────────────

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:TAX\s*Invoice\s*No[:\s.]*|Invoice\s*No[:\s.]*|Bill\s*[Nn]o[:\s.]*)([A-Z0-9/\-]{5,30})",
            r"(MUM-\d{6}-\d{4})",
            r"(K/\d{2}-\d{2}/\d{6})",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_invoice_date(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Tax\s*Invoice\s*Date|Invoice\s*Date|Bill\s*Date)[:\s.-]*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
            r"(?:Date)[:\s]*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_vendor_name(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:M/S|M/s)\s+(.+?)(?:\n|Near|Phone|GSTIN)",
            r"(Karnataka\s+Roadlines\s+Pvt\.?\s*Ltd\.?)",
            r"(S\.?\s*P\.?\s*GOLDEN\s+TRANSPORT\s+PVT\.?\s*LTD\.?)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_vendor_gstin(self, text: str) -> Optional[str]:
        # First GSTIN in the doc is usually vendor's
        m = re.search(r"GSTIN[:\s]*([0-9A-Z]{15})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _extract_vendor_address(self, text: str) -> Optional[str]:
        m = re.search(r"(?:Near|Address)[:\s]+(.{10,100}?)(?:Phone|GSTIN|PAN|\n\n)", text, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        return None

    def _extract_customer_name(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:Service\s*Recipient|Name\s*[-:]\s*)(Reliance[^\n]{0,60})",
            r"(?:Recipient|Bill\s*To|Customer)[:\s]+([A-Z][^\n]{5,60})",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_customer_gstin(self, text: str) -> Optional[str]:
        # Second GSTIN occurrence is usually customer's
        matches = re.findall(r"GSTIN[:\s]*([0-9A-Z]{15})", text, re.IGNORECASE)
        if len(matches) >= 2:
            return matches[1].strip()
        return None

    def _extract_customer_address(self, text: str) -> Optional[str]:
        m = re.search(
            r"(?:Flat\s*No|Plot\s*No)[.:\s]+(.{10,200}?)(?:GSTIN|PAN|State\s*Name|\n\n)",
            text, re.IGNORECASE | re.DOTALL
        )
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        return None

    def _extract_place_of_supply(self, text: str) -> Optional[str]:
        m = re.search(r"Place\s+of\s+[Ss]upply(?:\s+of\s+[Ss]ervice)?[:\s]+([A-Za-z\s]+)", text)
        if m:
            return m.group(1).strip()
        return None

    def _extract_sac_code(self, text: str) -> Optional[str]:
        m = re.search(r"SAC[:\s]+(?:Code[+\s]*(?:Category)?[:\s]+)?(\d{6})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _extract_transport_mode(self, text: str) -> Optional[str]:
        m = re.search(r"Mode\s+of\s+Transport[:\s]+([A-Za-z\s]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _extract_subtotal(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:Freight\s*\(?\s*in\s+amount\s*\)?)[:\s]*([\d,]+)",
            r"(?:TOTAL|Total\s+Amount)[:\s]*([\d,]+\.?\d*)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return float(m.group(1).replace(",", ""))
        return None

    def _extract_tax(self, text: str, tax_type: str) -> Optional[float]:
        label = {"central": "Central Tax", "state": "State Tax"}.get(tax_type, "")
        m = re.search(rf"{label}[:\s]+([\d.]+%?)\s+([\d,]+\.?\d*)", text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(2).replace(",", ""))
            except Exception:
                return None
        return None

    def _extract_igst_rate(self, text: str) -> Optional[str]:
        m = re.search(r"Integrated\s*[Tt]ax[:\s]+([\d.]+%)", text, re.IGNORECASE)
        if m:
            return m.group(1)
        m2 = re.search(r"Integrated\s*[Tt]ax[:\s]+(\d+\.\d+)", text, re.IGNORECASE)
        if m2:
            return m2.group(1) + "%"
        return None

    def _extract_igst_amount(self, text: str) -> Optional[float]:
        m = re.search(r"Integrated\s*[Tt]ax[:\s]+[\d.]+%?\s+([\d,]+\.?\d*)", text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                return None
        return None

    def _extract_total_gst(self, text: str) -> Optional[float]:
        m = re.search(
            r"Total\s+GST\s+to\s+be\s+paid[^\d]*([\d,]+\.?\d*)",
            text, re.IGNORECASE
        )
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                return None
        return None

    def _extract_grand_total(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:Grand\s*Total|Total\s*Amount\s*in\s*Rs)[.:\s]*([\d,]+\.?\d*)",
            r"(?:Thirty\s+two\s+thousand|Rupees)[^\d]*([\d,]+\.?\d*)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    if val > 100:
                        return val
                except Exception:
                    continue

        # Try to compute: subtotal + igst
        sub = self._extract_subtotal(text)
        igst = self._extract_igst_amount(text)
        if sub and igst:
            return round(sub + igst, 2)
        return None

    def _extract_pan(self, text: str) -> Optional[str]:
        m = re.search(r"PAN[:\s]+([A-Z]{5}[0-9]{4}[A-Z])", text, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def _extract_line_items(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract line items from the annexure/table section of GTA invoices.
        Looks for rows with TCN numbers (RC prefix), vehicle numbers, LR numbers, amounts.
        """
        items = []

        # Pattern for GTA invoice line items (RC number pattern)
        tcn_pattern = re.finditer(
            r"(RC\d{8,12})"          # TCN number
            r"[^\d]*(\d{1,2}[-/]\w{3}[-/]\d{2,4})"  # date
            r"[^\d]*(\d{6,10})"      # indent no
            r".{0,200}?"
            r"(\d{14,16})\s+"        # weight
            r"(\d{3,6})\s+"          # pack qty
            r"([A-Z][A-Z0-9]{5,12})" # vehicle number
            r".{0,100}?"
            r"(\d{5,8})\s+"          # LR number
            r"(\d{1,2}[-/]\w{3}[-/]\d{2,4})"  # LR date
            r"[^\d]+([\d,]{4,8})"    # freight amount
            r"[^\d]+([\d,]{4,8})"    # detention/other
            r"[^\d]+([\d,]{4,8})",   # total
            text, re.IGNORECASE
        )

        for m in tcn_pattern:
            try:
                item = {
                    "tcn_number": m.group(1),
                    "tcn_date": m.group(2),
                    "indent_no": m.group(3),
                    "vehicle_number": m.group(6),
                    "lr_number": m.group(7),
                    "lr_date": m.group(8),
                    "freight": float(m.group(9).replace(",", "")),
                    "detention_or_other": float(m.group(10).replace(",", "")),
                    "total_amount": float(m.group(11).replace(",", "")),
                }
                items.append(item)
            except Exception:
                continue

        # Simpler fallback: extract any lines with amounts
        if not items:
            amount_pattern = re.finditer(
                r"(RC\d{8,12})[^\n]*([\d,]{4,8})\s*$",
                text, re.IGNORECASE | re.MULTILINE
            )
            for m in amount_pattern:
                items.append({
                    "tcn_number": m.group(1),
                    "total_amount": float(m.group(2).replace(",", ""))
                })

        return items
