
# Image to PDF (Flask)

A small **browser-based** tool to combine up to **20** images into a **single PDF**. It shows **upload sizes**, **actual output PDF sizes** for “no compression” and several **compression presets**, then lets you **download** the variant you want with a **custom filename** (your browser picks the save folder).

## High-level summary

This app is a **Flask** web UI on top of **Pillow** and **img2pdf**. You upload images in order, preview how large each PDF variant would be, then download one PDF. **No-compression** mode tries to **embed original JPEG/PNG bytes** (best fidelity). **Compressed** modes re-encode via Pillow’s PDF writer using mapped quality levels for **10%–50%** “compression strength” presets.

## Features

- **Web UI** — upload multiple images; page order matches selection order.
- **Up to 20 files** per run.
- **Formats** — `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.heic` (HEIC needs `pillow-heif`).
- **Per-file + total upload size** shown in the browser before submit.
- **Custom download filename** — only the **file name** is used; the **save location** is chosen by the browser’s download dialog (standard web security).
- **Size preview** — after upload, the server builds PDFs and shows **real byte sizes** for:
  - **No compression (0%)** — uses `img2pdf` to embed JPEG/PNG without recompression when safe.
  - **Compressed 10%, 20%, 30%, 40%, 50%** — Pillow PDF export with mapped JPEG quality (see table below).
- **HEIC / non-JPEG/PNG** — converted to **PNG (lossless)** for the no-compression path (HEIC cannot be embedded raw in PDF via this stack).
- **iPhone / multi-frame JPEG (MPO-style)** — detected and handled to avoid PDF frame errors (falls back to a safe single-frame path).
- **Short-lived preview cache** — generated PDFs are kept **in memory** for about **10 minutes** so you can download from the preview page; then they expire.

## Compression presets (implementation detail)

The UI labels **10%–50%** compression; internally these map to Pillow `quality` values:

| Preset | Pillow quality |
|--------|----------------|
| 10%    | 90             |
| 20%    | 85             |
| 30%    | 80             |
| 40%    | 70             |
| 50%    | 60             |

Higher quality → larger files. The preset name is a **relative strength**, not a guaranteed percentage of file size reduction.

## Project layout

```text
Image to PDF/
├── image2pdf.py          # Flask app (routes: /, /create, /download/...)
├── requirements.txt
├── README.md
└── templates/
    ├── index.html        # Upload + filename + file size summary
    └── preview.html      # Size table + download links
```

## Requirements

- Python **3.10+** recommended
- Dependencies (see `requirements.txt`):
  - `flask`
  - `pillow`
  - `pillow-heif` (for `.heic`)
  - `img2pdf` (for no-compression PDF assembly)

## Install

```bash
cd "path/to/Image to PDF"
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python image2pdf.py
```

Open **http://127.0.0.1:5000** in your browser.

## Usage

1. Select up to 20 images (order = PDF page order).
2. Optionally set **Output filename** (e.g. `report.pdf`).
3. Click **Preview sizes**.
4. On the preview page, pick **Download** next to the variant you want.
5. Use the browser dialog to choose where to save the file.

## Limitations & notes

- **Paths**: A website cannot silently write to arbitrary folders on your PC; **folder choice is always via the download dialog** unless you add a separate desktop-only feature (e.g. native file dialog or server-side save path — not in this version).
- **Preview expiry**: If downloads fail with “expired”, run preview again (cache TTL ~10 minutes).
- **Production**: `debug=True` is for local use only; use a proper WSGI server and turn off debug for deployment.

## License

TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
