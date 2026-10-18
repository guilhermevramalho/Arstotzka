"""As regras de histórico de ponta a ponta: o histórico é montado com POSTs
de verdade e o banco é quem responde as janelas de tempo.

Os cenários de valor-limite de cada regra estão em tests/unit (motor puro).
Aqui o que se prova é que o REPOSITÓRIO monta o histórico certo: quais
status contam, quais janelas, por pagador, por destino e por dispositivo.
"""

from datetime import datetime, timedelta

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator
from tests.utils.payload_generator import BRT

T0 = datetime(2026, 10, 15, 14, 0, tzinfo=BRT)
RIO = (-22.9068, -43.1729)


def post(**kwargs) -> dict:
    status, response = RequestGenerator.POST_pix_transaction(PayloadGenerator.pix_payload(**kwargs))
    assert status == 201, response
    return response


def rules(response: dict) -> dict:
    return {rule["rule_id"]: rule["points"] for rule in response["metadata"]["triggered_rules"]}


def new_payer() -> str:
    return RandomGenerator.generate_cpf()


class TestVelocity:
    def test_burst_to_different_destinations(self):
        payer = new_payer()

        first = post(payer_document=payer, transaction_date=T0)
        second = post(payer_document=payer, transaction_date=T0 + timedelta(seconds=30))
        third = post(payer_document=payer, transaction_date=T0 + timedelta(seconds=60))

        assert first["status"] == second["status"] == "approved"
        assert rules(third) == {"VEL_01": 45, "VEL_03": 40}
        assert third["status"] == "rejected"

    def test_identical_repetition(self):
        payer = new_payer()
        dest = RandomGenerator.generate_account_number()

        post(payer_document=payer, dest_account_number=dest, amount=25_000, transaction_date=T0)
        repeated = post(payer_document=payer, dest_account_number=dest, amount=25_000, transaction_date=T0 + timedelta(seconds=40))

        assert repeated["status"] == "rejected"
        assert rules(repeated) == {"VEL_02": 0}

    def test_old_attempts_leave_the_window(self):
        payer = new_payer()

        post(payer_document=payer, transaction_date=T0)
        post(payer_document=payer, transaction_date=T0 + timedelta(seconds=10))
        later = post(payer_document=payer, transaction_date=T0 + timedelta(minutes=11))

        assert later["status"] == "approved"
        assert rules(later) == {}


class TestAmount:
    def test_accumulation_in_one_hour(self):
        payer = new_payer()

        post(payer_document=payer, amount=300_000, transaction_date=T0)
        second = post(payer_document=payer, amount=150_000, transaction_date=T0 + timedelta(minutes=20))

        assert rules(second) == {"MON_01": 40}

    def test_rejected_pix_does_not_add_to_amount(self):
        payer = new_payer()

        blocked = post(payer_document=payer, amount=1_600_000, transaction_date=T0)     # LIM_01: teto PF
        assert blocked["status"] == "rejected"

        after = post(payer_document=payer, amount=400_000, transaction_date=T0 + timedelta(minutes=20))
        assert "MON_01" not in rules(after)


class TestProfile:
    def test_amount_far_above_customer_average(self):
        payer = new_payer()
        device = "dvc-perfil-" + payer

        for days_ago in (20, 10, 5):
            post(payer_document=payer, device_id=device, amount=10_000, transaction_date=T0 - timedelta(days=days_ago))

        outlier = post(payer_document=payer, device_id=device, amount=150_000, transaction_date=T0)

        assert rules(outlier) == {"PRF_01": 50}       # R$ 1.500 > 8 x R$ 100
        assert outlier["status"] == "two_factor_required"

    def test_new_device_for_customer_with_history(self):
        payer = new_payer()

        post(payer_document=payer, device_id="dvc-antigo-" + payer, transaction_date=T0 - timedelta(days=3))
        on_new_device = post(payer_document=payer, device_id="dvc-novo-" + payer, amount=50_000, transaction_date=T0)

        assert rules(on_new_device) == {"PRF_02": 30}

    def test_shared_device(self):
        device = "dvc-compartilhado-" + new_payer()

        post(device_id=device, transaction_date=T0)
        post(device_id=device, transaction_date=T0 + timedelta(hours=1))
        third_owner = post(device_id=device, transaction_date=T0 + timedelta(hours=2))

        assert rules(third_owner) == {"PRF_03": 45}

    def test_impossible_travel(self):
        payer = new_payer()
        device = "dvc-viagem-" + payer

        post(payer_document=payer, device_id=device, transaction_date=T0)                       # São Paulo
        in_rio = post(payer_document=payer, device_id=device, geo=RIO, transaction_date=T0 + timedelta(minutes=30))

        assert rules(in_rio) == {"PRF_04": 45}        # ~357 km em 30 min ≈ 714 km/h: acima de 300, abaixo de 800


class TestCounterparty:
    def test_known_counterparty_reduces_score(self):
        payer = new_payer()
        landlord = RandomGenerator.generate_account_number()
        device = "dvc-aluguel-" + payer

        post(payer_document=payer, device_id=device, dest_account_number=landlord, amount=250_000, transaction_date=T0 - timedelta(days=30))
        rent = post(payer_document=payer, device_id=device, dest_account_number=landlord, amount=600_000, transaction_date=T0)

        assert rules(rent) == {"LIM_01": 45, "CTP_03": -25}
        assert rent["status"] == "approved"

    def test_relationship_younger_than_24h_does_not_count(self):
        payer = new_payer()
        dest = RandomGenerator.generate_account_number()

        post(payer_document=payer, dest_account_number=dest, transaction_date=T0 - timedelta(hours=2))
        again = post(payer_document=payer, dest_account_number=dest, amount=600_000, transaction_date=T0)

        assert "CTP_03" not in rules(again)

    def test_many_payers_to_same_person(self):
        mule_account = RandomGenerator.generate_account_number()
        mule_document = RandomGenerator.generate_cpf()

        responses = [
            post(dest_account_number=mule_account, receiver_document=mule_document, transaction_date=T0 + timedelta(minutes=i))
            for i in range(5)
        ]

        assert [r["status"] for r in responses[:4]] == ["approved"] * 4
        assert rules(responses[4]) == {"CTP_02": 40}

    def test_store_receiving_from_many_customers_is_normal(self):
        store_account = RandomGenerator.generate_account_number()
        store_document = RandomGenerator.generate_cnpj()

        responses = [
            post(dest_account_number=store_account, receiver_document=store_document, transaction_date=T0 + timedelta(minutes=i))
            for i in range(6)
        ]

        assert all(r["status"] == "approved" for r in responses)
