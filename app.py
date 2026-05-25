from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import cgi
from copy import deepcopy
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlsplit

from proceeding_chair_app.checks import CHECKLIST_IDS, CHECKLIST_ITEMS, build_submission_records
from proceeding_chair_app.parsers import ensure_sample_pdfs, load_eright, load_hotcrp_html, load_xml_papers


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("PCB_DATA_DIR", ROOT)).resolve()
TRACKS_PATH = DATA_DIR / "tracks.json"
STATE_DIR = DATA_DIR / "review_state"
REVIEW_ASSETS_DIR = DATA_DIR / "review_assets"
TRACK_DATA_DIR = DATA_DIR / "track_data"
STATE_SCHEMA_VERSION = 2
SOURCE_KEYS = ["zip", "xml", "html"]
OPTIONAL_SOURCE_KEYS = ["copyright_html"]
COPYRIGHT_DASHBOARD_CHECK_IDS = {
    "copyright_doi_matches_pdf",
    "copyright_isbn_matches_pdf",
    "copyright_type_matches_pdf",
}
RETIRED_CHECKLIST_IDS = {"pdf_copyright_isbn"}


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


def optional_track_path(track: dict, key: str) -> Optional[Path]:
    value = track.get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else DATA_DIR / path


def load_track_state(track_id: str) -> dict:
    path = STATE_DIR / f"{track_id}.json"
    if not path.exists():
        return _empty_track_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty_track_state()
    return _normalize_track_state(state)


def save_track_state(track_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{track_id}.json"
    path.write_text(json.dumps(_normalize_track_state(state), indent=2, sort_keys=True), encoding="utf-8")


def save_tracks_config(tracks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRACKS_PATH.write_text(json.dumps({"tracks": tracks}, indent=2), encoding="utf-8")


def _empty_track_state() -> dict:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "root_review_id": "",
        "active_review_id": "",
        "next_review_seq": 1,
        "reviews": {},
    }


def _normalize_track_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return _empty_track_state()
    if "reviews" not in state and "papers" in state:
        state = _legacy_state_to_reviews(state)
    normalized = _empty_track_state()
    normalized.update({
        "schema_version": STATE_SCHEMA_VERSION,
        "root_review_id": str(state.get("root_review_id", "")),
        "active_review_id": str(state.get("active_review_id", "")),
        "next_review_seq": int(state.get("next_review_seq", 1) or 1),
        "reviews": {},
    })
    reviews = state.get("reviews", {}) if isinstance(state.get("reviews", {}), dict) else {}
    for review_id, review in reviews.items():
        if not isinstance(review, dict):
            continue
        normalized["reviews"][str(review_id)] = _normalize_review(review)
    if not normalized["root_review_id"] and normalized["reviews"]:
        normalized["root_review_id"] = _first_review_id(normalized["reviews"])
    if not normalized["active_review_id"] or normalized["active_review_id"] not in normalized["reviews"]:
        normalized["active_review_id"] = normalized["root_review_id"] or _first_review_id(normalized["reviews"])
    if not normalized["next_review_seq"] or normalized["next_review_seq"] < len(normalized["reviews"]) + 1:
        normalized["next_review_seq"] = len(normalized["reviews"]) + 1
    _normalize_follow_up_labels(normalized)
    return normalized


def _legacy_state_to_reviews(state: dict) -> dict:
    papers = state.get("papers", {}) if isinstance(state.get("papers", {}), dict) else {}
    root_review_id = "review-1"
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "root_review_id": root_review_id,
        "active_review_id": root_review_id,
        "next_review_seq": 2,
        "reviews": {
            root_review_id: {
                "id": root_review_id,
                "parent_id": "",
                "label": "Initial review",
                "created_at": _utc_now(),
                "sources": {},
                "paper_ids": [],
                "children": [],
                "papers": papers,
            }
        },
    }


def _normalize_review(review: dict) -> dict:
    normalized = {
        "id": str(review.get("id", "")),
        "parent_id": str(review.get("parent_id", "")),
        "label": str(review.get("label", "")),
        "created_at": str(review.get("created_at", "")),
        "sources": _normalize_review_sources(review.get("sources", {})),
        "paper_ids": [str(paper_id) for paper_id in review.get("paper_ids", []) if str(paper_id).strip()],
        "children": [str(child_id) for child_id in review.get("children", []) if str(child_id).strip()],
        "papers": {},
    }
    papers = review.get("papers", {}) if isinstance(review.get("papers", {}), dict) else {}
    for paper_id, paper_state in papers.items():
        if not isinstance(paper_state, dict):
            continue
        normalized["papers"][str(paper_id)] = _normalize_paper_state(paper_state)
    return normalized


def _normalize_paper_state(paper_state: dict) -> dict:
    normalized = {
        "completed": bool(paper_state.get("completed", False)),
        "checks": {},
    }
    baseline_checks = paper_state.get("baseline_checks", {})
    if isinstance(baseline_checks, dict):
        normalized["baseline_checks"] = {
            str(check_id): {
                "status": str(check.get("status", "")),
                "evidence": str(check.get("evidence", "")),
            }
            for check_id, check in baseline_checks.items()
            if isinstance(check, dict)
        }
    checks = paper_state.get("checks", {})
    if isinstance(checks, dict):
        normalized["checks"] = {
            str(check_id): {
                "status": str(check.get("status", "")),
                "evidence": str(check.get("evidence", "")),
            }
            for check_id, check in checks.items()
            if isinstance(check, dict)
        }
    parent_review_id = str(paper_state.get("parent_review_id", "")).strip()
    if parent_review_id:
        normalized["parent_review_id"] = parent_review_id
    return normalized


