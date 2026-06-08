import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app


class UploadField:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = io.BytesIO(data)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    return buffer.getvalue()


class FollowUpSourceSnapshotTests(unittest.TestCase):
    def test_uploaded_follow_up_zip_reuses_parent_pdfs_not_in_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            parent_inputs = data_dir / "review_assets" / "track-1" / "review-0" / "inputs"
            parent_pdfs = data_dir / "review_assets" / "track-1" / "review-0" / "pdfs"
            parent_inputs.mkdir(parents=True)
            parent_pdfs.mkdir(parents=True)

            (parent_inputs / "toc.xml").write_text("<toc />", encoding="utf-8")
            (parent_inputs / "hotcrp.html").write_text("<html></html>", encoding="utf-8")
            (parent_inputs / "old.zip").write_bytes(_zip_bytes({"paper1.pdf": b"old-one", "paper2.pdf": b"old-two"}))
            (parent_pdfs / "paper1.pdf").write_bytes(b"old-one")
            (parent_pdfs / "paper2.pdf").write_bytes(b"old-two")

            sources = {
                "xml": "review_assets/track-1/review-0/inputs/toc.xml",
                "html": "review_assets/track-1/review-0/inputs/hotcrp.html",
                "zip": "review_assets/track-1/review-0/inputs/old.zip",
                "pdf_dir": "review_assets/track-1/review-0/pdfs",
            }
            files = {
                "zip": UploadField("partial-update.zip", _zip_bytes({"paper2.pdf": b"new-two"})),
            }

            with patch.object(app, "DATA_DIR", data_dir), patch.object(app, "REVIEW_ASSETS_DIR", data_dir / "review_assets"):
                snapshot = app._snapshot_review_sources("track-1", "review-1", sources, files)

            child_pdfs = data_dir / snapshot["pdf_dir"]
            self.assertEqual((child_pdfs / "paper1.pdf").read_bytes(), b"old-one")
            self.assertEqual((child_pdfs / "paper2.pdf").read_bytes(), b"new-two")
            self.assertTrue((data_dir / snapshot["xml"]).is_file())
            self.assertTrue((data_dir / snapshot["html"]).is_file())


if __name__ == "__main__":
    unittest.main()
