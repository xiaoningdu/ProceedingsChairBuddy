from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .parsers import HtmlPaper, XmlPaper, extract_pdf_text, pdf_page_count


CHECKLIST_ITEMS = [
    {"id": "title_pdf_vs_xml", "label": "PDF title matches metadata", "source": "PDF + XML"},
    {"id": "authors_pdf_vs_xml", "label": "PDF author list matches metadata", "source": "PDF + XML"},
    {"id": "affiliations_pdf_vs_xml", "label": "PDF affiliations match metadata", "source": "PDF + XML"},
    {"id": "emails_in_pdf", "label": "All author emails in metadata appear in the PDF", "source": "PDF + XML"},
    {"id": "orcid", "label": "All authors have ORCID in metadata", "source": "XML"},
    {"id": "hotcrp_acm_keywords", "label": "ACM keywords added on HotCRP", "source": "HotCRP ACM HTML"},
    {"id": "hotcrp_ccs", "label": "ACM Computing Classification added on HotCRP", "source": "HotCRP ACM HTML"},
    {"id": "hotcrp_references", "label": "References added on HotCRP", "source": "HotCRP ACM HTML"},
    {"id": "source_files", "label": "Source files submitted", "source": "HotCRP ACM HTML"},
    {"id": "proceeding_messages", "label": "Other issues", "source": "HotCRP ACM HTML"},
    {"id": "pdf_copyright_isbn", "label": "PDF copyright information includes ISBN", "source": "PDF"},
    {"id": "page_count", "label": "Page count available and locally consistent", "source": "HotCRP ACM HTML + PDF"},
    {"id": "pdf_exists", "label": "Paper PDF provided", "source": "ZIP"},
    {"id": "pdf_page_numbers", "label": "PDF has no visible page numbers", "source": "PDF"},
    {"id": "latest_acm_template", "label": "Latest ACM template used", "source": "PDF + HotCRP"},
    {"id": "authors_stacked", "label": "Authors stacked individually", "source": "PDF"},
    {"id": "last_page_balanced", "label": "Last page balanced", "source": "PDF"},
    {"id": "track_page_limit", "label": "Track-specific page limit followed", "source": "HotCRP + rules"},
]

CHECKLIST_IDS = [item["id"] for item in CHECKLIST_ITEMS]


def build_submission_records(
    xml_papers: Dict[str, XmlPaper],
    html_papers: Dict[str, HtmlPaper],
    pdf_dir: Path,
    enabled_check_ids: Optional[List[str]] = None,
) -> List[Dict]:
    enabled_check_id_set = set(enabled_check_ids) if enabled_check_ids is not None else None
    ids = sorted(set(xml_papers) | set(html_papers) | set(_pdf_ids(pdf_dir)), key=lambda pid: int(pid))
    records: List[Dict] = []
    for paper_id in ids:
        xml_paper = xml_papers.get(paper_id)
        html_paper = html_papers.get(paper_id)
        pdf_path = _pdf_path(pdf_dir, paper_id)
        pdf_pages = pdf_page_count(pdf_path) if pdf_path.exists() else None
        pdf_text, pdf_text_error = extract_pdf_text(pdf_path)
        checks = _build_checks(xml_paper, html_paper, pdf_path, pdf_pages, pdf_text, pdf_text_error)
        if enabled_check_id_set is not None:
            checks = [check for check in checks if check["id"] in enabled_check_id_set]
        status_counts = {
            "pass": sum(1 for check in checks if check["status"] == "pass"),
            "issue": sum(1 for check in checks if check["status"] == "issue"),
            "manual": sum(1 for check in checks if check["status"] == "manual"),
            "unavailable": sum(1 for check in checks if check["status"] == "unavailable"),
        }
        records.append(
            {
                "id": paper_id,
                "title": _first_nonempty(
                    html_paper.title if html_paper else "",
                    xml_paper.title if xml_paper else "",
                    f"Paper {paper_id}",
                ),
                "xml": asdict(xml_paper) if xml_paper else None,
                "hotcrp": asdict(html_paper) if html_paper else None,
                "pdf": {
                    "filename": pdf_path.name if pdf_path.exists() else "",
                    "url": f"/pdf/{pdf_path.name}" if pdf_path.exists() else "",
                    "page_count_estimate": pdf_pages,
                    "text_extraction": "available" if pdf_text else pdf_text_error,
                },
                "checks": checks,
                "status_counts": status_counts,
            }
        )
    return records


