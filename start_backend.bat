@echo off
echo ============================================
echo  Invoice OCR Extractor - Backend (port 8001)
echo ============================================
cd /d "%~dp0"
pip install uvicorn[standard] fastapi python-multipart pdfplumber PyMuPDF pytesseract Pillow --quiet --user
echo.
echo Starting backend on http://localhost:8001
echo Press Ctrl+C to stop.
echo.
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
pause
