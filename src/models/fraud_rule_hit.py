from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base


class FraudRuleHit(Base):
    """O porquê: uma regra que disparou numa análise, com a evidência (imutável)."""

    __tablename__ = "fraud_rule_hit"

    id = Column(BigInteger, primary_key=True)
    risk_analysis_id = Column(BigInteger, ForeignKey("risk_analysis.id"), nullable=False)
    rule_code = Column(Text, nullable=False)
    rule_family = Column(Text, nullable=False)
    points = Column(Integer, nullable=False)
    is_hard_reject = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=False)
    evidence = Column(JSONB, nullable=False)

    analysis = relationship("RiskAnalysis", back_populates="rule_hits")