def _build_checks(
    xml_paper: Optional[XmlPaper],
    html_paper: Optional[HtmlPaper],
    pdf_path: Path,
    pdf_pages: Optional[int],
    pdf_text: str,
    pdf_text_error: str,
) -> List[Dict]:
    messages = html_paper.messages if html_paper else []
    message_text = " | ".join(message["text"] for message in messages).lower()
    return [
        _title_check(xml_paper, pdf_text, pdf_text_error),
        _authors_check(xml_paper, pdf_text, pdf_text_error),
        _affiliations_check(xml_paper, pdf_text, pdf_text_error),
        _emails_check(xml_paper, pdf_text, pdf_text_error),
        _check_orcid(xml_paper),
        _missing_warning_check(
            "hotcrp_acm_keywords",
            "ACM keywords added on HotCRP",
            "missing acm keywords" in message_text or "acm computing classification, acm keywords, and references" in message_text,
            messages,
        ),
        _missing_warning_check(
            "hotcrp_ccs",
            "ACM Computing Classification added on HotCRP",
            "missing acm computing classification" in message_text,
            messages,
        ),
        _missing_warning_check(
            "hotcrp_references",
            "References added on HotCRP",
            "missing references" in message_text or "acm computing classification, acm keywords, and references" in message_text,
            messages,
        ),
        _source_files_check(html_paper),
        _proceeding_messages_check(messages),
        _copyright_isbn_check(pdf_text, pdf_text_error),
        _page_count_check(html_paper, pdf_pages),
        _pdf_exists_check(pdf_path),
        _page_numbers_check(pdf_text, pdf_text_error),
        _check("latest_acm_template", "Latest ACM template used", "manual", "Chair review required. Select pass if acceptable, or issue if a correction is needed.", "PDF + HotCRP"),
        _check(
            "authors_stacked",
            "Authors stacked individually",
            "manual",
            "Chair review required. Select pass if acceptable, or issue if a correction is needed.",
            "PDF",
        ),
        _check(
            "last_page_balanced",
            "Last page balanced",
            "manual",
            "Chair review required. Select pass if acceptable, or issue if a correction is needed.",
            "PDF",
        ),
        _check(
            "track_page_limit",
            "Track-specific page limit followed",
            "manual",
            "Chair review required. Select pass if acceptable, or issue if a correction is needed.",
            "HotCRP + rules",
        ),
    ]


def _check_orcid(xml_paper: Optional[XmlPaper]) -> Dict:
    if not xml_paper:
        return _check("orcid", "All authors have ORCID in metadata", "unavailable", "No metadata found.", "XML")
    missing = [
        _author_position(author, index)
        for index, author in enumerate(xml_paper.authors, start=1)
        if not author.orcid
    ]
    if missing:
        return _check("orcid", "All authors have ORCID in metadata", "issue", "Missing ORCID for metadata author positions: " + ", ".join(missing), "XML")
    return _check("orcid", "All authors have ORCID in metadata", "pass", "Every metadata author has an ORCID value.", "XML")


