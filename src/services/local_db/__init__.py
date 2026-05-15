"""Local A-share data warehouse backed by parquet files.

See :mod:`src.services.local_db.store` for the public API.
"""

from .store import LocalStockDB, default_db

__all__ = ["LocalStockDB", "default_db"]
