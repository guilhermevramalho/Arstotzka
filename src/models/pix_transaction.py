from sqlalchemy import BigInteger, Column, Computed, DateTime, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import relationship
from models.base import Base


class PixTransaction(Base):
    __tablename__ = "pix_transaction"
    id = Column(BigInteger, primary_key=True)
    pix_id = Column(Text, nullable=False, unique=True)
    payload_hash = Column(Text, nullable=False)
    raw_payload = Column(JSONB, nullable=False)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    local_hour = Column(SmallInteger, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_branch = Column(Text, nullable=False)
    source_account_number = Column(Text, nullable=False)
    source_document = Column(Text, nullable=False)
    source_opening_date = Column(DateTime(timezone=True), nullable=False)
    source_account_key = Column(Text, Computed("source_branch || ':' || source_account_number"))
    source_person_type = Column(Text, Computed("CASE WHEN length(source_document) = 11 THEN 'PF' ELSE 'PJ' END"))
    dest_participant = Column(Text, nullable=False)
    dest_branch = Column(Text, nullable=False)
    dest_account_number = Column(Text, nullable=False)
    dest_document = Column(Text, nullable=False)
    dest_opening_date = Column(DateTime(timezone=True), nullable=False)
    dest_account_key = Column(Text, Computed("dest_participant || ':' || dest_branch || ':' || dest_account_number"))
    dest_person_type = Column(Text, Computed("CASE WHEN length(dest_document) = 11 THEN 'PF' ELSE 'PJ' END"))
    device_id = Column(Text, nullable=False)
    channel = Column(Text, nullable=False)
    ip = Column(INET, nullable=False)
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    analysis = relationship("RiskAnalysis", back_populates="pix_transaction", uselist=False, lazy="selectin")
