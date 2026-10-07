"""Private benefits/stability resource tracker over canonical NEXEN infrastructure.

This module does not submit applications, place calls, sign attestations, spend money,
or send sensitive records. It ranks locally stored resources, prepares minimum-necessary
drafts, and records owner-reviewed contact/application state.
"""
from datetime import datetime, timezone
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

BASE = Path(__file__).resolve().parent
RESOURCES = BASE / "data" / "benefit-resources.json"
PROFILE = Path(r"H:\NEXEN\state\benefits-profile.json")
Stage = Literal["ready", "contacted", "applied", "waiting", "won", "blocked", "ineligible"]


def now():
    return datetime.now(timezone.utc).isoformat()


class ResourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Stage
    notes: str = Field(default="", max_length=4000)
    next_followup: str | None = Field(default=None, max_length=40)
    last_contact: str | None = Field(default=None, max_length=80)


class ProfileUpdate(BaseModel):
    """Non-secret screening facts only; sensitive evidence belongs in official portals."""
    model_config = ConfigDict(extra="forbid")
    city: str = Field(default="", max_length=80)
    county: str = Field(default="", max_length=80)
    zip_code: str = Field(default="", max_length=10)
    household_size: int | None = Field(default=None, ge=1, le=20)
    gross_monthly_income: float | None = Field(default=None, ge=0, le=10_000_000)
    current_benefits: str = Field(default="", max_length=500)
    housing_balance: float | None = Field(default=None, ge=0, le=10_000_000)
    housing_notice_stage: Literal["unknown", "none", "late", "notice", "court"] = "unknown"
    driver_license: Literal["unknown", "yes", "no"] = "unknown"
    can_insure_vehicle: Literal["unknown", "yes", "no"] = "unknown"
    business_registered: Literal["unknown", "yes", "no"] = "unknown"
    business_tax_years: int | None = Field(default=None, ge=0, le=20)
    cat_spay_needed: bool = True
    tax_issue_active: bool = True


