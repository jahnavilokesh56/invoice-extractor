from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import json
import csv
import io
import time
import zipfile
from typing import List
from extractor import InvoiceExtractor

app = FastAPI(
    title="Invoice OCR Extractor API",
    description="Extract structured data from invoice PDFs using OCR",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://localhost:3005",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

extractor = InvoiceExtractor()

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_invoices")
ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"]
MAX_BATCH_SIZE = 50

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _validate_file(filename: str) -> str:
    """Return the lowercase extension or raise HTTPException."""
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    return ext


def _safe_remove(path: str) -> None:
    """Remove a file silently — never raises."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _build_csv_bytes(results: list) -> bytes:
    """
    Build a combined CSV from a list of extraction result dicts.
    Each result produces a block of rows starting with the filename header.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    for item in results:
        fname = item.get("filename", "unknown")
        data  = item.get("data", item)
        writer.writerow(["=== " + fname + " ==="])
        writer.writerow(["Field", "Value"])
        flat = extractor.flatten_for_csv(data)
        for row in flat:
            writer.writerow(row)
        writer.writerow([])

    return buf.getvalue().encode("utf-8")


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Invoice OCR Extractor API is running", "version": "2.1.0"}


# ── single invoice ────────────────────────────────────────────────────────────

@app.post("/extract")
async def extract_invoice(file: UploadFile = File(...)):
    ext = _validate_file(file.filename)
    temp_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)
        result = extractor.extract(temp_path)
        # FIX: save JSON output but do NOT delete temp file here — Result page needs it for preview
        out_path = os.path.join(OUTPUT_DIR, file.filename.replace(ext, ".json"))
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        _safe_remove(temp_path)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


@app.post("/export-csv")
async def export_csv(file: UploadFile = File(...)):
    ext = _validate_file(file.filename)
    temp_path = os.path.join(UPLOAD_DIR, file.filename)
    csv_path  = os.path.join(OUTPUT_DIR, file.filename.replace(ext, ".csv"))
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)
        result = extractor.extract(temp_path)
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Field", "Value"])
            for row in extractor.flatten_for_csv(result):
                writer.writerow(row)
        return FileResponse(csv_path, media_type="text/csv",
                            filename=os.path.basename(csv_path))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _safe_remove(temp_path)


# ── batch invoices (up to 50) ─────────────────────────────────────────────────

@app.post("/extract-multiple")
async def extract_multiple(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400,
                            detail=f"Maximum {MAX_BATCH_SIZE} files allowed per batch")
    results = []
    for file in files:
        if not file.filename:
            results.append({"filename": "unknown", "status": "error", "error": "Missing filename"})
            continue
        try:
            ext = _validate_file(file.filename)
        except HTTPException as e:
            results.append({"filename": file.filename, "status": "error", "error": e.detail})
            continue
        temp_path = os.path.join(UPLOAD_DIR, file.filename)
        try:
            content = await file.read()
            with open(temp_path, "wb") as f:
                f.write(content)
            result = extractor.extract(temp_path)
            results.append({"filename": file.filename, "status": "success", "data": result})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
        # FIX: always clean up temp files in batch mode
        finally:
            _safe_remove(temp_path)
    return JSONResponse(content={"total": len(results), "results": results})


