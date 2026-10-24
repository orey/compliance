from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from .. import db
from ..models import Assessment, AssessmentResult, Framework, FrameworkVersion
from ..services import assessments as svc
from ..services.spreadsheet import export_assessment
from .utils import get_or_404, parse_date, safe_filename, safe_next, send_xlsx

bp = Blueprint("assessments", __name__, url_prefix="/assessments")


@bp.route("/")
def index():
    status = request.args.get("status", "")
    q = Assessment.query
    if status:
        q = q.filter_by(status=status)
    items = sorted(q.all(), key=lambda a: (a.reference_date, a.id), reverse=True)
    return render_template("assessments/index.html", assessments=items, status=status)


@bp.route("/new", methods=["GET", "POST"])
def create():
    versions = (FrameworkVersion.query.filter_by(status="published")
                .join(Framework).order_by(Framework.name, FrameworkVersion.created_at).all())
    previous = Assessment.query.order_by(Assessment.started_at.desc()).all()
    form = request.form if request.method == "POST" else request.args
    if request.method == "POST":
        version = db.session.get(FrameworkVersion, request.form.get("version_id", type=int) or 0)
        based_on_id = request.form.get("based_on_id", type=int)
        based_on = db.session.get(Assessment, based_on_id) if based_on_id else None
        if version is None:
            flash("Choose a repository version.", "danger")
        else:
            try:
                a = svc.create_assessment(
                    version, request.form.get("name", ""), scope=request.form.get("scope", "").strip(),
                    assessor=request.form.get("assessor", "").strip(),
                    assessment_date=parse_date(request.form.get("assessment_date")),
                    based_on=based_on, carry_actions=bool(request.form.get("carry_actions")),
                )
                db.session.commit()
                msg = "Assessment created."
                if based_on:
                    msg += f" Answers pre-filled from '{based_on.name}'."
                flash(msg, "success")
                return redirect(url_for(".work", assessment_id=a.id))
            except svc.AssessmentError as e:
                db.session.rollback()
                flash(str(e), "danger")
    return render_template("assessments/new.html", versions=versions, previous=previous, form=form)


@bp.route("/<int:assessment_id>")
def work(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    actions_by_req = {}
    for act in a.actions:
        actions_by_req.setdefault(act.requirement_id, []).append(act)
    return render_template("assessments/work.html", a=a, results=svc.sorted_results(a),
                           kpis=svc.compute_kpis(a), actions_by_req=actions_by_req)


@bp.route("/<int:assessment_id>/save", methods=["POST"])
def save(assessment_id):
    """Non-JS fallback: save the whole form at once."""
    a = get_or_404(Assessment, assessment_id)
    try:
        for r in a.results:
            if f"comment_{r.id}" not in request.form:
                continue  # result not rendered in the submitted form
            new_status = request.form.get(f"status_{r.id}", "")
            svc.update_result(
                a, r,
                status=new_status if (new_status or None) != r.status else None,
                comment=request.form.get(f"comment_{r.id}", ""),
                evidence=request.form.get(f"evidence_{r.id}", ""),
            )
        db.session.commit()
        flash("Assessment saved. You can come back to it any time.", "success")
    except svc.AssessmentError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for(".work", assessment_id=a.id))


@bp.route("/<int:assessment_id>/results/<int:result_id>", methods=["POST"])
def autosave(assessment_id, result_id):
    a = get_or_404(Assessment, assessment_id)
    r = get_or_404(AssessmentResult, result_id)
    if r.assessment_id != a.id:
        return jsonify(error="not found"), 404
    data = request.get_json(silent=True) or {}
    try:
        svc.update_result(a, r, status=data.get("status"), comment=data.get("comment"),
                          evidence=data.get("evidence"))
        db.session.commit()
    except svc.AssessmentError as e:
        db.session.rollback()
        return jsonify(error=str(e)), 400
    k = svc.compute_kpis(a)
    return jsonify(ok=True, counts=k["counts"], progress=k["progress"], score=k["score"],
                   needs_review=k["needs_review"])


@bp.route("/<int:assessment_id>/edit", methods=["POST"])
def edit(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    a.name = request.form.get("name", "").strip() or a.name
    a.scope = request.form.get("scope", "").strip()
    a.assessor = request.form.get("assessor", "").strip()
    a.general_comment = request.form.get("general_comment", "").strip()
    a.assessment_date = parse_date(request.form.get("assessment_date")) or a.assessment_date
    db.session.commit()
    flash("Assessment details saved.", "success")
    return redirect(safe_next(request.referrer, url_for(".work", assessment_id=a.id)))


@bp.route("/<int:assessment_id>/complete", methods=["POST"])
def complete(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    try:
        svc.complete(a, assessment_date=parse_date(request.form.get("assessment_date")),
                     allow_unanswered=bool(request.form.get("allow_unanswered")))
        db.session.commit()
        flash("Assessment completed.", "success")
        return redirect(url_for(".report", assessment_id=a.id))
    except svc.AssessmentError as e:
        flash(f"{e} Tick 'complete anyway' to terminate it nevertheless.", "warning")
        return redirect(url_for(".work", assessment_id=a.id))


@bp.route("/<int:assessment_id>/reopen", methods=["POST"])
def reopen(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    svc.reopen(a)
    db.session.commit()
    flash("Assessment reopened.", "info")
    return redirect(url_for(".work", assessment_id=a.id))


@bp.route("/<int:assessment_id>/delete", methods=["POST"])
def delete(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    db.session.delete(a)
    db.session.commit()
    flash("Assessment deleted.", "success")
    return redirect(url_for(".index"))


@bp.route("/<int:assessment_id>/report")
def report(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    prev = svc.previous_assessment(a)
    return render_template("assessments/report.html", a=a, kpis=svc.compute_kpis(a), prev=prev,
                           diff=svc.compare(a, prev) if prev else None,
                           prev_kpis=svc.compute_kpis(prev) if prev else None)


@bp.route("/<int:assessment_id>/export.xlsx")
def export(assessment_id):
    a = get_or_404(Assessment, assessment_id)
    buf = export_assessment(a, svc.compute_kpis(a), svc.sorted_results(a))
    return send_xlsx(buf, safe_filename(a.name, a.reference_date.isoformat()) + ".xlsx")
