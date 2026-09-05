"""نگاشتِ نسخه‌دارِ منبع (§۸.۲) — تاریخچه‌ی افزودنیِ نگاشتِ ستون‌ها به‌ازای امضای سرستون.

جدولِ legacy `mapping_profiles` با upsert بازنویسی می‌شود و فقط «آخرین» را دارد؛
اینجا هر نگاشتِ متفاوتی که روی یک امضا نهایی شد نسخه می‌گیرد. تحلیلِ دوباره با
همان نگاشت (همان نقش→ستون، همان واحدها) نسخه‌ی تازه **نمی‌سازد**.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from .base import now_ts
from .models import ImportBatch, MappingProfileVersion

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def mapping_hash(mapping: dict, file_currency: str | None, display_currency: str | None) -> str:
    """اثرِ انگشتِ یک نگاشت: نقش→ستون + واحدِ فایل و نمایش (ترتیب‌مستقل)."""
    canonical = json.dumps(
        {
            "mapping": {str(k): str(v) for k, v in sorted(mapping.items(), key=lambda kv: str(kv[0]))},
            "file_currency": file_currency,
            "display_currency": display_currency,
        },
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_mapping_version(
    session: Session, business_id: int, *, signature: str, columns: list[str],
    mapping: dict, file_currency: str | None, display_currency: str | None,
) -> MappingProfileVersion:
    """نسخه‌ی این نگاشت برای این امضا — موجود اگر همان باشد، وگرنه نسخه‌ی بعدی."""
    digest = mapping_hash(mapping, file_currency, display_currency)
    existing = session.scalar(
        select(MappingProfileVersion).where(
            MappingProfileVersion.business_id == business_id,
            MappingProfileVersion.signature == signature,
            MappingProfileVersion.mapping_hash == digest,
        )
    )
    if existing is not None:
        return existing
    latest = session.scalar(
        select(func.max(MappingProfileVersion.version)).where(
            MappingProfileVersion.business_id == business_id,
            MappingProfileVersion.signature == signature,
        )
    )
    row = MappingProfileVersion(
        business_id=business_id,
        signature=signature,
        version=int(latest or 0) + 1,
        mapping_hash=digest,
        columns_json=json.dumps([str(c) for c in columns], ensure_ascii=False),
        mapping_json=json.dumps(
            {str(k): str(v) for k, v in mapping.items()}, ensure_ascii=False,
        ),
        file_currency=file_currency,
        display_currency=display_currency,
        created_at=now_ts(),
    )
    session.add(row)
    session.flush()
    return row


def _version_payload(row: MappingProfileVersion, batches: list[int]) -> dict:
    try:
        columns = json.loads(row.columns_json)
    except (TypeError, ValueError):
        columns = []
    try:
        mapping = json.loads(row.mapping_json)
    except (TypeError, ValueError):
        mapping = {}
    return {
        "version": row.version,
        "mapping": mapping,
        "columns": columns,
        "file_currency": row.file_currency,
        "display_currency": row.display_currency,
        "created_at": row.created_at,
        "batch_ids": batches,
    }


def mapping_history(
    session: Session, business_id: int, *, signature: str | None = None,
) -> list[dict]:
    """امضاها با تاریخچه‌ی نسخه‌هایشان (نسخه‌ی ۱ اول) و دسته‌هایی که هر نسخه ساخت."""
    stmt = select(MappingProfileVersion).where(
        MappingProfileVersion.business_id == business_id,
    )
    if signature:
        stmt = stmt.where(MappingProfileVersion.signature == signature)
    rows = session.scalars(
        stmt.order_by(MappingProfileVersion.signature, MappingProfileVersion.version)
    ).all()
    if not rows:
        return []
    used = session.execute(
        select(ImportBatch.mapping_signature, ImportBatch.mapping_version, ImportBatch.id)
        .where(
            ImportBatch.business_id == business_id,
            ImportBatch.mapping_signature.isnot(None),
        )
        .order_by(ImportBatch.id)
    ).all()
    batches_of: dict[tuple[str, int], list[int]] = {}
    for sig, version, batch_id in used:
        batches_of.setdefault((str(sig), int(version or 0)), []).append(int(batch_id))

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.signature, []).append(
            _version_payload(row, batches_of.get((row.signature, row.version), []))
        )
    return [
        {
            "signature": sig,
            "versions": len(history),
            "latest_version": history[-1]["version"],
            "history": history,
        }
        for sig, history in grouped.items()
    ]


__all__ = ["mapping_hash", "mapping_history", "record_mapping_version"]
