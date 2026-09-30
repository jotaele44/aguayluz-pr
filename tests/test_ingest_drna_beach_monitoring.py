from scripts.ingest_drna_beach_monitoring import CATEGORY_URL, crawl_archive, parse_notice


def test_parser_preserves_bav_exceedance_and_separate_non_bav_advisory():
    html = """
    <html><head>
      <meta property="article:published_time" content="2026-03-09T12:32:00-04:00">
    </head><body>
      <p>Resultados de los muestreos del 3 y 4 de marzo de 2026.</p>
      <p>No son aptas para bañistas por exceder el Beach Action Value para Enterococos
      (70 colonias/100 mL).</p>
      <table>
        <tr><th>Estación</th><th>Nombre de la Playa</th><th>Municipio</th></tr>
        <tr><td>RW-26</td><td>Playita del Condado</td><td>San Juan</td></tr>
      </table>
      <p>No se recomienda el uso de la Playa Buyé para contacto primario, debido a
      una observación independiente de calidad de agua.</p>
      <p>De requerir información adicional, consulte al DRNA.</p>
    </body></html>
    """.encode()

    published, rows, issue = parse_notice(
        html,
        "https://www.drna.pr.gov/programas-y-proyectos/monitoria-de-playas/"
        "notificaciones-ambientales/notificacion-monitoria-de-playas-244/",
    )

    assert issue is None
    assert published.isoformat() == "2026-03-09"
    assert len(rows) == 2
    by_state = {row["advisory_state"]: row for row in rows}
    exceedance = by_state["BAV_EXCEEDANCE_NOT_SUITABLE_FOR_BATHERS"]
    separate = by_state["OTHER_WATER_QUALITY_PRIMARY_CONTACT_NOT_RECOMMENDED"]
    assert exceedance["station_id"] == "RW-26"
    assert exceedance["municipality_raw"] == "San Juan"
    assert exceedance["sample_date_start"] == "2026-03-03"
    assert exceedance["sample_date_end"] == "2026-03-04"
    assert separate["beach_name"] == "Playa Buyé"
    assert separate["bav_value"] is None


def test_parser_preserves_program_wide_all_clear_without_fabricating_station_rows():
    html = """
    <html><head>
      <meta property="article:published_time" content="2026-08-19T12:53:00-04:00">
    </head><body>
      <p>Resultados de los muestreos del 17 de agosto de 2026.</p>
      <p>Las playas que son parte del Programa de Playas se encuentran aptas para bañistas.</p>
    </body></html>
    """.encode()

    published, rows, issue = parse_notice(
        html,
        "https://www.drna.pr.gov/programas-y-proyectos/monitoria-de-playas/"
        "notificaciones-ambientales/notificacion-monitoria-de-playas-265/",
    )

    assert issue is None
    assert published.isoformat() == "2026-08-19"
    assert len(rows) == 1
    assert rows[0]["advisory_state"] == "ALL_MONITORED_BEACHES_SUITABLE_FOR_BATHERS"
    assert rows[0]["station_id"] is None
    assert rows[0]["municipality_raw"] is None


def test_parser_fails_closed_when_sampling_date_is_missing():
    html = """
    <html><head>
      <meta property="article:published_time" content="2026-09-25T10:39:00-04:00">
    </head><body>
      <p>No son aptas para bañistas por exceder el Beach Action Value para Enterococos.</p>
      <table><tr><td>RW-22</td><td>Pico de Piedra</td><td>Aguada</td></tr></table>
    </body></html>
    """.encode()

    _, rows, issue = parse_notice(
        html,
        "https://www.drna.pr.gov/programas-y-proyectos/monitoria-de-playas/"
        "notificaciones-ambientales/notificacion-monitoria-de-playas-269/",
    )

    assert len(rows) == 1
    assert issue == "SAMPLING_DATE_UNRESOLVED"

class _FakeResponse:
    def __init__(self, url, content):
        self.url = url
        self.content = content
        self.headers = {}

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return _FakeResponse(url, self.pages[url])


def test_archive_crawl_stops_after_complete_prior_year_overlap_page():
    page2 = f"{CATEGORY_URL}page/2/"
    page3 = f"{CATEGORY_URL}page/3/"
    post2026 = (
        "https://www.drna.pr.gov/programas-y-proyectos/monitoria-de-playas/"
        "notificaciones-ambientales/notificacion-monitoria-de-playas-900/"
    )
    post2025 = (
        "https://www.drna.pr.gov/programas-y-proyectos/monitoria-de-playas/"
        "notificaciones-ambientales/notificacion-monitoria-de-playas-899/"
    )
    pages = {
        CATEGORY_URL: f"""
          <a href="{post2026}">notice</a>
          <a href="{page2}">2</a>
        """.encode(),
        page2: f"""
          <a href="{post2025}">notice</a>
          <a href="{page3}">3</a>
        """.encode(),
        post2026: b'<meta property="article:published_time" content="2026-01-20T08:00:00-04:00">',
        post2025: b'<meta property="article:published_time" content="2025-12-18T08:00:00-04:00">',
    }
    client = _FakeClient(pages)

    archive, candidates, notices, errors = crawl_archive(
        client,
        max_pages=10,
        target_year=2026,
    )

    assert len(archive) == 2
    assert candidates == [post2026, post2025]
    assert set(notices) == {post2026, post2025}
    assert errors == {}
    assert page3 not in client.requested

