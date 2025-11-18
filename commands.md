## Start API 
uvicorn app:app --reload --port 8000

## Start API with test client
uvicorn test_app.app:app --reload --port 8001

## Run tests
pytest tests/ -v

## Run specific test file
pytest tests/test_api.py -v

## Run tests with coverage
pytest tests/ -v --cov=app
