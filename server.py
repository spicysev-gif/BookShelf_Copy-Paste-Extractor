"""FastAPI backend for Bookshelf Extractor.

Wraps the library functions in bookshelf_extract.py. Stateless: no auth,
no storage, no logging of HTML payloads. The user's browser does the
authentication; this service just converts HTML to PDF/TXT.

Run locally:
    .venv/bin/uvicorn server:app --reload --port 8000
"""
import io
import os
import zipfile
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bookshelf_extract import (
    html_to_pdf_bytes,
    html_to_txt,
    split_sections,
)

MAX_HTML_BYTES = 10 * 1024 * 1024  # 10 MB

app = FastAPI(title="Bookshelf Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    html: str = Field(..., description="Raw HTML copied from Bookshelf")
    mode: Literal["single", "split"] = "single"
    format: Literal["pdf", "txt"] = "pdf"
    filename: str | None = Field(None, description="Optional download filename stem")


def _safe_name(stem: str | None, fallback: str) -> str:
    if not stem:
        return fallback
    cleaned = "".join(c for c in stem if c.isalnum() or c in "._- ")
    return cleaned.strip() or fallback


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/extract")
def extract(req: ExtractRequest):
    if len(req.html.encode("utf-8")) > MAX_HTML_BYTES:
        raise HTTPException(413, "HTML too large (max 10 MB)")

    if req.mode == "single":
        stem = _safe_name(req.filename, "extract")
        if req.format == "pdf":
            return Response(
                html_to_pdf_bytes(req.html),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'},
            )
        return Response(
            html_to_txt(req.html),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'},
        )

    sections = split_sections(req.html)
    if not sections:
        raise HTTPException(400, "No <section> tags found; try mode=single")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, section_html in sections:
            if req.format == "pdf":
                zf.writestr(f"{name}.pdf", html_to_pdf_bytes(section_html))
            else:
                zf.writestr(f"{name}.txt", html_to_txt(section_html))

    stem = _safe_name(req.filename, "extract")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}.zip"'},
    )


web_dir = os.path.join(os.path.dirname(__file__), "web")
if os.path.isdir(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
