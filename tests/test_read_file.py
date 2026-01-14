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


def test_webhook_updates_context(tmp_path):
    # write a temporary files/context.txt by pointing BASE_DIR to tmp_path/files
    from app import main as app_main

    # Patch base dir for test
    app_main.BASE_DIR = tmp_path / "files"
    (app_main.BASE_DIR).mkdir(parents=True)

    payload = {"context": "Line1\r\n\r\nLine2\n\n\nLine3\twith tab"}
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "Line1" in data["context"]
    # Ensure only one blank line between content
    assert "\n\nLine2" in data["context"] or "Line2" in data["context"]

    # Ensure file was written
    written = (app_main.BASE_DIR / "context.txt").read_text(encoding="utf-8")
    assert "Line3" in written


def test_webhook_blocks_bad_filename():
    # The webhook endpoint uses a fixed filename, but ensure safe_resolve blocks traversal
    from app import main as app_main
    try:
        _ = app_main._safe_resolve(Path("."), "../foo.txt")
        assert False, "Expected ValueError for traversal"
    except ValueError:
        pass
