# 🧾 Invoice OCR Extractor

A full-stack application to extract structured data from invoice PDFs and images using OCR.

**Stack:** FastAPI (Python) backend · React (Vite) frontend · Tesseract OCR

---

## 📁 Project Structure

```
invoice-extractor/
├── backend/
│   ├── main.py          ← FastAPI app (routes)
│   ├── extractor.py     ← OCR + field extraction logic
│   ├── requirements.txt ← Python dependencies
│   └── README.md
├── frontend/
│   ├── src/
│   │   ├── pages/       ← Home, Result, History
│   │   ├── components/  ← Layout, Navbar
│   │   ├── utils/       ← API helper
│   │   └── App.jsx
│   ├── package.json
│   └── vite.config.js
└── README.md            ← (this file)
```

---

## ⚙️ STEP 1 — Install System Dependencies

### Tesseract OCR (REQUIRED — must install separately)

**Windows:**
1. Download installer from: https://github.com/UB-Mannheim/tesseract/wiki
2. Run the `.exe` and install to `C:\Program Files\Tesseract-OCR\`
3. Add it to your system PATH:
   - Search "Environment Variables" in Windows
   - Under System Variables → Path → Add: `C:\Program Files\Tesseract-OCR\`
4. Verify: open a new terminal and run `tesseract --version`

**macOS:**
```bash
brew install tesseract
```

**Ubuntu/Debian Linux:**
```bash
sudo apt-get update
sudo apt-get install tesseract-ocr
sudo apt-get install poppler-utils
```

### Poppler (needed by pdf2image)

**Windows:**
1. Download from: https://github.com/oschwartz10612/poppler-windows/releases
2. Extract to `C:\poppler\`
3. Add `C:\poppler\Library\bin` to your PATH (same way as Tesseract above)

**macOS:**
```bash
brew install poppler
```

**Linux:**
```bash
sudo apt-get install poppler-utils
```

---

## 🐍 STEP 2 — Backend Setup

Open a terminal in VS Code, navigate to the backend folder:

```bash
cd backend
```

Create and activate a virtual environment:

```bash
# Create venv
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate
```

Install all Python packages:

```bash
pip install -r requirements.txt
```

This installs:
| Package | Purpose |
|---|---|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server to run FastAPI |
| `python-multipart` | File upload support |
| `pytesseract` | Python wrapper for Tesseract OCR |
| `easyocr` | Alternative OCR engine (deep learning) |
| `pdf2image` | Convert PDF pages to images |
| `opencv-python` | Image preprocessing |
| `Pillow` | Image handling (PIL) |
| `PyPDF2` | Read embedded text from PDFs |
| `numpy` | Numerical operations (required by OpenCV/EasyOCR) |

Start the backend server:

```bash
uvicorn main:app --reload --port 8000
```

✅ API is now running at: http://localhost:8000
✅ Interactive API docs: http://localhost:8000/docs

---

## ⚛️ STEP 3 — Frontend Setup

Open a **second terminal** in VS Code:

```bash
cd frontend
```

Install Node.js packages:

```bash
npm install
```

This installs:
| Package | Purpose |
|---|---|
| `react` + `react-dom` | UI framework |
| `react-router-dom` | Page routing |
| `axios` | HTTP requests to backend |
| `react-dropzone` | Drag & drop file upload |
| `react-hot-toast` | Toast notifications |
| `framer-motion` | Animations |
| `lucide-react` | Icon library |
| `vite` | Fast build tool / dev server |

Start the frontend:

```bash
npm run dev
```

✅ Frontend running at: http://localhost:3000

---

## 🚀 Running the Full App

You need **two terminals** running simultaneously:

| Terminal | Command | URL |
|---|---|---|
| Terminal 1 (backend) | `uvicorn main:app --reload --port 8000` | http://localhost:8000 |
| Terminal 2 (frontend) | `npm run dev` | http://localhost:3000 |

Then open **http://localhost:3000** in your browser.

---

## 📌 Features

- **Upload** PDF or image invoices (drag & drop or click)
- **Single extraction** → view results with all fields parsed
- **Batch extraction** → upload up to 10 invoices at once
- **Export CSV** → download extracted data as CSV
- **Copy / Download JSON** → structured output
- **History** → all past extractions saved in browser (localStorage)

---

## 🔬 How the OCR Pipeline Works

```
PDF / Image
    │
    ▼
[PyPDF2]  ──── Try text layer first (fast, accurate)
    │           if text found → skip OCR
    ▼
[pdf2image] ── Convert each PDF page → high-res PNG (300 DPI)
    │
    ▼
[OpenCV + PIL] ─ Preprocess:
    │              • Grayscale
    │              • Contrast enhancement
    │              • Sharpen
    │              • Adaptive threshold (binarize)
    ▼
[Tesseract] ── Run OCR → raw text string
    │
    ▼
[Regex Parser] ─ Extract fields:
                  • Invoice number, date
                  • Vendor / customer name, GSTIN
                  • Line items (TCN, vehicle, LR, amounts)
                  • GST breakdown (IGST, CGST, SGST)
                  • Totals
    │
    ▼
JSON / CSV Output
```

---

## 🛠️ Troubleshooting

**"TesseractNotFoundError"**
→ Tesseract is not in your PATH. See Step 1 above.

**"pdf2image: PDFInfoNotInstalledError"**
→ Poppler is not installed or not in PATH. See Step 1 above.

**"CORS error" in browser**
→ Make sure backend is running on port 8000.

**EasyOCR slow on first run**
→ It downloads model weights (~100MB) the first time. Normal behaviour.

---

## 🗂️ API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check |
| POST | `/extract` | Single invoice → JSON |
| POST | `/extract-multiple` | Multiple invoices → JSON array |
| POST | `/export-csv` | Single invoice → CSV download |

Full interactive docs at: http://localhost:8000/docs