class Benefits:
    def __init__(self, db, resources_path=RESOURCES, profile_path=PROFILE):
        self.db = db
        self.resources_path = Path(resources_path)
        self.profile_path = Path(profile_path)
        with db.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS benefit_resource_state(
              resource_id TEXT PRIMARY KEY,
              stage TEXT NOT NULL DEFAULT 'ready',
              notes TEXT NOT NULL DEFAULT '',
              last_contact TEXT,
              next_followup TEXT,
              updated_at TEXT NOT NULL
            );
            """)

    def profile(self):
        try:
            data = json.loads(self.profile_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {"eligibility_flags": {}, "unknowns": [], "disclosure_policy": "Profile unavailable."}
        data.pop("secrets", None)
        data.setdefault("facts", {})
        return data

    def update_profile(self, body):
        # A PATCH must preserve facts the owner did not supply. Never replace a
        # damaged existing profile with the read-only display fallback.
        if self.profile_path.exists():
            try:
                existing = json.loads(self.profile_path.read_text(encoding="utf-8-sig"))
                if not isinstance(existing, dict) or not isinstance(existing.get("facts", {}), dict):
                    raise ValueError("invalid profile")
            except (OSError, ValueError):
                raise HTTPException(503, "Existing benefits profile cannot be updated; original preserved.")
        current = self.profile()
        facts = dict(current.get("facts", {}))
        facts.update(body.model_dump(exclude_unset=True))
        current["facts"] = facts
        location = current.setdefault("location", {"state": "OR"})
        for key in ("city", "county", "zip_code"):
            if key in facts:
                location[key] = facts[key] or None
        labels = {
            "household_size": "household size",
            "gross_monthly_income": "gross monthly household income",
            "current_benefits": "current SSI/SSDI/SNAP/OHP or other benefit status",
            "county": "county",
            "city": "city",
            "driver_license": "driver license status",
            "can_insure_vehicle": "ability to insure/maintain a vehicle",
            "housing_balance": "current rent balance",
            "housing_notice_stage": "rent notice/court stage",
            "business_registered": "business registration status",
            "business_tax_years": "number of business tax-return years available",
        }
        missing = []
        for key, label in labels.items():
            value = facts.get(key)
            if value is None or value == "" or value == "unknown":
                missing.append(label)
        current["unknowns"] = missing
        current["updated_at"] = now()
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.profile_path.parent,
                                             prefix=".benefits-profile-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(current, indent=2))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.profile_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return self.profile()

    def _catalog(self):
        try:
            payload = json.loads(self.resources_path.read_text(encoding="utf-8-sig"))
            rows = payload.get("resources", [])
        except (OSError, ValueError):
            raise HTTPException(503, "Benefits resource catalog is unavailable.")
        if not isinstance(rows, list):
            raise HTTPException(503, "Benefits resource catalog is invalid.")
        return [dict(x) for x in rows if isinstance(x, dict) and x.get("id")]

    @staticmethod
    def _match_tags(profile):
        flags = profile.get("eligibility_flags", {})
        tags = set()
        mapping = {
            "disability_materially_limits_work": {"disability", "work-limited", "assistive-tech"},
            "justice_involved": {"justice-involved", "felony"},
            "minority_owned_business": {"minority-owned"},
            "business_owner": {"business", "small-business", "funding", "contracts"},
            "no_vehicle": {"no-car"},
            "housing_risk": {"rent", "eviction", "housing"},
            "pet_care_need": {"cat", "pet", "spay"},
        }
        for key, values in mapping.items():
            if flags.get(key):
                tags.update(values)
        return tags
    def listing(self):
        profile = self.profile()
        wanted = self._match_tags(profile)
        states = {r["resource_id"]: r for r in self.db.rows("SELECT * FROM benefit_resource_state")}
        rows = self._catalog()
        for row in rows:
            state = states.get(row["id"], {})
            row["stage"] = state.get("stage", "ready")
            row["notes"] = state.get("notes", "")
            row["last_contact"] = state.get("last_contact")
            row["next_followup"] = state.get("next_followup")
            tags = set(row.get("tags") or [])
            row["match_tags"] = sorted(tags & wanted)
            row["match_count"] = len(row["match_tags"])
            row["requires_owner_attestation"] = row.get("submission") in {"human_attestation", "human_review"}
            row["executed"] = False
        rows.sort(key=lambda x: (int(x.get("priority", 9)), -x["match_count"], x.get("name", "")))
        stages = {name: 0 for name in ("ready", "contacted", "applied", "waiting", "won", "blocked", "ineligible")}
        for row in rows:
            stages[row["stage"]] = stages.get(row["stage"], 0) + 1
        return {
            "updated_at": now(),
            "resources": rows,
            "stages": stages,
            "profile": profile,
            "execution": {
                "calls_placed": False,
                "emails_sent": False,
                "applications_submitted": False,
                "purpose": "screen, prepare, track, and preserve evidence"
            }
        }

    def get(self, resource_id):
        for row in self.listing()["resources"]:
            if row["id"] == resource_id:
                return row
        raise HTTPException(404, "Benefit resource not found.")

    def update(self, resource_id, body):
        self.get(resource_id)
        with self.db.connect() as c:
            c.execute("""INSERT INTO benefit_resource_state(resource_id,stage,notes,last_contact,next_followup,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET
                stage=excluded.stage,notes=excluded.notes,last_contact=excluded.last_contact,
                next_followup=excluded.next_followup,updated_at=excluded.updated_at""",
                (resource_id, body.stage, body.notes.strip(), body.last_contact, body.next_followup, now()))
        return self.get(resource_id)
    def draft(self, resource_id, method):
        row = self.get(resource_id)
        method = method.lower()
        if method not in {"call", "email"}:
            raise HTTPException(422, "method must be call or email")
        tags = set(row.get("tags") or [])
        context = []
        if tags & {"rent", "eviction", "housing"}:
            context.append("I am trying to preserve stable housing and need to know which current assistance route fits my actual notice and income situation.")
        if tags & {"disability", "work-limited", "assistive-tech"}:
            context.append("I have a long-term disability that materially limits my ability to work.")
        if "no-car" in tags:
            context.append("I currently lack sustainable personal transportation.")
        if tags & {"business", "small-business", "funding", "contracts", "minority-owned"}:
            context.append("I own an Oregon technology business and want to be screened for the programs or certifications I actually qualify for.")
        if tags & {"cat", "pet", "spay"}:
            context.append("I need affordable care for my cat and want to confirm the current low-income assistance process.")
        if tags & {"tax", "refund"}:
            context.append("I have an unresolved federal refund/payment issue and the delay is contributing to financial hardship.")
        if "justice-involved" in tags:
            context.append("I have a justice-system history that can create an employment barrier.")
        intro = " ".join(context) or "I would like to be screened for the assistance or services I may qualify for."
        questions = (
            "Are you accepting applications or screenings now? "
            "What eligibility facts and documents do you need? "
            "What is the next deadline or follow-up date if capacity is full?"
        )
        if method == "call":
            return {"method": "call", "to": row.get("phone", ""), "draft": f"Hi, I'm calling about {row['name']}. {intro} {questions}"}
        if not row.get("email"):
            raise HTTPException(409, "This resource has no verified email in the catalog.")
        subject = f"Eligibility screening request — {row['name']}"
        draft = f"Hello,\n\n{intro}\n\n{questions}\n\nThank you."
        return {"method": "email", "to": row["email"], "subject": subject, "draft": draft,
                "warning": "Do not attach SSN, banking data, medical records, diagnoses, or legal records to a general inquiry email."}
def register(app, db):
    from pc_control import validate_request
    benefits = Benefits(db)

    @app.get("/benefits", response_class=HTMLResponse)
    def page(request: Request):
        validate_request(request)
        return (BASE / "benefits.html").read_text(encoding="utf-8")

    @app.get("/api/benefits")
    def listing(request: Request):
        validate_request(request)
        return benefits.listing()

    @app.patch("/api/benefits/profile")
    def profile_update(body: ProfileUpdate, request: Request):
        validate_request(request, mutation=True)
        return benefits.update_profile(body)

    @app.patch("/api/benefits/{resource_id}")
    def update(resource_id: str, body: ResourceUpdate, request: Request):
        validate_request(request, mutation=True)
        return benefits.update(resource_id, body)

    @app.get("/api/benefits/{resource_id}/draft")
    def draft(resource_id: str, request: Request, method: str = Query(default="call")):
        validate_request(request)
        return benefits.draft(resource_id, method)

    return benefits
