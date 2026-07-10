import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # The database columns are all TIMESTAMPTZ (see schema.sql), so datetime
    # attributes must map to timezone-aware DateTime — otherwise asyncpg
    # rejects aware datetimes bound against naive-typed parameters.
    type_annotation_map = {datetime: DateTime(timezone=True)}


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("phone_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str | None]
    email: Mapped[str | None]
    notes: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="customer")


class CapacityLimit(Base):
    """A staff-defined window where the number of seated customers is capped
    (e.g. reduced capacity for a private event). Outside any window, the
    default capacity from settings applies. Overlapping windows: the lowest
    cap wins."""

    __tablename__ = "capacity_limits"
    __table_args__ = (
        CheckConstraint("max_customers >= 0", name="ck_capacity_limit_nonnegative"),
        CheckConstraint("ends_at > starts_at", name="ck_capacity_limit_time_order"),
        Index("idx_capacity_limits_time", "starts_at", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    max_customers: Mapped[int] = mapped_column(nullable=False)
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("party_size > 0", name="ck_reservation_party_positive"),
        CheckConstraint("ends_at > starts_at", name="ck_reservation_time_order"),
        Index("idx_reservations_time", "starts_at", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    party_size: Mapped[int] = mapped_column(nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="confirmed")
    source: Mapped[str] = mapped_column(default="ai_call")
    special_requests: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="reservations")


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (UniqueConstraint("username"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PhoneCall(Base):
    __tablename__ = "phone_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_sid: Mapped[str] = mapped_column(unique=True, nullable=False)
    from_number: Mapped[str] = mapped_column(nullable=False)
    ivr_choice: Mapped[str | None]
    outcome: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]