def _normalize_review_sources(sources: object) -> dict:
    if not isinstance(sources, dict):
        return {}
    normalized = {}
    for key in [*SOURCE_KEYS, *OPTIONAL_SOURCE_KEYS, "pdf_dir"]:
        value = sources.get(key)
        if value:
            normalized[key] = str(value)
    return normalized


def _first_review_id(reviews: dict) -> str:
    return sorted(reviews.keys(), key=_review_sort_key)[0] if reviews else ""


def _normalize_follow_up_labels(state: dict) -> None:
    reviews = state.get("reviews", {})
    root_id = state.get("root_review_id")
    if not root_id or root_id not in reviews:
        return

    def visit(review_id: str, number: int) -> None:
        review = reviews.get(review_id)
        if not review:
            return
        if review.get("parent_id"):
            review["label"] = f"Follow-up {number}"
        for child_id in review.get("children", []):
            visit(child_id, number + 1)

    for child_id in reviews[root_id].get("children", []):
        visit(child_id, 1)


def _review_sort_key(review_id: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", review_id)
    return (int(match.group(1)) if match else 0, review_id)


def _paper_sort_key(paper_id: str) -> tuple[int, str]:
    match = re.search(r"\d+", paper_id)
    return (int(match.group(0)) if match else 0, paper_id)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_checklist_ids(values: object, default_all: bool = True) -> list[str]:
    if values is None:
        return list(CHECKLIST_IDS) if default_all else []
    if isinstance(values, str):
        raw_values = [item.strip() for item in values.split(",") if item.strip()]
    elif isinstance(values, list):
        raw_values = [str(item).strip() for item in values if str(item).strip()]
    else:
        raw_values = []
    selected = set(raw_values) - RETIRED_CHECKLIST_IDS
    unknown = sorted(selected - set(CHECKLIST_IDS))
    if unknown:
        raise ValueError("Unknown checklist item: " + ", ".join(unknown))
    if selected == set(CHECKLIST_IDS) - COPYRIGHT_DASHBOARD_CHECK_IDS:
        selected = set(CHECKLIST_IDS)
    return [check_id for check_id in CHECKLIST_IDS if check_id in selected]


def _review_or_default(state: dict, review_id: Optional[str] = None) -> dict:
    reviews = state.get("reviews", {})
    if not reviews:
        raise KeyError("No reviews exist for this track")
    active_id = review_id or state.get("active_review_id") or state.get("root_review_id")
    if active_id not in reviews:
        active_id = state.get("root_review_id") or _first_review_id(reviews)
    review = reviews.get(active_id)
    if not review:
        raise KeyError(active_id)
    return review


def _review_chain(state: dict) -> list[dict]:
    reviews = state.get("reviews", {})
    ordered_reviews = []
    roots = [review for review in reviews.values() if not review.get("parent_id")]
    for root in sorted(roots, key=lambda review: (_review_sort_key(review.get("id", "")))):
        _walk_review_tree(root, reviews, ordered_reviews, depth=0)
    return ordered_reviews


def _walk_review_tree(review: dict, reviews: dict, ordered_reviews: list[dict], depth: int) -> None:
    review_copy = deepcopy(review)
    review_copy["depth"] = depth
    ordered_reviews.append(review_copy)
    for child_id in review.get("children", []):
        child = reviews.get(child_id)
        if child:
            _walk_review_tree(child, reviews, ordered_reviews, depth + 1)


def _review_paper_ids(review: dict, all_record_ids: list[str]) -> list[str]:
    paper_ids = [str(paper_id) for paper_id in review.get("paper_ids", []) if str(paper_id).strip()]
    if paper_ids:
        return paper_ids
    return all_record_ids


def _issue_paper_ids(review: dict) -> list[str]:
    issue_ids = []
    for paper_id, paper_state in review.get("papers", {}).items():
        checks = paper_state.get("checks", {})
        if any(check.get("status") == "issue" for check in checks.values()):
            issue_ids.append(paper_id)
    return sorted(issue_ids, key=_paper_sort_key)


def _review_issue_count(review: dict) -> int:
    return sum(
        1
        for paper_state in review.get("papers", {}).values()
        if any(check.get("status") == "issue" for check in paper_state.get("checks", {}).values())
    )


def _review_counts(review: dict) -> dict:
    completed_count = sum(1 for paper_state in review.get("papers", {}).values() if paper_state.get("completed", False))
    paper_count = len(review.get("paper_ids", []))
    child_count = len(review.get("children", []))
    return {
        "paper_count": paper_count,
        "issue_paper_count": len(_issue_paper_ids(review)),
        "paper_issue_count": _review_issue_count(review),
        "child_count": child_count,
        "locked": child_count > 0,
        "completed_count": completed_count,
        "remaining_count": max(paper_count - completed_count, 0),
    }


def _next_follow_up_number(parent_review: dict) -> int:
    match = re.search(r"Follow-up\s+(\d+)$", parent_review.get("label", ""))
    return int(match.group(1)) + 1 if match else 1


def _review_title(review: dict) -> str:
    return review.get("label") or "Review"


def _review_snapshot(track: dict) -> dict:
    snapshot = {
        "xml": track["xml"],
        "html": track["html"],
        "zip": track["zip"],
        "pdf_dir": track["pdf_dir"],
    }
    if track.get("copyright_html"):
        snapshot["copyright_html"] = track["copyright_html"]
    return snapshot


def _review_asset_dir(track_id: str, review_id: str) -> Path:
    return REVIEW_ASSETS_DIR / track_id / review_id


def _review_asset_path(track_id: str, review_id: str, key: str, filename: str) -> Path:
    return _review_asset_dir(track_id, review_id) / "inputs" / filename


def _resolve_review_source_path(source: str, key: str) -> Path:
    return Path(source) if Path(source).is_absolute() else DATA_DIR / source


def _snapshot_review_sources(track_id: str, review_id: str, sources: dict, files: dict) -> dict:
    asset_dir = _review_asset_dir(track_id, review_id)
    input_dir = asset_dir / "inputs"
    pdf_dir = asset_dir / "pdfs"
    input_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {}
    zip_replaced = False
    for key in SOURCE_KEYS:
        uploaded = files.get(key)
        if uploaded is not None and getattr(uploaded, "filename", ""):
            saved_path = _save_uploaded_file(uploaded, input_dir)
            snapshot[key] = _relative_path(saved_path)
            if key == "zip":
                zip_replaced = True
        else:
            source = sources.get(key)
            if not source:
                raise ValueError(f"Missing {key} source for follow-up review")
            source_path = _resolve_review_source_path(source, key)
            if not source_path.exists():
                raise ValueError(f"Source file does not exist: {source_path}")
            target = input_dir / source_path.name
            if source_path.resolve() != target.resolve():
                shutil.copy2(source_path, target)
                if key == "zip":
                    zip_replaced = True
            snapshot[key] = _relative_path(target)
    for key in OPTIONAL_SOURCE_KEYS:
        uploaded = files.get(key)
        if uploaded is not None and getattr(uploaded, "filename", ""):
            saved_path = _save_uploaded_file(uploaded, input_dir)
            snapshot[key] = _relative_path(saved_path)
            continue
        source = sources.get(key)
        if not source:
            continue
        source_path = _resolve_review_source_path(source, key)
        if not source_path.exists():
            continue
        target = input_dir / source_path.name
        if source_path.resolve() != target.resolve():
            shutil.copy2(source_path, target)
        snapshot[key] = _relative_path(target)
    zip_source = _resolve_review_source_path(snapshot["zip"], "zip")
    if zip_replaced:
        shutil.rmtree(pdf_dir, ignore_errors=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
    ensure_sample_pdfs(zip_source, pdf_dir)
    snapshot["pdf_dir"] = _relative_path(pdf_dir)
    return snapshot


def _review_source_names(review: dict) -> dict:
    sources = review.get("sources", {})
    return {
        "xml": Path(sources["xml"]).name if sources.get("xml") else "",
        "html": Path(sources["html"]).name if sources.get("html") else "",
        "copyright_html": Path(sources["copyright_html"]).name if sources.get("copyright_html") else "",
        "zip": Path(sources["zip"]).name if sources.get("zip") else "",
        "pdf_dir": Path(sources["pdf_dir"]).name if sources.get("pdf_dir") else "",
    }


def _comparison_for_checks(current_checks: list[dict], baseline_checks: dict) -> dict:
    comparison_counts = {"fixed": 0, "still_present": 0, "new": 0, "unchanged": 0}
    for check in current_checks:
        baseline = baseline_checks.get(check["id"])
        if baseline and baseline.get("status") == "issue":
            if check["status"] == "issue":
                comparison = "still_present"
            else:
                comparison = "fixed"
        elif baseline and check["status"] == "issue":
            comparison = "new"
        else:
            comparison = ""
        check["comparison"] = comparison
        if comparison:
            comparison_counts[comparison] += 1
        else:
            comparison_counts["unchanged"] += 1
        check["baseline_status"] = baseline.get("status") if baseline else ""
        check["baseline_evidence"] = baseline.get("evidence") if baseline else ""
    return comparison_counts


def _build_review_records(
    track: dict,
    review: dict,
    xml_papers: dict,
    html_papers: dict,
    pdf_dir: Path,
    copyright_papers: Optional[dict] = None,
    review_id: str = "",
) -> list[dict]:
    checklist_ids = parse_checklist_ids(track.get("checklist_ids"))
    records = build_submission_records(xml_papers, html_papers, pdf_dir, copyright_papers or {}, checklist_ids)
    review_paper_ids = set(_review_paper_ids(review, [record["id"] for record in records]))
    records = [record for record in records if record["id"] in review_paper_ids]
    paper_states = review.get("papers", {})
    for record in records:
        paper_state = paper_states.get(record["id"], {})
        record["completed"] = bool(paper_state.get("completed", False))
        if record["pdf"]["filename"]:
            query = f"?review_id={quote(review_id)}" if review_id else ""
            record["pdf"]["url"] = f"/api/tracks/{track['id']}/pdf/{record['pdf']['filename']}{query}"
        else:
            record["pdf"]["url"] = ""
        checks_by_id = paper_state.get("checks", {})
        for check in record["checks"]:
            saved = checks_by_id.get(check["id"])
            if saved:
                check["status"] = saved.get("status", check["status"])
                check["evidence"] = saved.get("evidence", check["evidence"])
        record["comparison_counts"] = _comparison_for_checks(record["checks"], paper_state.get("baseline_checks", {}))
        record["status_counts"] = {
            "pass": sum(1 for check in record["checks"] if check["status"] == "pass"),
            "issue": sum(1 for check in record["checks"] if check["status"] == "issue"),
            "manual": sum(1 for check in record["checks"] if check["status"] == "manual"),
            "unavailable": sum(1 for check in record["checks"] if check["status"] == "unavailable"),
        }
    return records


def _review_paths(review: dict, track: dict) -> dict:
    sources = review.get("sources", {})
    if sources.get("zip") and sources.get("xml") and sources.get("html") and sources.get("pdf_dir"):
        merged_sources = dict(sources)
        for key in OPTIONAL_SOURCE_KEYS:
            if not merged_sources.get(key) and track.get(key):
                merged_sources[key] = track[key]
        return merged_sources
    return _review_snapshot(track)


def _load_copyright_papers(source_paths: dict) -> dict:
    source = source_paths.get("copyright_html")
    if not source:
        return {}
    source_path = _resolve_review_source_path(source, "copyright_html")
    if not source_path.exists():
        return {}
    return load_eright(source_path)


def _ensure_root_review(state: dict, track: dict, xml_papers: dict, html_papers: dict, pdf_dir: Path, copyright_papers: Optional[dict] = None) -> dict:
    if state.get("reviews"):
        return state

    checklist_ids = parse_checklist_ids(track.get("checklist_ids"))
    records = build_submission_records(xml_papers, html_papers, pdf_dir, copyright_papers or {}, checklist_ids)
    root_review_id = "review-1"
    root_review = {
        "id": root_review_id,
        "parent_id": "",
        "label": "Initial review",
        "created_at": _utc_now(),
        "sources": _review_snapshot(track),
        "paper_ids": [record["id"] for record in records],
        "children": [],
        "papers": {},
    }
    for record in records:
        root_review["papers"][record["id"]] = {
            "completed": False,
            "checks": {
                check["id"]: {"status": check["status"], "evidence": check["evidence"]}
                for check in record["checks"]
            },
        }
    state["schema_version"] = STATE_SCHEMA_VERSION
    state["root_review_id"] = root_review_id
    state["active_review_id"] = root_review_id
    state["next_review_seq"] = 2
    state["reviews"] = {root_review_id: root_review}
    save_track_state(track["id"], state)
    return state


def add_track(payload: dict) -> dict:
    track_id = str(payload.get("id", "")).strip()
    name = str(payload.get("name", "")).strip()
    xml = str(payload.get("xml", "")).strip()
    html = str(payload.get("html", "")).strip()
    copyright_html = str(payload.get("copyright_html", "")).strip()
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
    if copyright_html and not track_path({"copyright_html": copyright_html}, "copyright_html").is_file():
        raise ValueError("copyright_html file does not exist")
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
    if copyright_html:
        track["copyright_html"] = copyright_html
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
    for key in SOURCE_KEYS:
        if key not in files or not getattr(files[key], "filename", ""):
            raise ValueError(f"{key} file is required")

    base_dir = TRACK_DATA_DIR / track_id
    input_dir = base_dir / "inputs"
    pdf_dir = base_dir / "pdfs"
    input_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = {}
    for key in SOURCE_KEYS:
        saved_paths[key] = _save_uploaded_file(files[key], input_dir)
    if files.get("copyright_html") is not None and getattr(files["copyright_html"], "filename", ""):
        saved_paths["copyright_html"] = _save_uploaded_file(files["copyright_html"], input_dir)

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
    if "copyright_html" in saved_paths:
        track["copyright_html"] = _relative_path(saved_paths["copyright_html"])
    tracks.append(track)
    save_tracks_config(tracks)
    return {"ok": True, "track": track}


def update_track_files(track_id: str, files: dict) -> dict:
    if not re_match_track_id(track_id):
        raise ValueError("Track ID may contain only letters, numbers, dashes, and underscores")
    tracks = load_tracks_config()
    track = next((candidate for candidate in tracks if candidate.get("id") == track_id), None)
    if not track:
        raise KeyError(track_id)

    replacement_keys = [key for key in [*SOURCE_KEYS, *OPTIONAL_SOURCE_KEYS] if key in files and getattr(files[key], "filename", "")]
    if not replacement_keys:
        raise ValueError("Select at least one replacement ZIP, XML, HotCRP HTML, or e-Right file")

    base_dir = TRACK_DATA_DIR / track_id
    input_dir = base_dir / "inputs"
    pdf_dir = base_dir / "pdfs"
    staging_dir = base_dir / ".update_tmp"
    staging_input_dir = staging_dir / "inputs"
    staging_pdf_dir = staging_dir / "pdfs"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_input_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = {}
    for key in replacement_keys:
        saved_paths[key] = _save_uploaded_file(files[key], staging_input_dir)

    try:
        if "zip" in saved_paths:
            # Validate and extract the replacement ZIP before touching the
            # existing pdfs directory. If extraction fails, the current track
            # files remain active.
            ensure_sample_pdfs(saved_paths["zip"], staging_pdf_dir)
    except Exception as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValueError(f"Could not extract replacement ZIP: {exc}") from exc

    input_dir.mkdir(parents=True, exist_ok=True)
    final_paths = {}
    for key, staged_path in saved_paths.items():
        final_path = input_dir / staged_path.name
        if final_path.exists():
            final_path.unlink()
        shutil.move(str(staged_path), final_path)
        final_paths[key] = final_path
        track[key] = _relative_path(final_path)

    if "zip" in final_paths:
        if pdf_dir.exists():
            shutil.rmtree(pdf_dir)
        shutil.move(str(staging_pdf_dir), pdf_dir)
        track["pdf_dir"] = _relative_path(pdf_dir)

    shutil.rmtree(staging_dir, ignore_errors=True)

    save_tracks_config(tracks)
    return {"ok": True, "updated": replacement_keys}


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


def load_track_data(track_id: str, review_id: Optional[str] = None) -> dict:
    return load_track_data_for_review(track_id, review_id)


def load_tracks_summary() -> dict:
    summaries = []
    for track in load_tracks_config():
        data = load_track_data_for_review(track["id"])
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
                "review": data["review"],
                "reviews": data["reviews"],
                "sources": data["sources"],
            }
        )
    return {"tracks": summaries}


