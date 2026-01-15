from fastapi import FastAPI, HTTPException, Request
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from pprint import pformat

app = FastAPI()

# Base directory where text files live. This keeps file reads constrained to this folder.
BASE_DIR = Path("/tmp") / "files"
ATTACH_DIR = BASE_DIR / "attachments"

def extract_text_from_file(path: Path) -> str:
    """
    Best-effort text extraction for common types.
    - .docx uses python-docx (you have it)
    - .pdf uses pypdf (install if you want PDF text)
    """
    suffix = path.suffix.lower()

    if suffix in {".txt", ".csv", ".log"}:
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".docx":
        import docx
        d = docx.Document(str(path))
        return "\n".join(p.text for p in d.paragraphs).strip()

    if suffix == ".pdf":
        # pip install pypdf   (only if you want PDF extraction)
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()

    # images/other binaries: skip
    return ""


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


def clean_text(text: str) -> str:
    """Clean input text before persisting.

    - Normalize CRLF to LF
    - Strip leading/trailing whitespace
    - Collapse multiple consecutive blank lines to a single blank line
    - Remove C0 control characters except for tab and newline
    """
    if text is None:
        return ""

    # Normalize line endings
    s = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove undesired control characters (keep tab and newline)
    cleaned_chars = []
    for ch in s:
        # allow printable characters, newline and tab
        if ch == "\n" or ch == "\t" or (" " <= ch <= "~") or (ord(ch) > 0x7f):
            cleaned_chars.append(ch)
        # else drop the character
    s = "".join(cleaned_chars)

    # Strip leading/trailing whitespace on each line, then collapse multiple blank lines
    lines = [ln.rstrip() for ln in s.split("\n")]  # remove trailing spaces

    out_lines = []
    blank_seq = 0
    for ln in lines:
        if ln.strip() == "":
            blank_seq += 1
        else:
            blank_seq = 0

        if blank_seq > 1:
            # skip extra blank lines
            continue
        out_lines.append(ln)

    result = "\n".join(out_lines).strip() + ("\n" if out_lines and out_lines[-1] == "" else "")
    return result


class ProxiedMailWebhook(BaseModel):
    id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class LegacyWebhook(BaseModel):
    context: str

def sanitize_filename(name: str) -> str:
    # minimal sanitize for Vercel/tmp
    name = (name or "file.bin").replace("/", "_").replace("\\", "_").strip()
    return name[:200] if name else "file.bin"


async def download_attachment(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


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
    if subject:
        parts.append(f"Subject: {subject}".rstrip())
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

    # ---- DEBUG: PRINT STRUCTURE ----
    print("=== RAW WEBHOOK PAYLOAD ===")
    print(pformat(data, width=120))
    print("=== END PAYLOAD ===")

    # 1) Legacy path
    if isinstance(data, dict) and "context" in data:
        legacy = LegacyWebhook.model_validate(data)
        cleaned = clean_text(legacy.context)

    # 2) ProxiedMail path
    elif isinstance(data, dict) and "payload" in data and isinstance(data["payload"], dict):
        pm = ProxiedMailWebhook.model_validate(data)
        context = extract_context_from_proxiedmail(pm)
        cleaned = clean_text(context)

        attachments = data.get("attachments", []) if isinstance(data, dict) else []
        if not isinstance(attachments, list):
            attachments = []
        ATTACH_DIR.mkdir(parents=True, exist_ok=True)
        
        extracted_texts = []
        for a in attachments:
            if not isinstance(a, dict):
                continue
            filename = sanitize_filename(a.get("filename"))
            url = a.get("url")
            if not url:
                continue

            content = await download_attachment(url)

            file_path = ATTACH_DIR / filename
            file_path.write_bytes(content)

            # extract text inside docx/pdf/txt
            try:
                t = extract_text_from_file(file_path)
                if t.strip():
                    extracted_texts.append(t)
            except Exception as e:
                print(f"Failed to extract text from {filename}: {e}")
        
        cleaned += "\n" + "\n".join(extracted_texts)
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

    # If the file doesn't exist yet, return empty context (not an error).
    if not path.exists() or not path.is_file():
        return {"context": ""}

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    return {"context": text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
