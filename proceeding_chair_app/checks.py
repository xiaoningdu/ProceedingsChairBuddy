from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .parsers import CopyrightPaper, HtmlPaper, XmlPaper, extract_pdf_text, pdf_page_count


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
    {"id": "copyright_doi_matches_pdf", "label": "PDF DOI matches e-Right", "source": "PDF + e-Right"},
    {"id": "copyright_isbn_matches_pdf", "label": "PDF ISBN matches e-Right", "source": "PDF + e-Right"},
    {"id": "copyright_type_matches_pdf", "label": "PDF copyright type matches e-Right", "source": "PDF + e-Right"},
    {"id": "pdf_exists", "label": "Paper PDF provided", "source": "ZIP"},
    {"id": "pdf_page_numbers", "label": "PDF has no visible page numbers", "source": "PDF"},
    {"id": "latest_acm_template", "label": "Latest ACM template used", "source": "PDF + HotCRP"},
    {"id": "authors_stacked", "label": "Authors stacked individually", "source": "PDF"},
    {"id": "last_page_balanced", "label": "Last page balanced", "source": "PDF"},
    {"id": "track_page_limit", "label": "Track-specific page limit followed", "source": "HotCRP ACM HTML + rules"},
]

CHECKLIST_IDS = [item["id"] for item in CHECKLIST_ITEMS]


