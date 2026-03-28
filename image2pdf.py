from __future__ import annotations

import io
import time
import uuid
from pathlib import Path

from flask import Flask, render_template, request, send_file
from PIL import Image

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".heic"}
MAX_FILES = 20


app = Flask(__name__)

# Enable HEIC/HEIF decoding via pillow-heif (if installed).
try:
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
except Exception:
    # App still works for non-HEIC formats even if HEIC support isn't available.
    pass


def _allowed_filename(filename: str) -> bool:
    p = Path(filename)
    return bool(p.suffix) and p.suffix.lower() in SUPPORTED_EXTS


def _pil_to_rgb(img: Image.Image) -> Image.Image:
    """
    Convert to a standalone single-frame RGB image suitable for PDF export.

    This intentionally returns a *new* image object (copy/convert) to avoid
    issues with container formats like MPO/Live-Photos where Pillow may behave
    like a frame sequence during PDF save.
    """
    # Always use first frame if the format is multi-frame (e.g. MPO).
    try:
        img.seek(0)
    except Exception:
        pass

    try:
        img.load()
    except Exception:
        pass

    if img.mode in {"RGBA", "LA"}:
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg.copy()

    # Always return a new object even if already RGB.
    return img.convert("RGB")


def _is_probably_multiframe(src: Image.Image) -> bool:
    if getattr(src, "format", None) == "MPO":
        return True
    n_frames = getattr(src, "n_frames", 1)
    return isinstance(n_frames, int) and n_frames > 1


def _fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    x = float(n)
    i = 0
    while x >= 1024 and i < len(units) - 1:
        x /= 1024
        i += 1
    if i == 0:
        return f"{int(x)} {units[i]}"
    return f"{x:.2f} {units[i]}"


def _normalize_download_name(name: str) -> str:
    name = (name or "").strip().strip('"')
    if not name:
        return "combined.pdf"
    p = Path(name)
    if p.suffix.lower() != ".pdf":
        name = str(p.with_suffix(".pdf"))
    # only the filename portion (browser chooses directory)
    return Path(name).name


def _build_pdf_no_compress(files) -> bytes:
    import img2pdf  # type: ignore

    inputs: list[bytes] = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        try:
            f.stream.seek(0)
        except Exception:
            pass

        if ext in {".jpg", ".jpeg", ".png"}:
            raw = f.read()
            try:
                f.stream.seek(0)
            except Exception:
                pass

            if ext in {".jpg", ".jpeg"}:
                try:
                    with Image.open(io.BytesIO(raw)) as probe:
                        if _is_probably_multiframe(probe):
                            raise ValueError("multiframe")
                except Exception:
                    with Image.open(f.stream) as src:
                        safe = _pil_to_rgb(src)
                        buf = io.BytesIO()
                        safe.save(buf, format="PNG")
                        inputs.append(buf.getvalue())
                    continue

            inputs.append(raw)
            continue

        with Image.open(f.stream) as src:
            safe = _pil_to_rgb(src)
            buf = io.BytesIO()
            safe.save(buf, format="PNG")
            inputs.append(buf.getvalue())

    return img2pdf.convert(inputs)


def _build_pdf_compress(files, quality: int) -> bytes:
    images: list[Image.Image] = []
    try:
        for f in files:
            try:
                f.stream.seek(0)
            except Exception:
                pass
            with Image.open(f.stream) as src:
                images.append(_pil_to_rgb(src))

        first, rest = images[0], images[1:]
        pdf_bytes = io.BytesIO()
        first.save(
            pdf_bytes,
            format="PDF",
            save_all=True,
            append_images=rest,
            quality=quality,
        )
        return pdf_bytes.getvalue()
    finally:
        for img in images:
            try:
                img.close()
            except Exception:
                pass


# Simple in-memory cache for preview downloads (local usage).
_CACHE: dict[str, dict] = {}
_CACHE_TTL_S = 10 * 60


