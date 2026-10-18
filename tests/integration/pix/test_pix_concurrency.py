"""O principal desafio: Pix simultâneos do mesmo pagador.

Sem a trava por pagador, as dez análises abaixo leriam todas "nenhum Pix
recente" ao mesmo tempo e aprovariam as dez. Com a trava, elas passam uma
de cada vez: 1º e 2º aprovados; 3º e 4º somam VEL_01 (45) + VEL_03 (40) e
são rejeitados; do 5º em diante VEL_01/VEL_03 eliminam direto.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from tests.utils import PayloadGenerator, RandomGenerator, RequestGenerator
from tests.utils.payload_generator import BRT

T0 = datetime(2026, 10, 15, 14, 0, tzinfo=BRT)


def post_all_at_once(payloads):
    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        return list(pool.map(RequestGenerator.POST_pix_transaction, payloads))


class TestPixConcurrency:
    def test_simultaneous_burst_from_same_payer_is_serialized(self):
        payer = RandomGenerator.generate_cpf()
        payloads = [PayloadGenerator.pix_payload(payer_document=payer, amount=1000 + i, transaction_date=T0) for i in range(10)]

        results = post_all_at_once(payloads)

        assert [status for status, _ in results] == [201] * 10
        decisions = Counter(response["status"] for _, response in results)
        assert decisions == {"approved": 2, "rejected": 8}

    def test_same_pix_sent_in_parallel_is_analyzed_once(self):
        payload = PayloadGenerator.pix_payload(transaction_date=T0)

        results = post_all_at_once([payload] * 6)

        statuses = sorted(status for status, _ in results)
        assert statuses == [200, 200, 200, 200, 200, 201]
        assert len({response["key"] for _, response in results}) == 1
