# 📖 Bookshelf Text Extractor

Extract clean, readable **text** and **PDF** files from VitalSource Bookshelf HTML content — including tables, headers, and multi-section chapters.

Three ways to use it, all on the same conversion engine:

| | What it is | Best for |
|---|---|---|
| **Browser extension** | One-click extract from any open Bookshelf chapter | Day-to-day use |
| **Paste website** | Paste HTML, click Convert, download | Anyone who won't install the extension |
| **CLI** | `python bookshelf_extract.py file.html` | Bulk / scripted workflows |

## The Problem

Bookshelf's built-in export is limited. The HTML source contains mountains of nested tags, inline styles, SVG icons, plugin markup, and other noise that makes copy-paste useless. This tool strips all of that away and gives you clean, formatted output.

## How It Works

The core idea is dead simple:

1. Walk through the HTML character by character
2. When you see `<`, stop collecting text. When you see `>`, start collecting again.
3. On top of that, track *which* tags you're inside (`<table>`, `<tr>`, `<td>`, `<h4>`, `<strong>`, etc.) to format the output properly — tables become actual table rows, headers get bolded, junk tags (`<script>`, `<svg>`, `<iframe>`) get skipped entirely.

No BeautifulSoup. No lxml. Just a boolean and a state machine.

## Setup

```bash
git clone https://github.com/YOUR_USERNAME/bookshelf-extract.git
cd bookshelf-extract

python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Python 3.8+ required. `requirements.txt` covers everything (`reportlab`, `fastapi`, `uvicorn`). For CLI-only use you can install just `reportlab`.

## Quickstart: extension + website

The extension and paste page both call the same backend, so start that first:

```bash
.venv/bin/uvicorn server:app --port 8000
```

Then either:

**Option A — Browser extension (recommended).**
1. In Chrome, open [chrome://extensions](chrome://extensions) → toggle **Developer mode** (top right) → **Load unpacked** → select the `extension/` folder.
2. Pin "Bookshelf Extractor" via the puzzle icon.
3. Open a Bookshelf chapter (you log in to Bookshelf yourself in your normal browser — the extension never sees your password).
4. Click the extension icon → choose PDF or TXT → click **Extract this page**. The file downloads.

The popup's "Backend" field is saved per-browser. The repo ships with a deployed default in `extension/popup.js:1` — change it to `http://localhost:8000` for local dev, or to your own Fly.io URL after deploying (see [Deploying the backend](#deploying-the-backend)).

**Option B — Paste page (no install).**
Open <http://localhost:8000> → follow the in-page instructions to copy the section from Bookshelf's DevTools console → paste → Convert.

## Deploying the backend

