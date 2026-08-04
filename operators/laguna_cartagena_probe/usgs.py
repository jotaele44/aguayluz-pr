"""USGS NWIS, modern OGC, and WQX3 parsers."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from .model import (
    FetchReceipt,
    SITE_METADATA,
    WQ_CHARACTERISTIC_MAP,
    build_observation,
    parse_datetime,
)


def parse_usgs_iv(body: bytes, source: FetchReceipt) -> list[dict[str, Any]]:
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    output: list[dict[str, Any]] = []
    for item in document.get("value", {}).get("timeSeries", []):
        codes = item.get("sourceInfo", {}).get("siteCode", [])
        site_id = str(codes[0].get("value", "")) if codes else ""
        if site_id not in SITE_METADATA:
            continue
        variable = item.get("variable", {})
        variable_codes = variable.get("variableCode", [])
        parameter = str(variable_codes[0].get("value", "")) if variable_codes else ""
        metric = SITE_METADATA[site_id]["metric_by_parameter"].get(parameter)
        if not metric:
            continue
        unit = str(variable.get("unit", {}).get("unitCode") or "unknown")
        values: list[dict[str, Any]] = []
        for group in item.get("values", []):
            values.extend(group.get("value", []))
        for row in values:
            observed = parse_datetime(row.get("dateTime"))
            try:
                value = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            if observed is None:
                continue
            qualifiers = [str(value) for value in row.get("qualifiers", [])]
            qa_status = (
                "provisional"
                if any(qualifier.lower().startswith("p") for qualifier in qualifiers)
                else "accepted"
            )
            output.append(
                build_observation(
                    source_id=source.source_id,
                    source_record_id=f"{site_id}:{parameter}:{observed.isoformat()}",
                    source_hash=source.sha256,
                    provider="USGS",
                    location_id=site_id,
                    metric=metric,
                    value=value,
                    unit=unit,
                    observed_at=observed,
                    window_id=f"USGS_IV_{observed.strftime('%Y%m%d')}",
                    qa_status=qa_status,
                    method="USGS instantaneous values service",
                    notes=f"parameter_code={parameter};qualifiers={','.join(qualifiers)}",
                )
            )
    return output


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            output.update(_flatten(child, path))
    else:
        output[prefix] = value
    return output


def _property(properties: dict[str, Any], *names: str) -> Any:
    normalized: dict[str, Any] = {}
    for key, value in _flatten(properties).items():
        normalized.setdefault(_normalize_key(key.split(".")[-1]), value)
        normalized.setdefault(_normalize_key(key), value)
    for name in names:
        value = normalized.get(_normalize_key(name))
        if value not in (None, ""):
            return value
    return None


def parse_usgs_ogc(body: bytes, source: FetchReceipt) -> list[dict[str, Any]]:
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    features = document.get("features", []) if isinstance(document, dict) else []
    output: list[dict[str, Any]] = []
    for index, feature in enumerate(features, start=1):
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            continue
        properties = feature["properties"]
        raw_site = _property(
            properties,
            "monitoring_location_id",
            "monitoring_location_identifier",
            "site_no",
            "site_code",
        )
        site_id = str(raw_site or "").removeprefix("USGS-").removeprefix("USGS:")
        if site_id not in SITE_METADATA:
            continue
        parameter = str(
            _property(properties, "parameter_code", "parameter_cd", "variable_code") or ""
        ).zfill(5)
        metric = SITE_METADATA[site_id]["metric_by_parameter"].get(parameter)
        if not metric:
            continue
        observed_value = _property(
            properties,
            "time",
            "date_time",
            "datetime",
            "measurement_date_time",
            "measurement_datetime",
            "observation_time",
        )
        if observed_value is None:
            date_value = _property(properties, "measurement_date", "date")
            time_value = _property(properties, "measurement_time")
            observed_value = (
                f"{date_value}T{time_value}" if date_value and time_value else date_value
            )
        observed = parse_datetime(observed_value)
        raw_value = _property(
            properties,
            "value",
            "measurement_value",
            "result_measure_value",
            "numeric_value",
        )
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if observed is None:
            continue
        unit = str(
            _property(
                properties,
                "unit_of_measure",
                "unit_code",
                "measurement_unit",
                "unit",
            )
            or "unknown"
        )
        approval = str(_property(properties, "approval_status", "approval", "qualifier") or "")
        qa_status = (
            "accepted"
            if approval.lower() in {"a", "approved", "accepted"}
            else "provisional"
        )
        record_id = str(feature.get("id") or "")
        if not record_id:
            record_id = f"{site_id}:{parameter}:{observed.isoformat()}:{index}"
        output.append(
            build_observation(
                source_id=source.source_id,
                source_record_id=record_id,
                source_hash=source.sha256,
                provider="USGS Water Data OGC",
                location_id=site_id,
                metric=metric,
                value=value,
                unit=unit,
                observed_at=observed,
                window_id=f"USGS_OGC_{observed.strftime('%Y%m%d')}",
                qa_status=qa_status,
                method="USGS Water Data OGC API",
                notes=f"parameter_code={parameter};approval={approval}",
            )
        )
    return output


def _first_present(row: dict[str, str], *names: str) -> str:
    lower = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lower.get(name.lower())
        if value not in (None, ""):
            return str(value)
    return ""


def _characteristic_to_metric(value: str) -> str | None:
    for pattern, metric in WQ_CHARACTERISTIC_MAP:
        if pattern.search(value.strip()):
            return metric
    return None


def parse_wqx3_csv(
    body: bytes,
    source: FetchReceipt,
    expected_site: str,
) -> list[dict[str, Any]]:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    if not text.strip() or text.lstrip().startswith(("{", "<")):
        return []
    output: list[dict[str, Any]] = []
    for index, row in enumerate(csv.DictReader(io.StringIO(text)), start=1):
        site = _first_present(
            row,
            "MonitoringLocationIdentifier",
            "Monitoring Location Identifier",
            "MonitoringLocationID",
        ).removeprefix("USGS-")
        if site != expected_site:
            continue
        characteristic = _first_present(row, "CharacteristicName", "Characteristic Name")
        metric = _characteristic_to_metric(characteristic)
        if not metric:
            continue
        date = _first_present(row, "ActivityStartDate", "Activity Start Date")
        time = _first_present(row, "ActivityStartTime/Time", "ActivityStartTime")
        observed = parse_datetime(f"{date}T{time}" if date and time else date)
        raw_value = _first_present(row, "ResultMeasureValue", "Result Measure Value")
        try:
            value: float | str = float(raw_value)
        except ValueError:
            if not raw_value:
                continue
            value = raw_value
        if observed is None:
            continue
        unit = _first_present(
            row,
            "ResultMeasure/MeasureUnitCode",
            "ResultMeasureMeasureUnitCode",
            "Result Measure Unit Code",
        ) or "unknown"
        record_id = _first_present(row, "ResultIdentifier", "Result ID", "ActivityIdentifier")
        if not record_id:
            record_id = f"{expected_site}:{metric}:{observed.isoformat()}:{index}"
        output.append(
            build_observation(
                source_id=source.source_id,
                source_record_id=record_id,
                source_hash=source.sha256,
                provider="USGS/WQP-WQX3",
                location_id=expected_site,
                metric=metric,
                value=value,
                unit=unit,
                observed_at=observed,
                window_id=f"WQX3_{expected_site}_{observed.strftime('%Y%m%d')}",
                qa_status="provisional",
                method=_first_present(
                    row,
                    "ResultAnalyticalMethod/MethodName",
                    "ResultAnalyticalMethodName",
                )
                or None,
                notes=f"characteristic={characteristic}",
            )
        )
    return output
