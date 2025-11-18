"""
Test Application - FlatGeobuf API with OpenLayers frontend (Class-based)

This is a test version that includes both the API and an OpenLayers frontend
to visualize FlatGeobuf data.

Uses the same class structure as the core API, but with extra frontend middleware.

Start with: uvicorn test_app.app:app --reload --port 8001
Open: http://127.0.0.1:8001
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse, Response, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Generator
from dataclasses import dataclass
import os
from dotenv import load_dotenv

# Load environment variables from .env file in project root
project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

# Import core classes from main app
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import Config, RangeParser, LocalDataSource, FlatGeobufService


@dataclass
class TestAppConfig:
    """Configuration for test application"""
    base_dir: Path
    test_app_dir: Path
    data_dir: Path
    static_dir: Path
    node_modules_dir: Path
    max_range_bytes: int = 2 * 1024 * 1024  # 2 MB
    chunk_size: int = 1024 * 64  # 64 KB
    dataforsyningen_token: str = ""  # Token for Danish basemap
    
    @classmethod
    def from_defaults(cls) -> "TestAppConfig":
        """Create config with default values for test app"""
        test_app_dir = Path(__file__).resolve().parent
        base_dir = test_app_dir.parent
        
        return cls(
            base_dir=base_dir,
            test_app_dir=test_app_dir,
            data_dir=base_dir / "data",
            static_dir=test_app_dir / "static",
            node_modules_dir=base_dir / "node_modules",
            dataforsyningen_token=os.getenv("DATAFORSYNINGEN_TOKEN", "")
        )


class StaticFileMiddleware:
    """Middleware to handle static files with .js extension"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
    
    def should_handle(self, request: Request) -> bool:
        """Check if request should be handled by middleware"""
        return request.url.path.startswith("/node_modules/")
    
    def try_add_js_extension(self, request: Request) -> FileResponse | None:
        """
        Try to find file with .js extension if original not found.
        
        Some older npm modules import files without .js extension
        (e.g. "./empty" instead of "./empty.js").
        This method catches these requests and automatically adds .js.
        """
        path = Path(self.base_dir / request.url.path.lstrip("/"))
        
        # If file doesn't exist and doesn't end with .js, try adding .js
        if not path.exists() and not request.url.path.endswith(".js"):
            js_path = path.with_suffix(".js")
            if js_path.exists():
                return FileResponse(js_path, media_type="application/javascript")
        
        return None


class FrontendService:
    """Service to handle frontend operations"""
    
    def __init__(self, config: TestAppConfig):
        self.config = config
    
    def get_index_html(self) -> str:
        """
        Get index.html content.
        
        Raises:
            HTTPException: If index.html not found
        """
        index_file = self.config.static_dir / "index.html"
        if not index_file.exists():
            raise HTTPException(500, "index.html not found")
        return index_file.read_text(encoding="utf-8")


class TestAppService:
    """
    Main service for test application.
    
    Combines FlatGeobuf service with frontend service.
    """
    
    def __init__(self, config: TestAppConfig):
        self.config = config
        
        # Create FlatGeobuf service with config from test app
        fgb_config_dict = {
            'base_dir': config.base_dir,
            'data_dir': config.data_dir,
            'max_range_bytes': config.max_range_bytes,
            'chunk_size': config.chunk_size
        }
        
        # Import Config from app module
        from app import Config
        fgb_config = Config(**fgb_config_dict)
        
        self.fgb_service = FlatGeobufService(fgb_config)
        self.frontend_service = FrontendService(config)
        self.static_middleware = StaticFileMiddleware(config.base_dir)


# Initialize application
config = TestAppConfig.from_defaults()
service = TestAppService(config)

app = FastAPI(title="FlatGeobuf Test App - OpenLayers + API")


# Custom middleware to handle JavaScript modules without .js extension
@app.middleware("http")
async def add_js_extension(request: Request, call_next):
    """
    Middleware that handles missing .js extensions.
    
    Delegates to StaticFileMiddleware to keep logic separated.
    """
    if service.static_middleware.should_handle(request):
        response = service.static_middleware.try_add_js_extension(request)
        if response:
            return response
    
    return await call_next(request)


# Mount static directories
app.mount("/static", StaticFiles(directory=config.static_dir), name="static")
app.mount("/node_modules", StaticFiles(directory=config.node_modules_dir), name="node_modules")


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve index.html as root page"""
    return service.frontend_service.get_index_html()


@app.get("/api/info")
def api_info():
    """API information endpoint"""
    return {
        "name": "FlatGeobuf Test App",
        "version": "2.0.0",
        "architecture": "class-based",
        "components": {
            "frontend": "OpenLayers",
            "api": "FlatGeobuf Range Request API"
        },
        "endpoints": {
            "GET /": "Frontend (OpenLayers map)",
            "GET /api/info": "API information",
            "GET /api/config": "Frontend configuration (includes tokens)",
            "HEAD /fgb/{layer_name}.fgb": "Get file metadata",
            "GET /fgb/{layer_name}.fgb": "Get file data (requires Range header)"
        },
        "config": {
            "max_range_bytes": config.max_range_bytes,
            "chunk_size": config.chunk_size,
            "static_dir": str(config.static_dir),
            "data_dir": str(config.data_dir)
        }
    }


@app.get("/api/config")
def get_config():
    """
    Frontend configuration endpoint.
    
    Returns configuration needed by frontend, including API tokens.
    Tokens are stored in environment variables and never committed to git.
    """
    return {
        "dataforsyningen_token": config.dataforsyningen_token
    }


# ========== FlatGeobuf API Endpoints ==========
# These endpoints delegate to FlatGeobufService from core app

@app.head("/fgb/{layer_name}.fgb")
def head_flatgeobuf(layer_name: str):
    """
    HEAD request - returns file metadata.
    
    Delegates to FlatGeobufService from core API.
    """
    return service.fgb_service.handle_head_request(layer_name)


@app.get("/fgb/{layer_name}.fgb")
def get_flatgeobuf(layer_name: str, request: Request):
    """
    GET request with Range header - returns file data.
    
    Delegates to FlatGeobufService from core API.
    """
    return service.fgb_service.handle_get_request(layer_name, request)
