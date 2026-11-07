"""Regression tests for the RC4 read-only review importer."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.pipelines_rc4_quarantine import verify

class QuarantineTests(unittest.TestCase):
    def make_fixture(self, publishable=False, corrupt=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        row = {"asset_id":"A1","asset_sha256":"a"*64,"classification":"CANDIDATE_NOT_IDENTITY","canonical_entity_id":None,"geometry":None,"publishable":publishable,"foia_submitted":False}
        payload = (json.dumps(row)+"\n").encode()
        (root/"spiderweb-pr.jsonl").write_bytes(payload + (b"corrupt" if corrupt else b""))
        (root/"manifest.json").write_text(json.dumps({"publication_gate":"DENY","files":{"spiderweb-pr.jsonl":{"sha256":hashlib.sha256(payload).hexdigest(),"size":len(payload)}}}))
        return temp,root

    def test_valid_review_only(self):
        hold, root = self.make_fixture()
        with hold: self.assertEqual(verify(root,"spiderweb-pr")["canonical_promoted"],0)

    def test_reject_promotion(self):
        hold, root = self.make_fixture(publishable=True)
        with hold, self.assertRaises(ValueError):
            verify(root, "spiderweb-pr")

    def test_reject_tampering(self):
        hold, root = self.make_fixture(corrupt=True)
        with hold, self.assertRaises(ValueError):
            verify(root, "spiderweb-pr")

    def test_reject_publication_gate(self):
        hold, root = self.make_fixture()
        with hold:
            m=json.loads((root/"manifest.json").read_text())
            m["publication_gate"] = "ALLOW"
            (root/"manifest.json").write_text(json.dumps(m))
            with self.assertRaises(ValueError):
                verify(root, "spiderweb-pr")

if __name__ == "__main__":
    unittest.main()