def save_paper_review(track_id: str, payload: dict) -> dict:
    paper_id = str(payload.get("paper_id", ""))
    if not paper_id:
        raise ValueError("paper_id is required")
    review_id = str(payload.get("review_id", "")).strip()
    state = load_track_state(track_id)
    review = _review_or_default(state, review_id or None)
    if review.get("children"):
        raise ValueError("This review is locked because it already has a follow-up.")
    papers = review.setdefault("papers", {})
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
    if paper_id not in review.setdefault("paper_ids", []):
        review["paper_ids"].append(paper_id)
    save_track_state(track_id, state)
    return {"ok": True}


def create_follow_up_review(track_id: str, payload: dict, files: Optional[dict] = None) -> dict:
    parent_review_id = str(payload.get("parent_review_id", "")).strip()
    if not parent_review_id:
        raise ValueError("parent_review_id is required")
    track = find_track(track_id)
    if not track:
        raise KeyError(track_id)

    state = load_track_state(track_id)
    parent_review = _review_or_default(state, parent_review_id)
    if parent_review.get("children"):
        raise ValueError("The selected review already has a follow-up.")
    issue_paper_ids = _issue_paper_ids(parent_review)
    if not issue_paper_ids:
        raise ValueError("The selected review has no issue papers to carry forward.")

    track_zip = track_path(track, "zip")
    track_pdf_dir = track_path(track, "pdf_dir")
    ensure_sample_pdfs(track_zip, track_pdf_dir)
    parent_sources = _review_paths(parent_review, track)

    child_index = _next_follow_up_number(parent_review)
    child_review_id = f"review-{state.get('next_review_seq', 1)}"
    state["next_review_seq"] = int(state.get("next_review_seq", 1) or 1) + 1
    review_assets = _snapshot_review_sources(track_id, child_review_id, parent_sources, files or {})
    child_xml_path = _resolve_review_source_path(review_assets["xml"], "xml")
    child_html_path = _resolve_review_source_path(review_assets["html"], "html")
    child_pdf_dir = _resolve_review_source_path(review_assets["pdf_dir"], "pdf_dir")
    xml_papers = load_xml_papers(child_xml_path)
    html_papers, _ = load_hotcrp_html(child_html_path)
    copyright_papers = _load_copyright_papers(review_assets)
    current_review = {
        "paper_ids": issue_paper_ids,
        "papers": {
            paper_id: {
                "baseline_checks": deepcopy(parent_review.get("papers", {}).get(paper_id, {}).get("checks", {})),
                "checks": {},
            }
            for paper_id in issue_paper_ids
        },
    }
    current_records = _build_review_records(track, current_review, xml_papers, html_papers, child_pdf_dir, copyright_papers, child_review_id)
    current_records_by_id = {record["id"]: record for record in current_records}

    child_review = {
        "id": child_review_id,
        "parent_id": parent_review_id,
        "label": f"Follow-up {child_index}",
        "created_at": _utc_now(),
        "sources": review_assets,
        "paper_ids": issue_paper_ids,
        "children": [],
        "papers": {},
    }
    for paper_id in issue_paper_ids:
        current_record = current_records_by_id.get(paper_id)
        if not current_record:
            continue
        parent_paper_state = parent_review.get("papers", {}).get(paper_id, {})
        child_review["papers"][paper_id] = {
            "completed": False,
            "baseline_checks": deepcopy(parent_paper_state.get("checks", {})),
            "checks": {
                check["id"]: {"status": check["status"], "evidence": check["evidence"]}
                for check in current_record["checks"]
            },
        }

    reviews = state.setdefault("reviews", {})
    reviews[child_review_id] = child_review
    parent_review.setdefault("children", []).append(child_review_id)
    state["active_review_id"] = child_review_id
    if not state.get("root_review_id"):
        state["root_review_id"] = parent_review_id
    save_track_state(track_id, state)
    return {"ok": True, "review_id": child_review_id}


