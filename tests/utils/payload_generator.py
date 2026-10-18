from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import uuid4
from tests.utils.random_generator import RandomGenerator

BRT = timezone(timedelta(hours=-3))
DEFAULT_GEO = (-23.5505, -46.6333)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class PayloadGenerator:

    @staticmethod
    def pix_payload(
        amount: int = 10000,
        transaction_date: Optional[datetime] = None,
        payer_document: Optional[str] = None,
        receiver_document: Optional[str] = None,
        dest_account_number: Optional[str] = None,
        dest_opening_date: Optional[datetime] = None,
        source_opening_date: Optional[datetime] = None,
        device_id: Optional[str] = None,
        geo: Optional[Tuple[float, float]] = DEFAULT_GEO,
        pix_id: Optional[str] = None,
    ) -> dict:
        if transaction_date is None:
            transaction_date = datetime(2026, 10, 15, 14, 0, tzinfo=BRT)
        payer_document = payer_document or RandomGenerator.generate_cpf()
        if device_id is None:
            device_id = "dvc-" + "".join((c for c in payer_document if c.isdigit()))
        payload = {
            "id": pix_id or f"pix-{uuid4()}",
            "amount": amount,
            "transaction_date": iso(transaction_date),
            "source_account": {
                "branch": "0001",
                "account_number": "88213",
                "opening_date": iso(source_opening_date or datetime(2024, 1, 10, 10, 0, tzinfo=BRT)),
                "owner": {"document_number": payer_document},
            },
            "destination_account": {
                "participant": "60701190",
                "branch": "3675",
                "account_number": dest_account_number or RandomGenerator.generate_account_number(),
                "opening_date": iso(dest_opening_date or datetime(2023, 5, 2, 9, 0, tzinfo=BRT)),
                "owner": {"document_number": receiver_document or RandomGenerator.generate_cpf()},
            },
            "source": {"device_id": device_id, "channel": "app", "ip": "198.51.100.23"},
        }
        if geo is not None:
            payload["source"]["geolocation"] = {"latitude": geo[0], "longitude": geo[1]}
        return payload