def build_submission_records(
    xml_papers: Dict[str, XmlPaper],
    html_papers: Dict[str, HtmlPaper],
    pdf_dir: Path,
    copyright_papers: Optional[Dict[str, CopyrightPaper]] = None,
    enabled_check_ids: Optional[List[str]] = None,
) -> List[Dict]:
    if enabled_check_ids is None and isinstance(copyright_papers, list):
        enabled_check_ids = copyright_papers
        copyright_papers = {}
    enabled_check_id_set = set(enabled_check_ids) if enabled_check_ids is not None else None
    ids = sorted(set(xml_papers) | set(html_papers) | set(_pdf_ids(pdf_dir)), key=lambda pid: int(pid))
    records: List[Dict] = []
    for paper_id in ids:
        xml_paper = xml_papers.get(paper_id)
        html_paper = html_papers.get(paper_id)
        copyright_paper = _copyright_for_paper(paper_id, xml_paper, copyright_papers or {})
        pdf_path = _pdf_path(pdf_dir, paper_id)
        pdf_pages = pdf_page_count(pdf_path) if pdf_path.exists() else None
        pdf_text, pdf_text_error = extract_pdf_text(pdf_path)
        checks = _build_checks(xml_paper, html_paper, copyright_paper, pdf_path, pdf_pages, pdf_text, pdf_text_error)
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
                "copyright": asdict(copyright_paper) if copyright_paper else None,
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
    copyright_paper: Optional[CopyrightPaper],
    pdf_path: Path,
    pdf_pages: Optional[int],
    pdf_text: str,
    pdf_text_error: str,
) -> List[Dict]:
    messages = html_paper.messages if html_paper else []
    checks = [
        _title_check(xml_paper, pdf_text, pdf_text_error),
        _authors_check(xml_paper, pdf_text, pdf_text_error),
        _affiliations_check(xml_paper, pdf_text, pdf_text_error),
        _emails_check(xml_paper, pdf_text, pdf_text_error),
        _check_orcid(xml_paper),
        _missing_warning_check(
            "hotcrp_acm_keywords",
            "ACM keywords added on HotCRP",
            "acm keywords",
            messages,
        ),
        _missing_warning_check(
            "hotcrp_ccs",
            "ACM Computing Classification added on HotCRP",
            "acm computing classification",
            messages,
        ),
        _missing_warning_check(
            "hotcrp_references",
            "References added on HotCRP",
            "references",
            messages,
        ),
        _source_files_check(html_paper),
        _proceeding_messages_check(messages),
        _copyright_doi_match_check(copyright_paper, pdf_text, pdf_text_error),
        _copyright_isbn_match_check(copyright_paper, pdf_text, pdf_text_error),
        _copyright_type_match_check(copyright_paper, pdf_text, pdf_text_error),
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
    _add_source_notes(checks, xml_paper, html_paper, copyright_paper, pdf_path, pdf_pages)
    return checks


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
    pdf_title = _pdf_title_candidate(xml_paper, pdf_text)
    if not pdf_title:
        return _check("title_pdf_vs_xml", label, "manual", "Could not identify the PDF title near the top of the extracted PDF text.", "PDF + XML")
    if _title_words_match(xml_paper.title, pdf_title):
        return _check("title_pdf_vs_xml", label, "pass", "The metadata title matches the title found near the top of the extracted PDF text.", "PDF + XML")
    return _check(
        "title_pdf_vs_xml",
        label,
        "issue",
        f"PDF title appears to be '{pdf_title}', but XML title is '{xml_paper.title}'.",
        "PDF + XML",
    )


def _authors_check(xml_paper: Optional[XmlPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF author list matches metadata"
    if not xml_paper:
        return _check("authors_pdf_vs_xml", label, "unavailable", "No metadata found.", "PDF + XML")
    if not pdf_text:
        return _check("authors_pdf_vs_xml", label, "manual", "PDF text extraction is unavailable.", "PDF + XML")
    author_region = _pdf_author_region(xml_paper, pdf_text)
    if not author_region:
        return _check("authors_pdf_vs_xml", label, "manual", "Could not identify the PDF author block near the top of the extracted PDF text.", "PDF + XML")
    missing = [
        _author_position(author, index)
        for index, author in enumerate(xml_paper.authors, start=1)
        if not _author_name_in_pdf_author_region(author.name, author_region)
    ]
    if missing:
        return _check("authors_pdf_vs_xml", label, "issue", "Authors whose names in PDF don't match those in HotCRP metadata: " + ", ".join(missing), "PDF + XML")
    return _check("authors_pdf_vs_xml", label, "pass", "All metadata author names match those found in extracted PDF text.", "PDF + XML")


def _affiliations_check(xml_paper: Optional[XmlPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF affiliations match metadata"
    if not xml_paper:
        return _check("affiliations_pdf_vs_xml", label, "unavailable", "No metadata found.", "PDF + XML")
    if not pdf_text:
        return _check("affiliations_pdf_vs_xml", label, "manual", "PDF text extraction is unavailable.", "PDF + XML")
    author_affiliations = _pdf_author_affiliation_segments(xml_paper, pdf_text)
    if not author_affiliations:
        return _check("affiliations_pdf_vs_xml", label, "manual", "Could not align PDF affiliations with individual authors near the top of the extracted PDF text.", "PDF + XML")
    missing = []
    unaligned = []
    for index, author in enumerate(xml_paper.authors, start=1):
        if not author.affiliation:
            continue
        pdf_affiliation = author_affiliations.get(index - 1, "")
        if not pdf_affiliation:
            unaligned.append(_author_position(author, index))
        elif not _words_in_order(author.affiliation, pdf_affiliation):
            missing.append(_author_position(author, index))
    if missing:
        detail = "Authors whose affiliations in PDF don't match those in HotCRP metadata: " + ", ".join(missing)
        if unaligned:
            detail += ". Could not align PDF affiliations for metadata author positions: " + ", ".join(unaligned)
        return _check("affiliations_pdf_vs_xml", label, "issue", detail, "PDF + XML")
    if unaligned:
        return _check("affiliations_pdf_vs_xml", label, "manual", "Could not align PDF affiliations for metadata author positions: " + ", ".join(unaligned), "PDF + XML")
    return _check("affiliations_pdf_vs_xml", label, "pass", "All metadata affiliations match those found in extracted PDF text.", "PDF + XML")


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
        return _check("emails_in_pdf", label, "issue", "Authors whose emails in PDF don't match those in HotCRP metadata: " + ", ".join(missing), "PDF + XML")
    return _check("emails_in_pdf", label, "pass", "All metadata author emails match those found in extracted PDF text.", "PDF + XML")


def _page_numbers_check(pdf_text: str, pdf_text_error: str) -> Dict:
    if not pdf_text:
        return _check("pdf_page_numbers", "PDF has no visible page numbers", "manual", "PDF text extraction is unavailable.", "PDF")
    evidence = _detect_page_number_evidence(pdf_text)
    if evidence:
        return _check(
            "pdf_page_numbers",
            "PDF has no visible page numbers",
            "issue",
            "Page numbers are identified. You have to disable the page numbers in the camera ready version.",
            "PDF",
        )
    return _check("pdf_page_numbers", "PDF has no visible page numbers", "pass", "No standalone page-number-like text found near page boundaries.", "PDF")


def _copyright_doi_match_check(copyright_paper: Optional[CopyrightPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF DOI matches e-Right"
    if not copyright_paper:
        return _check("copyright_doi_matches_pdf", label, "unavailable", "No matching e-Right row found for this paper.", "PDF + e-Right")
    expected = _first_nonempty(copyright_paper.rights_doi, copyright_paper.doi)
    if not expected:
        return _check("copyright_doi_matches_pdf", label, "unavailable", "The e-Right row does not include a DOI.", "PDF + e-Right")
    if not pdf_text:
        return _check("copyright_doi_matches_pdf", label, "manual", "PDF text extraction is unavailable. Compare the e-Right DOI manually.", "PDF + e-Right")
    if _identifier_in_text(expected, pdf_text):
        return _check("copyright_doi_matches_pdf", label, "pass", "The e-Right DOI was found in the extracted PDF text.", "PDF + e-Right")
    return _check("copyright_doi_matches_pdf", label, "issue", "The e-Right DOI was not found in the extracted PDF text.", "PDF + e-Right")


def _copyright_isbn_match_check(copyright_paper: Optional[CopyrightPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF ISBN matches e-Right"
    if not copyright_paper:
        return _check("copyright_isbn_matches_pdf", label, "unavailable", "No matching e-Right row found for this paper.", "PDF + e-Right")
    if not copyright_paper.has_rights_detail:
        return _check("copyright_isbn_matches_pdf", label, "unavailable", "The saved e-Right row was not expanded with rights details.", "PDF + e-Right")
    if not copyright_paper.isbn:
        return _check("copyright_isbn_matches_pdf", label, "unavailable", "The e-Right rights details do not include an ISBN.", "PDF + e-Right")
    if not pdf_text:
        return _check("copyright_isbn_matches_pdf", label, "manual", "PDF text extraction is unavailable. Compare the e-Right ISBN manually.", "PDF + e-Right")
    if _identifier_in_text(copyright_paper.isbn, pdf_text):
        return _check("copyright_isbn_matches_pdf", label, "pass", "The e-Right ISBN was found in the extracted PDF text.", "PDF + e-Right")
    return _check("copyright_isbn_matches_pdf", label, "issue", "The e-Right ISBN was not found in the extracted PDF text.", "PDF + e-Right")


def _copyright_type_match_check(copyright_paper: Optional[CopyrightPaper], pdf_text: str, pdf_text_error: str) -> Dict:
    label = "PDF copyright type matches e-Right"
    if not copyright_paper:
        return _check("copyright_type_matches_pdf", label, "unavailable", "No matching e-Right row found for this paper.", "PDF + e-Right")
    if not copyright_paper.has_rights_detail:
        return _check("copyright_type_matches_pdf", label, "unavailable", "The saved e-Right row was not expanded with rights details.", "PDF + e-Right")
    expected = copyright_paper.copyright_type
    if not expected:
        return _check("copyright_type_matches_pdf", label, "unavailable", "The e-Right rights details do not include a copyright type.", "PDF + e-Right")
    if not pdf_text:
        return _check("copyright_type_matches_pdf", label, "manual", "PDF text extraction is unavailable. Compare the e-Right copyright type manually.", "PDF + e-Right")
    if _copyright_type_in_text(expected, pdf_text):
        return _check("copyright_type_matches_pdf", label, "pass", "The e-Right copyright type was found in the extracted PDF text.", "PDF + e-Right")
    return _check("copyright_type_matches_pdf", label, "issue", "The e-Right copyright type was not found in the extracted PDF text.", "PDF + e-Right")


def _missing_warning_check(check_id: str, label: str, keyword: str, messages: List[Dict[str, str]]) -> Dict:
    matching_messages = [
        message["text"]
        for message in messages
        if keyword in message["text"].lower()
    ]
    if matching_messages:
        return _check(check_id, label, "issue", "; ".join(matching_messages), "HotCRP ACM HTML")
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
    issues = [
        message["text"]
        for message in messages
        if message["severity"] in {"error", "warning"}
    ]
    if issues:
        return _check("proceeding_messages", "Other issues", "issue", "; ".join(issues), "HotCRP ACM HTML")
    return _check("proceeding_messages", "Other issues", "pass", "No per-paper proceeding messages found.", "HotCRP ACM HTML")


def _pdf_exists_check(pdf_path: Path) -> Dict:
    if pdf_path.exists():
        return _check("pdf_exists", "Paper PDF provided", "pass", "A local paper PDF was found.", "ZIP")
    return _check("pdf_exists", "Paper PDF provided", "issue", "No local PDF found for this paper.", "ZIP")


def _check(check_id: str, label: str, status: str, evidence: str, source: str) -> Dict:
    return {"id": check_id, "label": label, "status": status, "evidence": evidence, "source": source, "note": ""}


def _add_source_notes(
    checks: List[Dict],
    xml_paper: Optional[XmlPaper],
    html_paper: Optional[HtmlPaper],
    copyright_paper: Optional[CopyrightPaper],
    pdf_path: Path,
    pdf_pages: Optional[int],
) -> None:
    notes = {
        "title_pdf_vs_xml": _xml_note("XML title", xml_paper.title if xml_paper else ""),
        "authors_pdf_vs_xml": _xml_note("XML authors", _author_names(xml_paper)),
        "affiliations_pdf_vs_xml": _xml_note("XML affiliations", _author_affiliations(xml_paper)),
        "emails_in_pdf": _xml_note("XML email addresses", _author_emails(xml_paper)),
        "orcid": _xml_note("XML ORCID values", _author_orcids(xml_paper)),
        "hotcrp_acm_keywords": _hotcrp_messages_note(html_paper, "acm keywords"),
        "hotcrp_ccs": _hotcrp_messages_note(html_paper, "acm computing classification"),
        "hotcrp_references": _hotcrp_messages_note(html_paper, "references"),
        "source_files": _hotcrp_source_files_note(html_paper),
        "proceeding_messages": _hotcrp_all_messages_note(html_paper),
        "copyright_doi_matches_pdf": _eright_value_note(copyright_paper, "DOI", _first_nonempty(copyright_paper.rights_doi, copyright_paper.doi) if copyright_paper else ""),
        "copyright_isbn_matches_pdf": _eright_value_note(copyright_paper, "ISBN", copyright_paper.isbn if copyright_paper else ""),
        "copyright_type_matches_pdf": _eright_value_note(copyright_paper, "copyright type", copyright_paper.copyright_type if copyright_paper else ""),
        "pdf_exists": f"ZIP PDF file: {pdf_path.name if pdf_path.exists() else 'none found'}.",
        "pdf_page_numbers": "No non-PDF reference source is used for this check.",
        "latest_acm_template": _hotcrp_summary_note(html_paper),
        "authors_stacked": "No non-PDF reference source is used for this check.",
        "last_page_balanced": "No non-PDF reference source is used for this check.",
        "track_page_limit": _hotcrp_page_limit_note(html_paper),
    }
    for check in checks:
        check["note"] = notes.get(check["id"], "")


def _xml_note(label: str, value: str) -> str:
    return f"{label}: {value}." if value else f"{label}: unavailable."


def _author_names(xml_paper: Optional[XmlPaper]) -> str:
    if not xml_paper:
        return ""
    return ", ".join(author.name for author in xml_paper.authors if author.name)


def _author_affiliations(xml_paper: Optional[XmlPaper]) -> str:
    if not xml_paper:
        return ""
    affiliations = []
    for author in xml_paper.authors:
        if author.affiliation and author.affiliation not in affiliations:
            affiliations.append(author.affiliation)
    return ", ".join(affiliations)


def _author_emails(xml_paper: Optional[XmlPaper]) -> str:
    if not xml_paper:
        return ""
    emails = [author.email for author in xml_paper.authors if author.email]
    return ", ".join(emails)


def _author_orcids(xml_paper: Optional[XmlPaper]) -> str:
    if not xml_paper:
        return ""
    available = sum(1 for author in xml_paper.authors if author.orcid)
    total = len(xml_paper.authors)
    return f"{available}/{total} authors have ORCID values" if total else ""


def _hotcrp_messages_note(html_paper: Optional[HtmlPaper], keyword: str) -> str:
    if not html_paper:
        return "HotCRP ACM messages: unavailable."
    matches = [message["text"] for message in html_paper.messages if keyword in message["text"].lower()]
    if matches:
        return "HotCRP ACM message: " + "; ".join(matches)
    return "HotCRP ACM message: no matching warning found."


def _hotcrp_source_files_note(html_paper: Optional[HtmlPaper]) -> str:
    if not html_paper:
        return "HotCRP ACM source-file data: unavailable."
    if not html_paper.source_files:
        return "HotCRP ACM source-file data: no source-file archive found."
    names = ", ".join(file["name"] for file in html_paper.source_files if file.get("name"))
    return f"HotCRP ACM source-file data: {names or str(len(html_paper.source_files)) + ' archive(s)'}."


def _hotcrp_all_messages_note(html_paper: Optional[HtmlPaper]) -> str:
    if not html_paper:
        return "HotCRP ACM messages: unavailable."
    if not html_paper.messages:
        return "HotCRP ACM messages: no per-paper messages found."
    return "HotCRP ACM messages: " + "; ".join(message["text"] for message in html_paper.messages)


def _eright_value_note(copyright_paper: Optional[CopyrightPaper], field_label: str, value: str) -> str:
    if not copyright_paper:
        return f"e-Right {field_label}: no matching e-Right row found."
    if not copyright_paper.has_rights_detail and field_label != "DOI":
        return f"e-Right {field_label}: row found, but saved rights details were not expanded."
    return f"e-Right {field_label}: {value or 'not found'}."


def _hotcrp_summary_note(html_paper: Optional[HtmlPaper]) -> str:
    if not html_paper:
        return "HotCRP ACM data: unavailable."
    return f"HotCRP ACM class: {html_paper.acm_class or 'unavailable'}; proceeding status: {html_paper.proceeding_status or 'unknown'}."


def _hotcrp_page_limit_note(html_paper: Optional[HtmlPaper]) -> str:
    if not html_paper:
        return "HotCRP ACM page data: unavailable."
    page_count = html_paper.page_count if html_paper.page_count is not None else "unavailable"
    return f"HotCRP ACM class: {html_paper.acm_class or 'unavailable'}; page count: {page_count}."


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


def _pdf_title_candidate(xml_paper: XmlPaper, pdf_text: str) -> str:
    return " ".join(_pdf_title_lines(xml_paper, pdf_text))


def _pdf_title_lines(xml_paper: XmlPaper, pdf_text: str) -> List[str]:
    title_words = set(_meaningful_words(xml_paper.title))
    if not title_words:
        return []
    lines = _first_page_text_lines(pdf_text)
    title_lines: List[str] = []
    for line in lines[:30]:
        line_words = _meaningful_words(line)
        if not line_words:
            continue
        if _looks_like_title_boundary(line, xml_paper):
            if title_lines:
                break
            continue
        overlap = title_words.intersection(line_words)
        if overlap:
            title_lines.append(line)
            continue
        if title_lines:
            break
    return title_lines


def _pdf_author_region(xml_paper: XmlPaper, pdf_text: str) -> str:
    return " ".join(re.sub(r"\s+", " ", line).strip() for line in _pdf_author_raw_lines(xml_paper, pdf_text) if line.strip())


def _pdf_author_affiliation_segments(xml_paper: XmlPaper, pdf_text: str) -> Dict[int, str]:
    groups = _pdf_author_raw_line_groups(xml_paper, pdf_text)
    author_segments: Dict[int, str] = {}
    next_author_index = 0
    for group in groups:
        name_line_index = -1
        spans = []
        for line_index, line in enumerate(group):
            line_spans = []
            for author_index in range(next_author_index, len(xml_paper.authors)):
                span = _author_name_span_in_line(line, xml_paper.authors[author_index].name)
                if span:
                    line_spans.append((author_index, span[0], span[1]))
            if line_spans:
                name_line_index = line_index
                spans = sorted(line_spans, key=lambda value: value[1])
                break
        if name_line_index < 0 or not spans:
            continue

        column_spans = _layout_chunk_spans(group[name_line_index])
        if len(column_spans) < len(spans):
            column_spans = [(start, end) for _, start, end in spans]
        group_width = max(len(line) for line in group)
        centers = [(start + end) / 2 for start, end in column_spans]
        mapped_author_indexes = []
        for span_index, (start, end) in enumerate(column_spans):
            author_index = next_author_index + span_index
            if author_index >= len(xml_paper.authors):
                break
            mapped_author_indexes.append(author_index)
            left = 0 if span_index == 0 else int((centers[span_index - 1] + centers[span_index]) / 2)
            right = group_width if span_index == len(column_spans) - 1 else int((centers[span_index] + centers[span_index + 1]) / 2)
            pieces = []
            for line in group[name_line_index + 1:]:
                piece = line[left:right].strip()
                if piece:
                    pieces.append(piece)
            author_segments[author_index] = " ".join(pieces)
        if mapped_author_indexes:
            next_author_index = max(mapped_author_indexes) + 1
    return author_segments


def _pdf_author_raw_line_groups(xml_paper: XmlPaper, pdf_text: str) -> List[List[str]]:
    groups: List[List[str]] = []
    current: List[str] = []
    for line in _pdf_author_raw_lines(xml_paper, pdf_text):
        if line.strip():
            current.append(line.rstrip())
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _pdf_author_raw_lines(xml_paper: XmlPaper, pdf_text: str) -> List[str]:
    raw_lines = _first_page_raw_lines(pdf_text)
    lines = _first_page_text_lines(pdf_text)
    title_lines = _pdf_title_lines(xml_paper, pdf_text)
    if not raw_lines or not lines:
        return []
    start_index = -1
    if title_lines:
        start_index = _find_subsequence_index(lines, title_lines)
    raw_start_index = 0
    if start_index >= 0:
        nonempty_raw_indexes = [index for index, line in enumerate(raw_lines) if line.strip()]
        raw_start_index = nonempty_raw_indexes[start_index + len(title_lines)] if start_index + len(title_lines) < len(nonempty_raw_indexes) else len(raw_lines)
    author_lines: List[str] = []
    for line in raw_lines[raw_start_index:]:
        normalized_line = re.sub(r"\s+", " ", line).strip()
        if normalized_line and _looks_like_author_block_boundary(normalized_line):
            break
        author_lines.append(line)
    return author_lines


def _first_page_raw_lines(pdf_text: str) -> List[str]:
    return [line.rstrip("\r\n") for line in pdf_text.split("\f", 1)[0].splitlines()]


def _first_page_text_lines(pdf_text: str) -> List[str]:
    first_page = pdf_text.split("\f", 1)[0]
    return [
        line
        for line in (
            re.sub(r"\s+", " ", line).strip()
            for line in first_page.splitlines()
        )
        if line
    ]


def _find_subsequence_index(values: List[str], subsequence: List[str]) -> int:
    if not subsequence:
        return -1
    limit = len(values) - len(subsequence) + 1
    for index in range(max(limit, 0)):
        if values[index:index + len(subsequence)] == subsequence:
            return index
    return -1


def _looks_like_title_boundary(line: str, xml_paper: XmlPaper) -> bool:
    lower = line.lower()
    if "@" in line:
        return True
    if lower in {"abstract", "keywords", "ccs concepts"}:
        return True
    if lower.startswith(("abstract ", "keywords ", "acm reference format", "ccs concepts")):
        return True
    return any(_words_in_order(author.name, line) for author in xml_paper.authors if author.name)


def _looks_like_author_block_boundary(line: str) -> bool:
    lower = line.lower()
    if lower in {"abstract", "keywords", "ccs concepts"}:
        return True
    return lower.startswith(("abstract ", "keywords ", "acm reference format", "ccs concepts"))


def _author_name_in_pdf_author_region(name: str, author_region: str) -> bool:
    name_words = _author_name_words(name)
    region_words = _author_name_words(author_region)
    if _contains_contiguous_words(name_words, region_words):
        return True
    return _short_author_name_in_region(name_words, region_words)


def _author_name_span_in_line(line: str, name: str) -> Optional[tuple[int, int]]:
    name_words = _author_name_words(name)
    tokens = _line_word_tokens(line)
    if not name_words or not tokens:
        return None
    limit = len(tokens) - len(name_words) + 1
    for index in range(max(limit, 0)):
        if [token[0] for token in tokens[index:index + len(name_words)]] == name_words:
            return tokens[index][1], tokens[index + len(name_words) - 1][2]
    if len(name_words) >= 2:
        first_word = name_words[0]
        last_word = name_words[-1]
        first_positions = [index for index, token in enumerate(tokens) if token[0] == first_word]
        last_positions = [index for index, token in enumerate(tokens) if token[0] == last_word]
        for first_index in first_positions:
            for last_index in last_positions:
                if 0 < last_index - first_index <= 8:
                    return tokens[first_index][1], tokens[last_index][2]
    return None


def _title_words_match(expected: str, actual: str) -> bool:
    return _meaningful_words(expected) == _meaningful_words(actual)


def _contains_contiguous_words(needle_words: List[str], haystack_words: List[str]) -> bool:
    if not needle_words:
        return False
    limit = len(haystack_words) - len(needle_words) + 1
    for index in range(max(limit, 0)):
        if haystack_words[index:index + len(needle_words)] == needle_words:
            return True
    return False


def _short_author_name_in_region(name_words: List[str], region_words: List[str]) -> bool:
    if len(name_words) != 2:
        return False
    first, last = name_words
    first_positions = [index for index, word in enumerate(region_words) if word == first]
    last_positions = [index for index, word in enumerate(region_words) if word == last]
    return any(
        0 < last_index - first_index <= 8
        for first_index in first_positions
        for last_index in last_positions
    )


def _author_name_words(value: str) -> List[str]:
    words = []
    for word in _meaningful_words(value):
        words.append(re.sub(r"(?<=[a-z])[0-9]+$", "", word))
    return [word for word in words if word]


def _line_word_tokens(line: str) -> List[tuple[str, int, int]]:
    tokens = []
    for match in re.finditer(r"[^\W_]+", line, flags=re.UNICODE):
        words = _author_name_words(match.group(0))
        if words:
            tokens.append((words[0], match.start(), match.end()))
    return tokens


def _layout_chunk_spans(line: str) -> List[tuple[int, int]]:
    return [
        (match.start(), match.end())
        for match in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", line)
    ]


def _meaningful_words(value: str) -> List[str]:
    value = value.translate(str.maketrans({
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
    }))
    value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
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


def _copyright_for_paper(
    paper_id: str,
    xml_paper: Optional[XmlPaper],
    copyright_papers: Dict[str, CopyrightPaper],
) -> Optional[CopyrightPaper]:
    if not copyright_papers:
        return None
    if xml_paper and xml_paper.tracking_number:
        paper = copyright_papers.get(xml_paper.tracking_number.lower())
        if paper:
            return paper
    exact_pid_matches = [paper for paper in copyright_papers.values() if paper.paper_id == paper_id]
    return exact_pid_matches[0] if len(exact_pid_matches) == 1 else None


def _identifier_in_text(expected: str, pdf_text: str) -> bool:
    normalized_expected = _compact_identifier(expected)
    normalized_text = _compact_identifier(pdf_text)
    return bool(normalized_expected and normalized_expected in normalized_text)


def _compact_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _copyright_type_in_text(expected: str, pdf_text: str) -> bool:
    expected_normalized = expected.strip().upper().replace(" ", "-")
    text_lower = pdf_text.lower()
    compact_text = _compact_identifier(pdf_text)
    if expected_normalized == "CC-BY-NC-ND":
        return any(
            phrase in text_lower
            for phrase in [
                "cc-by-nc-nd",
                "cc by-nc-nd",
                "creativecommons.org/licenses/by-nc-nd",
                "creative commons attribution-noncommercial",
                "creative commons attribution noncommercial",
            ]
        ) or (
            "creativecommonsattributionnoncommercial" in compact_text
            and ("noderivatives" in compact_text or "noderivs" in compact_text)
        )
    if expected_normalized == "CC-BY":
        return bool(re.search(r"\bcc[- ]by\b(?![- ]nc)", text_lower)) or any(
            phrase in text_lower
            for phrase in [
                "creativecommons.org/licenses/by/4.0",
                "creative commons attribution international",
                "creative commons attribution 4.0 international",
            ]
        )
    return _compact_identifier(expected_normalized) in compact_text


def _first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""
