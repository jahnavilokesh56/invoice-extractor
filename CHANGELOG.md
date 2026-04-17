# Changelog — v2.1.0

## Bug Fixes

### `extractor.py`
- **Missing `pypdf` dependency**: `pypdf` is now listed in `requirements.txt`. Without it, the primary PDF text extraction path silently failed and fell through to the slower OCR fallback on every file.
- **Duplicate GSTIN assignment**: The old code assigned `all_gstins[0]` to `vendor_gstin` unconditionally, then also searched for the customer GSTIN from the same list without guaranteeing the two were different. `_extract_customer_gstin()` now explicitly rejects any GSTIN that matches `vendor_gstin`.
- **`pan` field echoed `vendor_pan` verbatim**: The output had a redundant `pan` key that was a copy of `vendor_pan`. Removed; vendor PAN is now in `vendor_pan` only.
- **Grand total wrong on CGST+SGST invoices**: The fallback calculation was `subtotal + igst_amount`, which equals zero on domestic invoices that use CGST+SGST instead of IGST. Fixed to use `subtotal + total_gst` (which covers all tax types).
- **IGST 5% auto-injection**: The extractor previously assumed 5% IGST for *any* invoice that didn't have explicit IGST data. This caused wrong tax amounts on CGST+SGST invoices. Fixed: 5% IGST is now only inferred when the `IGST` keyword is actually present in the document.
- **Temp file leaks**: Batch endpoints did not clean up uploaded temp files on failure. Added a `_safe_remove()` helper and `finally` blocks throughout.
- **`/extract-sample` path traversal**: Added `os.path.commonpath` check to prevent `../` escapes.
- **OCR PSM fallback**: When Tesseract PSM 6 returns < 50 characters (complex multi-block layouts), the extractor now retries with PSM 3 before giving up.
- **Invoice number matched amounts**: A pure-numeric regex match was occasionally returning a monetary amount as the invoice number. Added guard to skip pure-numeric matches.

## New Features / Accuracy Improvements

### Backend
- **`customer_pan`**: Derived from the customer GSTIN (positions 3-12), just like `vendor_pan`.
- **`freight_charges`**: Separate extraction of the freight line amount, distinct from `subtotal`.
- **`bank_name`, `bank_account_no`, `bank_ifsc`, `bank_account_type`**: New bank/payment info fields.
- **`confidence_score`**: Integer 0–100 indicating how many of the 8 key fields were successfully extracted. Surfaces in the UI as High/Medium/Low.
- **Extended date patterns**: Now handles `DD-Mon-YYYY` (e.g. `15-Apr-2025`) and `YYYY-MM-DD` ISO format in addition to `DD/MM/YYYY`.
- **Expanded OCR corrections**: Added rupee symbol normalisation (`₹` → `Rs.`), common Indian state name OCR garbles, and digit confusion fixes in numeric contexts.
- **Place of supply**: Added `Place of Service` as an additional fallback label.
- **Raw text preview**: Extended from 600 to 1000 characters.

### Frontend (`Result.jsx`)
- Shows all new fields: `customer_pan`, `freight_charges`, bank details, `confidence_score`.
- Confidence score renders with colour coding (green ≥ 75%, amber ≥ 50%, red < 50%).
- Bank Details section is hidden when all four bank fields are empty (no noisy empty rows).
- Summary card shows confidence instead of `total_gst` (more actionable).

### Frontend (`api.js`)
- Added `exportCSVBatch`, `exportJSONBatch`, `listSampleInvoices`, `extractSample`, `extractAllSamples` — these were used in `Home.jsx` but missing from the shared `api.js` utility.