@app.post("/export-csv-batch")
async def export_csv_batch(files: List[UploadFile] = File(...)):
    """Extract multiple invoices and return a single combined CSV file."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400,
                            detail=f"Maximum {MAX_BATCH_SIZE} files allowed per batch")

    items = []
    for file in files:
        if not file.filename:
            continue
        try:
            _validate_file(file.filename)
        except HTTPException:
            continue
        temp_path = os.path.join(UPLOAD_DIR, file.filename)
        try:
            content = await file.read()
            with open(temp_path, "wb") as f:
                f.write(content)
            result = extractor.extract(temp_path)
            items.append({"filename": file.filename, "data": result})
        except Exception:
            pass
        finally:
            _safe_remove(temp_path)

    if not items:
        raise HTTPException(status_code=400, detail="No files could be processed")

    csv_bytes = _build_csv_bytes(items)
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices_batch.csv"}
    )


@app.post("/export-json-batch")
async def export_json_batch(files: List[UploadFile] = File(...)):
    """Extract multiple invoices and return a single combined JSON file."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400,
                            detail=f"Maximum {MAX_BATCH_SIZE} files allowed per batch")

    results = []
    for file in files:
        if not file.filename:
            continue
        try:
            _validate_file(file.filename)
        except HTTPException:
            continue
        temp_path = os.path.join(UPLOAD_DIR, file.filename)
        try:
            content = await file.read()
            with open(temp_path, "wb") as f:
                f.write(content)
            result = extractor.extract(temp_path)
            results.append({"filename": file.filename, "status": "success", "data": result})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
        finally:
            _safe_remove(temp_path)

    json_bytes = json.dumps({"total": len(results), "results": results}, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=invoices_batch.json"}
    )


# ── sample invoices ───────────────────────────────────────────────────────────

@app.get("/sample-invoices")
def list_sample_invoices():
    sample_path = os.path.abspath(SAMPLE_DIR)
    if not os.path.isdir(sample_path):
        return {"count": 0, "files": []}
    files = []
    for fname in sorted(os.listdir(sample_path)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in ALLOWED_EXTENSIONS:
            fpath = os.path.join(sample_path, fname)
            stat  = os.stat(fpath)
            files.append({"filename": fname, "size_kb": round(stat.st_size / 1024, 2)})
    return {"count": len(files), "files": files}


# FIX: accept filename as a Query param (was missing Query import in original)
@app.post("/extract-sample")
async def extract_sample_invoice(filename: str = Query(...)):
    sample_path = os.path.abspath(SAMPLE_DIR)
    file_path   = os.path.join(sample_path, filename)
    # Security: prevent path traversal
    if not os.path.commonpath([file_path, sample_path]).startswith(sample_path):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"Sample invoice '{filename}' not found")
    ext = _validate_file(filename)
    try:
        result = extractor.extract(file_path)
        out_path = os.path.join(OUTPUT_DIR, filename.replace(ext, ".json"))
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")


@app.post("/extract-all-samples")
async def extract_all_samples():
    sample_path = os.path.abspath(SAMPLE_DIR)
    if not os.path.isdir(sample_path):
        raise HTTPException(status_code=404, detail="sample_invoices/ directory not found")
    results = []
    for fname in sorted(os.listdir(sample_path)):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        file_path = os.path.join(sample_path, fname)
        try:
            result = extractor.extract(file_path)
            results.append({"filename": fname, "status": "success", "data": result})
        except Exception as e:
            results.append({"filename": fname, "status": "error", "error": str(e)})
    return JSONResponse(content={"total": len(results), "results": results})


@app.get("/sample-invoices/file/{filename}")
def serve_sample_invoice(filename: str):
    sample_path = os.path.abspath(SAMPLE_DIR)
    file_path   = os.path.join(sample_path, filename)
    # Security: prevent path traversal
    if not os.path.commonpath([file_path, sample_path]).startswith(sample_path):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="application/pdf")


# ── uploads management ────────────────────────────────────────────────────────

@app.delete("/uploads/cleanup")
def cleanup_uploads(older_than_hours: int = 24):
    if older_than_hours < 0:
        raise HTTPException(status_code=400, detail="older_than_hours must be >= 0")
    cutoff = time.time() - (older_than_hours * 3600)
    removed, errors = [], []
    for fname in os.listdir(UPLOAD_DIR):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
            try:
                os.remove(fpath)
                removed.append(fname)
            except Exception as e:
                errors.append({"file": fname, "error": str(e)})
    return {"removed": len(removed), "files": removed, "errors": errors}


@app.get("/uploads/list")
def list_uploads():
    files = []
    for fname in sorted(os.listdir(UPLOAD_DIR)):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            files.append({
                "filename": fname,
                "size_kb": round(stat.st_size / 1024, 2),
                "last_modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
            })
    return {"count": len(files), "files": files}


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
