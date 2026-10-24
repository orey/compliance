"""Data model.

Framework (a "repository" of requirements: ISO 27001, NATO, corporate...)
  └─ FrameworkVersion (draft → published; published versions are immutable)
       └─ Requirement (has a predecessor in the previous version and a lineage id
                       shared by all versions of "the same" requirement)

Assessment (against one published FrameworkVersion; in_progress → completed)
  ├─ AssessmentResult (one per requirement: status + comment + evidence)
  └─ Action (the action plan; optionally linked to a requirement)
"""

from datetime import date, datetime, timezone

from . import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Ordered (key, label, bootstrap colour) tuples, used by templates and KPIs.
RESULT_STATUSES = [
    ("compliant", "Compliant", "success"),
    ("partial", "Partially compliant", "warning"),
    ("non_compliant", "Non compliant", "danger"),
    ("not_applicable", "Not applicable", "secondary"),
]
RESULT_KEYS = [s[0] for s in RESULT_STATUSES]
RESULT_LABELS = {k: label for k, label, _ in RESULT_STATUSES}
RESULT_COLORS = {k: color for k, _, color in RESULT_STATUSES}
# Hex equivalents for charts.
RESULT_HEX = {"compliant": "#198754", "partial": "#ffc107", "non_compliant": "#dc3545",
              "not_applicable": "#6c757d", "not_assessed": "#ced4da"}

ACTION_STATUSES = [
    ("open", "Open", "danger"),
    ("in_progress", "In progress", "warning"),
    ("done", "Done", "success"),
    ("cancelled", "Cancelled", "secondary"),
    # Set automatically when an open action is transferred to a follow-up assessment.
    ("carried_over", "Carried over", "info"),
]
EDITABLE_ACTION_STATUSES = [s for s in ACTION_STATUSES if s[0] != "carried_over"]
ACTION_KEYS = [s[0] for s in ACTION_STATUSES]
ACTION_LABELS = {k: label for k, label, _ in ACTION_STATUSES}
ACTION_COLORS = {k: color for k, _, color in ACTION_STATUSES}
OPEN_ACTION_KEYS = ("open", "in_progress")

PRIORITIES = [("high", "High"), ("medium", "Medium"), ("low", "Low")]
PRIORITY_KEYS = [p[0] for p in PRIORITIES]


class Framework(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    versions = db.relationship(
        "FrameworkVersion",
        back_populates="framework",
        order_by="FrameworkVersion.created_at",
        cascade="all, delete-orphan",
    )

    @property
    def published_versions(self):
        return [v for v in self.versions if v.is_published]

    @property
    def latest_published(self):
        published = self.published_versions
        return published[-1] if published else None


class FrameworkVersion(db.Model):
    __table_args__ = (db.UniqueConstraint("framework_id", "label"),)

    id = db.Column(db.Integer, primary_key=True)
    framework_id = db.Column(db.Integer, db.ForeignKey("framework.id"), nullable=False)
    label = db.Column(db.String(50), nullable=False)
    effective_date = db.Column(db.Date)
    notes = db.Column(db.Text, default="")
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft | published
    previous_version_id = db.Column(db.Integer, db.ForeignKey("framework_version.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    published_at = db.Column(db.DateTime)

    framework = db.relationship("Framework", back_populates="versions")
    previous_version = db.relationship("FrameworkVersion", remote_side=[id])
    requirements = db.relationship(
        "Requirement",
        back_populates="version",
        order_by="Requirement.position",
        cascade="all, delete-orphan",
        foreign_keys="Requirement.version_id",
    )
    assessments = db.relationship("Assessment", back_populates="version")

    @property
    def is_published(self):
        return self.status == "published"

    @property
    def display_name(self):
        return f"{self.framework.name} {self.label}"


class Requirement(db.Model):
    __table_args__ = (db.UniqueConstraint("version_id", "code"),)

    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("framework_version.id"), nullable=False)
    code = db.Column(db.String(100), nullable=False)
    section = db.Column(db.String(300), default="")
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, default="")
    guidance = db.Column(db.Text, default="")
    position = db.Column(db.Integer, nullable=False, default=0)
    # Same requirement in the previous version (None if new).
    predecessor_id = db.Column(db.Integer, db.ForeignKey("requirement.id"))
    # Stable identifier shared by every version of the same requirement.
    lineage_id = db.Column(db.Integer, index=True)
    # Relative to the previous version: new | modified | unchanged (None for a first version).
    change_type = db.Column(db.String(20))

    version = db.relationship("FrameworkVersion", back_populates="requirements", foreign_keys=[version_id])
    predecessor = db.relationship("Requirement", remote_side=[id])

    def content_signature(self):
        norm = lambda s: " ".join((s or "").split())  # noqa: E731
        return (norm(self.section), norm(self.title), norm(self.description))


class Assessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    version_id = db.Column(db.Integer, db.ForeignKey("framework_version.id"), nullable=False)
    scope = db.Column(db.Text, default="")
    assessor = db.Column(db.String(200), default="")
    general_comment = db.Column(db.Text, default="")
    status = db.Column(db.String(20), nullable=False, default="in_progress")  # in_progress | completed
    based_on_id = db.Column(db.Integer, db.ForeignKey("assessment.id"))
    started_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    # Reference date of the assessment, used for the evolution timeline.
    assessment_date = db.Column(db.Date)
    completed_at = db.Column(db.DateTime)

    version = db.relationship("FrameworkVersion", back_populates="assessments")
    based_on = db.relationship("Assessment", remote_side=[id])
    results = db.relationship("AssessmentResult", back_populates="assessment", cascade="all, delete-orphan")
    actions = db.relationship(
        "Action", back_populates="assessment", cascade="all, delete-orphan", order_by="Action.due_date"
    )

    @property
    def is_completed(self):
        return self.status == "completed"

    @property
    def framework(self):
        return self.version.framework

    @property
    def reference_date(self):
        return self.assessment_date or (self.completed_at or self.started_at).date()


class AssessmentResult(db.Model):
    __table_args__ = (db.UniqueConstraint("assessment_id", "requirement_id"),)

    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey("requirement.id"), nullable=False)
    status = db.Column(db.String(20))  # one of RESULT_KEYS, None = not assessed yet
    comment = db.Column(db.Text, default="")
    evidence = db.Column(db.Text, default="")
    # Set when pre-filled from an older assessment whose requirement text has since changed.
    needs_review = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    assessment = db.relationship("Assessment", back_populates="results")
    requirement = db.relationship("Requirement")


class Action(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"), nullable=False)
    requirement_id = db.Column(db.Integer, db.ForeignKey("requirement.id"))
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, default="")
    owner = db.Column(db.String(200), default="")
    priority = db.Column(db.String(10), nullable=False, default="medium")
    status = db.Column(db.String(20), nullable=False, default="open")
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    closed_at = db.Column(db.DateTime)
    carried_from_id = db.Column(db.Integer, db.ForeignKey("action.id"))

    assessment = db.relationship("Assessment", back_populates="actions")
    requirement = db.relationship("Requirement")
    carried_from = db.relationship("Action", remote_side=[id])

    @property
    def is_open(self):
        return self.status in OPEN_ACTION_KEYS

    @property
    def is_overdue(self):
        return self.is_open and self.due_date is not None and self.due_date < date.today()

    def set_status(self, status):
        if status not in ACTION_KEYS:
            raise ValueError(status)
        self.status = status
        self.closed_at = None if status in OPEN_ACTION_KEYS else (self.closed_at or utcnow())
