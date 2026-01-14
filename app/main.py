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

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI()

# --- your existing clean_text(...) stays as-is ---


class ProxiedMailWebhook(BaseModel):
    id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class LegacyWebhook(BaseModel):
    context: str


def extract_context_from_proxiedmail(pm: ProxiedMailWebhook) -> str:
    """
    ProxiedMail puts message content in pm.payload["body-plain"] (preferred) and/or pm.payload["body-html"].
    It also includes fields like "from", "to", "subject" in the same payload object. :contentReference[oaicite:1]{index=1}
    """
    p = pm.payload or {}

    body_plain = p.get("body-plain") or p.get("body_plain") or ""
    body_html = p.get("body-html") or p.get("body_html") or ""

    # Optional: prepend a tiny header for your stored context
    subject = p.get("Subject") or p.get("subject") or ""
    from_ = p.get("from") or p.get("From") or ""
    to_ = p.get("to") or p.get("To") or ""

    # Prefer plain text; fall back to HTML if needed
    body = body_plain if str(body_plain).strip() else body_html

    # If you don't want metadata, return just `body`
    parts = []
    if subject or from_ or to_:
        parts.append(f"Subject: {subject}".rstrip())
        parts.append(f"From: {from_}".rstrip())
        parts.append(f"To: {to_}".rstrip())
        parts.append("")  # blank line before body

    parts.append(str(body))
    return "\n".join(parts)


@app.post("/webhook")
async def webhook(request: Request):
    """
    Accept either:
      - legacy: {"context": "..."}
      - ProxiedMail: {"id": "...", "payload": {..., "body-plain": "...", ...}}
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 1) Legacy path
    if isinstance(data, dict) and "context" in data:
        legacy = LegacyWebhook.model_validate(data)
        cleaned = clean_text(legacy.context)

    # 2) ProxiedMail path
    elif isinstance(data, dict) and "payload" in data and isinstance(data["payload"], dict):
        pm = ProxiedMailWebhook.model_validate(data)
        context = extract_context_from_proxiedmail(pm)
        cleaned = clean_text(context)

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported webhook payload. Expected either {context: ...} or {payload: {...}}",
        )

    # Ensure base dir exists
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        path = _safe_resolve(BASE_DIR, filename="context.txt")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        path.write_text(cleaned, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {e}")

    return {"success": True}


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
