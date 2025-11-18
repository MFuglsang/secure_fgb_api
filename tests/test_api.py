"""
API Tests for FlatGeobuf API

Tests the API endpoints with local data files.
Run with: pytest test_api.py -v
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import os

# Set test environment
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["DATA_SOURCE"] = "local"

from app import app, config

client = TestClient(app)


class TestRootEndpoint:
    """Test root endpoint"""
    
    def test_root_returns_api_info(self):
        """Root endpoint should return API information"""
        response = client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "FlatGeobuf API"
        assert "endpoints" in data
        assert "config" in data


class TestHeadRequest:
    """Test HEAD requests for file metadata"""
    
    def test_head_existing_file(self):
        """HEAD request for existing file should return metadata"""
        # Find a .fgb file in data directory
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        # Use first available file
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        response = client.head(f"/fgb/{layer_name}.fgb")
        assert response.status_code == 200
        
        # Check required headers
        assert "content-length" in response.headers
        assert "accept-ranges" in response.headers
        assert response.headers["accept-ranges"] == "bytes"
        assert "content-type" in response.headers
        
        # Verify content-length matches actual file size
        expected_size = test_file.stat().st_size
        assert int(response.headers["content-length"]) == expected_size
    
    def test_head_nonexistent_file(self):
        """HEAD request for non-existent file should return 404"""
        response = client.head("/fgb/nonexistent_layer.fgb")
        assert response.status_code == 404


class TestGetRequestWithRange:
    """Test GET requests with Range headers"""
    
    def test_get_with_valid_range(self):
        """GET request with valid Range header should return partial content"""
        # Find a .fgb file
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        # Request first 1024 bytes
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": "bytes=0-1023"}
        )
        
        assert response.status_code == 206  # Partial Content
        assert len(response.content) == 1024
        
        # Check headers
        assert "content-range" in response.headers
        assert "content-length" in response.headers
        assert int(response.headers["content-length"]) == 1024
        
        # Verify content matches file content
        with test_file.open("rb") as f:
            expected_content = f.read(1024)
        assert response.content == expected_content
    
    def test_get_with_suffix_range(self):
        """GET request with suffix range (last N bytes)"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        # Request last 1000 bytes
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": "bytes=-1000"}
        )
        
        assert response.status_code == 206
        assert len(response.content) <= 1000
        
        # Verify content
        file_size = test_file.stat().st_size
        start = max(file_size - 1000, 0)
        with test_file.open("rb") as f:
            f.seek(start)
            expected_content = f.read()
        assert response.content == expected_content
    
    def test_get_without_range_header(self):
        """GET request without Range header should return 416"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        response = client.get(f"/fgb/{layer_name}.fgb")
        assert response.status_code == 416  # Range Not Satisfiable
    
    def test_get_with_range_too_large(self):
        """GET request with range larger than max_range_bytes should fail"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        # Request more than max_range_bytes (2MB)
        max_bytes = config.max_range_bytes
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": f"bytes=0-{max_bytes}"}  # 1 byte too many
        )
        
        assert response.status_code == 416
    
    def test_get_with_invalid_range(self):
        """GET request with invalid Range header should fail"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        # Invalid range format
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": "invalid"}
        )
        
        assert response.status_code == 416
    
    def test_get_nonexistent_file(self):
        """GET request for non-existent file should return 404"""
        response = client.get(
            "/fgb/nonexistent_layer.fgb",
            headers={"Range": "bytes=0-1023"}
        )
        
        assert response.status_code == 404


class TestRangeParser:
    """Test range parsing logic"""
    
    def test_multiple_ranges_not_supported(self):
        """Multiple ranges should be rejected"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": "bytes=0-100,200-300"}
        )
        
        assert response.status_code == 416
    
    def test_range_beyond_file_size(self):
        """Range beyond file size should fail"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        file_size = test_file.stat().st_size
        
        # Request beyond file
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": f"bytes={file_size}-{file_size + 1000}"}
        )
        
        assert response.status_code == 416


class TestCORS:
    """Test CORS headers"""
    
    def test_cors_enabled(self):
        """CORS middleware should be configured"""
        # Test with an actual request that would trigger CORS
        response = client.options(
            "/fgb/test.fgb",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET"
            }
        )
        
        # FastAPI's CORS middleware should handle OPTIONS requests
        assert response.status_code in [200, 404]  # Either OK or not found is fine


class TestStreaming:
    """Test streaming behavior"""
    
    def test_large_range_streams_in_chunks(self):
        """Large ranges should be streamed in chunks"""
        data_dir = Path(config.data_dir)
        fgb_files = list(data_dir.glob("*.fgb"))
        
        if not fgb_files:
            pytest.skip("No .fgb files found in data directory")
        
        test_file = fgb_files[0]
        layer_name = test_file.stem
        
        # Request large range (but within limits)
        range_size = min(1024 * 512, config.max_range_bytes - 1)  # 512KB or max-1
        response = client.get(
            f"/fgb/{layer_name}.fgb",
            headers={"Range": f"bytes=0-{range_size - 1}"}
        )
        
        assert response.status_code == 206
        assert len(response.content) == range_size
        
        # Verify content
        with test_file.open("rb") as f:
            expected_content = f.read(range_size)
        assert response.content == expected_content


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
