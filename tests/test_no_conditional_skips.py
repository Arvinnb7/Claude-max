"""نگهبان: هیچ تستی نباید با `pytest.skip` **داده‌محور** خودش را خاموش کند.

چهار گاردِ خطِ سرخ همین‌طور بی‌صدا از اجرا افتاده بودند و در شمارشِ «سبز»
دیده می‌شدند. skipِ محیطی (نبودِ یک کتابخانه) مجاز است و اینجا فهرست شده.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# skipهای محیطی که عمداً مجازند: (فایل، متنِ دلیل)
ALLOWED = {
    ("test_reporting.py", "WeasyPrint نصب نیست"),
}


def _skip_calls(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            is_skip = (
                isinstance(func, ast.Attribute) and func.attr == "skip"
                and isinstance(func.value, ast.Name) and func.value.id == "pytest"
            )
            if not is_skip:
                continue
            reason = ""
            if call.args and isinstance(call.args[0], ast.Constant):
                reason = str(call.args[0].value)
            found.append((call.lineno, reason))
    return found


def test_no_data_dependent_skip_inside_a_test_body():
    offenders: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, reason in _skip_calls(tree):
            if (path.name, reason) in ALLOWED:
                continue
            offenders.append(f"{path.name}:{lineno} — {reason or '(بدون دلیل)'}")
    assert not offenders, (
        "skipِ داده‌محور در بدنه‌ی تست ممنوع است؛ فیکسچر را قطعی کنید یا در ALLOWED "
        "با دلیلِ محیطی ثبت کنید:\n" + "\n".join(offenders)
    )
