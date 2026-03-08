"""SQLAlchemy async models for ONI Cortex multi-tenant system."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(64), nullable=False)
    plan = Column(String(50), nullable=False, default="free")
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    api_key_live = Column(String(255), unique=True, nullable=False)
    api_key_test = Column(String(255), unique=True, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    collections = relationship("TenantCollection", back_populates="tenant")
    usage_records = relationship("UsageRecord", back_populates="tenant")


class TenantCollection(Base):
    __tablename__ = "tenant_collections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "collection_name", name="uq_tenant_collection"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    collection_name = Column(String(255), nullable=False)
    data_type = Column(String(100), nullable=True)
    vector_count = Column(Integer, nullable=False, default=0)
    config = Column(Text, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="collections")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        String(36), ForeignKey("tenants.id"), nullable=False, index=True
    )
    metric = Column(String(100), nullable=False)
    count = Column(Integer, nullable=False, default=0)
    recorded_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="usage_records")
