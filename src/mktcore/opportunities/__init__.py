"""موتور فرصت‌ها — تبدیل «فهرست اقدام لحظه‌ای» به موجودیتِ ماندگار.

تفاوت بنیادی با آنچه هست: `analysis/actions.py` امروز یک فهرستِ درست و رتبه‌بندی
شده می‌سازد که با هر تحلیل از نو ساخته می‌شود. آن ماژول **تغییر نمی‌کند** —
ریاضی‌اش درست است و تست دارد. این لایه همان خروجی را می‌گیرد و چیزی می‌سازد که
نبود: فرصتی که پذیرفته می‌شود، به کسی سپرده می‌شود، نتیجه می‌گیرد، و دفعه‌ی بعد
دوباره از صفر ساخته نمی‌شود.

بدون این، حلقه‌ی «پیشنهاد → اقدام → نتیجه» باز می‌ماند و نرم‌افزار در حد
«گزارش‌گر» می‌ماند.
"""

from .contract import (
    FILTER_CODES,
    OpportunityCandidate,
    OpportunityFactorNote,
)
from .engine import ENGINE_VERSION, OpportunityRunResult, run_opportunity_engine

__all__ = [
    "ENGINE_VERSION",
    "FILTER_CODES",
    "OpportunityCandidate",
    "OpportunityFactorNote",
    "OpportunityRunResult",
    "run_opportunity_engine",
]
