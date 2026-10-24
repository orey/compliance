from datetime import date

from flask import Blueprint, render_template

from ..models import OPEN_ACTION_KEYS, Action, Assessment, Framework

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    open_actions = Action.query.filter(Action.status.in_(OPEN_ACTION_KEYS))
    upcoming = (open_actions.filter(Action.due_date.isnot(None))
                .order_by(Action.due_date).limit(10).all())
    return render_template(
        "dashboard.html",
        frameworks=Framework.query.order_by(Framework.name).all(),
        in_progress=Assessment.query.filter_by(status="in_progress").order_by(Assessment.updated_at.desc()).all(),
        recent_completed=Assessment.query.filter_by(status="completed")
        .order_by(Assessment.completed_at.desc()).limit(5).all(),
        open_count=open_actions.count(),
        overdue_count=open_actions.filter(Action.due_date < date.today()).count(),
        upcoming=upcoming,
    )
