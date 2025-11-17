"""
FlatGeobuf API med S3 support.

Kan servere .fgb filer fra enten:
- Lokal disk (data/ mappen)
- AWS S3 bucket

Konfigurér via .env fil:
- DATA_SOURCE=local  (brug lokal data/ mappe)
- DATA_SOURCE=s3     (brug S3 bucket)

Start med: uvicorn app_s3:app --reload
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import os

# Load environment variables fra .env fil
load_dotenv()

app = FastAPI(title="FlatGeobuf API with S3")

# CORS support
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # I produktion: angiv specifikke domæner
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Konfiguration
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_SOURCE = os.getenv("DATA_SOURCE", "local")  # "local" eller "s3"
MAX_RANGE_BYTES = 2 * 1024 * 1024  # 2 MB

# S3 konfiguration (kun brugt hvis DATA_SOURCE=s3)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# Initialisér S3 client hvis nødvendigt
s3_client = None
if DATA_SOURCE == "s3":
    if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME]):
        raise ValueError(
            "S3 credentials mangler! Sæt AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY "
            "og S3_BUCKET_NAME i .env filen"
        )
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )
    print(f"✓ S3 client initialiseret - bucket: {S3_BUCKET_NAME}")
else:
    print(f"✓ Bruger lokal data source - mappe: {DATA_DIR}")


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


def get_file_size_local(layer_name: str) -> int:
    """Hent filstørrelse fra lokal disk"""
    file_path = DATA_DIR / f"{layer_name}.fgb"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Layer not found")
    return file_path.stat().st_size


def get_file_size_s3(layer_name: str) -> int:
    """Hent filstørrelse fra S3"""
    try:
        response = s3_client.head_object(
            Bucket=S3_BUCKET_NAME,
            Key=f"{layer_name}.fgb"
        )
        return response['ContentLength']
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            raise HTTPException(status_code=404, detail="Layer not found in S3")
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")


def iter_file_local(layer_name: str, start: int, end: int, chunk_size: int = 1024 * 64):
    """Stream fil fra lokal disk i chunks"""
    file_path = DATA_DIR / f"{layer_name}.fgb"
    with file_path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def iter_file_s3(layer_name: str, start: int, end: int, chunk_size: int = 1024 * 64):
    """
    Stream fil fra S3 i chunks.
    
    Bruger S3's get_object med Range parameter til at hente kun den del vi skal bruge.
    Derefter streamer vi det i mindre chunks til klienten.
    """
    try:
        # S3 Range format: "bytes=start-end"
        response = s3_client.get_object(
            Bucket=S3_BUCKET_NAME,
            Key=f"{layer_name}.fgb",
            Range=f"bytes={start}-{end}"
        )
        
        # Stream body i chunks
        remaining = end - start + 1
        body = response['Body']
        
        while remaining > 0:
            chunk = body.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
            
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")


@app.head("/fgb/{layer_name}.fgb")
def head_flatgeobuf(layer_name: str):
    """
    HEAD request - returnerer fil metadata.
    
    Henter filstørrelse fra enten lokal disk eller S3 afhængigt af DATA_SOURCE.
    """
    if DATA_SOURCE == "s3":
        file_size = get_file_size_s3(layer_name)
    else:
        file_size = get_file_size_local(layer_name)
    
    headers = {
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",
        "Content-Type": "application/octet-stream",
    }
    return Response(status_code=200, headers=headers)


@app.get("/fgb/{layer_name}.fgb")
def get_flatgeobuf(layer_name: str, request: Request):
    """
    GET request med Range header - returnerer del af filen.
    
    Streamer data fra enten lokal disk eller S3 afhængigt af DATA_SOURCE.
    """
    # Hent filstørrelse
    if DATA_SOURCE == "s3":
        file_size = get_file_size_s3(layer_name)
    else:
        file_size = get_file_size_local(layer_name)
    
    # Kræv Range header
    range_header: Optional[str] = request.headers.get("range") or request.headers.get("Range")
    if not range_header:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Range header required",
        )

    # Parser range
    start, end = parse_range(range_header, file_size)

    # Hent data fra korrekt kilde
    if DATA_SOURCE == "s3":
        file_iterator = iter_file_s3(layer_name, start, end)
    else:
        file_iterator = iter_file_local(layer_name, start, end)

    content_length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": "application/octet-stream",
    }

    return StreamingResponse(
        file_iterator,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers=headers,
    )


@app.get("/")
def root():
    """API info"""
    return {
        "name": "FlatGeobuf API with S3",
        "version": "1.0.0",
        "data_source": DATA_SOURCE,
        "s3_bucket": S3_BUCKET_NAME if DATA_SOURCE == "s3" else None,
        "endpoints": {
            "HEAD /fgb/{layer_name}.fgb": "Get file metadata",
            "GET /fgb/{layer_name}.fgb": "Get file data (requires Range header)"
        }
    }
