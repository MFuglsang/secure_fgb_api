"""
FlatGeobuf API - Core Application (Class-based Structure)

This is the core API that serves FlatGeobuf files with HTTP Range request support.

Refactored with classes for better structure and reusability.

Start with: uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from typing import Optional, Generator, Protocol
from dataclasses import dataclass
import logging
from datetime import datetime
import os

# Configure logging based on environment variable
# Set LOG_LEVEL environment variable to: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info(f"Logging configured at level: {LOG_LEVEL}")

# S3 import - optional dependency
try:
    import boto3
    from botocore.exceptions import ClientError
    S3_AVAILABLE = True
except ImportError:
    S3_AVAILABLE = False
    logger.warning("boto3 not installed - S3 support disabled")


@dataclass
class Config:
    """Configuration for the API"""
    base_dir: Path
    data_dir: Path
    max_range_bytes: int = 2 * 1024 * 1024  # 2 MB
    chunk_size: int = 1024 * 64  # 64 KB
    log_level: str = "INFO"
    # S3 configuration
    use_s3: bool = False
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "eu-west-1"
    s3_bucket_name: Optional[str] = None
    
    @classmethod
    def from_defaults(cls) -> "Config":
        """Create config with default values"""
        base_dir = Path(__file__).resolve().parent
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        
        # Check if S3 should be used
        data_source = os.getenv("DATA_SOURCE", "local").lower()
        use_s3 = data_source == "s3"
        
        return cls(
            base_dir=base_dir,
            data_dir=base_dir / "data",
            log_level=log_level,
            use_s3=use_s3,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_region=os.getenv("AWS_REGION", "eu-west-1"),
            s3_bucket_name=os.getenv("S3_BUCKET_NAME")
        )


class RangeParser:
    """Handles parsing of HTTP Range headers"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.RangeParser")
    
    def parse(self, range_header: str, file_size: int, max_bytes: int) -> tuple[int, int]:
        """
        Parse an HTTP Range header and return (start, end) byte positions.
        
        Args:
            range_header: HTTP Range header (e.g. "bytes=0-1023")
            file_size: Total file size in bytes
            max_bytes: Maximum allowed range size
            
        Returns:
            Tuple with (start_byte, end_byte)
            
        Raises:
            HTTPException: If range is invalid or too large
            
        Examples:
            - "bytes=0-1023" -> get the first 1024 bytes
            - "bytes=1024-2047" -> get bytes from 1024 to 2047
            - "bytes=-1000" -> get the last 1000 bytes
        """
        self.logger.debug(f"Parsing range header: {range_header} (file_size: {file_size})")
        
        if not range_header.startswith("bytes="):
            raise HTTPException(status_code=416, detail="Only 'bytes' ranges supported")

        range_spec = range_header[len("bytes="):].strip()
        
        if "," in range_spec:
            raise HTTPException(status_code=416, detail="Multiple ranges not supported")

        # Handle suffix range: "bytes=-1000" means the last 1000 bytes
        if range_spec.startswith("-"):
            suffix_length = int(range_spec[1:])
            if suffix_length <= 0:
                raise HTTPException(status_code=416, detail="Invalid suffix length")
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            # Normal range: "bytes=0-1023" or "bytes=0-" (rest of file)
            start, end = self._parse_normal_range(range_spec, file_size)

        # Validate range
        self._validate_range(start, end, file_size, max_bytes)
        
        range_size = end - start + 1
        self.logger.info(f"Parsed range: {start}-{end} ({range_size} bytes, {range_size/1024:.2f} KB)")
        
        return start, end
    
    def _parse_normal_range(self, range_spec: str, file_size: int) -> tuple[int, int]:
        """Parse normal range format: start-end"""
        parts = range_spec.split("-")
        if len(parts) != 2:
            raise HTTPException(status_code=416, detail="Invalid range format")

        start_str, end_str = parts
        
        try:
            start = int(start_str)
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid range start")

        if end_str == "":
            # If end is empty, get rest of file
            end = file_size - 1
        else:
            try:
                end = int(end_str)
            except ValueError:
                raise HTTPException(status_code=416, detail="Invalid range end")
        
        return start, end
    
    def _validate_range(self, start: int, end: int, file_size: int, max_bytes: int):
        """Validate that range is valid"""
        if start < 0 or end >= file_size or start > end:
            self.logger.warning(f"Invalid range: {start}-{end} for file size {file_size}")
            raise HTTPException(status_code=416, detail="Range not satisfiable")

        # Check that requested range is not too large
        length = end - start + 1
        if length > max_bytes:
            self.logger.warning(f"Range too large: {length} bytes (max: {max_bytes})")
            raise HTTPException(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                detail=f"Requested range too large (>{max_bytes} bytes)",
            )


