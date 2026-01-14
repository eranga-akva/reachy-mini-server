from fastapi import FastAPI, HTTPException
from pathlib import Path

app = FastAPI()

# Base directory where text files live. This keeps file reads constrained to this folder.
BASE_DIR = Path(__file__).resolve().parent.parent / "files"


def _safe_resolve(base: Path, filename: str) -> Path:
    """Resolve filename against base and prevent path traversal.

    Raises ValueError if the resolved path is outside the base directory.
    """
    candidate = (base / filename).resolve()
    try:
        base_resolved = base.resolve()
    except Exception:
        base_resolved = base
    if base_resolved == candidate or base_resolved in candidate.parents:
        return candidate
    raise ValueError("invalid filename")


@app.get("/latest-context")
async def get_latest_context():
    """Return the contents of a text file (from the `files` directory) as JSON.

    Response format:
    {
      "context": "... file contents ..."
    }
    """
    try:
        path = _safe_resolve(BASE_DIR, filename="context.txt")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    return {"context": text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
