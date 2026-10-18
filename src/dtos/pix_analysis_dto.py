from copy import deepcopy

from models import RiskAnalysis


class PixAnalysisDTO:
    """A resposta do contrato: só três campos — key, status e metadata.

    O metadata devolvido é EXATAMENTE o que foi gravado na análise: o GET
    mostra o que o POST respondeu, sem recalcular nada.
    """

    @staticmethod
    def obj_to_dict(analysis: RiskAnalysis) -> dict:
        return {
            "key": str(analysis.analysis_key),
            "status": analysis.status,
            "metadata": deepcopy(analysis.analysis_metadata),
        }
