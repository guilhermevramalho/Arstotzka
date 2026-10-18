from typing import Tuple
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import PixAnalysisDTO
from engine.decision import build_metadata, evaluate
from errors import ConflictingPixId, NotFoundPixTransaction
from models import PixTransaction
from repositories import PixTransactionRepository
from utils.pix_payload import payload_hash, to_pix_data


class PixTransactionController(BaseController):
    """Recebe um Pix, decide e grava. Aqui mora o "pode" e o "não pode"."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repository = PixTransactionRepository(self.context)

    def analyze(self, payload: dict) -> Tuple[dict, bool]:
        """Devolve (resposta, criou_agora).

        criou_agora = False quando é um reenvio do mesmo Pix: a resposta é
        a análise original, sem rodar as regras de novo e sem contar o Pix
        duas vezes no histórico.

        A ordem é a regra:
          1. converte o payload (422 se a data não existe ou o IP é inválido);
          2. trava o pagador — Pix simultâneos dele passam um de cada vez;
          3. com a trava, confere idempotência (mesmo id: devolve ou 409);
          4. lê o histórico, roda o motor;
          5. grava fato + decisão + motivos e faz UM commit, que solta a trava.
        """
        pix = to_pix_data(payload)
        current_hash = payload_hash(payload)

        self.pix_repository.lock_payer(pix.source_document)

        existing = self.pix_repository.get_by_pix_id(pix.pix_id)
        if existing is not None:
            return self._replay_or_conflict(existing, current_hash, pix.pix_id), False

        history = self.pix_repository.get_history_snapshot(pix)
        decision = evaluate(pix, history)
        metadata = build_metadata(decision)

        self.logger.info(
            f"Pix {pix.pix_id}: {decision.status} (score {decision.score}, "
            f"regras {[hit.rule_code for hit in decision.hits]})"
        )

        try:
            transaction = self.pix_repository.create_transaction(pix, current_hash, payload)
            analysis = self.pix_repository.create_analysis(transaction, str(uuid4()), decision, metadata)
            response = PixAnalysisDTO.obj_to_dict(analysis)
            self.session.commit()
        except IntegrityError:
            # O mesmo id chegou ao mesmo tempo vindo de OUTRO pagador (a
            # trava é por pagador, então não serializou). A UNIQUE do
            # pix_id barrou o segundo: desfaz e responde pelo que ficou.
            self.session.rollback()
            existing = self.pix_repository.get_by_pix_id(pix.pix_id)
            if existing is None:
                raise
            return self._replay_or_conflict(existing, current_hash, pix.pix_id), False

        return response, True

    def get_by_pix_id(self, pix_id: str) -> dict:
        transaction = self.pix_repository.get_by_pix_id(pix_id)

        if transaction is None or transaction.analysis is None:
            raise NotFoundPixTransaction(pix_id)

        return PixAnalysisDTO.obj_to_dict(transaction.analysis)

    def _replay_or_conflict(self, existing: PixTransaction, current_hash: str, pix_id: str) -> dict:
        if existing.payload_hash != current_hash:
            raise ConflictingPixId(pix_id)

        return PixAnalysisDTO.obj_to_dict(existing.analysis)
