from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse, Response, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Optional

app = FastAPI(title="OL + FlatGeobuf + Skærmkort")

# Definér stier til mapper
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"  # FlatGeobuf filer (.fgb)
STATIC_DIR = BASE_DIR / "static"  # HTML, CSS, JS filer
NODE_MODULES_DIR = BASE_DIR / "node_modules"  # npm pakker (OpenLayers, FlatGeobuf, etc.)

# Servér /static (index.html mm.)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Custom middleware til at håndtere JavaScript moduler uden .js extension
# Nogle ældre npm moduler importerer filer uden .js extension (f.eks. "./empty" i stedet for "./empty.js")
# Denne middleware fanger disse requests og tilføjer automatisk .js hvis filen findes
@app.middleware("http")
async def add_js_extension(request: Request, call_next):
    if request.url.path.startswith("/node_modules/"):
        path = Path(BASE_DIR / request.url.path.lstrip("/"))
        # Hvis filen ikke findes og ikke ender med .js, prøv at tilføje .js
        if not path.exists() and not request.url.path.endswith(".js"):
            js_path = path.with_suffix(".js")
            if js_path.exists():
                return FileResponse(js_path, media_type="application/javascript")
    
    response = await call_next(request)
    return response

# Servér hele node_modules på /node_modules
# Dette gør at browseren kan importere npm pakker direkte
app.mount("/node_modules", StaticFiles(directory=NODE_MODULES_DIR), name="node_modules")

@app.get("/", response_class=HTMLResponse)
def index():
    """Servér index.html som root-side"""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(500, "index.html ikke fundet")
    return index_file.read_text(encoding="utf-8")


# ---------- FlatGeobuf range-endpoints ----------
# FlatGeobuf bruger HTTP Range requests til at hente kun de dele af filen der er nødvendige
# Dette gør det muligt at indlæse geografiske data effektivt uden at skulle downloade hele filen

# Maksimal størrelse per range request (sikkerhedsgrænse)
MAX_RANGE_BYTES = 2 * 1024 * 1024  # 2 MB per request


def parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """
    Parser en HTTP Range header og returnerer (start, end) byte positions.
    
    Eksempler på Range headers:
    - "bytes=0-1023" -> hent de første 1024 bytes
    - "bytes=1024-2047" -> hent bytes fra 1024 til 2047
    - "bytes=-1000" -> hent de sidste 1000 bytes
    
    Returnerer tuple med (start_byte, end_byte)
    """
    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="Only 'bytes' ranges supported")

    range_spec = range_header[len("bytes="):].strip()
    if "," in range_spec:
        raise HTTPException(status_code=416, detail="Multiple ranges not supported")

    # Håndtér suffix range: "bytes=-1000" betyder de sidste 1000 bytes
    if range_spec.startswith("-"):
        suffix_length = int(range_spec[1:])
        if suffix_length <= 0:
            raise HTTPException(status_code=416, detail="Invalid suffix length")
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        # Normal range: "bytes=0-1023" eller "bytes=0-" (resten af filen)
        parts = range_spec.split("-")
        if len(parts) != 2:
            raise HTTPException(status_code=416, detail="Invalid range format")

        start_str, end_str = parts
        try:
            start = int(start_str)
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid range start")

        if end_str == "":
            # Hvis end er tom, hent resten af filen
            end = file_size - 1
        else:
            try:
                end = int(end_str)
            except ValueError:
                raise HTTPException(status_code=416, detail="Invalid range end")

    # Valider at range er gyldigt
    if start < 0 or end >= file_size or start > end:
        raise HTTPException(status_code=416, detail="Range not satisfiable")

    # Tjek at requested range ikke er for stor
    length = end - start + 1
    if length > MAX_RANGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail=f"Requested range too large (>{MAX_RANGE_BYTES} bytes)",
        )
    return start, end


@app.head("/fgb/{layer_name}.fgb")
def head_flatgeobuf(layer_name: str):
    """
    HEAD request - returnerer metadata om .fgb filen uden at sende selve indholdet.
    
    FlatGeobuf klienten (i browseren) bruger dette til at finde ud af:
    - Filstørrelsen (Content-Length)
    - Om serveren understøtter range requests (Accept-Ranges: bytes)
    
    Dette er første step før den begynder at hente data med range requests.
    """
    file_path = DATA_DIR / f"{layer_name}.fgb"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Layer not found")

    file_size = file_path.stat().st_size
    headers = {
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",  # Fortæller klienten at vi understøtter range requests
        "Content-Type": "application/octet-stream",
    }
    return Response(status_code=200, headers=headers)


@app.get("/fgb/{layer_name}.fgb")
def get_flatgeobuf(layer_name: str, request: Request):
    """
    GET request med Range header - returnerer en specifik del af .fgb filen.
    
    FlatGeobuf klienten sender flere små range requests for at:
    1. Læse header og spatial index (de første bytes i filen)
    2. Hente kun de features der er i det synlige område på kortet
    
    Dette gør det meget effektivt - en 150KB fil kan bruges uden at downloade det hele.
    
    Eksempel flow:
    1. Klient: "Range: bytes=0-1023" -> læs header
    2. Klient: "Range: bytes=1024-2047" -> læs spatial index
    3. Klient: "Range: bytes=5000-8000" -> hent features i synligt område
    """
    file_path = DATA_DIR / f"{layer_name}.fgb"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Layer not found")

    file_size = file_path.stat().st_size
    range_header: Optional[str] = request.headers.get("range") or request.headers.get("Range")

    # Vi kræver Range header for .fgb filer (sikkerhed - ingen fuld download)
    if not range_header:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Range header required",
        )

    # Parser range header for at finde hvilke bytes der skal returneres
    start, end = parse_range(range_header, file_size)

    def iter_file(path: Path, start: int, end: int, chunk_size: int = 1024 * 64):
        """
        Generator der læser og streamer den ønskede del af filen i chunks.
        
        I stedet for at læse hele range'en i memory på én gang, 
        sender vi den i små 64KB chunks for bedre memory effektivitet.
        """
        with path.open("rb") as f:
            f.seek(start)  # Gå til start position i filen
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    content_length = end - start + 1
    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",  # Fortæller klienten hvilke bytes den får
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": "application/octet-stream",
    }

    # Returnér 206 Partial Content (standard HTTP status for range responses)
    return StreamingResponse(
        iter_file(file_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers=headers,
    )
