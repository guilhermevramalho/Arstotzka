from datetime import timedelta
import pytest
from utils.geo import haversine_km
from errors import InvalidDateTime, InvalidIpAddress
from utils.pix_payload import only_digits, payload_hash, to_pix_data


def pdf_payload() -> dict:
    return {
        "id": "pix-000123",
        "amount": 150000,
        "transaction_date": "2026-10-17T22:15:00-03:00",
        "source_account": {
            "branch": "0001",
            "account_number": "88213",
            "opening_date": "2025-03-02T10:00:00-03:00",
            "owner": {"document_number": "123.456.789-09"},
        },
        "destination_account": {
            "participant": "60701190",
            "branch": "3675",
            "account_number": "10442",
            "opening_date": "2026-10-10T09:00:00-03:00",
            "owner": {"document_number": "987.654.321-00"},
        },
        "source": {
            "device_id": "dvc-9f2c71a8",
            "channel": "app",
            "ip": "198.51.100.23",
            "geolocation": {"latitude": -23.56, "longitude": -46.65},
        },
    }


def test_hash_ignores_key_order():
    payload = pdf_payload()
    reordered = dict(reversed(list(payload.items())))
    assert payload_hash(payload) == payload_hash(reordered)


def test_hash_changes_with_content():
    other = pdf_payload()
    other["amount"] = 150001
    assert payload_hash(pdf_payload()) != payload_hash(other)


def test_documents_are_normalized_to_digits():
    assert only_digits("123.456.789-09") == "12345678909"
    assert only_digits("11.222.333/0001-81") == "11222333000181"


def test_pdf_payload_conversion():
    pix = to_pix_data(pdf_payload())
    assert pix.amount == 150000
    assert pix.local_hour == 22
    assert pix.is_night is True
    assert pix.source_document == "12345678909"
    assert pix.source_person_type == "PF"
    assert pix.dest_account_key == "60701190:3675:10442"
    assert pix.transaction_date.utcoffset() == timedelta(hours=-3)
    assert round(pix.dest_account_age_seconds / 86400, 2) == 7.55


def test_local_hour_comes_from_payload_offset():
    payload = pdf_payload()
    payload["transaction_date"] = "2026-10-18T01:15:00+00:00"
    assert to_pix_data(payload).local_hour == 1


def test_geolocation_is_optional():
    payload = pdf_payload()
    del payload["source"]["geolocation"]
    assert to_pix_data(payload).has_geolocation is False
    payload["source"]["geolocation"] = None
    assert to_pix_data(payload).has_geolocation is False


def test_impossible_date_raises_422_error():
    payload = pdf_payload()
    payload["transaction_date"] = "2026-02-30T10:00:00-03:00"
    with pytest.raises(InvalidDateTime):
        to_pix_data(payload)


def test_invalid_ip_raises_422_error():
    payload = pdf_payload()
    payload["source"]["ip"] = "999.1.1.1"
    with pytest.raises(InvalidIpAddress):
        to_pix_data(payload)


def test_haversine_sao_paulo_rio():
    assert 350 < haversine_km(-23.5505, -46.6333, -22.9068, -43.1729) < 365