def rerun_track_checks(track_id: str, review_id: Optional[str] = None) -> dict:
    track = find_track(track_id)
    if not track:
        raise KeyError(track_id)
    state = load_track_state(track_id)
    review = _review_or_default(state, review_id or None)
    if review.get("children"):
        raise ValueError("This review is locked because it already has a follow-up.")

    review_paths = _review_paths(review, track)
    zip_path = _resolve_review_source_path(review_paths["zip"], "zip")
    xml_path = _resolve_review_source_path(review_paths["xml"], "xml")
    html_path = _resolve_review_source_path(review_paths["html"], "html")
    pdf_dir = _resolve_review_source_path(review_paths["pdf_dir"], "pdf_dir")
    ensure_sample_pdfs(zip_path, pdf_dir)
    xml_papers = load_xml_papers(xml_path)
    html_papers, _ = load_hotcrp_html(html_path)
    copyright_papers = _load_copyright_papers(review_paths)
    fresh_review = {
        "paper_ids": review.get("paper_ids", []),
        "papers": {
            paper_id: {
                "baseline_checks": deepcopy(review.get("papers", {}).get(paper_id, {}).get("baseline_checks", {})),
                "checks": {},
            }
            for paper_id in review.get("paper_ids", [])
        },
    }
    refreshed_records = _build_review_records(track, fresh_review, xml_papers, html_papers, pdf_dir, copyright_papers, review.get("id", ""))
    refreshed_by_id = {record["id"]: record for record in refreshed_records}
    for paper_id in review.get("paper_ids", []):
        current_record = refreshed_by_id.get(paper_id)
        if not current_record:
            continue
        paper_state = review.setdefault("papers", {}).setdefault(paper_id, {})
        paper_state["checks"] = {
            check["id"]: {"status": check["status"], "evidence": check["evidence"]}
            for check in current_record["checks"]
        }
        paper_state.setdefault("baseline_checks", paper_state.get("baseline_checks", {}))
    save_track_state(track_id, state)
    return {"ok": True}


