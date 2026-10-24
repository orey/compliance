"""Assessment lifecycle, KPIs, comparison between assessments and evolution over time."""

from collections import OrderedDict
from datetime import date

from .. import db
from ..models import (
    ACTION_KEYS,
    OPEN_ACTION_KEYS,
    RESULT_KEYS,
    Action,
    Assessment,
    AssessmentResult,
    Framework,
    FrameworkVersion,
    utcnow,
)

# Ordering used to tell improvements from regressions.
RANK = {"non_compliant": 0, "partial": 1, "compliant": 2}


class AssessmentError(Exception):
    pass


def create_assessment(version, name, scope="", assessor="", assessment_date=None, based_on=None,
                      carry_actions=False):
    """Create an assessment with one (empty) result per requirement.

    With based_on, answers of that earlier assessment are copied over for requirements that
    still exist (matched by lineage, so it works across versions). Answers whose requirement
    text changed in between are flagged needs_review. Open actions can be carried over too.
    """
    if not version.is_published:
        raise AssessmentError("Assessments can only be made on a published version.")
    if not (name or "").strip():
        raise AssessmentError("A name is required.")
    if based_on is not None and based_on.framework.id != version.framework.id:
        raise AssessmentError("The assessment to start from must be on the same repository.")

    assessment = Assessment(name=name.strip(), version=version, scope=scope, assessor=assessor,
                            assessment_date=assessment_date or date.today(), based_on=based_on)
    db.session.add(assessment)

    previous = {}
    if based_on is not None:
        previous = {r.requirement.lineage_id: r for r in based_on.results}

    by_lineage = {}
    for req in version.requirements:
        result = AssessmentResult(requirement=req)
        src = previous.get(req.lineage_id)
        if src is not None:
            result.status = src.status
            result.comment = src.comment
            result.evidence = src.evidence
            result.needs_review = src.needs_review or (
                src.requirement.content_signature() != req.content_signature()
            )
        assessment.results.append(result)
        by_lineage[req.lineage_id] = req

    if based_on is not None and carry_actions:
        for old in based_on.actions:
            if not old.is_open:
                continue
            new_req = by_lineage.get(old.requirement.lineage_id) if old.requirement else None
            assessment.actions.append(Action(
                requirement=new_req, title=old.title, description=old.description, owner=old.owner,
                priority=old.priority, status=old.status, due_date=old.due_date, carried_from=old,
            ))
            old.set_status("carried_over")

    db.session.flush()
    return assessment


def update_result(assessment, result, status=None, comment=None, evidence=None):
    if assessment.is_completed:
        raise AssessmentError("This assessment is completed; reopen it to change answers.")
    if status is not None:
        if status not in RESULT_KEYS and status != "":
            raise AssessmentError(f"Unknown status '{status}'.")
        result.status = status or None
        result.needs_review = False  # answering (or confirming) clears the review flag
    if comment is not None:
        result.comment = comment
    if evidence is not None:
        result.evidence = evidence
    assessment.updated_at = utcnow()


def complete(assessment, assessment_date=None, allow_unanswered=False):
    unanswered = sum(1 for r in assessment.results if r.status is None)
    if unanswered and not allow_unanswered:
        raise AssessmentError(f"{unanswered} requirement(s) are not assessed yet.")
    assessment.status = "completed"
    assessment.completed_at = utcnow()
    if assessment_date:
        assessment.assessment_date = assessment_date


def reopen(assessment):
    assessment.status = "in_progress"
    assessment.completed_at = None


def sorted_results(assessment):
    return sorted(assessment.results, key=lambda r: r.requirement.position)


def _empty_counts():
    counts = OrderedDict((k, 0) for k in RESULT_KEYS)
    counts["not_assessed"] = 0
    return counts


def _score(counts):
    applicable = counts["compliant"] + counts["partial"] + counts["non_compliant"]
    if not applicable:
        return None
    return round(100 * (counts["compliant"] + 0.5 * counts["partial"]) / applicable, 1)


def compute_kpis(assessment):
    counts = _empty_counts()
    sections = OrderedDict()
    needs_review = 0
    for r in sorted_results(assessment):
        key = r.status or "not_assessed"
        counts[key] += 1
        sec = sections.setdefault(r.requirement.section or "(no section)", _empty_counts())
        sec[key] += 1
        needs_review += r.needs_review

    total = sum(counts.values())
    action_counts = OrderedDict((k, 0) for k in ACTION_KEYS)
    for a in assessment.actions:
        action_counts[a.status] += 1
    return {
        "total": total,
        "counts": counts,
        "score": _score(counts),
        "progress": round(100 * (total - counts["not_assessed"]) / total, 1) if total else 0,
        "needs_review": needs_review,
        "sections": [{"name": n, "counts": c, "score": _score(c), "total": sum(c.values())}
                     for n, c in sections.items()],
        "actions": {
            "counts": action_counts,
            "open_total": sum(action_counts[k] for k in OPEN_ACTION_KEYS),
            "overdue": sum(1 for a in assessment.actions if a.is_overdue),
        },
    }


def assessments_of_framework(framework, completed_only=True):
    q = Assessment.query.join(FrameworkVersion).filter(FrameworkVersion.framework_id == framework.id)
    if completed_only:
        q = q.filter(Assessment.status == "completed")
    return sorted(q.all(), key=lambda a: (a.reference_date, a.id))


def previous_assessment(assessment):
    """Latest completed assessment of the same repository before this one."""
    earlier = [a for a in assessments_of_framework(assessment.framework)
               if a.id != assessment.id and (a.reference_date, a.id) < (assessment.reference_date, assessment.id)]
    return earlier[-1] if earlier else None


def compare(current, previous):
    """Requirement-level differences between two assessments of the same repository."""
    prev_by_lineage = {r.requirement.lineage_id: r for r in previous.results}
    cur_lineages = set()
    out = {"improved": [], "regressed": [], "changed": [], "unchanged": [], "new": [], "removed": []}
    for r in sorted_results(current):
        lineage = r.requirement.lineage_id
        cur_lineages.add(lineage)
        old = prev_by_lineage.get(lineage)
        if old is None:
            out["new"].append((r, None))
        elif old.status == r.status:
            out["unchanged"].append((r, old))
        elif old.status in RANK and r.status in RANK:
            out["improved" if RANK[r.status] > RANK[old.status] else "regressed"].append((r, old))
        else:
            out["changed"].append((r, old))
    out["removed"] = [(None, old) for lin, old in prev_by_lineage.items() if lin not in cur_lineages]
    return out


def evolution(framework: Framework, include_in_progress=False):
    """Timeline of KPIs and a requirement × assessment status matrix.

    Rows are requirement lineages so a requirement keeps its history across versions
    even if renumbered; cells are None where the requirement did not exist yet.
    """
    assessments = assessments_of_framework(framework, completed_only=not include_in_progress)
    points = []
    for a in assessments:
        k = compute_kpis(a)
        points.append({"assessment": a, "counts": k["counts"], "score": k["score"], "total": k["total"]})

    # Row order: latest version first, then requirements that were removed along the way.
    rows = OrderedDict()
    for a in reversed(assessments):
        for r in sorted_results(a):
            rows.setdefault(r.requirement.lineage_id, r.requirement)
    matrix = []
    status_by = [{r.requirement.lineage_id: r.status or "not_assessed" for r in a.results} for a in assessments]
    for lineage, req in rows.items():
        cells = [s.get(lineage) for s in status_by]  # None = requirement not in that version
        matrix.append({"requirement": req, "cells": cells})
    return {"assessments": assessments, "points": points, "matrix": matrix}
