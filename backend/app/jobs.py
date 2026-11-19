"""Background scrape/enrichment jobs (one at a time, in a worker thread).

Progress is kept in memory for live polling and persisted to public.scrape_runs every few
seconds, so the history survives restarts. Run the API with a single worker process.
"""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from startup_scraper.enrichment import Enricher, EnrichmentResult
from startup_scraper.pipeline import ENRICH_TARGETS, collect, run_enrichment, select_enrichment_ids
from startup_scraper.supabase import SupabaseStore
from startup_scraper.stage_filter import filter_by_stage_types

from .auth import admin_user
from .companies import invalidate_facets, valid_id
from .config import Settings, get_settings
from .schemas import CollectJobInput, EnrichJobInput, UserContext
from .supabase import SupabaseAPI, eq


router = APIRouter(prefix="/admin/jobs", tags=["admin", "jobs"])
LOG_LIMIT = 300
PERSIST_EVERY = 3.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job:
    def __init__(self, run_id: str, kind: str, options: dict[str, Any], store: SupabaseStore):
        self.id = run_id
        self.kind = kind
        self.options = options
        self.store = store
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.status = "queued"
        self.started_at: str | None = None
        self.progress: dict[str, Any] = {"stage": "queued", "processed": 0, "total": 0}
        self.counters: dict[str, int] = {
            "companies_found": 0, "rounds_found": 0, "companies_saved": 0, "rounds_saved": 0,
            "enriched_count": 0, "websites_found": 0, "careers_found": 0, "founded_found": 0,
        }
        self.log_lines: list[str] = []
        self.error: str | None = None
        self._last_persist = 0.0

    # -- state updates (called from the worker thread) ------------------------------
    def log(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {message}"
        with self.lock:
            self.log_lines.append(line[:500])
            del self.log_lines[:-LOG_LIMIT]
        self.persist()

    def stage(self, name: str, total: int = 0) -> None:
        with self.lock:
            self.progress.update({"stage": name, "processed": 0, "total": total})
        self.persist(force=True)

    def record(self, result: EnrichmentResult) -> None:
        with self.lock:
            self.progress["processed"] = self.progress.get("processed", 0) + 1
            self.counters["enriched_count"] += 1
            self.counters["websites_found"] += int(result.website_found)
            self.counters["careers_found"] += int(result.careers_found)
            self.counters["founded_found"] += int(result.founded_found)
            self.progress["errors"] = self.progress.get("errors", 0) + int(result.error is not None)
            interesting = [
                line for line in result.log
                if line.startswith(("website found", "founded ")) or (line.startswith("careers: ") and "none" not in line)
            ]
        if interesting:
            self.log(f"{result.company_id[:8]} · " + " · ".join(interesting)[:400])
        else:
            self.persist()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "progress": dict(self.progress),
                "log": list(self.log_lines),
                "error": self.error,
                **self.counters,
            }

    def persist(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_persist < PERSIST_EVERY:
            return
        self._last_persist = time.monotonic()
        try:
            self.store.patch("scrape_runs", f"id=eq.{self.id}", self.snapshot(), origin="jobs")
        except Exception:  # noqa: BLE001 - progress is best effort; the job keeps running
            pass

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "options": self.options, "started_at": self.started_at, **self.snapshot()}


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active: Job | None = None

    def busy(self) -> bool:
        return self.active is not None and self.active.status in {"queued", "running"}

    def start(self, kind: str, options: dict[str, Any], admin: UserContext, settings: Settings) -> Job:
        with self._lock:
            if self.busy():
                raise HTTPException(409, "Another job is already running. Cancel it or wait for it to finish.")
            store = SupabaseStore(settings.supabase_url, settings.supabase_service_role_key, origin="scraper")
            row = store.insert("scrape_runs", {
                "kind": kind,
                "status": "queued",
                "requested_by": admin.id,
                "requested_by_email": admin.email,
                "sources": options.get("sources") or [],
                "options": options,
            })[0]
            job = Job(row["id"], kind, options, store)
            self.active = job
        threading.Thread(target=self._run, args=(job, settings), name=f"job-{job.id[:8]}", daemon=True).start()
        return job

    def _run(self, job: Job, settings: Settings) -> None:
        job.status = "running"
        job.started_at = utc_now()
        try:
            job.store.patch("scrape_runs", f"id=eq.{job.id}", {"status": "running", "started_at": job.started_at}, origin="jobs")
        except Exception:  # noqa: BLE001
            pass
        try:
            if job.kind == "collect":
                self._collect(job, settings)
            else:
                self._enrich(job, settings, job.options)
            job.status = "cancelled" if job.cancel.is_set() else "completed"
            job.log("Job cancelled" if job.cancel.is_set() else "Job finished")
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = f"{exc.__class__.__name__}: {exc}"[:2000]
            job.log(f"Failed: {job.error}")
            traceback.print_exc()
        finally:
            job.progress["stage"] = job.status
            try:
                job.store.patch(
                    "scrape_runs", f"id=eq.{job.id}", {**job.snapshot(), "completed_at": utc_now()}, origin="jobs"
                )
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            invalidate_facets()

    def _collect(self, job: Job, settings: Settings) -> None:
        options = job.options
        job.stage("collecting")
        companies, rounds = collect(
            set(options["sources"]),
            sec_user_agent=settings.sec_user_agent,
            sec_quarters=options["sec_quarters"],
            limit=options.get("limit"),
            include_funds=options.get("include_funds", False),
            log=job.log,
        )
        selected_types = options.get("funding_types") or []
        if selected_types:
            before = len(companies)
            companies, rounds = filter_by_stage_types(companies, rounds, selected_types)
            job.log(
                f"Early-stage filter kept {len(companies)} of {before} companies "
                f"({', '.join(selected_types)})"
            )
        job.counters["companies_found"] = len(companies)
        job.counters["rounds_found"] = len(rounds)
        if job.cancel.is_set():
            return
        job.stage("saving", total=len(companies))
        saved_companies, saved_rounds = job.store.save(companies, rounds)
        job.counters["companies_saved"] = saved_companies
        job.counters["rounds_saved"] = saved_rounds
        job.log(f"Saved {saved_companies} companies and {saved_rounds} funding rounds")
        invalidate_facets()
        if options.get("enrich_after") and options.get("enrich_limit") and not job.cancel.is_set():
            self._enrich(job, settings, {
                "target": options.get("enrich_target") or "never",
                "limit": options["enrich_limit"],
                "only_startups": True,
            })

    def _enrich(self, job: Job, settings: Settings, options: dict[str, Any]) -> None:
        job.stage("selecting companies")
        if options.get("ids"):
            ids = list(dict.fromkeys(options["ids"]))[: options.get("limit") or 2000]
        else:
            ids = select_enrichment_ids(
                job.store,
                options["target"],
                options["limit"],
                only_startups=options.get("only_startups", False),
                sources=options.get("sources") or None,
            )
        target = ENRICH_TARGETS.get(options.get("target", ""), "selected companies")
        job.log(f"Enriching {len(ids)} companies ({target.lower()})")
        job.stage("enriching", total=len(ids))
        enricher = Enricher(settings.enrich_user_agent, brave_api_key=settings.brave_search_api_key or "")
        run_enrichment(
            job.store,
            ids,
            enricher=enricher,
            workers=settings.enrich_workers,
            should_stop=job.cancel.is_set,
            on_result=job.record,
        )
        job.log(
            f"Enrichment done: {job.counters['websites_found']} websites, {job.counters['careers_found']} careers pages, "
            f"{job.counters['founded_found']} founding dates"
        )