def _cache_put(variants: dict[str, bytes]) -> str:
    token = uuid.uuid4().hex
    _CACHE[token] = {"created": time.time(), "variants": variants}
    return token


def _cache_get(token: str) -> dict | None:
    item = _CACHE.get(token)
    if not item:
        return None
    if time.time() - float(item.get("created", 0)) > _CACHE_TTL_S:
        _CACHE.pop(token, None)
        return None
    return item


@app.get("/")
def index():
    return render_template("index.html", max_files=MAX_FILES, supported=sorted(SUPPORTED_EXTS))


@app.post("/create")
def create_pdf():
    files = request.files.getlist("images")
    files = [f for f in files if f and f.filename]
    outname = _normalize_download_name(request.form.get("outname", "combined.pdf"))

    if not files:
        return render_template(
            "index.html",
            max_files=MAX_FILES,
            supported=sorted(SUPPORTED_EXTS),
            error="Please select at least 1 image.",
        ), 400

    if len(files) > MAX_FILES:
        return render_template(
            "index.html",
            max_files=MAX_FILES,
            supported=sorted(SUPPORTED_EXTS),
            error=f"Please upload at most {MAX_FILES} images.",
        ), 400

    for f in files:
        if not _allowed_filename(f.filename):
            return render_template(
                "index.html",
                max_files=MAX_FILES,
                supported=sorted(SUPPORTED_EXTS),
                error=f"Unsupported file type: {f.filename}",
            ), 400

    # Compute sizes for: no compression + % presets (actual bytes, not guesses).
    variants: dict[str, bytes] = {}
    try:
        variants["no_compress"] = _build_pdf_no_compress(files)
    except ModuleNotFoundError:
        return render_template(
            "index.html",
            max_files=MAX_FILES,
            supported=sorted(SUPPORTED_EXTS),
            error="Missing dependency: img2pdf. Run: pip install -r requirements.txt",
        ), 500

    # Map requested "compression %" -> Pillow quality.
    pct_to_quality = {10: 90, 20: 85, 30: 80, 40: 70, 50: 60}
    for pct, q in pct_to_quality.items():
        variants[f"c{pct}"] = _build_pdf_compress(files, q)

    token = _cache_put(variants)

    input_total = 0
    for f in files:
        try:
            f.stream.seek(0, 2)
            input_total += int(f.stream.tell())
            f.stream.seek(0)
        except Exception:
            pass

    variant_rows = [
        {"key": "no_compress", "label": "No compression (best quality)", "note": "0%", "size_h": _fmt_bytes(len(variants["no_compress"]))},
        {"key": "c10", "label": "Compressed", "note": "10%", "size_h": _fmt_bytes(len(variants["c10"]))},
        {"key": "c20", "label": "Compressed", "note": "20%", "size_h": _fmt_bytes(len(variants["c20"]))},
        {"key": "c30", "label": "Compressed", "note": "30%", "size_h": _fmt_bytes(len(variants["c30"]))},
        {"key": "c40", "label": "Compressed", "note": "40%", "size_h": _fmt_bytes(len(variants["c40"]))},
        {"key": "c50", "label": "Compressed", "note": "50%", "size_h": _fmt_bytes(len(variants["c50"]))},
    ]

    return render_template(
        "preview.html",
        token=token,
        variants=variant_rows,
        input_total_h=_fmt_bytes(input_total),
        outname=outname,
    )


@app.get("/download/<token>/<variant>")
def download(token: str, variant: str):
    item = _cache_get(token)
    if not item:
        return "Preview expired. Please go back and upload again.", 410
    data = item["variants"].get(variant)
    if not data:
        return "Invalid download option.", 404

    name = _normalize_download_name(request.args.get("name", "combined.pdf"))
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=name,
        max_age=0,
    )


if __name__ == "__main__":
    # Run: python image2pdf.py
    # Then open: http://127.0.0.1:5000
    app.run(debug=True)
