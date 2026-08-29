"""Per-type cursor for the central company asset catalog."""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin


class CompanyAssetCheckpoint(TimestampMixin, Base):
    __tablename__ = "company_asset_checkpoints"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    cursor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
