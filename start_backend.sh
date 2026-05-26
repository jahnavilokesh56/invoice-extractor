#!/bin/bash
# Start Invoice OCR Extractor Backend
# Run from the project root (invoice-extractor-edited/)
#
# First-time setup:
#   pip install -r backend/requirements.txt
#   # Also ensure tesseract is installed:
#   # Ubuntu/Debian: sudo apt-get install tesseract-ocr
#   # macOS:         brew install tesseract
#   # Windows:       https://github.com/UB-Mannheim/tesseract/wiki

cd "$(dirname "$0")"
echo "Starting Invoice OCR backend on http://localhost:8000 ..."
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
