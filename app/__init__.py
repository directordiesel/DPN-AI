"""DPN AI application package bootstrap.

Install the hardened SQLite boundary before application modules import
``Database`` from ``app.db``. The schema implementation remains in app.db,
while production and test imports receive SecureDatabase by default.
"""

from app import db as _db
from app.secure_database import SecureDatabase

_db.Database = SecureDatabase

__all__ = ["SecureDatabase"]
