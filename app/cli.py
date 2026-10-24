from datetime import date, timedelta

import click
from flask_migrate import upgrade

from . import db
from .models import Action, Framework
from .services import assessments as svc
from .services import versioning
from .services.spreadsheet import RequirementRow

DEMO_V1 = [
    ("1.1", "1. Governance", "Information security policy", "A security policy is approved and communicated."),
    ("1.2", "1. Governance", "Roles and responsibilities", "Security roles are defined and allocated."),
    ("2.1", "2. Assets", "Asset inventory", "An inventory of assets and their owners is maintained."),
    ("2.2", "2. Assets", "Acceptable use", "Rules for acceptable use of assets are documented."),
    ("3.1", "3. Access control", "Access control policy", "Access is granted on a need-to-know basis."),
    ("3.2", "3. Access control", "Password management", "Passwords follow a documented policy."),
    ("4.1", "4. Operations", "Backups", "Backups are performed and restoration is tested."),
    ("4.2", "4. Operations", "Logging", "Security events are logged and kept for 6 months."),
]
# v2: 3.2 replaced by 3.3 (MFA), 4.2 modified, 2.2 removed, 5.1 added.
DEMO_V2 = [
    ("1.1", "1. Governance", "Information security policy", "A security policy is approved and communicated."),
    ("1.2", "1. Governance", "Roles and responsibilities", "Security roles are defined and allocated."),
    ("2.1", "2. Assets", "Asset inventory", "An inventory of assets and their owners is maintained."),
    ("3.1", "3. Access control", "Access control policy", "Access is granted on a need-to-know basis."),
    ("3.3", "3. Access control", "Multi-factor authentication", "MFA is enforced for remote and privileged access."),
    ("4.1", "4. Operations", "Backups", "Backups are performed and restoration is tested."),
    ("4.2", "4. Operations", "Logging and monitoring", "Security events are logged, kept 12 months and reviewed."),
    ("5.1", "5. Suppliers", "Supplier security", "Security requirements are included in supplier contracts."),
]


def _rows(data):
    return [RequirementRow(code=c, section=s, title=t, description=d) for c, s, t, d in data]


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create or upgrade the database schema (runs the migrations)."""
        upgrade()
        click.echo("Database is up to date.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Load a small demo repository with two versions and three assessments."""
        if Framework.query.filter_by(name="Demo Security Baseline").first():
            click.echo("Demo data already present.")
            return
        fw = Framework(name="Demo Security Baseline", description="Small example repository to try the tool.")
        db.session.add(fw)
        v1, _ = versioning.create_version(fw, "2024", rows=_rows(DEMO_V1), effective_date=date(2024, 1, 1))
        versioning.publish(v1)
        v2, _ = versioning.create_version(fw, "2025", rows=_rows(DEMO_V2), base_version=v1,
                                          effective_date=date(2025, 1, 1))
        versioning.publish(v2)

        today = date.today()
        a1 = svc.create_assessment(v1, "Initial assessment", assessor="Demo", assessment_date=today - timedelta(days=400))
        for r, s in zip(svc.sorted_results(a1), ["partial", "non_compliant", "non_compliant", "compliant",
                                                  "partial", "non_compliant", "compliant", "not_applicable"]):
            r.status = s
        reqs = {r.requirement.code: r.requirement for r in a1.results}
        a1.actions.append(_action(reqs["1.2"], "Publish a RACI for security roles", today - timedelta(days=200)))
        a1.actions.append(_action(reqs["2.1"], "Build the asset inventory in the CMDB", today + timedelta(days=30)))
        a1.actions.append(_action(reqs["3.2"], "Roll out password manager", today - timedelta(days=10)))
        svc.complete(a1)
        db.session.flush()
        a1.actions[0].set_status("done")

        a2 = svc.create_assessment(v1, "Follow-up", assessor="Demo", assessment_date=today - timedelta(days=200),
                                   based_on=a1, carry_actions=True)
        for r in a2.results:
            if r.requirement.code in ("1.2", "3.1"):
                r.status = "compliant"
            if r.requirement.code == "2.1":
                r.status = "partial"
        svc.complete(a2)

        a3 = svc.create_assessment(v2, "Annual assessment (new version)", assessor="Demo",
                                   assessment_date=today, based_on=a2, carry_actions=True)
        db.session.commit()
        click.echo(f"Demo data loaded. Open assessment #{a3.id} to finish the ongoing assessment.")


def _action(req, title, due):
    return Action(requirement=req, title=title, owner="CISO", priority="high", due_date=due)
