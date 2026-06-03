import unittest

from proceeding_chair_app.checks import _authors_check
from proceeding_chair_app.parsers import Author, XmlPaper


def _paper_with_author(name: str) -> XmlPaper:
    return XmlPaper(
        paper_id="49",
        tracking_number="fse2026-ivr-p49",
        paper_type="Short Paper",
        title="Characterizing Real-World Accessibility Issues Reported in Kotlin Mobile Apps",
        submission_date="22-JAN-2026",
        authors=[
            Author(
                name=name,
                affiliation="Pontificia Universidad Catolica de Chile",
                country="CL",
                email="afernandb@uc.cl",
                orcid="0000-0003-1784-814X",
                contact_author=False,
                sequence_no="3",
            )
        ],
    )


class AuthorPdfMetadataCheckTests(unittest.TestCase):
    def test_author_check_flags_pdf_hyphen_missing_from_metadata(self):
        check = _authors_check(
            _paper_with_author("Alison Fernandez Blanco"),
            "Alison Fernandez-Blanco1, Leonel Merino1",
            "",
        )

        self.assertEqual(check["status"], "issue")
        self.assertIn("3rd", check["evidence"])

    def test_author_check_accepts_matching_hyphenated_name(self):
        check = _authors_check(
            _paper_with_author("Alison Fernandez-Blanco"),
            "Alison Fernandez-Blanco1, Leonel Merino1",
            "",
        )

        self.assertEqual(check["status"], "pass")


if __name__ == "__main__":
    unittest.main()
