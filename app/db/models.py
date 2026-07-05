import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


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


class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(nullable=False)
    seats: Mapped[int] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (CheckConstraint("seats > 0", name="ck_table_seats_positive"),)


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("party_size > 0", name="ck_reservation_party_positive"),
        CheckConstraint("ends_at > starts_at", name="ck_reservation_time_order"),
        Index("idx_reservations_table_time", "table_id", "starts_at"),
        # The overlap-prevention EXCLUDE constraint lives in schema.sql / the
        # Alembic migration — SQLAlchemy's ORM layer can't express EXCLUDE USING gist.
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("restaurant_tables.id", ondelete="RESTRICT"))
    party_size: Mapped[int] = mapped_column(nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="confirmed")
    source: Mapped[str] = mapped_column(default="ai_call")
    special_requests: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="reservations")
    table: Mapped["RestaurantTable"] = relationship()


class PhoneCall(Base):
    __tablename__ = "phone_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_sid: Mapped[str] = mapped_column(unique=True, nullable=False)
    from_number: Mapped[str] = mapped_column(nullable=False)
    ivr_choice: Mapped[str | None]
    outcome: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None]

    logs: Mapped[list["CallLog"]] = relationship(back_populates="call")


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("phone_calls.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(nullable=False)  # caller | agent | tool
    content: Mapped[str] = mapped_column(nullable=False)
    tool_name: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    call: Mapped["PhoneCall"] = relationship(back_populates="logs")
