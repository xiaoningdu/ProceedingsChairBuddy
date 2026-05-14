from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import cgi
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from proceeding_chair_app.checks import CHECKLIST_IDS, CHECKLIST_ITEMS, build_submission_records
from proceeding_chair_app.parsers import ensure_sample_pdfs, load_hotcrp_html, load_xml_papers


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("PCB_DATA_DIR", ROOT)).resolve()
TRACKS_PATH = DATA_DIR / "tracks.json"
STATE_DIR = DATA_DIR / "review_state"
TRACK_DATA_DIR = DATA_DIR / "track_data"


def load_tracks_config() -> list[dict]:
    if not TRACKS_PATH.exists():
        return []
    data = json.loads(TRACKS_PATH.read_text(encoding="utf-8"))
    return data.get("tracks", [])


def find_track(track_id: str) -> Optional[dict]:
    for track in load_tracks_config():
        if track.get("id") == track_id:
            return track
    return None


def default_track_id() -> str:
    tracks = load_tracks_config()
    return tracks[0]["id"] if tracks else ""


def track_path(track: dict, key: str) -> Path:
    path = Path(track[key])
    return path if path.is_absolute() else DATA_DIR / path


def load_track_state(track_id: str) -> dict:
    path = STATE_DIR / f"{track_id}.json"
    if not path.exists():
        return {"papers": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"papers": {}}