def _title_check(xml_paper: Optional[XmlPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF title matches metadata"
    if not xml_paper:
        return _check("title_pdf_vs_xml", label, "unavailable", "No metadata found.", "PDF + XML")
    if not pdf_text:
        return _check("title_pdf_vs_xml", label, "manual", "PDF text extraction is unavailable.", "PDF + XML")
    if _words_in_order(xml_paper.title, pdf_text):
        return _check("title_pdf_vs_xml", label, "pass", "The metadata title was found in extracted PDF text.", "PDF + XML")
    return _check("title_pdf_vs_xml", label, "issue", "The metadata title was not found in extracted PDF text.", "PDF + XML")


def _authors_check(xml_paper: Optional[XmlPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF author list matches metadata"
    if not xml_paper:
        return _check("authors_pdf_vs_xml", label, "unavailable", "No metadata found.", "PDF + XML")
    if not pdf_text:
        return _check("authors_pdf_vs_xml", label, "manual", "PDF text extraction is unavailable.", "PDF + XML")
    missing = [
        _author_position(author, index)
        for index, author in enumerate(xml_paper.authors, start=1)
        if not _words_in_order(author.name, pdf_text)
    ]
    if missing:
        return _check("authors_pdf_vs_xml", label, "issue", "Missing metadata author positions from extracted PDF text: " + ", ".join(missing), "PDF + XML")
    return _check("authors_pdf_vs_xml", label, "pass", "All metadata author names were found in extracted PDF text.", "PDF + XML")


def _affiliations_check(xml_paper: Optional[XmlPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF affiliations match metadata"
    if not xml_paper:
        return _check("affiliations_pdf_vs_xml", label, "unavailable", "No metadata found.", "PDF + XML")
    if not pdf_text:
        return _check("affiliations_pdf_vs_xml", label, "manual", "PDF text extraction is unavailable.", "PDF + XML")
    missing = []
    for index, author in enumerate(xml_paper.authors, start=1):
        if author.affiliation and not _words_in_order(author.affiliation, pdf_text):
            missing.append(_author_position(author, index))
    if missing:
        return _check("affiliations_pdf_vs_xml", label, "issue", "Missing metadata affiliation positions from extracted PDF text: " + ", ".join(missing), "PDF + XML")
    return _check("affiliations_pdf_vs_xml", label, "pass", "All metadata affiliations were found in extracted PDF text.", "PDF + XML")


def _emails_check(xml_paper: Optional[XmlPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "All author emails in metadata appear in the PDF"
    if not xml_paper:
        return _check("emails_in_pdf", label, "unavailable", "No metadata found.", "PDF + XML")
    if not pdf_text:
        return _check("emails_in_pdf", label, "manual", "PDF text extraction is unavailable.", "PDF + XML")
    normalized_pdf_text = pdf_text.lower()
    missing = [
        _author_position(author, index)
        for index, author in enumerate(xml_paper.authors, start=1)
        if author.email and author.email.lower() not in normalized_pdf_text
    ]
    if missing:
        return _check("emails_in_pdf", label, "issue", "Missing email for metadata author positions from extracted PDF text: " + ", ".join(missing), "PDF + XML")
    return _check("emails_in_pdf", label, "pass", "All metadata author emails were found in extracted PDF text.", "PDF + XML")


def _page_numbers_check(pdf_text: str, pdf_text_error: str) -> Dict:
    if not pdf_text:
        return _check("pdf_page_numbers", "PDF has no visible page numbers", "manual", "PDF text extraction is unavailable.", "PDF")
    evidence = _detect_page_number_evidence(pdf_text)
    if evidence:
        return _check("pdf_page_numbers", "PDF has no visible page numbers", "issue", evidence, "PDF")
    return _check("pdf_page_numbers", "PDF has no visible page numbers", "pass", "No standalone page-number-like text found near page boundaries.", "PDF")


def _copyright_isbn_check(pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF copyright information includes ISBN"
    if not pdf_text:
        return _check("pdf_copyright_isbn", label, "manual", "PDF text extraction is unavailable.", "PDF")
    has_copyright = bool(re.search(r"(?i)(copyright|©|creative commons|licensed under)", pdf_text))
    has_isbn = bool(re.search(r"(?i)\bISBN\b", pdf_text))
    if has_copyright and has_isbn:
        return _check("pdf_copyright_isbn", label, "pass", "Copyright/license text and an ISBN marker were found in extracted PDF text.", "PDF")
    missing = []
    if not has_copyright:
        missing.append("copyright/license text")
    if not has_isbn:
        missing.append("ISBN marker")
    return _check("pdf_copyright_isbn", label, "issue", "Missing from extracted PDF text: " + ", ".join(missing), "PDF")


def _missing_warning_check(check_id: str, label: str, is_missing: bool, messages: List[Dict[str, str]]) -> Dict:
    if is_missing:
        evidence = "HotCRP reported this metadata is missing."
        return _check(check_id, label, "issue", evidence, "HotCRP ACM HTML")
    return _check(check_id, label, "pass", "No matching missing-metadata warning found in the HotCRP ACM HTML.", "HotCRP ACM HTML")


def _source_files_check(html_paper: Optional[HtmlPaper]) -> Dict:
    if not html_paper:
        return _check("source_files", "Source files submitted", "unavailable", "No HotCRP ACM row found.", "HotCRP ACM HTML")
    if html_paper.source_files:
        count = len(html_paper.source_files)
        suffix = "" if count == 1 else "s"
        return _check("source_files", "Source files submitted", "pass", f"{count} source-file archive{suffix} found.", "HotCRP ACM HTML")
    return _check("source_files", "Source files submitted", "issue", "No source-file link found in the HotCRP ACM row.", "HotCRP ACM HTML")


def _proceeding_messages_check(messages: List[Dict[str, str]]) -> Dict:
    errors = [message["text"] for message in messages if message["severity"] == "error"]
    warnings = [message["text"] for message in messages if message["severity"] == "warning"]
    if errors:
        return _check("proceeding_messages", "Other issues", "issue", "; ".join(errors), "HotCRP ACM HTML")
    if warnings:
        return _check("proceeding_messages", "Other issues", "issue", "; ".join(warnings), "HotCRP ACM HTML")
    return _check("proceeding_messages", "Other issues", "pass", "No per-paper proceeding messages found.", "HotCRP ACM HTML")


def _page_count_check(html_paper: Optional[HtmlPaper], pdf_pages: Optional[int]) -> Dict:
    if html_paper and html_paper.page_count is not None:
        evidence = f"HotCRP page count: {html_paper.page_count}"
        if pdf_pages is not None:
            evidence += f"; local PDF estimate: {pdf_pages}"
            status = "pass" if html_paper.page_count == pdf_pages else "issue"
            if status == "issue":
                evidence += " (counts differ)"
            return _check("page_count", "Page count available and locally consistent", status, evidence, "HotCRP ACM HTML + PDF")
        return _check("page_count", "Page count available", "pass", evidence, "HotCRP ACM HTML")
    if pdf_pages is not None:
        return _check("page_count", "Page count available", "pass", f"Local PDF estimate: {pdf_pages}", "PDF")
    return _check("page_count", "Page count available", "unavailable", "No page count found.", "HotCRP ACM HTML + PDF")


def _pdf_exists_check(pdf_path: Path) -> Dict:
    if pdf_path.exists():
        return _check("pdf_exists", "Paper PDF provided", "pass", "A local paper PDF was found.", "ZIP")
    return _check("pdf_exists", "Paper PDF provided", "issue", "No local PDF found for this paper.", "ZIP")


def _check(check_id: str, label: str, status: str, evidence: str, source: str) -> Dict:
    return {"id": check_id, "label": label, "status": status, "evidence": evidence, "source": source}


def _words_in_order(needle: str, haystack: str) -> bool:
    needle_words = _meaningful_words(needle)
    haystack_words = _meaningful_words(haystack)
    if not needle_words:
        return False
    position = 0
    for word in haystack_words:
        if word == needle_words[position]:
            position += 1
            if position == len(needle_words):
                return True
    return False


def _meaningful_words(value: str) -> List[str]:
    return [
        word
        for word in re.findall(r"[A-Za-z0-9]+", value.lower())
        if not word.isdigit()
    ]


def _author_position(author, fallback_index: int) -> str:
    try:
        index = int(author.sequence_no)
    except (TypeError, ValueError):
        index = fallback_index
    return _ordinal(index)


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _detect_page_number_evidence(pdf_text: str) -> str:
    pages = pdf_text.split("\f")
    total_pages = len([page for page in pages if page.strip()])
    for index, page in enumerate(pages, start=1):
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        boundary_lines = lines[:8] + lines[-8:]
        for line in boundary_lines:
            if re.fullmatch(r"\d{1,3}", line):
                number = int(line)
                if number == index or number <= total_pages + 2:
                    return f"Detected standalone number '{line}' near the top or bottom of extracted page {index}."
    return ""


def _pdf_ids(pdf_dir: Path) -> List[str]:
    ids = []
    for path in pdf_dir.glob("*.pdf"):
        match = re.search(r"(?:paper|final)(\d+)\.pdf$", path.name)
        if match:
            ids.append(match.group(1))
    return ids


def _pdf_path(pdf_dir: Path, paper_id: str) -> Path:
    for pattern in [f"*final{paper_id}.pdf", f"*paper{paper_id}.pdf", f"*{paper_id}.pdf"]:
        matches = sorted(pdf_dir.glob(pattern))
        if matches:
            return matches[0]
    return pdf_dir / f"paper{paper_id}.pdf"


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""
