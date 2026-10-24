"""Building framework versions and tracking how requirements evolve between them."""

from .. import db
from ..models import FrameworkVersion, Requirement, utcnow


class VersionError(Exception):
    pass


def _refresh_change_type(req):
    pred = req.predecessor
    if req.version.previous_version_id is None:
        req.change_type = None
    elif pred is None:
        req.change_type = "new"
    elif pred.code != req.code or pred.content_signature() != req.content_signature():
        req.change_type = "modified"
    else:
        req.change_type = "unchanged"


def _assign_lineages(version):
    db.session.flush()
    for req in version.requirements:
        if req.lineage_id is None:
            req.lineage_id = req.id


def load_rows(version, rows):
    """(Re)fill a draft version from parsed spreadsheet rows. Returns warnings."""
    if version.is_published:
        raise VersionError("A published version cannot be modified.")
    for req in list(version.requirements):
        db.session.delete(req)
    version.requirements.clear()
    db.session.flush()

    base = version.previous_version
    base_by_code = {r.code: r for r in base.requirements} if base else {}
    used, warnings = set(), []
    for pos, row in enumerate(rows):
        req = Requirement(
            code=row.code, section=row.section, title=row.title, description=row.description,
            guidance=row.guidance, position=pos,
        )
        version.requirements.append(req)
        if base:
            pred = base_by_code.get(row.previous_code or row.code)
            if row.previous_code and pred is None:
                warnings.append(f"{row.code}: previous code '{row.previous_code}' not found in "
                                f"{base.label}; treated as a new requirement.")
            if pred is not None and pred.id in used:
                warnings.append(f"{row.code}: '{pred.code}' is already mapped to another requirement; "
                                "treated as a new requirement.")
                pred = None
            if pred is not None:
                used.add(pred.id)
                req.predecessor = pred
                req.lineage_id = pred.lineage_id
        _refresh_change_type(req)
    _assign_lineages(version)
    return warnings


def create_version(framework, label, rows=None, base_version=None, effective_date=None, notes=""):
    """Create a draft version, either from spreadsheet rows or as a copy of base_version."""
    label = (label or "").strip()
    if not label:
        raise VersionError("A version label is required.")
    if any(v.label == label for v in framework.versions):
        raise VersionError(f"Version '{label}' already exists for {framework.name}.")
    if base_version is not None and not base_version.is_published:
        raise VersionError("A new version can only be based on a published version.")

    version = FrameworkVersion(framework=framework, label=label, effective_date=effective_date, notes=notes,
                               previous_version=base_version)
    db.session.add(version)
    db.session.flush()
    if rows is not None:
        return version, load_rows(version, rows)

    # Clone the base version: everything is "unchanged" until edited.
    for src in (base_version.requirements if base_version else []):
        version.requirements.append(Requirement(
            code=src.code, section=src.section, title=src.title, description=src.description,
            guidance=src.guidance, position=src.position, predecessor=src, lineage_id=src.lineage_id,
            change_type="unchanged",
        ))
    db.session.flush()
    return version, []


def save_requirement(version, data, req=None):
    """Add (req=None) or update a requirement of a draft version."""
    if version.is_published:
        raise VersionError("A published version cannot be modified.")
    code = (data.get("code") or "").strip()
    title = (data.get("title") or "").strip()
    if not code or not title:
        raise VersionError("Code and title are required.")
    clash = Requirement.query.filter_by(version_id=version.id, code=code).first()
    if clash is not None and clash is not req:
        raise VersionError(f"Code '{code}' already exists in this version.")
    if req is None:
        last = max((r.position for r in version.requirements), default=-1)
        req = Requirement(position=last + 1)
        version.requirements.append(req)
    req.code = code
    req.title = title
    for field in ("section", "description", "guidance"):
        setattr(req, field, (data.get(field) or "").strip())
    _refresh_change_type(req)
    _assign_lineages(version)
    return req


def delete_requirement(req):
    if req.version.is_published:
        raise VersionError("A published version cannot be modified.")
    db.session.delete(req)


def restore_requirement(version, removed):
    """Bring back a requirement of the previous version that was removed in this draft."""
    if version.is_published:
        raise VersionError("A published version cannot be modified.")
    if Requirement.query.filter_by(version_id=version.id, code=removed.code).first():
        raise VersionError(f"Code '{removed.code}' is already used in this version.")
    last = max((r.position for r in version.requirements), default=-1)
    version.requirements.append(Requirement(
        code=removed.code, section=removed.section, title=removed.title, description=removed.description,
        guidance=removed.guidance, position=last + 1, predecessor=removed, lineage_id=removed.lineage_id,
        change_type="unchanged",
    ))


def publish(version):
    if not version.requirements:
        raise VersionError("Cannot publish an empty version.")
    version.status = "published"
    version.published_at = utcnow()


def removed_requirements(version):
    """Requirements of the previous version that have no successor in this one."""
    base = version.previous_version
    if base is None:
        return []
    kept = {r.predecessor_id for r in version.requirements if r.predecessor_id}
    return [r for r in base.requirements if r.id not in kept]


def change_summary(version):
    counts = {"new": 0, "modified": 0, "unchanged": 0}
    for r in version.requirements:
        if r.change_type in counts:
            counts[r.change_type] += 1
    counts["removed"] = len(removed_requirements(version))
    counts["total"] = len(version.requirements)
    return counts
