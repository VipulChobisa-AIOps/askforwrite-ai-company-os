import pathlib
import sys

import pytest

# Ensure the os_gateway package root is on sys.path for both `app` and `tests` imports
_project_root = pathlib.Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Load fixtures from the helpers module (relative path works from any cwd)
pytest_plugins = ["tests.helpers"]

# Database session fixture for tests that need DB access
@pytest.fixture
def db_session():
    """Create an in‑memory SQLite session with all tables created.
    The session is yielded to the test and cleaned up afterwards.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
