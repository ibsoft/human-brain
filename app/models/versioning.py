from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session as OrmSession

from app.extensions import db


class RecordVersion(db.Model):
    __tablename__ = "record_versions"

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(120), nullable=False, index=True)
    record_id = db.Column(db.String(120), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False)
    event = db.Column(db.String(32), nullable=False, index=True)
    data = db.Column(db.JSON, nullable=False, default=dict)
    changed_fields = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.UniqueConstraint("table_name", "record_id", "version_number", name="uq_record_version_number"),
        db.Index("ix_record_versions_lookup", "table_name", "record_id", "version_number"),
    )


def _is_versioned(obj):
    return isinstance(obj, db.Model) and not isinstance(obj, RecordVersion) and hasattr(obj, "__table__")


def _record_id(obj):
    identity = inspect(obj).identity
    if not identity:
        return None
    return ":".join(str(part) for part in identity)


def _changed_fields(obj):
    state = inspect(obj)
    return sorted(attr.key for attr in state.mapper.column_attrs if state.attrs[attr.key].history.has_changes())


def _snapshot(obj):
    state = inspect(obj)
    return {attr.key: _json_value(getattr(obj, attr.key)) for attr in state.mapper.column_attrs}


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _next_version_number(session, table_name, record_id):
    latest = session.execute(
        select(func.max(RecordVersion.version_number)).where(
            RecordVersion.table_name == table_name,
            RecordVersion.record_id == record_id,
        )
    ).scalar()
    return (latest or 0) + 1


def current_record_version(table_name, record_id):
    latest = db.session.execute(
        select(func.max(RecordVersion.version_number)).where(
            RecordVersion.table_name == table_name,
            RecordVersion.record_id == str(record_id),
        )
    ).scalar()
    return latest or 0


def annotate_record_versions(records, table_name):
    records = list(records or [])
    record_ids = [str(record.id) for record in records if getattr(record, "id", None) is not None]
    versions = {}
    if record_ids:
        rows = db.session.execute(
            select(RecordVersion.record_id, func.max(RecordVersion.version_number))
            .where(RecordVersion.table_name == table_name, RecordVersion.record_id.in_(record_ids))
            .group_by(RecordVersion.record_id)
        ).all()
        versions = {record_id: version_number for record_id, version_number in rows}
    for record in records:
        record.current_version = versions.get(str(record.id), 0)
    return records


@event.listens_for(OrmSession, "before_flush")
def collect_record_versions(session, flush_context, instances):
    if session.info.get("record_versioning_disabled"):
        return
    pending = session.info.setdefault("pending_record_versions", [])
    seen = {(id(item["object"]), item["event"]) for item in pending}
    for obj in session.new:
        if _is_versioned(obj) and (id(obj), "inserted") not in seen:
            pending.append({"object": obj, "event": "inserted", "changed_fields": _changed_fields(obj)})
    for obj in session.dirty:
        if not _is_versioned(obj) or not session.is_modified(obj, include_collections=False):
            continue
        if (id(obj), "updated") in seen:
            continue
        pending.append({"object": obj, "event": "updated", "changed_fields": _changed_fields(obj)})


@event.listens_for(OrmSession, "after_flush_postexec")
def write_record_versions(session, flush_context):
    pending = session.info.pop("pending_record_versions", [])
    if not pending or session.info.get("record_versioning_disabled"):
        return
    session.info["record_versioning_disabled"] = True
    try:
        for item in pending:
            obj = item["object"]
            if not _is_versioned(obj):
                continue
            record_id = _record_id(obj)
            if record_id is None:
                continue
            table_name = obj.__tablename__
            version_number = _next_version_number(session, table_name, record_id)
            session.add(
                RecordVersion(
                    table_name=table_name,
                    record_id=record_id,
                    version_number=version_number,
                    event=item["event"],
                    data=_snapshot(obj),
                    changed_fields=item["changed_fields"],
                )
            )
    finally:
        session.info.pop("record_versioning_disabled", None)
