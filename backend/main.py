from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import json
import csv
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
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.get("/")
def root():
    return {"message": "Invoice OCR Extractor API is running", "version": "1.0.0"}


@app.post("/extract")
async def extract_invoice(file: UploadFile = File(...)):
    """
    Upload a PDF or image invoice and extract structured data.
    Returns JSON with all extracted invoice fields.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    allowed_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"]
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
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
    # No finally block — file is kept in uploads/ so frontend can display it


@app.post("/extract-multiple")
async def extract_multiple(files: List[UploadFile] = File(...)):
    """
    Upload multiple invoice files and extract data from all of them.
    """
    results = []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        temp_path = os.path.join(UPLOAD_DIR, file.filename)
        try:
            with open(temp_path, "wb") as f:
                content = await file.read()
                f.write(content)
            result = extractor.extract(temp_path)
            results.append({"filename": file.filename, "status": "success", "data": result})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "error": str(e)})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return JSONResponse(content={"total": len(results), "results": results})


@app.post("/export-csv")
async def export_csv(file: UploadFile = File(...)):
    """
    Upload an invoice and download extracted data as CSV.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    temp_path = os.path.join(UPLOAD_DIR, file.filename)
    csv_path = os.path.join(OUTPUT_DIR, file.filename.replace(ext, ".csv"))

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
        if os.path.exists(temp_path):
            os.remove(temp_path)


# Serve uploaded files so the frontend can display the invoice PDF/image
try:
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
except Exception:
    pass  # uploads dir empty or not ready — will work once first file is uploaded


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)