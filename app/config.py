import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    # Any SQLAlchemy URL works (sqlite, postgresql, mysql...). Relative sqlite
    # paths are resolved against the Flask instance folder.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///compliance.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # uploads up to 20 MB
    MAX_FORM_PARTS = 50_000  # an assessment form has 3 fields per requirement


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
