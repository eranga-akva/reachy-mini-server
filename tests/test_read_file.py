from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_read_existing_file():
    resp = client.get("/files/example.txt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "example.txt"
    assert "Hello from example file" in data["content"]


def test_file_not_found():
    resp = client.get("/files/missing.txt")
    assert resp.status_code == 404


def test_path_traversal_blocked():
    # Attempt to escape the files directory
    resp = client.get("/files/../requirements.txt")
    assert resp.status_code in (400, 404)
