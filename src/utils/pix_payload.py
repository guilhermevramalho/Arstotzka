"""Do payload cru (já validado pelo JSON Schema) para o PixData do motor.

O schema garantiu o FORMATO. Aqui sobra o que formato não sabe dizer:
se a data existe no calendário e se o IP é um endereço de verdade.
"""

import hashlib
import ipaddress
import json
from datetime import datetime

from engine.types import PixData
from errors import InvalidDateTime, InvalidIpAddress


def payload_hash(payload: dict) -> str:
    """SHA-256 do payload em forma canônica (chaves ordenadas, sem espaços).

    A mesma requisição reenviada gera o mesmo hash mesmo que as chaves
    venham em outra ordem. É o que separa "reenvio" (devolve o original)
    de "mesmo id, outro conteúdo" (409).
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def only_digits(document_number: str) -> str:
    return "".join(character for character in document_number if character.isdigit())


def parse_datetime(field: str, value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise InvalidDateTime(field, value)


def parse_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise InvalidIpAddress(value)


def to_pix_data(payload: dict) -> PixData:
    source_account = payload["source_account"]
    destination_account = payload["destination_account"]
    source = payload["source"]
    geolocation = source.get("geolocation") or {}

    transaction_date = parse_datetime("transaction_date", payload["transaction_date"])

    latitude = geolocation.get("latitude")
    longitude = geolocation.get("longitude")

    return PixData(
        pix_id=payload["id"],
        amount=int(payload["amount"]),   # 150000.0 também é inteiro para o JSON Schema
        transaction_date=transaction_date,
        # Hora no fuso que veio no payload: 22:15-03:00 é 22h, noite.
        local_hour=transaction_date.hour,
        source_branch=source_account["branch"],
        source_account_number=source_account["account_number"],
        source_document=only_digits(source_account["owner"]["document_number"]),
        source_opening_date=parse_datetime("source_account.opening_date", source_account["opening_date"]),
        dest_participant=destination_account["participant"],
        dest_branch=destination_account["branch"],
        dest_account_number=destination_account["account_number"],
        dest_document=only_digits(destination_account["owner"]["document_number"]),
        dest_opening_date=parse_datetime("destination_account.opening_date", destination_account["opening_date"]),
        device_id=source["device_id"],
        channel=source["channel"],
        ip=parse_ip(source["ip"]),
        latitude=float(latitude) if latitude is not None else None,
        longitude=float(longitude) if longitude is not None else None,
    )
