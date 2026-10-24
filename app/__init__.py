from datetime import date

from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Explicit constraint names keep Alembic migrations portable across databases.
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate()


def create_app(config_object="app.config.Config"):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch mode needed for SQLite ALTERs

    from . import models  # noqa: F401  (register models)
    from .routes import actions, assessments, frameworks, main

    app.register_blueprint(main.bp)
    app.register_blueprint(frameworks.bp)
    app.register_blueprint(assessments.bp)
    app.register_blueprint(actions.bp)

    from .cli import register_cli

    register_cli(app)

    from .models import ACTION_STATUSES, PRIORITIES, RESULT_HEX, RESULT_STATUSES

    @app.context_processor
    def inject_globals():
        return {
            "RESULT_STATUSES": RESULT_STATUSES,
            "RESULT_HEX": RESULT_HEX,
            "ACTION_STATUSES": ACTION_STATUSES,
            "PRIORITIES": PRIORITIES,
            "today": date.today(),
        }

    @app.template_filter("d")
    def format_date(value):
        return value.strftime("%Y-%m-%d") if value else ""

    return app
