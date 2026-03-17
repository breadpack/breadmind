"""Personal assistant REST API for Task/Event/Contact management."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/personal", tags=["personal"])


# --- Pydantic Models ---

class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: str = "medium"
    due_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    assignee: str | None = None

class TaskUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    priority: str | None = None
    due_at: str | None = None
    tags: list[str] | None = None

class EventCreate(BaseModel):
    title: str
    start_at: str
    end_at: str | None = None
    all_day: bool = False
    location: str | None = None
    attendees: list[str] = Field(default_factory=list)
    reminder_minutes: list[int] = Field(default_factory=lambda: [15])
    recurrence: str | None = None

class EventUpdate(BaseModel):
    title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    location: str | None = None

class ContactCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    organization: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


# --- Helper ---

def _get_registry(request: Request):
    registry = getattr(request.app.state, "adapter_registry", None)
    if not registry:
        raise HTTPException(503, "Personal assistant not available")
    return registry


def _get_default_adapter(registry, domain: str):
    """Get the best adapter for creating new items.

    Priority: connected external service > builtin.
    If multiple external services are connected, prefer the first authenticated one.
    Falls back to builtin if nothing else is available.
    """
    adapters = registry.list_adapters(domain)
    builtin = None
    for adapter in adapters:
        if adapter.source == "builtin":
            builtin = adapter
            continue
        # Check if external adapter is authenticated (has credentials)
        # External adapters typically have _api_key, _token, _oauth, etc.
        if _is_authenticated(adapter):
            return adapter
    # Fallback to builtin
    if builtin:
        return builtin
    if adapters:
        return adapters[0]
    raise HTTPException(503, f"No {domain} adapter available")


def _is_authenticated(adapter) -> bool:
    """Check if an external adapter has been authenticated."""
    # OAuth-based adapters have _oauth with credentials
    oauth = getattr(adapter, "_oauth", None)
    if oauth:
        # Can't await here, so check if oauth manager exists
        return True  # Will fail gracefully at API call time if not actually authed
    # API key-based adapters
    if getattr(adapter, "_api_key", None):
        return True
    # Token-based adapters
    if getattr(adapter, "_token", None):
        return True
    # Jira-style auth
    if getattr(adapter, "_auth_header", None):
        return True
    return False

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise HTTPException(400, f"Invalid datetime: {value}")


# --- Tasks ---

@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str | None = None,
    priority: str | None = None,
    due_before: str | None = None,
    source: str = "all",
):
    registry = _get_registry(request)
    filters: dict[str, Any] = {"user_id": "default"}
    if status:
        filters["status"] = status
    if priority:
        filters["priority"] = priority
    if due_before:
        filters["due_before"] = _parse_dt(due_before)

    if source == "all":
        adapters = registry.list_adapters("task")
    else:
        try:
            adapters = [registry.get_adapter("task", source)]
        except KeyError:
            raise HTTPException(404, f"Task adapter '{source}' not found")

    all_tasks = []
    for adapter in adapters:
        try:
            tasks = await adapter.list_items(filters=filters)
            all_tasks.extend(tasks)
        except Exception:
            pass  # Skip adapters that fail (e.g., not authenticated)
    return [_task_to_dict(t) for t in all_tasks]


@router.post("/tasks", status_code=201)
async def create_task(request: Request, body: TaskCreate):
    registry = _get_registry(request)
    from breadmind.personal.models import Task

    adapter = _get_default_adapter(registry, "task")
    task = Task(
        id="", title=body.title, description=body.description,
        priority=body.priority, due_at=_parse_dt(body.due_at),
        tags=body.tags, assignee=body.assignee, user_id="default",
    )
    task_id = await adapter.create_item(task)
    return {"id": task_id, "title": body.title, "source": adapter.source}


@router.patch("/tasks/{task_id}")
async def update_task(request: Request, task_id: str, body: TaskUpdate):
    registry = _get_registry(request)
    adapter = registry.get_adapter("task", "builtin")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "due_at" in changes:
        changes["due_at"] = _parse_dt(changes["due_at"])
    await adapter.update_item(task_id, changes)
    return {"updated": True, "id": task_id}


@router.delete("/tasks/{task_id}")
async def delete_task(request: Request, task_id: str):
    registry = _get_registry(request)
    adapter = registry.get_adapter("task", "builtin")
    await adapter.delete_item(task_id)
    return {"deleted": True, "id": task_id}


# --- Events ---

@router.get("/events")
async def list_events(
    request: Request,
    start_after: str | None = None,
    start_before: str | None = None,
    source: str = "all",
):
    registry = _get_registry(request)
    filters: dict[str, Any] = {"user_id": "default"}
    if start_after:
        filters["start_after"] = _parse_dt(start_after)
    if start_before:
        filters["start_before"] = _parse_dt(start_before)

    if source == "all":
        adapters = registry.list_adapters("event")
    else:
        try:
            adapters = [registry.get_adapter("event", source)]
        except KeyError:
            raise HTTPException(404, f"Event adapter '{source}' not found")

    all_events = []
    for adapter in adapters:
        try:
            events = await adapter.list_items(filters=filters)
            all_events.extend(events)
        except Exception:
            pass
    # Sort by start_at
    all_events.sort(key=lambda e: e.start_at if e.start_at else datetime.min.replace(tzinfo=timezone.utc))
    return [_event_to_dict(e) for e in all_events]


@router.post("/events", status_code=201)
async def create_event(request: Request, body: EventCreate):
    registry = _get_registry(request)
    from breadmind.personal.models import Event, normalize_recurrence
    from datetime import timedelta

    adapter = _get_default_adapter(registry, "event")
    start = _parse_dt(body.start_at)
    end = _parse_dt(body.end_at) if body.end_at else start + timedelta(hours=1)

    event = Event(
        id="", title=body.title, start_at=start, end_at=end,
        all_day=body.all_day, location=body.location,
        attendees=body.attendees, reminder_minutes=body.reminder_minutes,
        recurrence=normalize_recurrence(body.recurrence), user_id="default",
    )
    event_id = await adapter.create_item(event)
    return {"id": event_id, "title": body.title, "source": adapter.source}


@router.patch("/events/{event_id}")
async def update_event(request: Request, event_id: str, body: EventUpdate):
    registry = _get_registry(request)
    adapter = registry.get_adapter("event", "builtin")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "start_at" in changes:
        changes["start_at"] = _parse_dt(changes["start_at"])
    if "end_at" in changes:
        changes["end_at"] = _parse_dt(changes["end_at"])
    await adapter.update_item(event_id, changes)
    return {"updated": True, "id": event_id}


@router.delete("/events/{event_id}")
async def delete_event(request: Request, event_id: str):
    registry = _get_registry(request)
    adapter = registry.get_adapter("event", "builtin")
    await adapter.delete_item(event_id)
    return {"deleted": True, "id": event_id}


# --- Contacts ---

@router.get("/contacts")
async def list_contacts(request: Request, query: str | None = None):
    registry = _get_registry(request)
    adapters = registry.list_adapters("contact")
    if not adapters:
        return []

    all_contacts = []
    for adapter in adapters:
        filters: dict[str, Any] = {"user_id": "default"}
        if query:
            filters["query"] = query
        contacts = await adapter.list_items(filters=filters)
        all_contacts.extend(contacts)

    return [_contact_to_dict(c) for c in all_contacts]


@router.post("/contacts", status_code=201)
async def create_contact(request: Request, body: ContactCreate):
    registry = _get_registry(request)
    from breadmind.personal.models import Contact

    adapter = _get_default_adapter(registry, "contact")

    contact = Contact(
        id="", name=body.name, email=body.email, phone=body.phone,
        organization=body.organization, tags=body.tags, notes=body.notes,
        user_id="default",
    )
    contact_id = await adapter.create_item(contact)
    return {"id": contact_id, "name": body.name}


# --- Cross Domain ---

@router.get("/agenda")
async def daily_agenda(request: Request, date: str | None = None):
    """Get combined daily agenda (events + due tasks)."""
    registry = _get_registry(request)
    from breadmind.personal.cross_domain import CrossDomainQuery

    query = CrossDomainQuery(registry)
    result = await query.daily_agenda("default", _parse_dt(date))
    return {
        "events": [_event_to_dict(e) for e in result["events"]],
        "tasks": [_task_to_dict(t) for t in result["tasks"]],
        "message": result["message"],
    }


@router.get("/free-slots")
async def free_slots(
    request: Request,
    duration: int = 60,
    days: int = 3,
):
    registry = _get_registry(request)
    from breadmind.personal.cross_domain import CrossDomainQuery

    query = CrossDomainQuery(registry)
    slots = await query.find_free_slots("default", duration, days)
    return [{"start": s["start"].isoformat(), "end": s["end"].isoformat(),
             "duration_minutes": s["duration_minutes"]} for s in slots]


# --- Serialization helpers ---

def _task_to_dict(t) -> dict:
    return {
        "id": t.id, "title": t.title, "description": t.description,
        "status": t.status, "priority": t.priority,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "tags": t.tags, "assignee": t.assignee, "source": t.source,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }

def _event_to_dict(e) -> dict:
    return {
        "id": e.id, "title": e.title, "description": e.description,
        "start_at": e.start_at.isoformat() if e.start_at else None,
        "end_at": e.end_at.isoformat() if e.end_at else None,
        "all_day": e.all_day, "location": e.location,
        "attendees": e.attendees, "source": e.source,
    }

def _contact_to_dict(c) -> dict:
    return {
        "id": c.id, "name": c.name, "email": c.email,
        "phone": c.phone, "organization": c.organization,
        "tags": c.tags, "source": getattr(c, "source", "builtin"),
    }
