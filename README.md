# Compliance

A web app (Python, Flask, SQLAlchemy) to assess compliance against versioned repositories of
requirements, such as ISO 9001, ISO/IEC 27001, NATO or corporate policies, and to track the
action plan and how compliance changes over time.

## Features

- **Versioned repositories.** Each repository (framework) has versions. A new version is built
  from the previous one, either by uploading a spreadsheet or by copying the previous version and
  editing it. Each requirement is flagged **new / modified / unchanged**, and removed requirements
  are listed. Renumbered requirements keep their history through the `Previous code` column.
  A version stays a *draft* until you publish it. Published versions can no longer be changed.
- **Spreadsheet template.** Use *Repositories → Spreadsheet template* to download it (.xlsx; .csv
  uploads also work). Any version can be exported in the same format, so you can edit it and
  upload it as the next version.
- **Assessments.** Each assessment runs against one published version. Every requirement is
  rated *Compliant / Partially compliant / Non compliant / Not applicable*, with a comment and
  evidence. Answers **autosave**, so you can leave and come back later. When you **terminate**
  the assessment it becomes read-only (you can reopen it).
- **Follow-up assessments.** A new assessment can start from an earlier one, even on a newer
  version. Answers carry over for requirements that still exist. Answers whose requirement
  wording changed are flagged *to review*, and new requirements start empty. Open actions can be
  carried over too.
- **Action plan.** Each assessment has its own actions, which can be linked to a requirement and
  have an owner, a priority, a due date and a status. A global view lists actions across all
  assessments, filtered by status, overdue, repository or owner and sorted by due date.
- **KPIs and report.** Counts per status, a compliance score (`(compliant + ½ partial) /
  applicable`), a per-section breakdown, the gaps that have no action yet, and a comparison with
  the previous assessment (improved / regressed / new / removed). Excel export is included.
- **Evolution.** For each repository, a timeline chart of status counts and score, plus a
  requirement × assessment matrix. Requirements that did not exist yet are shown as `·`.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                 # optional
.venv/bin/flask --app wsgi init-db   # creates/upgrades the schema
.venv/bin/flask --app wsgi seed-demo # optional: demo repository, 2 versions, 3 assessments
.venv/bin/flask --app wsgi run --debug
```

Then open http://127.0.0.1:5000.

## Database

The app uses SQLite by default (`instance/compliance.db`). To use another database, set
`DATABASE_URL` to any SQLAlchemy URL and install its driver:

```bash
pip install "psycopg[binary]"
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/compliance flask --app wsgi init-db
```

Schema changes go through Alembic migrations (Flask-Migrate): after you change `app/models.py`,
run `flask --app wsgi db migrate -m "..."` and then `flask --app wsgi db upgrade`.

To move existing data from SQLite to another database, export it and import it with a tool such
as `pgloader`, or with a small SQLAlchemy script.

## Data model

```
Framework ──< FrameworkVersion ──< Requirement   (predecessor → same requirement in the previous version,
                    │                             lineage_id  → stable id across all versions)
                    └──< Assessment ──< AssessmentResult (status, comment, evidence, needs_review)
                                    └──< Action          (requirement?, owner, priority, due date, status)
```

## Project layout

```
app/
  models.py               data model and status vocabularies
  services/versioning.py  version building, diffing and lineage
  services/assessments.py prefill, KPIs, comparison, evolution
  services/spreadsheet.py template, import parsing, Excel exports
  routes/                 Flask blueprints (repositories, assessments, actions, dashboard)
  templates/, static/     Bootstrap 5 UI, Chart.js charts, autosave script
migrations/               Alembic migrations
tests/                    pytest suite
```

## Tests

```bash
.venv/bin/pytest
```

## Not included yet

There is no authentication or user management, and no CSRF protection. The app assumes it runs
on a trusted network or behind an authenticating reverse proxy. Add Flask-Login and Flask-WTF
before you expose it more widely.