def update_review_files(track_id: str, review_id: str, files: dict) -> dict:
    if not any(key in files and getattr(files[key], "filename", "") for key in [*SOURCE_KEYS, *OPTIONAL_SOURCE_KEYS]):
        raise ValueError("Select at least one replacement ZIP, XML, HotCRP HTML, or e-Right file")
    track = find_track(track_id)
    if not track:
        raise KeyError(track_id)
    state = load_track_state(track_id)
    review = _review_or_default(state, review_id)
    deleted_review_ids = []
    if not review.get("parent_id"):
        for child_id in list(review.get("children", [])):
            deleted_review_ids.extend(_delete_review_subtree(state, child_id))
        if state.get("active_review_id") in deleted_review_ids:
            state["active_review_id"] = review["id"]
    current_sources = _review_paths(review, track)
    review["sources"] = _snapshot_review_sources(track_id, review["id"], current_sources, files)
    save_track_state(track_id, state)
    for deleted_review_id in deleted_review_ids:
        asset_dir = _review_asset_dir(track_id, deleted_review_id)
        if asset_dir.exists():
            shutil.rmtree(asset_dir, ignore_errors=True)
    rerun_track_checks(track_id, review["id"])
    return {"ok": True}


def remove_follow_up_review(track_id: str, review_id: str) -> dict:
    track = find_track(track_id)
    if not track:
        raise KeyError(track_id)
    state = load_track_state(track_id)
    review = state.get("reviews", {}).get(review_id)
    if not review:
        raise KeyError(review_id)
    if not review.get("parent_id"):
        raise ValueError("The initial review cannot be removed with this action.")

    deleted_review_ids = _delete_review_subtree(state, review_id)
    if state.get("active_review_id") in deleted_review_ids:
        state["active_review_id"] = review.get("parent_id") or state.get("root_review_id") or _first_review_id(state.get("reviews", {}))
    save_track_state(track_id, state)
    for deleted_review_id in deleted_review_ids:
        asset_dir = _review_asset_dir(track_id, deleted_review_id)
        if asset_dir.exists():
            shutil.rmtree(asset_dir, ignore_errors=True)
    return {"ok": True}