manager = JobManager()


async def mark_interrupted_runs(settings: Settings) -> None:
    """Runs left 'running' by a previous process can never finish; close them out."""
    try:
        await SupabaseAPI(settings).update(
            "scrape_runs",
            "status=in.(queued,running)",
            {"status": "failed", "error": "Interrupted: the API server restarted", "completed_at": utc_now()},
        )
    except Exception:  # noqa: BLE001 - the table may not exist before the migration is applied
        pass


@router.post("/collect", status_code=202)
async def start_collect(payload: CollectJobInput, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    """Scrape SEC Form D / funding news / YC, save, then optionally enrich new companies."""
    job = await asyncio.to_thread(manager.start, "collect", payload.model_dump(), admin, settings)
    return job.public()


@router.post("/enrich", status_code=202)
async def start_enrich(payload: EnrichJobInput, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    """Find websites, careers pages, and founding dates for existing companies."""
    options = payload.model_dump()
    options["ids"] = [valid_id(item) for item in options["ids"]]
    job = await asyncio.to_thread(manager.start, "enrich", options, admin, settings)
    return job.public()


@router.get("/active")
async def active_job(admin: UserContext = Depends(admin_user)):
    job = manager.active
    return job.public() if job and manager.busy() else None


@router.get("")
async def job_history(admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    rows, _ = await SupabaseAPI(settings).select(
        "scrape_runs",
        "select=id,kind,status,sources,options,progress,companies_found,rounds_found,companies_saved,rounds_saved,"
        "enriched_count,websites_found,careers_found,founded_found,error,requested_by_email,created_at,started_at,completed_at"
        "&order=created_at.desc&limit=40",
    )
    job = manager.active
    if job and manager.busy():
        for row in rows:
            if row["id"] == job.id:
                row.update(job.snapshot())
    return rows


@router.get("/{run_id}")
async def job_detail(run_id: str, admin: UserContext = Depends(admin_user), settings: Settings = Depends(get_settings)):
    job = manager.active
    if job and job.id == run_id and manager.busy():
        return job.public()
    rows, _ = await SupabaseAPI(settings).select("scrape_runs", f"select=*&id={eq(valid_id(run_id))}&limit=1")
    if not rows:
        raise HTTPException(404, "Job not found")
    return rows[0]


@router.post("/{run_id}/cancel")
async def cancel_job(run_id: str, admin: UserContext = Depends(admin_user)):
    job = manager.active
    if not job or job.id != run_id or not manager.busy():
        raise HTTPException(404, "This job is not running")
    job.cancel.set()
    job.log(f"Cancellation requested by {admin.email}; finishing in-flight companies…")
    return {"id": run_id, "status": "cancelling"}
