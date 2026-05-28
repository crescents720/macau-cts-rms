from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PricingEvent:
    event_date: date
    name: str
    region: str
    category: str
    weight: float


def _date_range(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _event_range(
    start: date,
    end: date,
    name: str,
    region: str,
    category: str,
    weight: float,
) -> list[PricingEvent]:
    return [
        PricingEvent(
            event_date=event_date,
            name=name,
            region=region,
            category=category,
            weight=weight,
        )
        for event_date in _date_range(start, end)
    ]


EVENTS_2026 = [
    *_event_range(date(2026, 1, 1), date(2026, 1, 3), "元旦假期", "中国内地", "public_holiday", 0.08),
    *_event_range(date(2026, 2, 15), date(2026, 2, 23), "春节黄金周", "中国内地", "golden_week", 0.32),
    *_event_range(date(2026, 4, 4), date(2026, 4, 6), "清明节假期", "中国内地", "public_holiday", 0.10),
    *_event_range(date(2026, 5, 1), date(2026, 5, 5), "劳动节假期", "中国内地", "golden_week", 0.22),
    *_event_range(date(2026, 6, 19), date(2026, 6, 21), "端午节假期", "中国内地", "public_holiday", 0.12),
    *_event_range(date(2026, 9, 25), date(2026, 9, 27), "中秋节假期", "中国内地", "public_holiday", 0.14),
    *_event_range(date(2026, 10, 1), date(2026, 10, 7), "国庆黄金周", "中国内地", "golden_week", 0.30),
    PricingEvent(date(2026, 1, 1), "元旦", "澳门", "public_holiday", 0.08),
    PricingEvent(date(2026, 2, 16), "农历除夕下午豁免上班", "澳门", "partial_holiday", 0.06),
    PricingEvent(date(2026, 2, 17), "农历正月初一", "澳门", "lunar_new_year", 0.26),
    PricingEvent(date(2026, 2, 18), "农历正月初二", "澳门", "lunar_new_year", 0.26),
    PricingEvent(date(2026, 2, 19), "农历正月初三", "澳门", "lunar_new_year", 0.24),
    PricingEvent(date(2026, 4, 3), "耶稣受难日", "澳门", "public_holiday", 0.08),
    PricingEvent(date(2026, 4, 4), "复活节前日", "澳门", "public_holiday", 0.07),
    PricingEvent(date(2026, 4, 5), "清明节", "澳门", "public_holiday", 0.10),
    PricingEvent(date(2026, 4, 6), "复活节前日补假", "澳门", "compensatory_holiday", 0.06),
    PricingEvent(date(2026, 4, 7), "清明节补假", "澳门", "compensatory_holiday", 0.06),
    PricingEvent(date(2026, 5, 1), "劳动节", "澳门", "public_holiday", 0.16),
    PricingEvent(date(2026, 5, 24), "佛诞节", "澳门", "public_holiday", 0.06),
    PricingEvent(date(2026, 5, 25), "佛诞节补假", "澳门", "compensatory_holiday", 0.05),
    PricingEvent(date(2026, 6, 19), "端午节", "澳门", "public_holiday", 0.10),
    PricingEvent(date(2026, 9, 26), "中秋节翌日", "澳门", "public_holiday", 0.12),
    PricingEvent(date(2026, 9, 28), "中秋节翌日补假", "澳门", "compensatory_holiday", 0.06),
    PricingEvent(date(2026, 10, 1), "中华人民共和国国庆日", "澳门", "public_holiday", 0.20),
    PricingEvent(date(2026, 10, 2), "中华人民共和国国庆日翌日", "澳门", "public_holiday", 0.18),
    PricingEvent(date(2026, 10, 18), "重阳节", "澳门", "public_holiday", 0.08),
    PricingEvent(date(2026, 10, 19), "重阳节补假", "澳门", "compensatory_holiday", 0.05),
    PricingEvent(date(2026, 11, 2), "追思节", "澳门", "public_holiday", 0.04),
    PricingEvent(date(2026, 12, 8), "圣母无原罪瞻礼", "澳门", "public_holiday", 0.05),
    PricingEvent(date(2026, 12, 20), "澳门特别行政区成立纪念日", "澳门", "public_holiday", 0.12),
    PricingEvent(date(2026, 12, 21), "澳门特别行政区成立纪念日补假", "澳门", "compensatory_holiday", 0.06),
    PricingEvent(date(2026, 12, 22), "冬至", "澳门", "public_holiday", 0.05),
    PricingEvent(date(2026, 12, 24), "圣诞节前日", "澳门", "public_holiday", 0.08),
    PricingEvent(date(2026, 12, 25), "圣诞节", "澳门", "public_holiday", 0.14),
    PricingEvent(date(2026, 12, 31), "除夕下午豁免上班", "澳门", "partial_holiday", 0.08),
]


EVENTS_BY_DATE: dict[date, list[PricingEvent]] = {}
for event in EVENTS_2026:
    EVENTS_BY_DATE.setdefault(event.event_date, []).append(event)


def events_for_date(stay_date: date) -> list[PricingEvent]:
    return EVENTS_BY_DATE.get(stay_date, [])


def event_premium_for_date(stay_date: date) -> tuple[float, list[PricingEvent], list[str]]:
    events = events_for_date(stay_date)
    premium = 0.0
    logic = []
    for event in events:
        market_weight = 0.9 if event.region == "中国内地" else 0.35
        contribution = event.weight * market_weight
        premium += contribution
        logic.append(
            f"{event.region}{event.name}: 事件权重{event.weight:.0%} × 客源权重{market_weight:.0%} = {contribution:.1%}"
        )

    capped_premium = min(premium, 0.42)
    if capped_premium != premium:
        logic.append(f"多事件叠加封顶: {premium:.1%} -> {capped_premium:.1%}")
    return capped_premium, events, logic
