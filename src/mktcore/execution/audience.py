"""ساخت فهرست مخاطب از تحلیل و شخصی‌سازی پیام برای ارسال."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

if TYPE_CHECKING:
    from ..pipeline import MetricsBundle

_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_PHONE = standard_column(ColumnRole.PHONE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)


@dataclass
class Recipient:
    customer_id: str
    phone: str | None = None
    vars: dict[str, str] = field(default_factory=dict)


# انواع مخاطب قابل ساخت از تحلیل
AUDIENCE_KINDS = {
    "سررسیدشده": "مشتریانی که خرید بعدی‌شان سررسید شده است",
    "ناتمام_الگو": "مشتریانی که الگوی خرید توالی را کامل نکرده‌اند",
    "در_معرض_ریزش": "مشتریان سگمنت در معرض ریزش",
    "چرخه_عقب‌افتاده": "مشتریانی که از چرخه‌ی خرید یک کالای مصرفی عقب افتاده‌اند",
    "تارگت_تک‌خریدی": "بالقوه‌های یک کالای تک‌خریدی (هنوز نخریده‌اند)",
}


def _phone_lookup(df: pd.DataFrame) -> dict[str, str]:
    if df is None or _PHONE not in df.columns or _CUSTOMER not in df.columns:
        return {}
    return (
        df.dropna(subset=[_PHONE])
        .groupby(_CUSTOMER)[_PHONE]
        .first()
        .astype(str)
        .to_dict()
    )


def build_audience(
    bundle: MetricsBundle,
    kind: str,
    *,
    df: pd.DataFrame | None = None,
    limit: int = 200,
) -> list[Recipient]:
    """ساخت فهرست مخاطب بر اساس نوع، با تلفن و متغیرهای شخصی‌سازی."""
    phones = _phone_lookup(df) if df is not None else {}
    recipients: list[Recipient] = []

    if kind == "سررسیدشده" and bundle.next_purchase.available:
        for c in bundle.next_purchase.due_now(limit):
            recipients.append(Recipient(
                customer_id=c.customer_id,
                phone=phones.get(c.customer_id),
                vars={
                    "نام": c.customer_id,
                    "محصول": c.likely_products[0] if c.likely_products else "محصولات ما",
                    "سبد_پیشنهادی": "، ".join(c.likely_products) or "—",
                },
            ))

    elif kind == "ناتمام_الگو" and bundle.sequences.available:
        seen: set[str] = set()
        for pat in bundle.sequences.top(5):
            for cust in pat.incomplete_customers:
                if cust in seen:
                    continue
                seen.add(cust)
                recipients.append(Recipient(
                    customer_id=cust,
                    phone=phones.get(cust),
                    vars={"نام": cust, "محصول": pat.consequent, "محصول_قبلی": pat.antecedent},
                ))
                if len(recipients) >= limit:
                    break
            if len(recipients) >= limit:
                break

    elif kind == "چرخه_عقب‌افتاده" and bundle.purchase_cycle.available:
        for note in bundle.purchase_cycle.overdue(limit):
            recipients.append(Recipient(
                customer_id=note.customer_id,
                phone=phones.get(note.customer_id),
                vars={"نام": note.customer_id, "محصول": note.product,
                      "روز_عقب": str(max(note.days_offset, 0))},
            ))

    elif kind == "تارگت_تک‌خریدی" and bundle.purchase_cycle.onetime_targets:
        # پرجمعیت‌ترین هدف تک‌خریدی را انتخاب کن
        target = max(bundle.purchase_cycle.onetime_targets,
                     key=lambda t: len(t.potential_customers))
        for cust in target.potential_customers[:limit]:
            recipients.append(Recipient(
                customer_id=cust,
                phone=phones.get(cust),
                vars={"نام": cust, "محصول": target.product},
            ))

    elif kind == "در_معرض_ریزش" and not bundle.segmentation.rfm_table.empty:
        rfm = bundle.segmentation.rfm_table
        at_risk = rfm[rfm["segment"].isin(["at_risk", "hibernating"])]
        for cust in list(at_risk.index)[:limit]:
            recipients.append(Recipient(
                customer_id=str(cust),
                phone=phones.get(str(cust)),
                vars={"نام": str(cust), "محصول": "محصولات منتخب"},
            ))

    return recipients


_VAR_RE = re.compile(r"\{([^{}]+)\}")


def render_template(template: str, variables: dict[str, str]) -> str:
    """جای‌گذاری متغیرهای {کلید} در قالب پیام؛ متغیر ناموجود دست‌نخورده می‌ماند."""
    def _sub(m: re.Match) -> str:
        key = m.group(1).strip()
        return str(variables.get(key, m.group(0)))
    return _VAR_RE.sub(_sub, template)


@dataclass
class RenderedMessage:
    customer_id: str
    phone: str | None
    text: str


def render_messages(template: str, recipients: list[Recipient]) -> list[RenderedMessage]:
    """رندر پیام شخصی‌سازی‌شده برای هر مخاطب."""
    return [
        RenderedMessage(customer_id=r.customer_id, phone=r.phone,
                        text=render_template(template, r.vars))
        for r in recipients
    ]


__all__ = ["Recipient", "RenderedMessage", "build_audience", "render_messages",
           "render_template", "AUDIENCE_KINDS"]
