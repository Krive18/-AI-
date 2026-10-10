from datetime import datetime

from sqlalchemy import Index
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, JSON, VARBINARY, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """Append-only audit event.

    The runtime database user should receive SELECT and INSERT only on this table;
    migrations use a separate deploy-time principal for schema changes.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_actor_id_created_at", "actor_id", "created_at"),
        Index(
            "idx_audit_log_resource_created_at",
            "resource_type",
            "resource_public_id",
            "created_at",
        ),
        {
            "comment": "Append-only security and operation audit events",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_engine": "InnoDB",
        },
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )
    actor_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="Logical actor account id"
    )
    action: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Stable audit action code"
    )
    resource_type: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Audited resource type"
    )
    resource_public_id: Mapped[str | None] = mapped_column(
        CHAR(26), nullable=True, comment="Audited resource public identifier"
    )
    request_id: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Correlated API request identifier"
    )
    ip_address: Mapped[bytes | None] = mapped_column(
        VARBINARY(16), nullable=True, comment="Packed IPv4 or IPv6 address"
    )
    before_data: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True, comment="Redacted state before the action"
    )
    after_data: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True, comment="Redacted state after the action"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC event timestamp"
    )
