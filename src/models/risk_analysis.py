from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from models.base import Base


class RiskAnalysis(Base):
    __tablename__ = "risk_analysis"
    id = Column(BigInteger, primary_key=True)
    pix_transaction_id = Column(BigInteger, ForeignKey("pix_transaction.id"), nullable=False, unique=True)
    analysis_key = Column(UUID(as_uuid=False), nullable=False, unique=True)
    status = Column(Text, nullable=False)
    score = Column(Integer, nullable=False)
    decided_by = Column(Text, nullable=False)
    rules_version = Column(Text, nullable=False)
    analysis_metadata = Column("metadata", JSONB, nullable=False)
    analyzed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    pix_transaction = relationship("PixTransaction", back_populates="analysis")
    rule_hits = relationship("FraudRuleHit", back_populates="analysis", lazy="selectin")
