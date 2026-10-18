"""O contrato da API: formato, status HTTP, persistência e idempotência."""

from sqlalchemy import create_engine, text

from tests.utils import DbUtils, PayloadGenerator, RandomGenerator, RequestGenerator


def rule_ids(response: dict) -> list:
    return [rule["rule_id"] for rule in response["metadata"]["triggered_rules"]]


class TestPixContract:
    def test_post_returns_contract_and_get_returns_same_analysis(self):
        payload = PayloadGenerator.pix_payload()

        status, created = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert set(created.keys()) == {"key", "status", "metadata"}
        assert created["status"] == "approved"
        assert created["metadata"]["score"] == 0
        assert created["metadata"]["triggered_rules"] == []

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])
        assert status == 200
        assert fetched == created

    def test_pdf_example_payload(self):
        payload = PayloadGenerator.pix_payload(amount=150000)
        payload["transaction_date"] = "2026-10-17T22:15:00-03:00"

        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert response["status"] == "two_factor_required"
        assert rule_ids(response) == ["LIM_02"]

    def test_every_analysis_is_persisted_with_its_rule_hits(self):
        payload = PayloadGenerator.pix_payload(amount=600000)   # LIM_01: +45

        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        engine = create_engine(DbUtils.database_url())
        try:
            with engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT a.status, a.score, a.decided_by, a.rules_version, t.amount, t.raw_payload "
                    "FROM risk_analysis a JOIN pix_transaction t ON t.id = a.pix_transaction_id "
                    "WHERE a.analysis_key = :key"), {"key": response["key"]}).one()
                hits = connection.execute(text(
                    "SELECT h.rule_code, h.points FROM fraud_rule_hit h "
                    "JOIN risk_analysis a ON a.id = h.risk_analysis_id WHERE a.analysis_key = :key"),
                    {"key": response["key"]}).all()
        finally:
            engine.dispose()

        assert (row.status, row.score, row.decided_by) == ("two_factor_required", 45, "score")
        assert row.rules_version == response["metadata"]["policy_version"]
        assert row.amount == 600000
        assert row.raw_payload == payload
        assert [(hit.rule_code, hit.points) for hit in hits] == [("LIM_01", 45)]

    def test_resend_same_payload_returns_original_analysis(self):
        payload = PayloadGenerator.pix_payload()

        status, first = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        status, second = RequestGenerator.POST_pix_transaction(payload)
        assert status == 200
        assert second == first

        reordered = dict(reversed(list(payload.items())))
        status, third = RequestGenerator.POST_pix_transaction(reordered)
        assert status == 200
        assert third["key"] == first["key"]

    def test_resend_does_not_count_twice_in_history(self):
        payer = PayloadGenerator.pix_payload()["source_account"]["owner"]["document_number"]
        payload = PayloadGenerator.pix_payload(payer_document=payer)

        RequestGenerator.POST_pix_transaction(payload)
        RequestGenerator.POST_pix_transaction(payload)
        RequestGenerator.POST_pix_transaction(payload)

        # Se o reenvio contasse, este seria o 4º Pix em 2 min (VEL_01).
        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix_payload(payer_document=payer))
        assert status == 201
        assert "VEL_01" not in rule_ids(response)

    def test_same_id_with_different_content_is_conflict(self):
        payload = PayloadGenerator.pix_payload()
        status, original = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

        changed = dict(payload, amount=payload["amount"] + 1)
        status, response = RequestGenerator.POST_pix_transaction(changed)
        assert status == 409
        assert response["code"] == "QIT002002"

        status, fetched = RequestGenerator.GET_pix_transaction(payload["id"])
        assert fetched == original

    def test_get_unknown_id_is_404(self):
        status, response = RequestGenerator.GET_pix_transaction("pix-que-nao-existe")
        assert status == 404
        assert response["code"] == "QIT002001"

    def test_masked_and_unmasked_document_are_the_same_payer(self):
        masked = PayloadGenerator.pix_payload()["source_account"]["owner"]["document_number"]
        digits = masked.replace(".", "").replace("-", "")

        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix_payload(payer_document=masked))
        RequestGenerator.POST_pix_transaction(PayloadGenerator.pix_payload(payer_document=digits))
        status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix_payload(payer_document=masked))

        assert status == 201
        assert "VEL_01" in rule_ids(response)   # 3º Pix do MESMO pagador em 2 min

    def test_geolocation_absent_or_null_is_accepted(self):
        status, _ = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix_payload(geo=None))
        assert status == 201

        payload = PayloadGenerator.pix_payload()
        payload["source"]["geolocation"] = None
        status, _ = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201

    def test_cnpj_payer_is_accepted(self):
        payload = PayloadGenerator.pix_payload(payer_document=RandomGenerator.generate_cnpj(), amount=3_000_000)
        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 201
        assert rule_ids(response) == ["LIM_01"]   # PJ: R$ 30 mil está acima da atenção (25 mil), abaixo do teto


class TestPixInvalidPayload:
    def assert_bad_request(self, payload):
        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 400, response
        assert response["code"] == "QIT000001"

    def test_empty_body(self):
        self.assert_bad_request({})

    def test_missing_required_field(self):
        payload = PayloadGenerator.pix_payload()
        del payload["source"]["device_id"]
        self.assert_bad_request(payload)

    def test_unknown_field(self):
        payload = PayloadGenerator.pix_payload()
        payload["campo_extra"] = 1
        self.assert_bad_request(payload)

    def test_amount_must_be_positive_integer(self):
        for amount in [0, -100, 10.5, "100"]:
            self.assert_bad_request(PayloadGenerator.pix_payload(amount=amount))

    def test_date_must_have_timezone(self):
        payload = PayloadGenerator.pix_payload()
        payload["transaction_date"] = "2026-10-17T22:15:00"
        self.assert_bad_request(payload)

    def test_document_must_be_cpf_or_cnpj_shaped(self):
        payload = PayloadGenerator.pix_payload()
        payload["source_account"]["owner"]["document_number"] = "123.456"
        self.assert_bad_request(payload)

    def test_participant_must_have_8_digits(self):
        payload = PayloadGenerator.pix_payload()
        payload["destination_account"]["participant"] = "6070119"
        self.assert_bad_request(payload)

    def test_geolocation_needs_both_coordinates(self):
        payload = PayloadGenerator.pix_payload()
        payload["source"]["geolocation"] = {"latitude": -23.5}
        self.assert_bad_request(payload)

    def test_impossible_date_is_422(self):
        payload = PayloadGenerator.pix_payload()
        payload["transaction_date"] = "2026-02-30T10:00:00-03:00"
        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 422
        assert response["code"] == "QIT002003"

    def test_invalid_ip_is_422(self):
        payload = PayloadGenerator.pix_payload()
        payload["source"]["ip"] = "999.10.10.10"
        status, response = RequestGenerator.POST_pix_transaction(payload)
        assert status == 422
        assert response["code"] == "QIT002004"
