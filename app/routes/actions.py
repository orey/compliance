from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import db
from ..models import OPEN_ACTION_KEYS, PRIORITY_KEYS, Action, Assessment, Framework, FrameworkVersion, Requirement
from .utils import get_or_404, parse_date, safe_next

bp = Blueprint("actions", __name__, url_prefix="/actions")

PRIORITY_ORDER = {k: i for i, k in enumerate(PRIORITY_KEYS)}


@bp.route("/")
def index():
    status = request.args.get("status", "open")
    framework_id = request.args.get("framework_id", type=int)
    owner = request.args.get("owner", "").strip()
    q = Action.query.join(Assessment).join(FrameworkVersion)
    if status == "open":
        q = q.filter(Action.status.in_(OPEN_ACTION_KEYS))
    elif status == "overdue":
        q = q.filter(Action.status.in_(OPEN_ACTION_KEYS), Action.due_date < date.today())
    elif status:
        q = q.filter(Action.status == status)
    if framework_id:
        q = q.filter(FrameworkVersion.framework_id == framework_id)
    if owner:
        q = q.filter(Action.owner.ilike(f"%{owner}%"))
    # Dated actions first (soonest first), then by priority.
    items = sorted(q.all(), key=lambda a: (a.due_date is None, a.due_date or date.max,
                                           PRIORITY_ORDER.get(a.priority, 9)))
    return render_template("actions/index.html", actions=items, status=status, framework_id=framework_id,
                           owner=owner, frameworks=Framework.query.order_by(Framework.name).all())


def _fill(action, assessment, form):
    action.title = form.get("title", "").strip()
    action.description = form.get("description", "").strip()
    action.owner = form.get("owner", "").strip()
    action.priority = form.get("priority") if form.get("priority") in PRIORITY_KEYS else "medium"
    action.due_date = parse_date(form.get("due_date"))
    req_id = form.get("requirement_id", type=int)
    req = db.session.get(Requirement, req_id) if req_id else None
    action.requirement_id = req.id if req and req.version_id == assessment.version_id else None
    if form.get("status"):
        action.set_status(form["status"])


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:action_id>/edit", methods=["GET", "POST"])
def form(action_id=None):
    if action_id:
        action = get_or_404(Action, action_id)
        assessment = action.assessment
    else:
        assessment = get_or_404(Assessment, request.values.get("assessment_id", type=int) or 0)
        # Kept out of the session until saved (no relationship assignment => no autoflush).
        action = Action(assessment_id=assessment.id, requirement_id=request.args.get("requirement_id", type=int),
                        priority="medium", status="open")
    if request.method == "POST":
        with db.session.no_autoflush:
            _fill(action, assessment, request.form)
        if not action.title:
            db.session.rollback()
            flash("A title is required.", "danger")
        else:
            db.session.add(action)
            db.session.commit()
            flash("Action saved.", "success")
            return redirect(safe_next(request.form.get("next"),
                                     url_for("assessments.report", assessment_id=assessment.id)))
    return render_template("actions/form.html", action=action, assessment=assessment,
                           next=safe_next(request.values.get("next") or request.referrer, ""))


@bp.route("/<int:action_id>/status", methods=["POST"])
def set_status(action_id):
    action = get_or_404(Action, action_id)
    action.set_status(request.form["status"])
    db.session.commit()
    flash(f"Action '{action.title}' is now {action.status.replace('_', ' ')}.", "success")
    return redirect(safe_next(request.referrer, url_for(".index")))


@bp.route("/<int:action_id>/delete", methods=["POST"])
def delete(action_id):
    action = get_or_404(Action, action_id)
    db.session.delete(action)
    db.session.commit()
    flash("Action deleted.", "success")
    return redirect(safe_next(request.referrer, url_for(".index")))
