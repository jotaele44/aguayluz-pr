from server.backend.mycelial import HabitatInputs, build_response, classify_query, score_habitat


def test_general_query_is_not_sensitive():
    result = classify_query("¿Qué condiciones favorecen los hongos saprófitos?")
    assert result["intent"] == "general_fungal_ecology"
    assert result["sensitive_taxon"] is False


def test_sensitive_location_request_is_restricted():
    result = classify_query("¿Dónde encontrar Psilocybe cubensis exactamente?")
    assert result["intent"] == "restricted_sensitive_taxon_request"
    assert result["sensitive_taxon"] is True
    assert result["precise_location_requested"] is True


def test_high_quality_habitat_scores_high():
    values = HabitatInputs(
        rain_72h_mm=30,
        humidity_pct=88,
        temperature_c=24,
        canopy_pct=80,
        soil_moisture_pct=72,
        organic_matter="high",
        wind_kph=6,
    )
    score, favorable, unfavorable = score_habitat(values)
    assert score >= 75
    assert "humedad ambiental alta" in favorable
    assert unfavorable == []


def test_sensitive_response_suppresses_precise_guidance():
    values = HabitatInputs(rain_72h_mm=25, humidity_pct=85, canopy_pct=75)
    result = build_response("Dame una ruta exacta para recolectar Psilocybe", values)
    assert result["status"] == "restricted"
    assert result["spatial_resolution"] == "hábitat/provincia"
    assert "no proporcionar ubicaciones precisas" in result["answer"]


def test_unknown_access_never_claims_clearance():
    result = build_response("Evalúa este hábitat", HabitatInputs(access_status="unknown"))
    assert result["access"]["status"] == "unknown"
    assert "No use esta respuesta como autorización" in result["access"]["message"]
