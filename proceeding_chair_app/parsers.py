from __future__ import annotations

import html
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree


@dataclass
class Author:
    name: str
    affiliation: str
    country: str
    email: str
    orcid: str
    contact_author: bool
    sequence_no: str


@dataclass
class XmlPaper:
    paper_id: str
    tracking_number: str
    paper_type: str
    title: str
    submission_date: str
    authors: List[Author] = field(default_factory=list)


@dataclass
class HtmlPaper:
    paper_id: str
    title: str = ""
    acm_class: str = ""
    proceeding_status: str = "unknown"
    first_page: Optional[int] = None
    page_count: Optional[int] = None
    messages: List[Dict[str, str]] = field(default_factory=list)
    source_files: List[Dict[str, str]] = field(default_factory=list)
    final_pdf_href: str = ""
    paginated_pdf_href: str = ""


def _text(element: Optional[ElementTree.Element]) -> str:
    return "" if element is None or element.text is None else element.text.strip()


def load_xml_papers(path: Path) -> Dict[str, XmlPaper]:
    root = ElementTree.parse(path).getroot()
    papers: Dict[str, XmlPaper] = {}
    for paper_el in root.findall("paper"):
        tracking = _text(paper_el.find("event_tracking_number"))
        match = re.search(r"p(\d+)$", tracking)
        if not match:
            continue
        paper_id = match.group(1)
        paper = XmlPaper(
            paper_id=paper_id,
            tracking_number=tracking,
            paper_type=_text(paper_el.find("paper_type")),
            title=_text(paper_el.find("paper_title")),
            submission_date=_text(paper_el.find("art_submission_date")),
        )
        for author_el in paper_el.findall("./authors/author"):
            affiliation_el = author_el.find("./affiliations/affiliation")
            first = _text(author_el.find("first_name"))
            middle = _text(author_el.find("middle_name"))
            last = _text(author_el.find("last_name"))
            name = " ".join(part for part in [first, middle, last] if part)
            paper.authors.append(
                Author(
                    name=name,
                    affiliation=_text(affiliation_el.find("institution")) if affiliation_el is not None else "",
                    country=_text(affiliation_el.find("country")) if affiliation_el is not None else "",
                    email=_text(author_el.find("email_address")),
                    orcid=_text(author_el.find("ORCID")),
                    contact_author=_text(author_el.find("contact_author")) == "Y",
                    sequence_no=_text(author_el.find("sequence_no")),
                )
            )
        papers[paper_id] = paper
    return papers


class HotcrpAcmHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.papers: Dict[str, HtmlPaper] = {}
        self.global_messages: List[Dict[str, str]] = []
        self._row_kind = ""
        self._row_pid = ""
        self._td_class = ""
        self._td_text: List[str] = []
        self._plr_values: List[str] = []
        self._diag_class = ""
        self._diag_text: List[str] = []
        self._collect_diag = False
        self._current_link_href = ""
        self._current_link_text: List[str] = []

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        classes = attrs.get("class", "")
        if tag == "tr":
            pid = attrs.get("data-pid", "")
            if pid and "plx" in classes:
                self._row_kind = "detail"
                self._row_pid = pid
            elif pid and re.search(r"\bpl\b", classes):
                self._row_kind = "main"
                self._row_pid = pid
                self._plr_values = []
                self.papers.setdefault(pid, HtmlPaper(paper_id=pid))
        elif tag == "td" and self._row_kind:
            self._td_class = classes
            self._td_text = []
        elif tag == "span" and self._row_kind == "main":
            paper = self.papers.setdefault(self._row_pid, HtmlPaper(paper_id=self._row_pid))
            if "error-mark" in classes:
                paper.proceeding_status = "error"
            elif "warning-mark" in classes:
                paper.proceeding_status = "warning"
            elif "success-mark" in classes:
                paper.proceeding_status = "success"
        elif tag == "div" and "is-diagnostic" in classes:
            self._collect_diag = True
            self._diag_class = classes
            self._diag_text = []
        elif tag == "a" and self._row_kind:
            self._current_link_href = html.unescape(attrs.get("href", ""))
            self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row_kind == "main":
            text = _clean_text(" ".join(self._td_text))
            paper = self.papers.setdefault(self._row_pid, HtmlPaper(paper_id=self._row_pid))
            if "pl_title" in self._td_class:
                # Drop the link label duplication from nested PDF icon alt text if present.
                paper.title = re.sub(r"\s*\[PDF\]\s*$", "", text).strip()
            elif "nb" in self._td_class:
                paper.acm_class = text
            elif "plr" in self._td_class and text:
                self._plr_values.append(text)
                if len(self._plr_values) == 1:
                    paper.first_page = _parse_int(text)
                elif len(self._plr_values) == 2:
                    paper.page_count = _parse_int(text)
            self._td_class = ""
            self._td_text = []
        elif tag == "div" and self._collect_diag:
            text = _clean_text(" ".join(self._diag_text))
            if text:
                severity = "error" if "is-error" in self._diag_class else "warning"
                if self._row_kind == "detail" and self._row_pid:
                    self.papers.setdefault(self._row_pid, HtmlPaper(paper_id=self._row_pid)).messages.append(
                        {"severity": severity, "text": text}
                    )
                else:
                    self.global_messages.append({"severity": severity, "text": text})
            self._collect_diag = False
            self._diag_class = ""
            self._diag_text = []
        elif tag == "a" and self._current_link_href and self._row_kind:
            link_text = _clean_text(" ".join(self._current_link_text))
            paper = self.papers.setdefault(self._row_pid, HtmlPaper(paper_id=self._row_pid))
            href = self._current_link_href
            if "acm_source_files" in href:
                paper.source_files.append({"name": link_text, "href": href})
            elif re.search(r"final\d+\.pdf$", href):
                paper.final_pdf_href = href
            elif "acmpaginated" in href:
                paper.paginated_pdf_href = href
            self._current_link_href = ""
            self._current_link_text = []
        elif tag == "tr":
            self._row_kind = ""
            self._row_pid = ""

    def handle_data(self, data: str) -> None:
        if self._td_class:
            self._td_text.append(data)
        if self._collect_diag:
            self._diag_text.append(data)
        if self._current_link_href:
            self._current_link_text.append(data)


def load_hotcrp_html(path: Path) -> tuple[Dict[str, HtmlPaper], List[Dict[str, str]]]:
    parser = HotcrpAcmHtmlParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.papers, parser.global_messages


def ensure_sample_pdfs(zip_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.glob("*.pdf")):
        return
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(output_dir)


def pdf_page_count(path: Path) -> Optional[int]:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    # Good enough for a prototype and these samples; a real backend should use
    # pypdf, pdfminer, PyMuPDF, or Poppler.
    matches = re.findall(rb"/Type\s*/Page\b(?!s)", data)
    return len(matches) or None


def extract_pdf_text(path: Path) -> tuple[str, str]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return "", "pdftotext is not installed."
    if not path.exists():
        return "", "PDF file is missing."
    try:
        result = subprocess.run(
            [pdftotext, "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"pdftotext failed: {exc}"
    if result.returncode != 0:
        return "", (result.stderr or "pdftotext returned an error.").strip()
    return result.stdout, ""


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value.strip())
    except ValueError:
        return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()
