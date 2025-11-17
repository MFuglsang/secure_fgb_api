"""
Simpel FlatGeobuf API - kun range request endpoints.

Brug dette hvis du vil servere static filer på anden måde (nginx, Apache, etc.)
eller køre frontend og backend separat.

Start med: uvicorn app_simple:app --reload
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from typing import Optional

app = FastAPI(title="FlatGeobuf API")

# Tillad CORS så frontend kan køre på et andet domæne/port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # I produktion: angiv specifikke domæner
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#Sti til data mappen med .fgb filer
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Maksimal størrelse per range request (sikkerhedsgrænse)
MAX_RANGE_BYTES = 2 * 1024 * 1024  # 2 MB


def parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """
    Parser en HTTP Range header og returnerer (start, end) byte positions.
    
    Eksempler:
    - "bytes=0-1023" -> hent de første 1024 bytes
    - "bytes=1024-2047" -> hent bytes fra 1024 til 2047
    - "bytes=-1000" -> hent de sidste 1000 bytes
    """
    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="Only 'bytes' ranges supported")

    range_spec = range_header[len("bytes="):].strip()
    if "," in range_spec:
        raise HTTPException(status_code=416, detail="Multiple ranges not supported")

    # Håndtér suffix range: "bytes=-1000"
    if range_spec.startswith("-"):
        suffix_length = int(range_spec[1:])
        if suffix_length <= 0:
            raise HTTPException(status_code=416, detail="Invalid suffix length")
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        # Normal range: "bytes=0-1023" eller "bytes=0-"
        parts = range_spec.split("-")
        if len(parts) != 2:
            raise HTTPException(status_code=416, detail="Invalid range format")

        start_str, end_str = parts
        try:
            start = int(start_str)
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid range start")

        if end_str == "":
            end = file_size - 1
        else:
            try:
                end = int(end_str)
            except ValueError:
                raise HTTPException(status_code=416, detail="Invalid range end")

    # Valider range
    if start < 0 or end >= file_size or start > end:
        raise HTTPException(status_code=416, detail="Range not satisfiable")

    # Tjek størrelse
    length = end - start + 1
    if length > MAX_RANGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail=f"Requested range too large (>{MAX_RANGE_BYTES} bytes)",
        )
    return start, end


@app.head("/fgb/{layer_name}.fgb")
def head_flatgeobuf(layer_name: str):
    """HEAD request - returnerer fil metadata"""
    file_path = DATA_DIR / f"{layer_name}.fgb"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Layer not found")

    file_size = file_path.stat().st_size
    headers = {
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",
        "Content-Type": "application/octet-stream",
    }
    return Response(status_code=200, headers=headers)


@app.get("/fgb/{layer_name}.fgb")
def get_flatgeobuf(layer_name: str, request: Request):
    """GET request med Range header - returnerer del af filen"""
    file_path = DATA_DIR / f"{layer_name}.fgb"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Layer not found")

    file_size = file_path.stat().st_size
    range_header: Optional[str] = request.headers.get("range") or request.headers.get("Range")

    # Kræv Range header
    if not range_header:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Range header required",
        )

    start, end = parse_range(range_header, file_size)

    def iter_file(path: Path, start: int, end: int, chunk_size: int = 1024 * 64):
        """Stream fil i chunks"""
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    content_length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": "application/octet-stream",
    }

    return StreamingResponse(
        iter_file(file_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers=headers,
    )


@app.get("/")
def root():
    """API info"""
    return {
        "name": "FlatGeobuf API",
        "version": "1.0.0",
        "endpoints": {
            "HEAD /fgb/{layer_name}.fgb": "Get file metadata",
            "GET /fgb/{layer_name}.fgb": "Get file data (requires Range header)"
        }
    }
