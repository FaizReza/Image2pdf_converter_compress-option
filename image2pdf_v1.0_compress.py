from __future__ import annotations

import io
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


@app.get("/")
def index():
    return render_template("index.html", max_files=MAX_FILES, supported=sorted(SUPPORTED_EXTS))


@app.post("/create")
def create_pdf():
    files = request.files.getlist("images")
    files = [f for f in files if f and f.filename]
    compress = request.form.get("compress") == "on"
    try:
        quality = int(request.form.get("quality", "80"))
    except ValueError:
        quality = 80
    quality = max(30, min(95, quality))

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

    if not compress:
        try:
            import img2pdf  # type: ignore
        except ModuleNotFoundError:
            return render_template(
                "index.html",
                max_files=MAX_FILES,
                supported=sorted(SUPPORTED_EXTS),
                error="Missing dependency: img2pdf. Run: pip install -r requirements.txt",
            ), 500

        inputs: list[bytes] = []
        for f in files:
            ext = Path(f.filename).suffix.lower()
            try:
                f.stream.seek(0)
            except Exception:
                pass

            # Embed JPEG/PNG originals when safe (no recompression).
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
                        # Convert tricky multi-frame cases to PNG (lossless)
                        with Image.open(f.stream) as src:
                            safe = _pil_to_rgb(src)
                            buf = io.BytesIO()
                            safe.save(buf, format="PNG")
                            inputs.append(buf.getvalue())
                        continue

                inputs.append(raw)
                continue

            # HEIC/WEBP/TIFF/BMP -> convert to PNG (lossless) for embedding
            with Image.open(f.stream) as src:
                safe = _pil_to_rgb(src)
                buf = io.BytesIO()
                safe.save(buf, format="PNG")
                inputs.append(buf.getvalue())

        pdf_bytes = io.BytesIO(img2pdf.convert(inputs))
        pdf_bytes.seek(0)
    else:
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
            pdf_bytes.seek(0)
        finally:
            for img in images:
                try:
                    img.close()
                except Exception:
                    pass

    return send_file(
        pdf_bytes,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="combined.pdf" if not compress else f"combined_q{quality}.pdf",
        max_age=0,
    )


if __name__ == "__main__":
    # Run: python image2pdf.py
    # Then open: http://127.0.0.1:5000
    app.run(debug=True)