def _delete_review_subtree(state: dict, review_id: str) -> list[str]:
    reviews = state.get("reviews", {})
    review = reviews.get(review_id)
    if not review:
        return []
    deleted_review_ids = [review_id]
    for child_id in list(review.get("children", [])):
        deleted_review_ids.extend(_delete_review_subtree(state, child_id))
    parent_id = review.get("parent_id")
    if parent_id and parent_id in reviews:
        parent_children = reviews[parent_id].setdefault("children", [])
        reviews[parent_id]["children"] = [child_id for child_id in parent_children if child_id != review_id]
    reviews.pop(review_id, None)
    return deleted_review_ids


def remove_track(track_id: str) -> dict:
    tracks = load_tracks_config()
    # Keep a copy of the track configuration before rewriting tracks.json.
    # We need its file paths below to decide whether there is an app-managed
    # upload directory that can be safely removed from disk.
    track = find_track(track_id)
    remaining = [track for track in tracks if track.get("id") != track_id]
    if len(remaining) == len(tracks):
        raise KeyError(track_id)

    # Removing the track from the registry is the canonical "remove" action:
    # once this is saved, the track disappears from the UI and API summaries.
    save_tracks_config(remaining)

    # Review state is always owned by this app, so it is safe to delete for
    # both uploaded tracks and manually configured tracks.
    state_path = STATE_DIR / f"{track_id}.json"
    if state_path.exists():
        state_path.unlink()

    review_assets_path = REVIEW_ASSETS_DIR / track_id
    if review_assets_path.exists():
        shutil.rmtree(review_assets_path, ignore_errors=True)

    # Uploaded tracks are copied under track_data/<track-id>/. Delete that
    # entire directory only when the current track configuration proves it is
    # using exactly that app-managed layout. This avoids deleting arbitrary
    # user-provided folders for manually configured tracks.
    if track and _is_app_managed_track_dir(track, track_id):
        shutil.rmtree(TRACK_DATA_DIR / track_id, ignore_errors=True)
    return {"ok": True}


