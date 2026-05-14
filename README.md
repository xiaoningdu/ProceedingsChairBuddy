# Proceedings Chair Buddy

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

This is a local prototype for reviewing final proceeding submissions against metadata, HotCRP export data, and extracted PDF text.

The current version only supports proceedings that are prepared via HotCRP.

## Local Prerequisites

For local runs without Docker, install Poppler so the `pdftotext` command is available for PDF text extraction.

```sh
# macOS
brew install poppler

# Debian/Ubuntu
sudo apt-get install poppler-utils

# Windows
choco install poppler
```

## Run

```sh
PYTHONPYCACHEPREFIX=.pycache python3 app.py
```

Then open:

```text
http://127.0.0.1:8765
```

## Run With Docker

Build and start the container:

```sh
docker compose up --build
```

Then open:

```text
http://127.0.0.1:8765
```

Docker stores uploaded tracks, `tracks.json`, and review progress under `proceedings_data/` on the host.

To run without Compose:

```sh
docker build -t proceedings-chair-buddy .
docker run --rm -p 8765:8765 -v "$PWD/proceedings_data:/data" proceedings-chair-buddy
```

## Current Behavior

- Shows a homepage summary of configured tracks.
- Extracts uploaded final-version PDFs for each track.
- Parses e-rights XML metadata.
- Parses the HotCRP ACM settings HTML for ACM class, page count, source-file links, paginated PDF links, and per-paper warnings/errors.
- Uses Poppler `pdftotext` for PDF text extraction when available.
- Checks whether metadata titles, author names, affiliations, and author emails appear in extracted PDF text.
- Checks whether the PDF appears to contain visible page numbers near page boundaries.
- Shows the selected PDF beside checklist results.
- Saves per-paper checklist evidence edits and finished/open status under `review_state/`.
- Exports checklist results as CSV from the browser.

## Adding Tracks

Use the "Add track" form on the Tracks page. Select the track ZIP, XML, and HotCRP ACM HTML files with the browser file picker. The app copies them under `track_data/<track-id>/inputs/` and automatically extracts PDFs under `track_data/<track-id>/pdfs/`.

Tracks are recorded in `tracks.json`. Per-paper review edits are saved under `review_state/`. When running with Docker, these files live under `proceedings_data/`.

## Current Limits

- PDF text extraction depends on Poppler `pdftotext`.
- Author stacking, last-page balance, and exact ACM template-version checks are also marked as manual/heuristic.
- Track-specific page-limit decisions need configured rules.
- Copyright and ISBN detection depends on readable PDF text extraction.