def save_track_state(track_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{track_id}.json"
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def save_tracks_config(tracks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRACKS_PATH.write_text(json.dumps({"tracks": tracks}, indent=2), encoding="utf-8")


def parse_checklist_ids(values: object, default_all: bool = True) -> list[str]:
    if values is None:
        return list(CHECKLIST_IDS) if default_all else []
    if isinstance(values, str):
        raw_values = [item.strip() for item in values.split(",") if item.strip()]
    elif isinstance(values, list):
        raw_values = [str(item).strip() for item in values if str(item).strip()]
    else:
        raw_values = []
    unknown = sorted(set(raw_values) - set(CHECKLIST_IDS))
    if unknown:
        raise ValueError("Unknown checklist item: " + ", ".join(unknown))
    selected = set(raw_values)
    return [check_id for check_id in CHECKLIST_IDS if check_id in selected]


def add_track(payload: dict) -> dict:
    track_id = str(payload.get("id", "")).strip()
    name = str(payload.get("name", "")).strip()
    xml = str(payload.get("xml", "")).strip()
    html = str(payload.get("html", "")).strip()
    zip_path = str(payload.get("zip", "")).strip()
    pdf_dir = str(payload.get("pdf_dir", "")).strip()
    if not all([track_id, name, xml, html, zip_path, pdf_dir]):
        raise ValueError("All track fields are required")
    if not re_match_track_id(track_id):
        raise ValueError("Track ID may contain only letters, numbers, dashes, and underscores")
    tracks = load_tracks_config()
    if any(track.get("id") == track_id for track in tracks):
        raise ValueError("Track ID already exists")
    for file_key, file_path in [("xml", xml), ("html", html), ("zip", zip_path)]:
        if not track_path({file_key: file_path}, file_key).is_file():
            raise ValueError(f"{file_key} file does not exist")
    track_path({"pdf_dir": pdf_dir}, "pdf_dir").mkdir(parents=True, exist_ok=True)
    checklist_ids = parse_checklist_ids(payload.get("checklist_ids"))
    track = {
        "id": track_id,
        "name": name,
        "xml": xml,
        "html": html,
        "zip": zip_path,
        "pdf_dir": pdf_dir,
        "checklist_ids": checklist_ids,
    }
    tracks.append(track)
    save_tracks_config(tracks)
    return {"ok": True, "track": track}


def add_track_upload(fields: dict, files: dict) -> dict:
    track_id = str(fields.get("id", "")).strip()
    name = str(fields.get("name", "")).strip() or track_id
    if not track_id:
        raise ValueError("Track ID is required")
    if not re_match_track_id(track_id):
        raise ValueError("Track ID may contain only letters, numbers, dashes, and underscores")
    tracks = load_tracks_config()
    if any(track.get("id") == track_id for track in tracks):
        raise ValueError("Track ID already exists")
    for key in ["zip", "xml", "html"]:
        if key not in files or not getattr(files[key], "filename", ""):
            raise ValueError(f"{key} file is required")

    base_dir = TRACK_DATA_DIR / track_id
    input_dir = base_dir / "inputs"
    pdf_dir = base_dir / "pdfs"
    input_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = {}
    for key in ["zip", "xml", "html"]:
        saved_paths[key] = _save_uploaded_file(files[key], input_dir)

    checklist_ids = parse_checklist_ids(
        fields.get("checklist_ids"),
        default_all="checklist_ids_present" not in fields,
    )
    track = {
        "id": track_id,
        "name": name,
        "xml": _relative_path(saved_paths["xml"]),
        "html": _relative_path(saved_paths["html"]),
        "zip": _relative_path(saved_paths["zip"]),
        "pdf_dir": _relative_path(pdf_dir),
        "checklist_ids": checklist_ids,
    }
    tracks.append(track)
    save_tracks_config(tracks)
    return {"ok": True, "track": track}


def _save_uploaded_file(field, directory: Path) -> Path:
    filename = _safe_filename(field.filename)
    target = directory / filename
    field.file.seek(0)
    with target.open("wb") as output:
        shutil.copyfileobj(field.file, output)
    return target


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not name or name in {".", ".."}:
        raise ValueError("Uploaded file has an invalid name")
    return name


def _relative_path(path: Path) -> str:
    return str(path.relative_to(DATA_DIR))


def re_match_track_id(track_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", track_id))


def load_track_data(track_id: str) -> dict:
    track = find_track(track_id)
    if not track:
        raise KeyError(track_id)

    zip_path = track_path(track, "zip")
    pdf_dir = track_path(track, "pdf_dir")
    ensure_sample_pdfs(zip_path, pdf_dir)
    xml_papers = load_xml_papers(track_path(track, "xml"))
    html_papers, global_messages = load_hotcrp_html(track_path(track, "html"))
    checklist_ids = parse_checklist_ids(track.get("checklist_ids"))
    records = build_submission_records(xml_papers, html_papers, pdf_dir, checklist_ids)
    sample_ids = {
        match.group(1)
        for path in pdf_dir.glob("*.pdf")
        for match in [re.search(r"(?:paper|final)(\d+)\.pdf$", path.name)]
        if match
    }
    records = [record for record in records if record["id"] in sample_ids]

    state = load_track_state(track_id)
    for record in records:
        paper_state = state.get("papers", {}).get(record["id"], {})
        record["completed"] = bool(paper_state.get("completed", False))
        record["pdf"]["url"] = f"/api/tracks/{track_id}/pdf/{record['pdf']['filename']}" if record["pdf"]["filename"] else ""
        checks_by_id = paper_state.get("checks", {})
        for check in record["checks"]:
            saved = checks_by_id.get(check["id"])
            if saved:
                check["status"] = saved.get("status", check["status"])
                check["evidence"] = saved.get("evidence", check["evidence"])
        record["status_counts"] = {
            "pass": sum(1 for check in record["checks"] if check["status"] == "pass"),
            "issue": sum(1 for check in record["checks"] if check["status"] == "issue"),
            "manual": sum(1 for check in record["checks"] if check["status"] == "manual"),
            "unavailable": sum(1 for check in record["checks"] if check["status"] == "unavailable"),
        }

    return {
        "track": {
            "id": track["id"],
            "name": track["name"],
            "checklist_ids": checklist_ids,
        },
        "submissions": records,
        "global_messages": global_messages,
        "sources": {
            "xml": Path(track["xml"]).name,
            "hotcrp_html": Path(track["html"]).name,
            "zip": Path(track["zip"]).name,
            "pdf_dir": Path(track["pdf_dir"]).name,
        },
    }


def load_tracks_summary() -> dict:
    summaries = []
    for track in load_tracks_config():
        data = load_track_data(track["id"])
        submissions = data["submissions"]
        completed = sum(1 for submission in submissions if submission.get("completed"))
        issues = sum(submission["status_counts"]["issue"] for submission in submissions)
        summaries.append(
            {
                "id": track["id"],
                "name": track["name"],
                "paper_count": len(submissions),
                "completed_count": completed,
                "remaining_count": len(submissions) - completed,
                "issue_count": issues,
                "sources": data["sources"],
            }
        )
    return {"tracks": summaries}


def save_paper_review(track_id: str, payload: dict) -> dict:
    paper_id = str(payload.get("paper_id", ""))
    if not paper_id:
        raise ValueError("paper_id is required")
    state = load_track_state(track_id)
    papers = state.setdefault("papers", {})
    paper_state = papers.setdefault(paper_id, {})
    paper_state["completed"] = bool(payload.get("completed", False))
    checks = {}
    for check in payload.get("checks", []):
        check_id = check.get("id")
        if check_id:
            checks[check_id] = {
                "status": check.get("status", ""),
                "evidence": check.get("evidence", ""),
            }
    paper_state["checks"] = checks
    save_track_state(track_id, state)
    return {"ok": True}


def remove_track(track_id: str) -> dict:
    tracks = load_tracks_config()
    remaining = [track for track in tracks if track.get("id") != track_id]
    if len(remaining) == len(tracks):
        raise KeyError(track_id)
    save_tracks_config(remaining)
    state_path = STATE_DIR / f"{track_id}.json"
    if state_path.exists():
        state_path.unlink()
    return {"ok": True}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif self.path == "/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
        elif self.path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        elif self.path == "/api/checklist-items":
            self._serve_json({"items": CHECKLIST_ITEMS})
        elif self.path == "/api/tracks":
            self._serve_json(load_tracks_summary())
        elif self.path.startswith("/api/tracks/") and self.path.endswith("/pdf"):
            self.send_error(404)
        elif self.path.startswith("/api/tracks/") and "/pdf/" in self.path:
            self._serve_track_pdf()
        elif self.path.startswith("/api/tracks/"):
            track_id = unquote(self.path.removeprefix("/api/tracks/")).strip("/")
            try:
                self._serve_json(load_track_data(track_id))
            except KeyError:
                self.send_error(404)
        elif self.path == "/api/submissions":
            self._serve_json(load_track_data(default_track_id()))
        elif self.path.startswith("/pdf/"):
            filename = Path(unquote(self.path.removeprefix("/pdf/"))).name
            track = find_track(default_track_id())
            pdf_dir = track_path(track, "pdf_dir") if track else ROOT
            self._serve_file(pdf_dir / filename, mimetypes.guess_type(filename)[0] or "application/pdf")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/tracks":
            try:
                if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                    fields, files = self._read_multipart()
                    self._serve_json(add_track_upload(fields, files))
                else:
                    payload = self._read_json()
                    self._serve_json(add_track(payload))
            except ValueError as exc:
                self.send_error(400, str(exc))
        elif self.path.startswith("/api/tracks/") and self.path.endswith("/reviews"):
            track_id = unquote(self.path.removeprefix("/api/tracks/").removesuffix("/reviews").strip("/"))
            if not find_track(track_id):
                self.send_error(404)
                return
            try:
                payload = self._read_json()
                self._serve_json(save_paper_review(track_id, payload))
            except ValueError as exc:
                self.send_error(400, str(exc))
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/tracks/"):
            track_id = unquote(self.path.removeprefix("/api/tracks/")).strip("/")
            try:
                self._serve_json(remove_track(track_id))
            except KeyError:
                self.send_error(404)
        else:
            self.send_error(404)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8") or "{}")

    def _read_multipart(self) -> tuple[dict, dict]:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        fields = {}
        files = {}
        for key in form.keys():
            item = form[key]
            if isinstance(item, list):
                if item and item[0].filename:
                    files[key] = item[0]
                else:
                    fields[key] = [field.value for field in item]
                continue
            if item.filename:
                files[key] = item
            else:
                fields[key] = item.value
        return fields, files

    def _serve_track_pdf(self) -> None:
        prefix = "/api/tracks/"
        rest = self.path.removeprefix(prefix)
        track_id, _, filename = rest.partition("/pdf/")
        track = find_track(unquote(track_id))
        if not track:
            self.send_error(404)
            return
        filename = Path(unquote(filename)).name
        pdf_dir = track_path(track, "pdf_dir")
        self._serve_file(pdf_dir / filename, mimetypes.guess_type(filename)[0] or "application/pdf")

    def _serve_json(self, data: dict) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    host = os.environ.get("PCB_HOST", "127.0.0.1")
    port = int(os.environ.get("PCB_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Proceedings Chair Buddy running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