def _is_app_managed_track_dir(track: dict, track_id: str) -> bool:
    # add_track_upload() stores files like this:
    #
    #   track_data/<track-id>/inputs/<uploaded xml/html/zip>
    #   track_data/<track-id>/pdfs/<extracted PDFs>
    #
    # Only this exact structure is considered app-managed. If a track points
    # anywhere else—absolute paths, shared directories, or a custom pdf_dir—we
    # leave those files alone when the track is removed.
    expected_dir = (TRACK_DATA_DIR / track_id).resolve()
    expected_input_dir = expected_dir / "inputs"
    expected_pdf_dir = expected_dir / "pdfs"

    # Resolve paths before comparison so equivalent relative/absolute paths
    # are treated the same, and so prefix-like paths cannot pass by string
    # coincidence.
    managed_paths = [
        track_path(track, "xml").resolve(),
        track_path(track, "html").resolve(),
        track_path(track, "zip").resolve(),
        track_path(track, "pdf_dir").resolve(),
    ]
    managed = (
        managed_paths[0].parent == expected_input_dir
        and managed_paths[1].parent == expected_input_dir
        and managed_paths[2].parent == expected_input_dir
        and managed_paths[3] == expected_pdf_dir
    )
    copyright_path = optional_track_path(track, "copyright_html")
    if copyright_path:
        managed = managed and copyright_path.resolve().parent == expected_input_dir
    return managed


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        self._handle_read(head_only=False)

    def do_HEAD(self) -> None:
        self._handle_read(head_only=True)

    def _handle_read(self, head_only: bool = False) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in {"/", "/index.html"}:
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8", head_only=head_only)
        elif path == "/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8", head_only=head_only)
        elif path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8", head_only=head_only)
        elif path == "/app-icon.svg":
            self._serve_file(STATIC_DIR / "app-icon.svg", "image/svg+xml", head_only=head_only)
        elif path == "/api/checklist-items":
            self._serve_json({"items": CHECKLIST_ITEMS})
        elif path == "/api/tracks":
            self._serve_json(load_tracks_summary())
        elif path.startswith("/api/tracks/") and path.endswith("/pdf"):
            self.send_error(404)
        elif path.startswith("/api/tracks/") and "/pdf/" in path:
            self._serve_track_pdf(head_only=head_only)
        elif path.startswith("/api/tracks/"):
            track_id = unquote(path.removeprefix("/api/tracks/")).strip("/")
            try:
                review_id = query.get("review_id", [None])[0]
                self._serve_json(load_track_data_for_review(track_id, review_id))
            except KeyError:
                self.send_error(404)
        elif path == "/api/submissions":
            self._serve_json(load_track_data(default_track_id()))
        elif path.startswith("/pdf/"):
            filename = Path(unquote(path.removeprefix("/pdf/"))).name
            track = find_track(default_track_id())
            pdf_dir = track_path(track, "pdf_dir") if track else ROOT
            self._serve_file(pdf_dir / filename, mimetypes.guess_type(filename)[0] or "application/pdf", head_only=head_only)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/api/tracks":
            try:
                if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                    fields, files = self._read_multipart()
                    self._serve_json(add_track_upload(fields, files))
                else:
                    payload = self._read_json()
                    self._serve_json(add_track(payload))
            except ValueError as exc:
                self.send_error(400, str(exc))
        elif path.startswith("/api/tracks/") and path.endswith("/reviews"):
            track_id = unquote(path.removeprefix("/api/tracks/").removesuffix("/reviews").strip("/"))
            if not find_track(track_id):
                self.send_error(404)
                return
            try:
                payload = self._read_json()
                self._serve_json(save_paper_review(track_id, payload))
            except ValueError as exc:
                self.send_error(400, str(exc))
        elif path.startswith("/api/tracks/") and "/reviews/" in path and path.endswith("/files"):
            rest = path.removeprefix("/api/tracks/")
            track_id, _, review_part = rest.partition("/reviews/")
            review_id = unquote(review_part.removesuffix("/files").strip("/"))
            if not find_track(unquote(track_id)):
                self.send_error(404)
                return
            try:
                fields, files = self._read_multipart()
                self._serve_json(update_review_files(unquote(track_id), review_id, files))
            except KeyError:
                self.send_error(404)
            except ValueError as exc:
                self.send_error(400, str(exc))
            except Exception as exc:
                self.send_error(500, str(exc))
        elif path.startswith("/api/tracks/") and path.endswith("/files"):
            track_id = unquote(path.removeprefix("/api/tracks/").removesuffix("/files").strip("/"))
            try:
                fields, files = self._read_multipart()
                self._serve_json(update_track_files(track_id, files))
            except KeyError:
                self.send_error(404)
            except ValueError as exc:
                self.send_error(400, str(exc))
        elif path.startswith("/api/tracks/") and path.endswith("/rerun-checks"):
            track_id = unquote(path.removeprefix("/api/tracks/").removesuffix("/rerun-checks").strip("/"))
            if not find_track(track_id):
                self.send_error(404)
                return
            try:
                payload = self._read_json() if int(self.headers.get("Content-Length", "0")) else {}
            except json.JSONDecodeError:
                payload = {}
            try:
                self._serve_json(rerun_track_checks(track_id, payload.get("review_id")))
            except ValueError as exc:
                self.send_error(400, str(exc))
        elif path.startswith("/api/tracks/") and path.endswith("/follow-ups"):
            track_id = unquote(path.removeprefix("/api/tracks/").removesuffix("/follow-ups").strip("/"))
            if not find_track(track_id):
                self.send_error(404)
                return
            try:
                if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
                    fields, files = self._read_multipart()
                    self._serve_json(create_follow_up_review(track_id, fields, files))
                else:
                    payload = self._read_json()
                    self._serve_json(create_follow_up_review(track_id, payload))
            except KeyError:
                self.send_error(404)
            except ValueError as exc:
                self.send_error(400, str(exc))
            except Exception as exc:
                self.send_error(500, str(exc))
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/api/tracks/") and "/reviews/" in path:
            rest = path.removeprefix("/api/tracks/")
            track_id, _, review_part = rest.partition("/reviews/")
            review_id = unquote(Path(review_part).name)
            if not find_track(unquote(track_id)):
                self.send_error(404)
                return
            try:
                self._serve_json(remove_follow_up_review(unquote(track_id), review_id))
            except KeyError:
                self.send_error(404)
            except ValueError as exc:
                self.send_error(400, str(exc))
        elif path.startswith("/api/tracks/"):
            track_id = unquote(path.removeprefix("/api/tracks/")).strip("/")
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

    def _serve_track_pdf(self, head_only: bool = False) -> None:
        prefix = "/api/tracks/"
        parsed = urlsplit(self.path)
        rest = parsed.path.removeprefix(prefix)
        track_id, _, filename = rest.partition("/pdf/")
        track = find_track(unquote(track_id))
        if not track:
            self.send_error(404)
            return
        filename = Path(unquote(filename)).name
        review_id = parse_qs(parsed.query).get("review_id", [None])[0]
        pdf_dir = track_path(track, "pdf_dir")
        if review_id:
            state = load_track_state(track["id"])
            try:
                review = _review_or_default(state, review_id)
                review_paths = _review_paths(review, track)
                pdf_dir = _resolve_review_source_path(review_paths["pdf_dir"], "pdf_dir")
            except KeyError:
                self.send_error(404)
                return
        self._serve_file(pdf_dir / filename, mimetypes.guess_type(filename)[0] or "application/pdf", head_only=head_only)

    def _serve_json(self, data: dict) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_file(self, path: Path, content_type: str, head_only: bool = False) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)