class DataSource(Protocol):
    """Protocol for data sources (local or S3)"""
    
    def get_file_size(self, layer_name: str) -> int:
        """Get file size for a layer"""
        ...
    
    def stream_range(self, layer_name: str, start: int, end: int, chunk_size: int) -> Generator[bytes, None, None]:
        """Stream a range from the file"""
        ...


class LocalDataSource:
    """Data source for local disk"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.logger = logging.getLogger(f"{__name__}.LocalDataSource")
    
    def get_file_path(self, layer_name: str) -> Path:
        """Get file path for a layer"""
        return self.data_dir / f"{layer_name}.fgb"
    
    def get_file_size(self, layer_name: str) -> int:
        """Get file size from local disk"""
        file_path = self.get_file_path(layer_name)
        if not file_path.exists():
            self.logger.warning(f"Layer not found: {file_path}")
            raise HTTPException(status_code=404, detail="Layer not found")
        return file_path.stat().st_size
    
    def stream_range(
        self, 
        layer_name: str, 
        start: int, 
        end: int, 
        chunk_size: int
    ) -> Generator[bytes, None, None]:
        """Stream a range from local file"""
        file_path = self.get_file_path(layer_name)
        total_bytes = end - start + 1
        
        self.logger.info(f"Streaming {total_bytes} bytes from {file_path.name} (local) ({start}-{end})")
        
        bytes_sent = 0
        with file_path.open("rb") as f:
            f.seek(start)
            remaining = total_bytes
            
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                bytes_sent += len(chunk)
                yield chunk
        
        self.logger.debug(f"Completed streaming {bytes_sent} bytes from local file")


class S3DataSource:
    """Data source for AWS S3"""
    
    def __init__(self, config: Config):
        if not S3_AVAILABLE:
            raise RuntimeError("boto3 not installed. Install with: pip install boto3")
        
        if not all([config.aws_access_key_id, config.aws_secret_access_key, config.s3_bucket_name]):
            raise ValueError(
                "S3 credentials missing! Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY "
                "and S3_BUCKET_NAME in .env file or environment variables"
            )
        
        self.bucket_name = config.s3_bucket_name
        self.logger = logging.getLogger(f"{__name__}.S3DataSource")
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            region_name=config.aws_region
        )
        
        self.logger.info(f"S3 data source initialized - bucket: {self.bucket_name}")
    
    def get_s3_key(self, layer_name: str) -> str:
        """Get S3 key for a layer"""
        return f"{layer_name}.fgb"
    
    def get_file_size(self, layer_name: str) -> int:
        """Get file size from S3"""
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=self.get_s3_key(layer_name)
            )
            size = response['ContentLength']
            self.logger.debug(f"S3 file size for {layer_name}: {size} bytes")
            return size
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                self.logger.warning(f"Layer not found in S3: {layer_name}")
                raise HTTPException(status_code=404, detail="Layer not found in S3")
            self.logger.error(f"S3 error getting file size: {e}")
            raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")
    
    def stream_range(
        self, 
        layer_name: str, 
        start: int, 
        end: int, 
        chunk_size: int
    ) -> Generator[bytes, None, None]:
        """
        Stream a range from S3.
        
        Uses S3's get_object with Range parameter to fetch only the part we need.
        Then streams it in smaller chunks to the client.
        """
        total_bytes = end - start + 1
        self.logger.info(f"Streaming {total_bytes} bytes from {layer_name} (S3) ({start}-{end})")
        
        try:
            # S3 Range format: "bytes=start-end"
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=self.get_s3_key(layer_name),
                Range=f"bytes={start}-{end}"
            )
            
            # Stream body in chunks
            bytes_sent = 0
            body = response['Body']
            remaining = total_bytes
            
            while remaining > 0:
                chunk = body.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                bytes_sent += len(chunk)
                yield chunk
            
            self.logger.debug(f"Completed streaming {bytes_sent} bytes from S3")
            
        except ClientError as e:
            self.logger.error(f"S3 error streaming range: {e}")
            raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")


class FlatGeobufService:
    """Service to handle FlatGeobuf file operations"""
    
    def __init__(self, config: Config):
        self.config = config
        self.range_parser = RangeParser()
        self.logger = logging.getLogger(f"{__name__}.FlatGeobufService")
        
        # Choose data source based on config
        if config.use_s3:
            self.data_source = S3DataSource(config)
            self.logger.info("Using S3 data source")
        else:
            self.data_source = LocalDataSource(config.data_dir)
            self.logger.info("Using local data source")
    
    def get_metadata_headers(self, file_size: int) -> dict[str, str]:
        """Generate headers for metadata response"""
        return {
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Type": "application/octet-stream",
        }
    
    def get_range_headers(self, start: int, end: int, file_size: int) -> dict[str, str]:
        """Generate headers for range response"""
        content_length = end - start + 1
        return {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": "application/octet-stream",
        }
    
    def handle_head_request(self, layer_name: str) -> Response:
        """
        Handle HEAD request for a layer.
        
        Returns file metadata without sending content.
        FlatGeobuf client uses this to find:
        - File size (Content-Length)
        - Whether server supports range requests (Accept-Ranges: bytes)
        """
        self.logger.info(f"HEAD request for layer: {layer_name}")
        
        # Use data source to get file size
        file_size = self.data_source.get_file_size(layer_name)
        headers = self.get_metadata_headers(file_size)
        
        self.logger.info(f"HEAD response: {layer_name} - {file_size} bytes ({file_size/1024:.2f} KB)")
        
        return Response(status_code=200, headers=headers)
    
    def handle_get_request(self, layer_name: str, request: Request) -> StreamingResponse:
        """
        Handle GET request with Range header.
        
        FlatGeobuf client sends multiple small range requests to:
        1. Read header and spatial index (the first bytes)
        2. Fetch only features in the visible area
        
        This makes it very efficient - a 150KB file can be used
        without downloading the whole thing.
        """
        client_ip = request.client.host if request.client else "unknown"
        self.logger.info(f"GET request for layer: {layer_name} from {client_ip}")
        
        # Use data source to get file size
        file_size = self.data_source.get_file_size(layer_name)
        range_header = request.headers.get("range") or request.headers.get("Range")
        
        # We require Range header for .fgb files (security)
        if not range_header:
            self.logger.warning(f"Missing Range header for {layer_name} from {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                detail="Range header required",
            )
        
        # Parse range header
        start, end = self.range_parser.parse(
            range_header, 
            file_size, 
            self.config.max_range_bytes
        )
        
        range_size = end - start + 1
        percentage = (range_size / file_size * 100) if file_size > 0 else 0
        self.logger.info(
            f"Serving {layer_name}: bytes {start}-{end} "
            f"({range_size} bytes, {percentage:.1f}% of file) to {client_ip}"
        )
        
        # Generate response with stream from data source
        headers = self.get_range_headers(start, end, file_size)
        file_iterator = self.data_source.stream_range(
            layer_name, 
            start, 
            end, 
            self.config.chunk_size
        )
        
        return StreamingResponse(
            file_iterator,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=headers,
        )


# Initialize application
config = Config.from_defaults()
service = FlatGeobufService(config)

app = FastAPI(title="FlatGeobuf API")

# CORS support - allows requests from other domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: specify specific domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """API info"""
    return {
        "name": "FlatGeobuf API",
        "version": "2.0.0",
        "architecture": "class-based",
        "endpoints": {
            "HEAD /fgb/{layer_name}.fgb": "Get file metadata",
            "GET /fgb/{layer_name}.fgb": "Get file data (requires Range header)"
        },
        "config": {
            "max_range_bytes": config.max_range_bytes,
            "chunk_size": config.chunk_size,
            "log_level": config.log_level
        }
    }


@app.head("/fgb/{layer_name}.fgb")
def head_flatgeobuf(layer_name: str):
    """HEAD request - returns file metadata"""
    return service.handle_head_request(layer_name)


@app.get("/fgb/{layer_name}.fgb")
def get_flatgeobuf(layer_name: str, request: Request):
    """GET request with Range header - returns file data"""
    return service.handle_get_request(layer_name, request)
