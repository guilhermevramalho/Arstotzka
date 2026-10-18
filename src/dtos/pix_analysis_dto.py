from copy import deepcopy
from models import RiskAnalysis


class PixAnalysisDTO:

    @staticmethod
    def obj_to_dict(analysis: RiskAnalysis) -> dict:
        return {
            "key": str(analysis.analysis_key),
            "status": analysis.status,
            "metadata": deepcopy(analysis.analysis_metadata),
        }
