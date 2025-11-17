# FlatGeobuf API med S3 Support

API til at servere FlatGeobuf (.fgb) filer med HTTP Range request support.

## Features

- ✅ Servér .fgb filer fra lokal disk eller AWS S3
- ✅ HTTP Range request support (effektiv streaming)
- ✅ CORS support
- ✅ Sikkerhedsgrænser på range størrelse
- ✅ Kommenteret og dokumenteret kode

## Installation

```bash
# Installér Python dependencies
pip install -r requirements.txt

# Installér Node.js dependencies (kun hvis du bruger app.py med frontend)
npm install
```

## Konfiguration

Kopiér `.env.example` til `.env` og udfyld dine credentials:

```bash
cp .env.example .env
```

Redigér `.env`:

```bash
# Vælg data source: "local" eller "s3"
DATA_SOURCE=local

# S3 credentials (kun nødvendigt hvis DATA_SOURCE=s3)
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_REGION=eu-west-1
S3_BUCKET_NAME=your-bucket-name
```

## Brug

### Med lokal data

Læg dine `.fgb` filer i `data/` mappen:

```bash
data/
  rekreative_omraader.fgb
  andre_data.fgb
```

### Med S3

Upload dine `.fgb` filer til din S3 bucket:

```bash
aws s3 cp rekreative_omraader.fgb s3://your-bucket-name/
```

Sæt `DATA_SOURCE=s3` i `.env` filen.

## Start serveren

### Fuld version (med frontend)
```bash
uvicorn app:app --reload
```
Åbn http://127.0.0.1:8000

### Simpel API (kun endpoints)
```bash
uvicorn app_simple:app --reload
```

### Med S3 support
```bash
uvicorn app_s3:app --reload
```

## API Endpoints

### `HEAD /fgb/{layer_name}.fgb`
Returnerer fil metadata (størrelse, Accept-Ranges header).

### `GET /fgb/{layer_name}.fgb`
Returnerer fil data. **Kræver Range header**.

Eksempel:
```bash
# Hent de første 1024 bytes
curl -H "Range: bytes=0-1023" http://127.0.0.1:8000/fgb/rekreative_omraader.fgb
```

## Projekt struktur

```
.
├── app.py              # Fuld version med static files og frontend
├── app_simple.py       # Simpel API version
├── app_s3.py          # API med S3 support
├── requirements.txt    # Python dependencies
├── package.json        # Node.js dependencies
├── .env.example        # Environment variable template
├── data/              # Lokal data mappe (.fgb filer)
├── static/            # Frontend filer
│   └── index.html     # OpenLayers klient
└── node_modules/      # npm pakker (OpenLayers, FlatGeobuf, etc.)
```

## Sikkerhed

- Range requests er begrænset til max 2MB per request
- S3 credentials skal holdes i `.env` (ikke commit til git)
- CORS er som standard åben (`*`) - konfigurér til specifikke domæner i produktion

## Licens

ISC
