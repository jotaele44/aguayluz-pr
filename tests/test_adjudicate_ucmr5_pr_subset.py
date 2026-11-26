import csv
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "adjudicate_ucmr5_pr_subset.py"
_SPEC = importlib.util.spec_from_file_location("adjudicate_ucmr5_pr_subset", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
adjudicate = _MODULE.adjudicate


def _write(path: Path, rows: list[dict[str, str]], order=None) -> None:
    fields = ["PWSID", "Contaminant", "Result"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        indexes = order if order is not None else range(len(rows))
        for index in indexes:
            writer.writerow(rows[index])


def test_byte_identical(tmp_path: Path):
    a = tmp_path / "a.tsv"
    b = tmp_path / "b.tsv"
    rows = [{"PWSID": "PR1", "Contaminant": "A", "Result": "1"}]
    _write(a, rows)
    b.write_bytes(a.read_bytes())
    result = adjudicate(a, b)
    assert result["classification"] == "BYTE_IDENTICAL"
    assert result["row_multiset"]["symmetric_difference"] == 0


def test_logically_identical_order_change(tmp_path: Path):
    a = tmp_path / "a.tsv"
    b = tmp_path / "b.tsv"
    rows = [
        {"PWSID": "PR1", "Contaminant": "A", "Result": "1"},
        {"PWSID": "PR2", "Contaminant": "B", "Result": "2"},
    ]
    _write(a, rows)
    _write(b, rows, [1, 0])
    result = adjudicate(a, b)
    assert result["classification"] == "LOGICALLY_IDENTICAL_ROW_MULTISET"
    assert result["pwsid_set"]["symmetric_difference"] == 0


def test_distinct_subset_preserves_set_deltas(tmp_path: Path):
    a = tmp_path / "a.tsv"
    b = tmp_path / "b.tsv"
    _write(a, [{"PWSID": "PR1", "Contaminant": "A", "Result": "1"}])
    _write(b, [{"PWSID": "PR2", "Contaminant": "A", "Result": "1"}])
    result = adjudicate(a, b)
    assert result["classification"] == "DISTINCT_PR_SUBSET"
    assert result["row_multiset"] == {
        "intersection": 0,
        "old_only": 1,
        "new_only": 1,
        "union": 2,
        "symmetric_difference": 2,
    }
    assert result["pwsid_set"]["old_only"] == ["PR1"]
    assert result["pwsid_set"]["new_only"] == ["PR2"]
