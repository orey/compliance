from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import Framework, FrameworkVersion, Requirement
from ..services import versioning
from ..services.assessments import evolution
from ..services.spreadsheet import SpreadsheetError, build_template, parse_requirements
from .utils import get_or_404, parse_date, safe_filename, send_xlsx

bp = Blueprint("frameworks", __name__, url_prefix="/repositories")


@bp.route("/")
def index():
    return render_template("frameworks/index.html", frameworks=Framework.query.order_by(Framework.name).all())


@bp.route("/template.xlsx")
def template():
    return send_xlsx(build_template(), "requirements_template.xlsx")


@bp.route("/new", methods=["POST"])
def create():
    name = request.form.get("name", "").strip()
    if not name:
        flash("A name is required.", "danger")
        return redirect(url_for(".index"))
    fw = Framework(name=name, description=request.form.get("description", "").strip())
    db.session.add(fw)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(f"A repository named '{name}' already exists.", "danger")
        return redirect(url_for(".index"))
    flash("Repository created. Now add its first version.", "success")
    return redirect(url_for(".new_version", framework_id=fw.id))


@bp.route("/<int:framework_id>")
def detail(framework_id):
    fw = get_or_404(Framework, framework_id)
    summaries = {v.id: versioning.change_summary(v) for v in fw.versions}
    assessments = [a for v in fw.versions for a in v.assessments]
    assessments.sort(key=lambda a: (a.reference_date, a.id), reverse=True)
    return render_template("frameworks/detail.html", fw=fw, summaries=summaries, assessments=assessments)


@bp.route("/<int:framework_id>/edit", methods=["POST"])
def edit(framework_id):
    fw = get_or_404(Framework, framework_id)
    fw.name = request.form.get("name", fw.name).strip() or fw.name
    fw.description = request.form.get("description", "").strip()
    try:
        db.session.commit()
        flash("Repository updated.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Another repository already has this name.", "danger")
    return redirect(url_for(".detail", framework_id=fw.id))


@bp.route("/<int:framework_id>/delete", methods=["POST"])
def delete(framework_id):
    fw = get_or_404(Framework, framework_id)
    if any(v.assessments for v in fw.versions):
        flash("This repository has assessments and cannot be deleted.", "danger")
        return redirect(url_for(".detail", framework_id=fw.id))
    db.session.delete(fw)
    db.session.commit()
    flash("Repository deleted.", "success")
    return redirect(url_for(".index"))


@bp.route("/<int:framework_id>/versions/new", methods=["GET", "POST"])
def new_version(framework_id):
    fw = get_or_404(Framework, framework_id)
    if request.method == "POST":
        mode = request.form.get("mode", "upload")
        base_id = request.form.get("base_version_id", type=int)
        base = db.session.get(FrameworkVersion, base_id) if base_id else None
        if base is not None and base.framework_id != fw.id:
            base = None
        rows = None
        if mode == "upload":
            upload = request.files.get("file")
            if not upload or not upload.filename:
                flash("Please choose a spreadsheet to upload.", "danger")
                return render_template("frameworks/new_version.html", fw=fw, form=request.form)
            try:
                rows = parse_requirements(upload.filename, upload.stream)
            except SpreadsheetError as e:
                for err in e.errors[:30]:
                    flash(err, "danger")
                return render_template("frameworks/new_version.html", fw=fw, form=request.form)
        elif mode == "clone" and base is None:
            flash("Choose the version to start from.", "danger")
            return render_template("frameworks/new_version.html", fw=fw, form=request.form)
        elif mode == "empty":
            rows = []
        try:
            version, warnings = versioning.create_version(
                fw, request.form.get("label"), rows=rows, base_version=base,
                effective_date=parse_date(request.form.get("effective_date")),
                notes=request.form.get("notes", "").strip(),
            )
        except versioning.VersionError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return render_template("frameworks/new_version.html", fw=fw, form=request.form)
        db.session.commit()
        for w in warnings[:30]:
            flash(w, "warning")
        flash(f"Draft version {version.label} created with {len(version.requirements)} requirement(s). "
              "Review it, then publish it to start assessing.", "success")
        return redirect(url_for(".version", version_id=version.id))
    latest = fw.latest_published
    return render_template("frameworks/new_version.html", fw=fw,
                           form={"base_version_id": str(latest.id) if latest else "",
                                 "mode": "clone" if latest else "upload"})


