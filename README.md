FastAPI file reader

This small app exposes a GET endpoint to read text files from the `files` directory and return their contents as JSON.

Endpoint:
- GET /files/{filename}

Example:

curl -s localhost:8000/files/example.txt

Run locally:

1. Create a virtualenv and install deps (using `uv`):
   uv venv --python 3.12.1 .venv
   source .venv/bin/activate
   pip install -r requirements.txt

2. Start server:
   uvicorn app.main:app --reload

3. Visit: http://127.0.0.1:8000/files/example.txt
