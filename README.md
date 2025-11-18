# FlatGeobuf API med S3 Support

API til at servere FlatGeobuf (.fgb) filer med HTTP Range request support fra lokal disk eller AWS S3.

## Projekt struktur

```
.
├── app.py              # Core API - med S3 support (BRUG DENNE)
├── app_simple.py       # Tidligere simpel version (deprecated)
├── app_old.py          # Gamle fuld version (backup)
├── test_app/          # Test applikation med OpenLayers frontend
│   ├── app.py         # Test server med API + frontend
│   ├── static/        # Frontend filer (HTML, CSS, JS)
│   └── README.md      # Test app dokumentation
├── data/              # Lokal data mappe (.fgb filer)
├── node_modules/      # npm pakker (OpenLayers, FlatGeobuf, etc.)
├── requirements.txt   # Python dependencies
├── package.json       # Node.js dependencies
├── .env.example       # Environment variable template
└── .gitignore         # Git ignore fil
```

## Features

- ✅ Servér .fgb filer fra **lokal disk** eller **AWS S3**
- ✅ HTTP Range request support (effektiv streaming)
- ✅ CORS support
- ✅ Sikkerhedsgrænser på range størrelse (max 2MB)
- ✅ Konfigurérbar logging (DEBUG, INFO, WARNING, ERROR)
- ✅ Class-baseret arkitektur med Protocol interface
- ✅ Automatisk S3 fallback hvis boto3 ikke installeret

## Installation

```bash
# Installér Python dependencies
pip install -r requirements.txt

# For S3 support, installér også boto3 (optional)
pip install boto3

# Installér Node.js dependencies (kun hvis du bruger test_app)
npm install
```

## Konfiguration

### Environment variables

Kopiér `.env.example` til `.env` og konfigurér:

```bash
cp .env.example .env
```

Redigér `.env`:

```bash
# Logging niveau: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Vælg data source: "local" eller "s3"
DATA_SOURCE=local

# S3 credentials (kun hvis DATA_SOURCE=s3)
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_REGION=eu-west-1
S3_BUCKET_NAME=your-bucket-name
```

### Lokal data

Læg dine `.fgb` filer i `data/` mappen:

```bash
data/
  rekreative_omraader.fgb
  andre_data.fgb
```

### S3 data

1. Sæt `DATA_SOURCE=s3` i `.env`
2. Udfyld AWS credentials i `.env`
3. Upload `.fgb` filer til S3 bucket:

```bash
aws s3 cp rekreative_omraader.fgb s3://your-bucket-name/
```

Filerne skal ligge i roden af bucket'en med navnet `{layer_name}.fgb`.

## Start serveren

### Core API (Production)
```bash
uvicorn app:app --reload --port 8000
```

API kører på http://127.0.0.1:8000

### Test App (med OpenLayers frontend)
```bash
uvicorn test_app.app:app --reload --port 8001
```

Åbn http://127.0.0.1:8001

## Logging

Logging niveauer kan kontrolleres via `LOG_LEVEL` environment variable:

**Logging niveauer:**
- `DEBUG` - Alt inkl. detaljeret parsing og streaming info
- `INFO` - Alle requests, ranges, og filstørrelser (default)
- `WARNING` - Kun advarsler og fejl (manglende filer, ugyldige ranges)
- `ERROR` - Kun fejl
- `CRITICAL` - Kun kritiske fejl

**Eksempler:**

```bash
# Via environment variable
export LOG_LEVEL=WARNING
uvicorn app:app --reload --port 8000

# Via .env fil
echo "LOG_LEVEL=WARNING" >> .env
uvicorn app:app --reload --port 8000
```

**Logging output eksempler:**

```
INFO - Using local data source
INFO - HEAD request for layer: rekreative_omraader
INFO - HEAD response: rekreative_omraader - 151580 bytes (148.03 KB)
INFO - GET request for layer: rekreative_omraader from 127.0.0.1
INFO - Serving rekreative_omraader: bytes 0-8191 (8192 bytes, 5.4% of file) to 127.0.0.1
```

## API Endpoints

### `HEAD /fgb/{layer_name}.fgb`
Returnerer fil metadata (størrelse, Accept-Ranges header).

**Response headers:**
- `Content-Length` - Filens totale størrelse i bytes
- `Accept-Ranges: bytes` - Serveren understøtter range requests
- `Content-Type: application/octet-stream`

### `GET /fgb/{layer_name}.fgb`
Returnerer fil data. **Kræver Range header**.

**Request headers:**
- `Range: bytes=start-end` (required)

**Response:**
- Status: `206 Partial Content`
- Headers:
  - `Content-Range: bytes start-end/total`
  - `Content-Length` - Antal bytes i denne range
  - `Content-Type: application/octet-stream`

**Eksempler:**

```bash
# Hent fil metadata
curl -I http://127.0.0.1:8000/fgb/rekreative_omraader.fgb

# Hent de første 1024 bytes
curl -H "Range: bytes=0-1023" http://127.0.0.1:8000/fgb/rekreative_omraader.fgb

# Hent bytes 1000-2000
curl -H "Range: bytes=1000-2000" http://127.0.0.1:8000/fgb/rekreative_omraader.fgb
```

## Arkitektur

### Class struktur

- `Config` - Konfiguration (dataclass med factory method)
- `DataSource` (Protocol) - Interface for data sources
  - `LocalDataSource` - Læser fra lokal disk
  - `S3DataSource` - Læser fra AWS S3
- `RangeParser` - Parser og validerer HTTP Range headers
- `FlatGeobufService` - Orchestrator for HEAD/GET requests

### Data Source Pattern

API'et bruger et Protocol-baseret interface design:

```python
class DataSource(Protocol):
    def get_file_size(self, layer_name: str) -> int: ...
    def stream_range(self, layer_name: str, start: int, end: int, chunk_size: int) -> Generator[bytes, None, None]: ...
```

Dette gør det nemt at tilføje nye data sources (Azure Blob, Google Cloud Storage, etc.)

## Sikkerhed

- Range requests er begrænset til max 2MB per request
- S3 credentials skal holdes i `.env` (ikke commit til git)
- `.gitignore` inkluderer `.env` automatisk
- CORS er som standard åben (`*`) - konfigurér til specifikke domæner i produktion
- boto3 er optional dependency - serveren virker uden S3 support

## Licens

ISC
