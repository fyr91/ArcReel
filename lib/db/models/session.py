"""Agent session ORM model."""

from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin, UserOwnedMixin


class AgentSession(TimestampMixin, UserOwnedMixin, Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sdk_session_id: Mapped[str] = mapped_column(String, unique=True)
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    # NULL 表示项目级会话；正整数表示会话固定聚焦该分集。作用域在建行时确定，
    # 后续不随前端路由变化，避免同一段历史对话在切集后被重新解释。
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String, server_default="")
    status: Mapped[str] = mapped_column(String, server_default="idle")
    # 分支会话指针：非空即表示本会话已被改写分叉取代（见 docs/adr/0058）。
    # 指针即标记，不占用 status——status 承载生命周期，闲置驱逐与启动期
    # interrupt 都按它运转。
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    # 分叉血统：本会话是从哪个会话的哪条消息处分叉出来的，建行时写入即不再变化。
    # fork_anchor_uuid 取 transcript 域——锚点消息本身不随前缀复制、只留在原会话，
    # 而同一条历史消息在所有分支里的 transcript uuid 相同，跨分支对齐由此免费。
    fork_parent_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fork_anchor_uuid: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_agent_sessions_project", "project_name", "updated_at"),
        Index("idx_agent_sessions_project_episode", "project_name", "episode", "updated_at"),
        Index("idx_agent_sessions_status", "status"),
    )
