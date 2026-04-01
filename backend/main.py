from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import json
import csv
import time
from typing import List
from extractor import InvoiceExtractor

app = FastAPI(
    title="Invoice OCR Extractor API",
    description="Extract structured data from invoice PDFs using OCR",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

extractor = InvoiceExtractor()

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"]

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.get("/")
def root():
    return {"message": "Invoice OCR Extractor API is running", "version": "1.0.0"}


@app.post("/extract")
async def extract_invoice(file: UploadFile = File(...)):
    """
    Upload a single PDF or image invoice and extract structured data.
    Returns JSON with all extracted invoice fields.
    File is kept on disk so the frontend PDF viewer can display it
    via GET /uploads/<filename>.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    temp_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        result = extractor.extract(temp_path)

        output_json_path = os.path.join(OUTPUT_DIR, file.filename.replace(ext, ".json"))
        with open(output_json_path, "w") as f:
            json.dump(result, f, indent=2)

        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
    # No finally block — file is intentionally kept in uploads/ for the PDF viewer


@app.post("/extract-multiple")
async def extract_multiple(files: List[UploadFile] = File(...)):
    """
    Upload multiple invoice files (up to 10) and extract data from all of them.
    Files are kept on disk so the frontend PDF viewer can display them
    via GET /uploads/<filename> when viewing history entries.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed per batch")

    results = []
    for file in files:
        if not file.filename:
            results.append({"filename": "unknown", "status": "error", "error": "Missing filename"})
            continue

        ext = os.path.splitext(file.filename)[1].lower()

        # Validate extension per file — skip unsupported types gracefully
        if ext not in ALLOWED_EXTENSIONS:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            })
            continue

        temp_path = os.path.join(UPLOAD_DIR, file.filename)
        try:
            with open(temp_path, "wb") as f:
                content = await file.read()
                f.write(content)
            result = extractor.extract(temp_path)
            results.append({"filename": file.filename, "status": "success", "data": result})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
        # No finally / no os.remove — file stays in uploads/ so history preview works

    return JSONResponse(content={"total": len(results), "results": results})


@app.post("/export-csv")
async def export_csv(file: UploadFile = File(...)):
    """
    Upload an invoice and download extracted data as CSV.
    Temporary file is cleaned up after the CSV is generated
    since it is not needed for preview (CSV export is a one-shot operation).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    temp_path = os.path.join(UPLOAD_DIR, file.filename)
    csv_path  = os.path.join(OUTPUT_DIR, file.filename.replace(ext, ".csv"))

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        result = extractor.extract(temp_path)

        with open(csv_path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Field", "Value"])
            flat = extractor.flatten_for_csv(result)
            for row in flat:
                writer.writerow(row)

        return FileResponse(
            csv_path,
            media_type="text/csv",
            filename=os.path.basename(csv_path)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # CSV export does not need the source file to persist — clean it up
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.delete("/uploads/cleanup")
def cleanup_uploads(older_than_hours: int = 24):
    """
    Remove files from uploads/ that are older than `older_than_hours` hours.
    Defaults to 24 hours. Call this periodically to prevent disk bloat.

    Examples:
        DELETE /uploads/cleanup                     → removes files older than 24 h
        DELETE /uploads/cleanup?older_than_hours=1  → removes files older than 1 h
        DELETE /uploads/cleanup?older_than_hours=0  → removes ALL files immediately
    """
    if older_than_hours < 0:
        raise HTTPException(status_code=400, detail="older_than_hours must be >= 0")

    cutoff  = time.time() - (older_than_hours * 3600)
    removed = []
    errors  = []

    for fname in os.listdir(UPLOAD_DIR):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
            try:
                os.remove(fpath)
                removed.append(fname)
            except Exception as e:
                errors.append({"file": fname, "error": str(e)})

    return {
        "removed": len(removed),
        "files":   removed,
        "errors":  errors,
    }


@app.get("/uploads/list")
def list_uploads():
    """
    List all files currently stored in the uploads/ directory.
    Useful for debugging or building an admin panel.
    Returns filename, size in KB, and last modified timestamp for each file.
    """
    files = []
    for fname in sorted(os.listdir(UPLOAD_DIR)):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            files.append({
                "filename":      fname,
                "size_kb":       round(stat.st_size / 1024, 2),
                "last_modified": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                ),
            })
    return {"count": len(files), "files": files}


# ── Static file serving ────────────────────────────────────────────────────────
# Serve uploaded files so the frontend PDF viewer can load them via
# GET http://localhost:8000/uploads/<filename>
# MUST be mounted after all route definitions so API routes take priority.
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)