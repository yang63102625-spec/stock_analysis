# -*- coding: utf-8 -*-
"""
Database manager core: singleton bookkeeping, engine/Session lifecycle,
schema migrations applied at first init.

Other concerns (daily data / news / analysis / picker / conversation /
LLM usage) live in dedicated mixin modules in this sub-package.
"""
from __future__ import annotations

import atexit
import logging
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_config

from .models import Base

logger = logging.getLogger(__name__)


class _DatabaseManagerCore:
    """Singleton + engine/session management. Other mixins extend this class."""

    _instance: Optional["_DatabaseManagerCore"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_url: Optional[str] = None):
        """
        初始化数据库管理器
        
        Args:
            db_url: 数据库连接 URL（可选，默认从配置读取）
        """
        if getattr(self, '_initialized', False):
            return
        
        if db_url is None:
            config = get_config()
            db_url = config.get_db_url()
        
        # 创建数据库引擎
        self._engine = create_engine(
            db_url,
            echo=False,  # 设为 True 可查看 SQL 语句
            pool_pre_ping=True,  # 连接健康检查
        )
        
        # 创建 Session 工厂
        self._SessionLocal = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
        )
        
        # 创建所有表
        Base.metadata.create_all(self._engine)

        # Migration: add picker_mode, picker_leader_bias_exempt_pct to picker_history
        try:
            from sqlalchemy import text
            with self._engine.connect() as conn:
                for sql in [
                    "ALTER TABLE picker_history ADD COLUMN picker_mode VARCHAR(20)",
                    "ALTER TABLE picker_history ADD COLUMN picker_leader_bias_exempt_pct FLOAT",
                    "ALTER TABLE picker_history ADD COLUMN picker_strategies_json TEXT",
                    "ALTER TABLE picker_history ADD COLUMN screened_pool_by_strategy_json TEXT",
                    "ALTER TABLE picker_backtest_history ADD COLUMN picker_strategies_json TEXT",
                    # Analysis history score dimension columns
                    "ALTER TABLE analysis_history ADD COLUMN trend_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN bias_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN volume_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN support_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN macd_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN rsi_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN capital_flow_score INTEGER DEFAULT 0",
                    # Analysis history: system-computed signal/regime + trade-level extras
                    "ALTER TABLE analysis_history ADD COLUMN signal_score INTEGER DEFAULT 0",
                    "ALTER TABLE analysis_history ADD COLUMN buy_signal VARCHAR(24)",
                    "ALTER TABLE analysis_history ADD COLUMN pe_ratio FLOAT",
                    "ALTER TABLE analysis_history ADD COLUMN market_environment VARCHAR(24)",
                    "ALTER TABLE analysis_history ADD COLUMN position_pct FLOAT",
                    "ALTER TABLE analysis_history ADD COLUMN risk_reward FLOAT",
                    "ALTER TABLE analysis_history ADD COLUMN take_profit_2_rule TEXT",
                    # v2 backtest engine: signal snapshot + dim snapshot + sim diagnostics
                    "ALTER TABLE backtest_results ADD COLUMN signal_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN buy_signal_at_eval VARCHAR(24)",
                    "ALTER TABLE backtest_results ADD COLUMN market_environment_at_eval VARCHAR(24)",
                    "ALTER TABLE backtest_results ADD COLUMN strategy_id VARCHAR(32)",
                    "ALTER TABLE backtest_results ADD COLUMN risk_reward_at_eval FLOAT",
                    "ALTER TABLE backtest_results ADD COLUMN position_pct_at_eval FLOAT",
                    "ALTER TABLE backtest_results ADD COLUMN trend_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN bias_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN volume_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN support_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN macd_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN rsi_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN capital_flow_score_at_eval INTEGER",
                    "ALTER TABLE backtest_results ADD COLUMN exit_reason VARCHAR(32)",
                    "ALTER TABLE backtest_results ADD COLUMN hold_days INTEGER",
                    "ALTER TABLE backtest_summaries ADD COLUMN signal_breakdown_json TEXT",
                    "ALTER TABLE backtest_summaries ADD COLUMN score_bucket_breakdown_json TEXT",
                    "ALTER TABLE backtest_summaries ADD COLUMN exit_reason_breakdown_json TEXT",
                    "ALTER TABLE backtest_summaries ADD COLUMN regime_breakdown_json TEXT",
                    "ALTER TABLE backtest_summaries ADD COLUMN strategy_breakdown_json TEXT",
                    # Per-strategy backtest + engine_version drop: rebuild unique indexes.
                    # Old indexes are dropped, new ones created without engine_version.
                    "DROP INDEX IF EXISTS uix_backtest_analysis_window_version",
                    "DROP INDEX IF EXISTS uix_backtest_analysis_window_version_strategy",
                    (
                        "CREATE UNIQUE INDEX IF NOT EXISTS uix_backtest_analysis_window_strategy "
                        "ON backtest_results (analysis_history_id, eval_window_days, strategy_id)"
                    ),
                    "DROP INDEX IF EXISTS uix_backtest_summary_scope_code_window_version",
                    (
                        "CREATE UNIQUE INDEX IF NOT EXISTS uix_backtest_summary_scope_code_window "
                        "ON backtest_summaries (scope, code, eval_window_days)"
                    ),
                    # Drop legacy columns. SQLite 3.35+ supports DROP COLUMN.
                    "ALTER TABLE backtest_results DROP COLUMN engine_version",
                    "ALTER TABLE backtest_summaries DROP COLUMN engine_version",
                    "ALTER TABLE backtest_summaries DROP COLUMN advice_breakdown_json",
                ]:
                    try:
                        conn.execute(text(sql))
                        conn.commit()
                    except Exception:
                        pass  # Column may already exist

                # v3 backtest engine: AI-plan execution (no strategy override).
                # Order matters:
                #   1) ADD COLUMN (always safe)
                #   2) WIPE legacy v2 rows so the new unique index doesn't conflict
                #   3) DROP old strategy-keyed index + CREATE the v3 index
                for sql in [
                    "ALTER TABLE backtest_results ADD COLUMN entry_status VARCHAR(24)",
                    "ALTER TABLE backtest_results ADD COLUMN r_multiple FLOAT",
                    "ALTER TABLE backtest_results ADD COLUMN mae_pct FLOAT",
                    "ALTER TABLE backtest_results ADD COLUMN mfe_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN fill_rate_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN filled_count INTEGER DEFAULT 0",
                    "ALTER TABLE backtest_summaries ADD COLUMN not_filled_count INTEGER DEFAULT 0",
                    "ALTER TABLE backtest_summaries ADD COLUMN not_filled_limit_up_count INTEGER DEFAULT 0",
                    "ALTER TABLE backtest_summaries ADD COLUMN trade_win_rate_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN expectancy_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN avg_r_multiple FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN profit_factor FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN max_drawdown_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN avg_mae_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN avg_mfe_pct FLOAT",
                    "ALTER TABLE backtest_summaries ADD COLUMN ambiguous_count INTEGER DEFAULT 0",
                ]:
                    try:
                        conn.execute(text(sql))
                        conn.commit()
                    except Exception:
                        pass

                # One-shot wipe of v2 backtest rows (engine semantics changed in v3).
                try:
                    sentinel = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM backtest_summaries "
                            "WHERE scope = '__migration_marker__' AND code = 'engine_v3'"
                        )
                    ).scalar() or 0
                    if int(sentinel) == 0:
                        legacy_results = conn.execute(text("SELECT COUNT(*) FROM backtest_results")).scalar() or 0
                        legacy_summaries = conn.execute(
                            text(
                                "SELECT COUNT(*) FROM backtest_summaries "
                                "WHERE scope != '__migration_marker__'"
                            )
                        ).scalar() or 0
                        if int(legacy_results) + int(legacy_summaries) > 0:
                            logger.info(
                                "[Migration] One-shot wipe v3: backtest_results=%d backtest_summaries=%d",
                                int(legacy_results), int(legacy_summaries),
                            )
                            conn.execute(text("DELETE FROM backtest_results"))
                            conn.execute(
                                text(
                                    "DELETE FROM backtest_summaries "
                                    "WHERE scope != '__migration_marker__'"
                                )
                            )
                        conn.execute(
                            text(
                                "INSERT INTO backtest_summaries (scope, code, eval_window_days) "
                                "VALUES ('__migration_marker__', 'engine_v3', 0)"
                            )
                        )
                        conn.commit()
                except Exception as exc:
                    logger.debug("[Migration] v3 wipe skipped: %s", exc)

                # Now that legacy duplicate-strategy rows are gone, swap the unique index.
                for sql in [
                    "DROP INDEX IF EXISTS uix_backtest_analysis_window_strategy",
                    (
                        "CREATE UNIQUE INDEX IF NOT EXISTS uix_backtest_analysis_window "
                        "ON backtest_results (analysis_history_id, eval_window_days)"
                    ),
                ]:
                    try:
                        conn.execute(text(sql))
                        conn.commit()
                    except Exception:
                        pass

                # Fallback: SQLite refuses ALTER TABLE DROP COLUMN when the column is
                # referenced by an inline table-level UNIQUE constraint (vs a separate
                # CREATE INDEX). Older DBs created backtest_results / backtest_summaries
                # with `CONSTRAINT ... UNIQUE (..., engine_version)` baked into the table
                # definition; the DROP above silently fails and writes then crash with
                # `NOT NULL constraint failed: backtest_results.engine_version`. Detect
                # any leftover engine_version column and rebuild the table without it.
                try:
                    self._drop_legacy_engine_version_column(conn, "backtest_results")
                    self._drop_legacy_engine_version_column(conn, "backtest_summaries")
                except Exception as exc:
                    logger.warning("[Migration] engine_version cleanup skipped: %s", exc)

                # One-shot wipe: legacy backtest data uses incompatible semantics
                # (text-based advice parsing, no signal_score, no exit_reason / hold_days,
                # picker backtest pre-trade_levels engine). Wipe everything once on the
                # first init that detects an unmigrated row, then mark with a sentinel.
                try:
                    sentinel = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM backtest_summaries "
                            "WHERE scope = '__migration_marker__' AND code = 'unified_v3'"
                        )
                    ).scalar() or 0
                    if int(sentinel) == 0:
                        legacy_results = conn.execute(text("SELECT COUNT(*) FROM backtest_results")).scalar() or 0
                        legacy_summaries = conn.execute(text("SELECT COUNT(*) FROM backtest_summaries")).scalar() or 0
                        legacy_picker = conn.execute(text("SELECT COUNT(*) FROM picker_backtest_history")).scalar() or 0
                        if int(legacy_results) + int(legacy_summaries) + int(legacy_picker) > 0:
                            logger.info(
                                "[Migration] One-shot wipe: backtest_results=%d backtest_summaries=%d "
                                "picker_backtest_history=%d (engine semantics changed in v3.x)",
                                int(legacy_results), int(legacy_summaries), int(legacy_picker),
                            )
                            conn.execute(text("DELETE FROM backtest_results"))
                            conn.execute(text("DELETE FROM backtest_summaries"))
                            conn.execute(text("DELETE FROM picker_backtest_history"))
                        # Insert sentinel so subsequent restarts don't re-wipe.
                        conn.execute(
                            text(
                                "INSERT INTO backtest_summaries (scope, code, eval_window_days) "
                                "VALUES ('__migration_marker__', 'unified_v3', 0)"
                            )
                        )
                        conn.commit()
                except Exception as exc:
                    logger.debug("[Migration] one-shot backtest wipe skipped: %s", exc)
        except Exception:
            pass

        self._initialized = True
        logger.info(f"数据库初始化完成: {db_url}")

        # 注册退出钩子，确保程序退出时关闭数据库连接
        atexit.register(type(self)._cleanup_engine, self._engine)
    
    @staticmethod
    def _drop_legacy_engine_version_column(conn, table: str) -> None:
        """Rebuild `table` to remove the `engine_version` column when ALTER TABLE
        DROP COLUMN was blocked by an inline UNIQUE constraint referencing it.

        Safe no-op if the column is already gone.
        """
        from sqlalchemy import text

        cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if not any(row[1] == "engine_version" for row in cols):
            return

        kept_cols = [row[1] for row in cols if row[1] != "engine_version"]
        col_list = ", ".join(f'"{c}"' for c in kept_cols)
        tmp_table = f"{table}__rebuild_no_engver"

        conn.execute(text(f"DROP TABLE IF EXISTS {tmp_table}"))
        conn.execute(text(f"ALTER TABLE {table} RENAME TO {tmp_table}"))
        # Indexes follow the renamed table; drop them so metadata.create can
        # recreate the canonical names without collision.
        idx_rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=:t "
                "AND name NOT LIKE 'sqlite_%'"
            ),
            {"t": tmp_table},
        ).fetchall()
        for (idx_name,) in idx_rows:
            conn.execute(text(f'DROP INDEX IF EXISTS "{idx_name}"'))
        Base.metadata.tables[table].create(bind=conn)
        conn.execute(
            text(f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {tmp_table}")
        )
        conn.execute(text(f"DROP TABLE {tmp_table}"))
        conn.commit()
        logger.info("[Migration] rebuilt %s without legacy engine_version column", table)

    @classmethod
    def get_instance(cls) -> 'DatabaseManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        if cls._instance is not None:
            if hasattr(cls._instance, '_engine') and cls._instance._engine is not None:
                cls._instance._engine.dispose()
            cls._instance._initialized = False
            cls._instance = None

    @classmethod
    def _cleanup_engine(cls, engine) -> None:
        """
        清理数据库引擎（atexit 钩子）

        确保程序退出时关闭所有数据库连接，避免 ResourceWarning

        Args:
            engine: SQLAlchemy 引擎对象
        """
        try:
            if engine is not None:
                engine.dispose()
                logger.debug("数据库引擎已清理")
        except Exception as e:
            logger.warning(f"清理数据库引擎时出错: {e}")
    
    def get_session(self) -> Session:
        """
        获取数据库 Session
        
        使用示例:
            with db.get_session() as session:
                # 执行查询
                session.commit()  # 如果需要
        """
        if not getattr(self, '_initialized', False) or not hasattr(self, '_SessionLocal'):
            raise RuntimeError(
                "DatabaseManager 未正确初始化。"
                "请确保通过 DatabaseManager.get_instance() 获取实例。"
            )
        session = self._SessionLocal()
        try:
            return session
        except Exception:
            session.close()
            raise

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