def load_track_data_for_review(track_id: str, review_id: Optional[str] = None) -> dict:
    track = find_track(track_id)
    if not track:
        raise KeyError(track_id)

    state = load_track_state(track_id)
    track_zip = track_path(track, "zip")
    track_pdf_dir = track_path(track, "pdf_dir")
    ensure_sample_pdfs(track_zip, track_pdf_dir)
    root_xml_papers = load_xml_papers(track_path(track, "xml"))
    root_html_papers, _ = load_hotcrp_html(track_path(track, "html"))
    root_copyright_papers = _load_copyright_papers(_review_snapshot(track))
    checklist_ids = parse_checklist_ids(track.get("checklist_ids"))
    state = _ensure_root_review(state, track, root_xml_papers, root_html_papers, track_pdf_dir, root_copyright_papers)
    active_review = _review_or_default(state, review_id or None)
    if active_review.get("id") and active_review.get("id") != state.get("active_review_id"):
        state["active_review_id"] = active_review["id"]
        save_track_state(track_id, state)
    review_paths = _review_paths(active_review, track)
    zip_path = _resolve_review_source_path(review_paths["zip"], "zip")
    xml_path = _resolve_review_source_path(review_paths["xml"], "xml")
    html_path = _resolve_review_source_path(review_paths["html"], "html")
    pdf_dir = _resolve_review_source_path(review_paths["pdf_dir"], "pdf_dir")
    ensure_sample_pdfs(zip_path, pdf_dir)
    xml_papers = load_xml_papers(xml_path)
    html_papers, global_messages = load_hotcrp_html(html_path)
    copyright_papers = _load_copyright_papers(review_paths)
    records = _build_review_records(track, active_review, xml_papers, html_papers, pdf_dir, copyright_papers, active_review.get("id", ""))
    if not active_review.get("paper_ids"):
        active_review["paper_ids"] = [record["id"] for record in records]
        for record in records:
            paper_state = active_review.setdefault("papers", {}).setdefault(record["id"], {"completed": False})
            paper_state.setdefault("checks", {
                check["id"]: {"status": check["status"], "evidence": check["evidence"]}
                for check in record["checks"]
            })
        save_track_state(track_id, state)
    chain = _review_chain(state)
    active_review_counts = _review_counts(active_review)
    review_sources = _review_source_names(active_review)
    return {
        "track": {
            "id": track["id"],
            "name": track["name"],
            "checklist_ids": checklist_ids,
        },
        "review": {
            "id": active_review["id"],
            "label": active_review.get("label", "Review"),
            "parent_id": active_review.get("parent_id", ""),
            "depth": next((review.get("depth", 0) for review in chain if review.get("id") == active_review["id"]), 0),
            "sources": review_sources,
            **active_review_counts,
        },
        "reviews": [
            {
                "id": review["id"],
                "label": review.get("label", review["id"]),
                "parent_id": review.get("parent_id", ""),
                "depth": review.get("depth", 0),
                "sources": _review_source_names(review),
                **_review_counts(review),
            }
            for review in chain
        ],
        "submissions": records,
        "global_messages": global_messages,
        "sources": {
            "xml": Path(review_paths["xml"]).name,
            "hotcrp_html": Path(review_paths["html"]).name,
            "zip": Path(review_paths["zip"]).name,
            "pdf_dir": Path(review_paths["pdf_dir"]).name,
            "copyright_html": Path(review_paths["copyright_html"]).name if review_paths.get("copyright_html") else "",
        },
    }


def main() -> None:
    host = os.environ.get("PCB_HOST", "127.0.0.1")
    port = int(os.environ.get("PCB_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Proceedings Chair Buddy running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