@bp.route("/versions/<int:version_id>")
def version(version_id):
    v = get_or_404(FrameworkVersion, version_id)
    return render_template("frameworks/version.html", v=v, summary=versioning.change_summary(v),
                           removed=versioning.removed_requirements(v),
                           change_filter=request.args.get("change", ""))


@bp.route("/versions/<int:version_id>/export.xlsx")
def export_version(version_id):
    v = get_or_404(FrameworkVersion, version_id)
    return send_xlsx(build_template(v.requirements), safe_filename(v.framework.name, v.label) + ".xlsx")


def _draft_or_redirect(version_id):
    v = get_or_404(FrameworkVersion, version_id)
    if v.is_published:
        flash("This version is published and can no longer be changed. Create a new version instead.", "warning")
        return v, redirect(url_for(".version", version_id=v.id))
    return v, None


@bp.route("/versions/<int:version_id>/upload", methods=["POST"])
def reupload(version_id):
    v, resp = _draft_or_redirect(version_id)
    if resp:
        return resp
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Please choose a spreadsheet to upload.", "danger")
        return redirect(url_for(".version", version_id=v.id))
    try:
        warnings = versioning.load_rows(v, parse_requirements(upload.filename, upload.stream))
    except SpreadsheetError as e:
        for err in e.errors[:30]:
            flash(err, "danger")
        return redirect(url_for(".version", version_id=v.id))
    db.session.commit()
    for w in warnings[:30]:
        flash(w, "warning")
    flash(f"Content replaced: {len(v.requirements)} requirement(s).", "success")
    return redirect(url_for(".version", version_id=v.id))


@bp.route("/versions/<int:version_id>/requirements/new", methods=["GET", "POST"])
@bp.route("/versions/<int:version_id>/requirements/<int:req_id>/edit", methods=["GET", "POST"])
def requirement_form(version_id, req_id=None):
    v, resp = _draft_or_redirect(version_id)
    if resp:
        return resp
    req = get_or_404(Requirement, req_id) if req_id else None
    if req is not None and req.version_id != v.id:
        return redirect(url_for(".version", version_id=v.id))
    if request.method == "POST":
        try:
            req = versioning.save_requirement(v, request.form, req)
            db.session.commit()
            flash(f"Requirement {req.code} saved.", "success")
            return redirect(url_for(".version", version_id=v.id) + f"#req-{req.id}")
        except versioning.VersionError as e:
            db.session.rollback()
            flash(str(e), "danger")
    return render_template("frameworks/requirement_form.html", v=v, req=req, form=request.form if request.method == "POST" else None)


@bp.route("/versions/<int:version_id>/requirements/<int:req_id>/delete", methods=["POST"])
def delete_requirement(version_id, req_id):
    v, resp = _draft_or_redirect(version_id)
    if resp:
        return resp
    req = get_or_404(Requirement, req_id)
    if req.version_id == v.id:
        versioning.delete_requirement(req)
        db.session.commit()
        flash(f"Requirement {req.code} removed from this version.", "success")
    return redirect(url_for(".version", version_id=v.id))


@bp.route("/versions/<int:version_id>/restore/<int:req_id>", methods=["POST"])
def restore_requirement(version_id, req_id):
    v, resp = _draft_or_redirect(version_id)
    if resp:
        return resp
    removed = get_or_404(Requirement, req_id)
    try:
        versioning.restore_requirement(v, removed)
        db.session.commit()
        flash(f"Requirement {removed.code} restored.", "success")
    except versioning.VersionError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for(".version", version_id=v.id))


@bp.route("/versions/<int:version_id>/publish", methods=["POST"])
def publish(version_id):
    v, resp = _draft_or_redirect(version_id)
    if resp:
        return resp
    try:
        versioning.publish(v)
        db.session.commit()
        flash(f"Version {v.label} published. You can now assess it.", "success")
    except versioning.VersionError as e:
        flash(str(e), "danger")
    return redirect(url_for(".version", version_id=v.id))


@bp.route("/versions/<int:version_id>/delete", methods=["POST"])
def delete_version(version_id):
    v, resp = _draft_or_redirect(version_id)
    if resp:
        return resp
    fw_id = v.framework_id
    db.session.delete(v)
    db.session.commit()
    flash("Draft version deleted.", "success")
    return redirect(url_for(".detail", framework_id=fw_id))


@bp.route("/<int:framework_id>/evolution")
def framework_evolution(framework_id):
    fw = get_or_404(Framework, framework_id)
    include = request.args.get("include_in_progress") == "1"
    return render_template("frameworks/evolution.html", fw=fw, evo=evolution(fw, include_in_progress=include),
                           include_in_progress=include)