The repo includes `Dockerfile` + `fly.toml` for [Fly.io](https://fly.io). The app is stateless, sleeps when idle (`auto_stop_machines = "stop"`), and a personal deploy typically costs $0–$1/mo within Fly's $5/mo trial credit.

```bash
brew install flyctl
fly auth signup            # or `fly auth login`

# Edit fly.toml: change `app = "..."` to a globally-unique name (lowercase + hyphens).
fly apps create $(grep '^app =' fly.toml | cut -d'"' -f2)
fly deploy

curl https://YOUR_APP.fly.dev/healthz   # → {"ok":true}
```

Then update `extension/popup.js:1`:

```js
const DEFAULT_BACKEND = "https://YOUR_APP.fly.dev";
```

Reload the extension on `chrome://extensions` and you're done. The same backend serves the paste page at `https://YOUR_APP.fly.dev/`.

Other hosts work too (Render, Railway, Cloud Run — anything that runs a `Dockerfile`). CORS is wide open in `server.py`; fine for personal use, tighten if you make it public.

## Sharing the extension with a non-technical user

After the backend is deployed and `extension/popup.js`'s `DEFAULT_BACKEND` points at it:

```bash
zip -r bookshelf-extractor-extension.zip extension -x "extension/.DS_Store"
```

Send them the zip + these instructions:

1. Unzip somewhere permanent (e.g. `~/Documents`). **Don't move or delete the folder afterward** — Chrome reads from it on every browser start.
2. Open `chrome://extensions` (works in Edge/Brave/Arc/Vivaldi too — not Firefox or Safari).
3. Toggle **Developer mode** (top-right).
4. Click **Load unpacked** → pick the unzipped folder.
5. Pin "Bookshelf Extractor" via the puzzle icon.

They open any Bookshelf chapter, click the extension icon, click Extract. Done.

- **Updates to the extension** = re-send the zip; they click the refresh icon on the extension card.
- **Updates to the backend** (`fly deploy`) need no action on their end.
- The yellow "developer mode extensions" banner Chrome shows on each startup is harmless — Google nudging users away from sideloaded extensions. Tell them to dismiss it.

## CLI usage

### Single file → single output

```bash
# Produces chapter16.txt + chapter16.pdf
python bookshelf_extract.py chapter16.txt

# PDF only
python bookshelf_extract.py chapter16.txt --pdf

# TXT only, custom output name
python bookshelf_extract.py chapter16.txt --txt -o my_notes
```

### Multi-section file → one output per section

If your file contains multiple `<section>` blocks (e.g., you copied several sections from the same chapter or multiple chapters):

```bash
# Auto-splits and names each section
python bookshelf_extract.py combined.txt --split

# PDF only, into a specific directory
python bookshelf_extract.py combined.txt --split --pdf -o output/
```

This produces files like:
```
output/
├── Musculoskeletal_Health_Assessment.pdf
├── Musculoskeletal_Clinical_Judgments.pdf
├── Neurologic_Health_Assessment.pdf
├── Neurologic_Clinical_Judgments.pdf
└── ...
```

The script auto-detects the body system (musculoskeletal, neurologic, etc.) and section type (health assessment vs. clinical judgments) from the content.

### Manual: getting the HTML for the CLI

If you'd rather feed a saved HTML file to the CLI instead of using the extension:

1. Open the chapter in **Chrome** or **Firefox**.
2. Open DevTools: `F12` (or `Cmd+Option+I` on Mac).
3. In the Elements tab, `Cmd+F` / `Ctrl+F` and search for `epub:type="division"`.
4. Right-click the matching `<section>` → **Copy** → **Copy element**.
5. Paste into a `.txt` or `.html` file.

(The extension does steps 2–5 for you.)

## What the Output Looks Like

**Headers** are bolded with `** markers **`:
```
** Health Assessment **

** Collecting Subjective Data: The Nursing Health History **
```

**Two-column tables** (Question | Rationale) are formatted side by side:
```
** History of Present Health Concern **

  Describe any recent changes     |  A sudden decrease in ability
  in your hearing.                |  to hear in one ear may be
                                  |  associated with otitis media,
                                  |  earwax impaction, or foreign-
                                  |  body obstruction.
--------------------------------------------------------------------------------
```

**PDF output** uses ReportLab to produce properly formatted documents with real tables, bold headers, and readable body text.

## Architecture

```
                    ┌──────────────────────────────┐
                    │  bookshelf_extract.py        │
                    │  parse_html → build_lines →  │
                    │  format_pdf / format_txt     │
                    └──────────────┬───────────────┘
                                   │ in-memory library API
       ┌───────────────────────────┼───────────────────────────┐
       │                           │                           │
┌──────▼──────┐           ┌────────▼─────────┐         ┌───────▼────────┐
│  CLI (main) │           │ server.py        │         │ Library import │
│  reads file │           │ FastAPI /extract │         │ html_to_pdf_   │
│  writes pdf │           │ + /healthz + /   │         │ bytes(html)    │
└─────────────┘           └────────┬─────────┘         └────────────────┘
                                   │
                          ┌────────┴──────────┐
                          │                   │
                   ┌──────▼──────┐    ┌───────▼────────┐
                   │ web/        │    │ extension/     │
                   │ paste page  │    │ MV3 popup +    │
                   │             │    │ executeScript  │
                   └─────────────┘    └────────────────┘
```

`server.py` exposes:
- `POST /extract` — body `{html, mode: "single"|"split", format: "pdf"|"txt"}` → PDF/TXT bytes (single) or ZIP (split).
- `GET /healthz` — `{"ok": true}`.
- `GET /` — serves the paste page.

The extension never handles credentials. The user is already logged into Bookshelf in their own browser; the popup just runs `document.querySelector('section[epub\\:type="division"]')` across all frames in the active tab and forwards the result to the backend.

## Command Reference (CLI)

```
usage: bookshelf_extract.py [-h] [-o OUTPUT] [--txt] [--pdf] [--split] input

positional arguments:
  input                 Path to the HTML/text file

options:
  -h, --help            Show this help message
  -o, --output OUTPUT   Output base name (single) or directory (split)
  --txt                 Output .txt only
  --pdf                 Output .pdf only
  --split               Split on <section> tags, one output per section
```

## FAQ

**Q: Does this work with any Bookshelf textbook?**
A: It's been tested with nursing/health assessment textbooks from Wolters Kluwer (the ones using `comment78305`-style class names). Other publishers use different HTML structures — the core tag-stripping will still work, but the header/table detection might need tweaking.

**Q: Can I use this with the Bookshelf desktop app?**
A: You need the **web version** (in a browser) for the extension and DevTools paste flow. The desktop app doesn't expose the DOM.

**Q: The output is missing some content.**
A: Make sure you're capturing the right element. If you copy a `<div>` instead of the full `<section>`, you'll get a subset. When in doubt, copy the `<body>` tag — the script filters out junk either way. The extension handles this automatically.

**Q: Some headers aren't showing as bold.**
A: The script detects headers by tag name (`<h1>`–`<h6>`) and by CSS class (`UNT2`, `UNTMT3`, etc.). If your textbook uses different class names for headers, add them to the `HEADER_CLASSES` set near the top of the script.

**Q: Why not have the backend log into Bookshelf for the user?**
A: University SSO + 2FA blocks headless logins, VitalSource has anti-automation, and storing credentials creates real legal exposure. The extension model sidesteps all three by letting the user's own authenticated browser do the data fetch.

**Q: How do I deploy the backend?**
A: See [Deploying the backend](#deploying-the-backend). One-line summary: `fly deploy` from the repo root after editing `fly.toml`.

## License

MIT — do whatever you want with it.
