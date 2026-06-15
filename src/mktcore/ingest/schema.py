"""قرارداد داده‌ی استاندارد فروش و نقش ستون‌ها."""

from __future__ import annotations

from enum import Enum


class ColumnRole(str, Enum):
    """نقش‌های استانداردی که هر ستون داده‌ی فروش می‌تواند بازی کند."""

    DATE = "DATE"
    REVENUE = "REVENUE"
    QUANTITY = "QUANTITY"
    UNIT_PRICE = "UNIT_PRICE"
    PRODUCT = "PRODUCT"
    CATEGORY = "CATEGORY"
    CUSTOMER_ID = "CUSTOMER_ID"
    CHANNEL = "CHANNEL"
    REGION = "REGION"
    COST = "COST"
    ORDER_ID = "ORDER_ID"
    DISCOUNT = "DISCOUNT"
    SALESPERSON = "SALESPERSON"
    BRANCH = "BRANCH"
    PHONE = "PHONE"
    EMAIL = "EMAIL"


# نام ستون استاندارد در StandardSalesFrame برای هر نقش (lowercase snake_case)
ROLE_TO_COLUMN: dict[ColumnRole, str] = {
    ColumnRole.DATE: "date",
    ColumnRole.REVENUE: "revenue",
    ColumnRole.QUANTITY: "quantity",
    ColumnRole.UNIT_PRICE: "unit_price",
    ColumnRole.PRODUCT: "product",
    ColumnRole.CATEGORY: "category",
    ColumnRole.CUSTOMER_ID: "customer_id",
    ColumnRole.CHANNEL: "channel",
    ColumnRole.REGION: "region",
    ColumnRole.COST: "cost",
    ColumnRole.ORDER_ID: "order_id",
    ColumnRole.DISCOUNT: "discount",
    ColumnRole.SALESPERSON: "salesperson",
    ColumnRole.BRANCH: "branch",
    ColumnRole.PHONE: "phone",
    ColumnRole.EMAIL: "email",
}

# نقش‌هایی که برای انجام هر تحلیلی ضروری‌اند
REQUIRED_ROLES: tuple[ColumnRole, ...] = (ColumnRole.DATE, ColumnRole.REVENUE)

# نقش‌های عددی (برای تبدیل و پاک‌سازی)
NUMERIC_ROLES: tuple[ColumnRole, ...] = (
    ColumnRole.REVENUE,
    ColumnRole.QUANTITY,
    ColumnRole.UNIT_PRICE,
    ColumnRole.COST,
    ColumnRole.DISCOUNT,
)

# نقش‌های دسته‌ای/برچسبی
CATEGORICAL_ROLES: tuple[ColumnRole, ...] = (
    ColumnRole.PRODUCT,
    ColumnRole.CATEGORY,
    ColumnRole.CHANNEL,
    ColumnRole.REGION,
    ColumnRole.SALESPERSON,
    ColumnRole.BRANCH,
)


def standard_column(role: ColumnRole) -> str:
    """نام ستون استاندارد متناظر با یک نقش."""
    return ROLE_TO_COLUMN[role]
