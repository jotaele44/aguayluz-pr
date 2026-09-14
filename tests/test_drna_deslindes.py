from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aguayluz.drna_deslindes import (
    DeslindeParseError,
    DeslindeRecord,
    SourceManifestation,
    diff_records,
    discover_detail_urls,
    freeze_snapshot,
    load_snapshot,
    parse_approved_notice,
)

PUNTA_BANDERA_URL = (
    "https://www.drna.pr.gov/deslindes-zmt/deslindes-zmt-aprobados/"
    "certificacion-de-deslinde-de-los-bienes-de-dominio-publico-maritimo-terrestre-y-la-zona-maritimo-tererrestre-11/"
)

PUNTA_BANDERA_HTML = b"""
<html><body>
<h3>Notificaci&oacute;n de Certificaci&oacute;n de Deslinde</h3>
<p>N&uacute;mero de Permiso: O-AG-CER02-SJ-00887-16062025</p>
<p>Promovente: BENIGNO RODRIGUEZ BURGOS</p>
<p>Propietario: PUNTA BANDERA ASSOCIATES, INC.</p>
<p>Direcci&oacute;n: LUQUILLO BEACH BOULEVARD/OCEAN DRIVE BO. MATA DE PLATANO, LUQUILLO</p>
<p>Prop&oacute;sito: DELIMITAR CABIDA Y PROYECTO RESIDENCIAL</p>
<p>Fecha Deslinde Certificado : 29/07/2026</p>
<p>Fecha de Publicaci&oacute;n del Aviso: 24/08/2026</p>
</body></html>
"""


def _record(permit_number: str, *, owner: str = "OWNER") -> DeslindeRecord:
    return DeslindeRecord(
        permit_number=permit_number,
        status="APPROVED",
        certified_date="2026-07-29",
        publication_date="2026-08-24",
        proponent_raw="PROMOVENTE",
        owner_raw=owner,
        address_raw="ADDRESS",
        purpose_raw="PURPOSE",
        source=SourceManifestation(
            source_url=PUNTA_BANDERA_URL,
            retrieved_at="2026-09-14T22:00:00Z",
            sha256="a" * 64,
            byte_count=123,
        ),
    )


def test_punta_bandera_notice_is_bound_by_stable_permit_and_certified_date() -> None:
    record = parse_approved_notice(
        PUNTA_BANDERA_HTML,
        PUNTA_BANDERA_URL,
        retrieved_at=datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc),
    )
    assert record.permit_number == "O-AG-CER02-SJ-00887-16062025"
    assert record.status == "APPROVED"
    assert record.certified_date == "2026-07-29"
    assert record.publication_date == "2026-08-24"
    assert record.owner_raw == "PUNTA BANDERA ASSOCIATES, INC."
    assert len(record.source.sha256) == 64


def test_non_drna_or_non_approved_path_cannot_emit_approval() -> None:
    with pytest.raises(DeslindeParseError):
        parse_approved_notice(PUNTA_BANDERA_HTML, "https://example.com/social-post")

    with pytest.raises(DeslindeParseError):
        parse_approved_notice(
            PUNTA_BANDERA_HTML,
            "https://www.drna.pr.gov/noticias/punta-bandera/",
        )


def test_keyword_only_notice_cannot_emit_approval() -> None:
    html = b"<html><body>deslinde aprobado aprobado aprobado</body></html>"
    with pytest.raises(DeslindeParseError):
        parse_approved_notice(html, PUNTA_BANDERA_URL)


def test_permit_without_certified_date_cannot_emit_approval() -> None:
    html = b"<html><body>Numero de Permiso: O-AG-CER02-SJ-00887-16062025</body></html>"
    with pytest.raises(DeslindeParseError):
        parse_approved_notice(html, PUNTA_BANDERA_URL)


def test_discovery_deduplicates_and_rejects_nonapproved_links() -> None:
    listing = f"""
    <a href="{PUNTA_BANDERA_URL}">approved</a>
    <a href="{PUNTA_BANDERA_URL}">duplicate</a>
    <a href="https://www.drna.pr.gov/noticias/other/">news</a>
    <a href="https://example.com/deslinde">social</a>
    """
    assert discover_detail_urls(listing) == [PUNTA_BANDERA_URL]


def test_new_authoritative_manifestation_emits_approved_transition() -> None:
    current = [_record("O-AG-CER02-SJ-00887-16062025")]
    events = diff_records([], current)
    assert len(events) == 1
    assert events[0].event_type == "DESLINDE_APPROVED"
    assert events[0].current == current[0]


def test_source_absence_does_not_become_revocation() -> None:
    previous = [_record("O-AG-CER02-SJ-00887-16062025")]
    events = diff_records(previous, [])
    assert len(events) == 1
    assert events[0].event_type == "SOURCE_ABSENCE"
    assert "revocation" not in events[0].event_type.lower()


def test_same_permit_changed_fields_is_manifestation_change_not_new_identity() -> None:
    previous = [_record("O-AG-CER02-SJ-00887-16062025", owner="OLD OWNER")]
    current = [_record("O-AG-CER02-SJ-00887-16062025", owner="NEW OWNER")]
    events = diff_records(previous, current)
    assert [event.event_type for event in events] == ["SOURCE_MANIFESTATION_CHANGED"]


def test_snapshot_round_trip_preserves_records(tmp_path: Path) -> None:
    path = freeze_snapshot([_record("O-AG-CER02-SJ-00887-16062025")], tmp_path / "snapshot.json")
    assert load_snapshot(path) == [_record("O-AG-CER02-SJ-00887-16062025")]
