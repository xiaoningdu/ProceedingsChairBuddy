# Proceedings Chair Buddy

Proceedings Chair Buddy is a local web app for proceedings chairs who need to review camera-ready papers against HotCRP proceedings data, TOC XML metadata, and extracted PDF text.

This tool is intended to facilitate proceedings chairs, not replace them. It brings the main checking sources into a one-stop review experience and automates checks where the source data supports it, but responsibility for camera-ready quality remains with the chairs unless the proceedings-chair role no longer exists for the venue. Chairs should treat automated results as review aids and apply their own judgment before accepting final papers.

The current version is built for proceedings prepared through HotCRP.

## Features

- Manage multiple tracks from a single home page.
- Add each track from a ZIP of final-version PDFs, TOC XML, HotCRP ACM HTML export, and optional ACM e-Right HTML.
- Choose which checklist items apply when adding a track.
- Review each paper with the PDF, metadata, issue summary, and editable checklist side by side.
- Save per-paper finished/open state, checklist result overrides, and edited comments.
- Create follow-up review rounds that carry forward only papers with issues.
- Lock earlier review rounds once they have a follow-up, so comments and reruns cannot be changed accidentally.
- Rerun checks for the currently selected review round only, with a confirmation that current check results will be overwritten.
- Export CSV results with one row per paper and checklist items as columns.

## Run With Docker

```sh
docker compose up --build
```

Then open:

```text
http://127.0.0.1:8765
```

Docker stores uploaded tracks, review state, and review assets under `proceedings_data/` on the host.

To run without Compose:

```sh
docker build -t proceedings-chair-buddy .
docker run --rm -p 8765:8765 -v "$PWD/proceedings_data:/data" proceedings-chair-buddy
```

## Run Locally

### Local Prerequisites

For local runs without Docker, install Poppler so `pdftotext` is available for PDF text extraction.

```sh
# macOS
brew install poppler

# Debian/Ubuntu
sudo apt-get install poppler-utils

# Windows
choco install poppler
```

```sh
PYTHONPYCACHEPREFIX=.pycache python3 app.py
```

Then open:

```text
http://127.0.0.1:8765
```

By default, local data is written under the project directory:

- `tracks.json`
- `review_state/`
- `track_data/`
- `review_assets/`

To store data elsewhere, set `PCB_DATA_DIR`:

```sh
PCB_DATA_DIR=/path/to/data PYTHONPYCACHEPREFIX=.pycache python3 app.py
```

## Track Workflow

1. Open the Tracks page.
2. Use Add track to select:
   - ZIP of final version
   - TOC XML
   - HotCRP HTML file
3. Select the checklist items that apply.
4. Open the generated initial review round.
5. Review each paper, edit checklist results/comments as needed, and mark papers finished.
6. Create a follow-up review when revised files are available for papers with issues.

Follow-up review rounds preserve the prior round as history. A review round with a follow-up is locked: checklist edits, finished/open changes, and reruns are disabled for that earlier round.

## CSV Export

CSV export creates one row per paper. The columns are:

- `paper_id`
- `issue_summary`
- one column for each displayed checklist item

The exported filename includes the track name and review round, for example:

```text
track-name-follow-up-1-results.csv
```

## Checks

Automated and assisted checks currently cover:

- PDF title, author list, affiliations, and author emails against metadata.
- ORCID presence in metadata.
- ACM keywords, CCS, references, source files, and other HotCRP proceedings messages.
- DOI, ISBN, and copyright type against ACM e-Right data.
- PDF availability.
- Visible page-number detection.
- Manual review prompts for ACM template version, author stacking, last-page balance, and track-specific page limit.

## Limits

- PDF checks depend on Poppler `pdftotext` and the quality of extracted text.
- Some formatting checks remain manual because they require visual judgment.
- Track-specific page-limit rules are not yet configurable in the app.
