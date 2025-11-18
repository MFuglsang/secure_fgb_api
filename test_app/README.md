# Test App - OpenLayers Frontend

OpenLayers frontend to test the FlatGeobuf API.

## Setup

### 1. Configure Dataforsyningen Token

The test app uses a Danish basemap from Dataforsyningen. You need a token:

1. Get a token from https://dataforsyningen.dk/
2. Add it to your `.env` file in the project root:

```bash
DATAFORSYNINGEN_TOKEN=your_token_here
```

**Important:** The `.env` file is already in `.gitignore` and will NOT be committed to git!

### 2. Start test app

```bash
# From root directory
uvicorn test_app.app:app --reload --port 8001
```

Open http://127.0.0.1:8001

## Features

- OpenLayers map with Skærmkort basemap from Dataforsyningen
- FlatGeobuf layer with spatial indexing
- Loads only features in visible area
- Debug logging in console
- Secure token handling (token served via API, not hardcoded in frontend)

## API Endpoints

- `GET /` - Frontend (OpenLayers map)
- `GET /api/info` - API information
- `GET /api/config` - Frontend configuration (includes Dataforsyningen token)
- `HEAD /fgb/{layer_name}.fgb` - Get file metadata
- `GET /fgb/{layer_name}.fgb` - Get file data (requires Range header)

## Security

- Dataforsyningen token is stored in `.env` file (not committed to git)
- Token is served via `/api/config` endpoint (not hardcoded in HTML)
- Frontend fetches token at runtime from API
