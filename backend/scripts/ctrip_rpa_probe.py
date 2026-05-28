from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


DEFAULT_GOLDEN_DRAGON_URL = (
    "https://hotels.ctrip.com/hotels/detail/"
    "?cityEnName=Macau&cityId=59&hotelId=345757"
    "&checkIn=2026-05-28&checkOut=2026-05-29"
    "&adult=1&children=0&crn=1&curr=CNY&barcurr=CNY"
    "&display=exavg&isCT=true&isFlexible=F&isFirstEnterDetail=T"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Human-in-the-loop Ctrip hotel page probe for competitor pricing PoC."
    )
    parser.add_argument("--url", default=DEFAULT_GOLDEN_DRAGON_URL)
    parser.add_argument("--hotel-id", default="golden-dragon")
    parser.add_argument("--profile-dir", default=str(_default_profile_dir()))
    parser.add_argument("--output-dir", default=str(_default_output_dir()))
    parser.add_argument("--pause-seconds", type=int, default=45)
    parser.add_argument("--scan-days", type=int, default=0)
    parser.add_argument("--scan-delay-seconds", type=int, default=5)
    parser.add_argument("--multiplier-strategy", action="store_true")
    parser.add_argument("--calendar-days", type=int, default=90)
    parser.add_argument("--open-calendar", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    asyncio.run(run_probe(args))


async def run_probe(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="msedge",
            headless=args.headless,
            slow_mo=250,
            viewport={"width": 1440, "height": 1100},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)

        print(
            "Ctrip page is open. If login, captcha, or consent is required, "
            f"handle it in the browser. Waiting {args.pause_seconds} seconds..."
        )
        await page.wait_for_timeout(args.pause_seconds * 1000)
        await _try_accept_common_popups(page)
        if args.multiplier_strategy:
            result = await _run_multiplier_strategy(page, args)
            json_path = output_dir / f"ctrip-{args.hotel_id}-multiplier-{stamp}.json"
            json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            await context.close()
            print(json.dumps({
                "json_path": str(json_path),
                "calendar_days": len(result["calendar_min_rates"]),
                "estimated_rows": len(result["estimated_room_rates"]),
                "weekday_sample": result["weekday_sample"]["stay_date"] if result.get("weekday_sample") else None,
                "weekend_sample": result["weekend_sample"]["stay_date"] if result.get("weekend_sample") else None,
            }, ensure_ascii=False, indent=2))
            return
        if args.scan_days > 0:
            result = await _scan_daily_room_rates(page, args)
            json_path = output_dir / f"ctrip-{args.hotel_id}-scan-{stamp}.json"
            json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            await context.close()
            print(json.dumps({
                "json_path": str(json_path),
                "days": len(result["daily_rates"]),
                "room_rate_rows": sum(len(day["room_rate_candidates"]) for day in result["daily_rates"]),
            }, ensure_ascii=False, indent=2))
            return
        if args.open_calendar:
            await _try_open_calendar(page)
        await _scroll_for_lazy_content(page)

        title = await page.title()
        visible_text = await page.locator("body").inner_text(timeout=30_000)
        html = await page.content()
        screenshot_path = output_dir / f"ctrip-{args.hotel_id}-{stamp}.png"
        text_path = output_dir / f"ctrip-{args.hotel_id}-{stamp}.txt"
        html_path = output_dir / f"ctrip-{args.hotel_id}-{stamp}.html"
        json_path = output_dir / f"ctrip-{args.hotel_id}-{stamp}.json"

        await page.screenshot(path=str(screenshot_path), full_page=True)
        text_path.write_text(visible_text, encoding="utf-8")
        html_path.write_text(html, encoding="utf-8")

        result = {
            "hotel_id": args.hotel_id,
            "source_url": args.url,
            "page_title": title,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "screenshot_path": str(screenshot_path),
            "text_path": str(text_path),
            "html_path": str(html_path),
            "stay_window": _extract_stay_window(visible_text),
            "room_rate_candidates": _extract_room_rate_candidates(visible_text),
            "room_candidates": _extract_room_candidates(visible_text),
            "price_candidates": _extract_price_candidates(visible_text),
            "date_price_candidates": _extract_date_price_candidates(visible_text),
        }
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        await context.close()

    print(json.dumps({
        "json_path": str(json_path),
        "screenshot_path": str(screenshot_path),
        "room_rate_candidates": len(result["room_rate_candidates"]),
        "room_candidates": len(result["room_candidates"]),
        "price_candidates": len(result["price_candidates"]),
        "date_price_candidates": len(result["date_price_candidates"]),
    }, ensure_ascii=False, indent=2))


async def _try_accept_common_popups(page: Any) -> None:
    labels = ["同意", "接受", "知道了", "我知道了", "稍后再说", "关闭"]
    for label in labels:
        try:
            locator = page.get_by_text(label, exact=True).first
            if await locator.count():
                await locator.click(timeout=1500)
                await page.wait_for_timeout(800)
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue


async def _scroll_for_lazy_content(page: Any) -> None:
    for ratio in [0.15, 0.35, 0.55, 0.75, 0.95, 0.35]:
        await page.evaluate(
            "(ratio) => window.scrollTo(0, document.body.scrollHeight * ratio)",
            ratio,
        )
        await page.wait_for_timeout(1800)


async def _try_open_calendar(page: Any) -> None:
    for selector in [
        "text=/\\d{1,2}月\\d{1,2}日/",
        "text=1晚",
        "text=澳门",
    ]:
        try:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.click(timeout=2500)
                await page.wait_for_timeout(3500)
                return
        except Exception:
            continue


async def _scan_daily_room_rates(page: Any, args: argparse.Namespace) -> dict[str, Any]:
    start_date = _start_date_from_url(args.url) or date.today()
    if start_date < date.today():
        start_date = date.today()
    daily_rates = []
    for offset in range(args.scan_days):
        check_in = start_date + timedelta(days=offset)
        check_out = check_in + timedelta(days=1)
        url = _url_with_dates(args.url, check_in, check_out)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeoutError:
            print(f"Navigation timed out for {check_in}; attempting to parse current page anyway.")
        await page.wait_for_timeout(args.scan_delay_seconds * 1000)
        await _try_accept_common_popups(page)
        await _scroll_to_rooms(page)
        await page.wait_for_timeout(2500)
        text = await page.locator("body").inner_text(timeout=30_000)
        daily_rates.append(
            {
                "stay_date": check_in.isoformat(),
                "check_out": check_out.isoformat(),
                "stay_window": _extract_stay_window(text),
                "room_rate_candidates": _extract_room_rate_candidates(text),
            }
        )
    return {
        "hotel_id": args.hotel_id,
        "source_url": args.url,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "daily_rates": daily_rates,
    }


async def _run_multiplier_strategy(page: Any, args: argparse.Namespace) -> dict[str, Any]:
    start_date = _start_date_from_url(args.url) or date.today()
    if start_date < date.today():
        start_date = date.today()
    opposite_date = _next_opposite_day_type(start_date)

    sample_dates = sorted({start_date, opposite_date})
    samples = {}
    for sample_date in sample_dates:
        room_rates = await _read_room_rates_for_date(page, args, sample_date)
        samples[_day_type(sample_date)] = _build_multiplier_sample(sample_date, room_rates)

    calendar_min_rates = await _read_calendar_min_rates(page, args, start_date)
    estimated_room_rates = _estimate_room_rates(
        calendar_min_rates=calendar_min_rates,
        weekday_sample=samples.get("weekday"),
        weekend_sample=samples.get("weekend"),
    )

    return {
        "hotel_id": args.hotel_id,
        "source_url": args.url,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "strategy": "ctrip_multiplier",
        "weekday_sample": samples.get("weekday"),
        "weekend_sample": samples.get("weekend"),
        "calendar_min_rates": calendar_min_rates,
        "estimated_room_rates": estimated_room_rates,
    }


async def _read_room_rates_for_date(
    page: Any,
    args: argparse.Namespace,
    stay_date: date,
) -> list[dict[str, Any]]:
    check_out = stay_date + timedelta(days=1)
    url = _url_with_dates(args.url, stay_date, check_out)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightTimeoutError:
        print(f"Navigation timed out for {stay_date}; attempting to parse current page anyway.")
    await page.wait_for_timeout(args.scan_delay_seconds * 1000)
    await _try_accept_common_popups(page)
    await _scroll_to_rooms(page)
    await page.wait_for_timeout(2500)
    text = await page.locator("body").inner_text(timeout=30_000)
    return _extract_room_rate_candidates(text)


def _build_multiplier_sample(stay_date: date, room_rates: list[dict[str, Any]]) -> dict[str, Any]:
    if not room_rates:
        return {
            "stay_date": stay_date.isoformat(),
            "day_type": _day_type(stay_date),
            "base_price": None,
            "room_rates": [],
            "multipliers": {},
        }
    base_price = min(item["price"] for item in room_rates)
    multipliers = {
        item["room_name"]: round(item["price"] / base_price, 4)
        for item in room_rates
        if base_price > 0
    }
    return {
        "stay_date": stay_date.isoformat(),
        "day_type": _day_type(stay_date),
        "base_price": base_price,
        "room_rates": room_rates,
        "multipliers": multipliers,
    }


async def _read_calendar_min_rates(
    page: Any,
    args: argparse.Namespace,
    start_date: date,
) -> list[dict[str, Any]]:
    url = _url_with_dates(args.url, start_date, start_date + timedelta(days=1))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightTimeoutError:
        print("Navigation timed out while opening calendar; attempting to parse current page anyway.")
    await page.wait_for_timeout(args.scan_delay_seconds * 1000)
    await _try_accept_common_popups(page)
    await _try_open_calendar(page)
    await page.wait_for_timeout(2500)

    rates: dict[str, int] = {}
    end_date = start_date + timedelta(days=args.calendar_days - 1)
    months_needed = max(1, (args.calendar_days + 30) // 31 + 1)
    for _ in range(months_needed):
        html = await page.content()
        rates.update(_extract_calendar_min_rates_from_html(html))
        covered_dates = [
            date.fromisoformat(stay_date)
            for stay_date in rates
            if start_date <= date.fromisoformat(stay_date) <= end_date
        ]
        if len(covered_dates) >= args.calendar_days or (
            covered_dates and max(covered_dates) >= end_date
        ):
            break
        clicked = await _click_next_calendar_month(page)
        if not clicked:
            break
        await page.wait_for_timeout(1800)

    return [
        {
            "stay_date": stay_date,
            "min_price": rates[stay_date],
            "day_type": _day_type(date.fromisoformat(stay_date)),
        }
        for stay_date in sorted(rates)
        if start_date <= date.fromisoformat(stay_date) <= end_date
    ][: args.calendar_days]


async def _click_next_calendar_month(page: Any) -> bool:
    for selector in [
        ".c-calendar-icon-next-mon",
        "[aria-label='Go to next month']",
    ]:
        try:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.click(timeout=2500, force=True)
                return True
        except Exception:
            continue
    try:
        return bool(
            await page.evaluate(
                """
                () => {
                  const next = document.querySelector(
                    '.c-calendar-icon-next-mon:not(.is-disable), [aria-label="Go to next month"]'
                  );
                  if (!next) return false;
                  next.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                  return true;
                }
                """
            )
        )
    except Exception:
        return False
    return False


def _extract_calendar_min_rates_from_html(html: str) -> dict[str, int]:
    rates: dict[str, int] = {}
    cell_pattern = re.compile(
        r'data-d="(?P<data_d>[^"]+)".{0,1200}?class="price"[^>]*>.*?<span[^>]*>(?P<price>\d{2,6})</span>',
        flags=re.S,
    )
    for match in cell_pattern.finditer(html):
        stay_date = _date_from_calendar_data_d(match.group("data_d"))
        if stay_date is None:
            continue
        price = int(match.group("price"))
        if price < 100 or price > 20_000:
            continue
        current = rates.get(stay_date.isoformat())
        if current is None or price < current:
            rates[stay_date.isoformat()] = price
    return rates


def _date_from_calendar_data_d(value: str) -> date | None:
    try:
        raw = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return raw + timedelta(days=1)


def _estimate_room_rates(
    calendar_min_rates: list[dict[str, Any]],
    weekday_sample: dict[str, Any] | None,
    weekend_sample: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    estimates = []
    for calendar_rate in calendar_min_rates:
        stay_date = date.fromisoformat(calendar_rate["stay_date"])
        sample = weekend_sample if _day_type(stay_date) == "weekend" else weekday_sample
        if not sample or not sample.get("multipliers"):
            continue
        for room_name, multiplier in sample["multipliers"].items():
            estimates.append(
                {
                    "stay_date": calendar_rate["stay_date"],
                    "room_name": room_name,
                    "estimated_price": int(round(calendar_rate["min_price"] * multiplier)),
                    "calendar_min_price": calendar_rate["min_price"],
                    "multiplier": multiplier,
                    "day_type": calendar_rate["day_type"],
                    "sample_date": sample["stay_date"],
                    "currency": "CNY",
                }
            )
    return estimates


def _next_opposite_day_type(start_date: date) -> date:
    target = "weekday" if _day_type(start_date) == "weekend" else "weekend"
    candidate = start_date + timedelta(days=1)
    while _day_type(candidate) != target:
        candidate += timedelta(days=1)
    return candidate


def _day_type(stay_date: date) -> str:
    return "weekend" if stay_date.weekday() in {4, 5} else "weekday"


async def _scroll_to_rooms(page: Any) -> None:
    for label in ["选择房间", "房间"]:
        try:
            locator = page.get_by_text(label, exact=True).first
            if await locator.count():
                await locator.scroll_into_view_if_needed(timeout=3000)
                return
        except Exception:
            continue
    await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight * 0.35)")


def _extract_room_candidates(text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in _clean_lines(text):
        if not _looks_like_room_line(line):
            continue
        name = line[:80]
        if name in seen:
            continue
        seen.add(name)
        candidates.append({"name": name, "raw": line})
    return candidates[:80]


def _extract_room_rate_candidates(text: str) -> list[dict[str, Any]]:
    lines = _clean_lines(text)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if not _looks_like_room_name(line):
            continue
        if index + 1 < len(lines) and re.fullmatch(r"\(\d+\)|\d+", lines[index + 1]):
            if index + 2 < len(lines) and not re.search(r"(张|平方米|Wi-Fi)", lines[index + 2]):
                continue
        window = lines[index:index + 28]
        price = _first_price(window)
        if price is None:
            continue
        if line in seen:
            continue
        seen.add(line)
        candidates.append(
            {
                "room_name": line,
                "price": price,
                "currency": "CNY",
                "raw": " | ".join(window[:12]),
            }
        )
    return candidates[:40]


def _extract_price_candidates(text: str) -> list[dict[str, str | int]]:
    candidates: list[dict[str, str | int]] = []
    for line in _clean_lines(text):
        prices = re.findall(r"(?:¥|￥|CNY\s*)\s*(\d{2,6})", line, flags=re.I)
        if not prices:
            prices = re.findall(r"(?:到手价|在线付|每晚|均价|含税价|价格)\D{0,8}(\d{2,6})", line)
        for price in prices:
            candidates.append({"price": int(price), "raw": line[:180]})
    return candidates[:200]


def _extract_date_price_candidates(text: str) -> list[dict[str, str | int]]:
    candidates: list[dict[str, str | int]] = []
    date_pattern = r"(?:(20\d{2})[年/-])?(\d{1,2})[月/-](\d{1,2})日?"
    price_pattern = r"(?:¥|￥|CNY\s*)\s*(\d{2,6})"
    for line in _clean_lines(text):
        date_match = re.search(date_pattern, line)
        price_match = re.search(price_pattern, line, flags=re.I)
        if date_match and price_match:
            year = date_match.group(1) or "2026"
            stay_date = f"{year}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
            candidates.append({
                "stay_date": stay_date,
                "price": int(price_match.group(1)),
                "raw": line[:180],
            })
    return candidates[:120]


def _extract_stay_window(text: str) -> dict[str, str] | None:
    lines = _clean_lines(text)
    for index, line in enumerate(lines):
        if not re.fullmatch(r"\d{1,2}月\d{1,2}日\(周.\)", line):
            continue
        if index + 2 < len(lines) and lines[index + 1] == "-":
            return {
                "check_in_label": line,
                "check_out_label": lines[index + 2],
            }
    return None


def _looks_like_room_name(line: str) -> bool:
    if not re.search(r"(房|套)$", line):
        return False
    if len(line) < 3 or len(line) > 28:
        return False
    negative_keywords = [
        "选择",
        "详情",
        "摘要",
        "酒店",
        "订房",
        "客房设施",
        "无障碍",
        "药房",
        "加床",
        "低价房",
    ]
    return not any(keyword in line for keyword in negative_keywords)


def _first_price(lines: list[str]) -> int | None:
    for line in lines:
        price_match = re.search(r"(?:¥|￥|CNY\s*)\s*(\d{2,6})", line, flags=re.I)
        if price_match:
            return int(price_match.group(1))
    return None


def _looks_like_room_line(line: str) -> bool:
    room_keywords = ["房", "床", "套", "大床", "双床", "客房", "景观", "豪华", "高级", "标准"]
    negative_keywords = ["查看", "筛选", "入住", "退房", "日期", "政策", "发票", "早餐"]
    return (
        4 <= len(line) <= 120
        and any(keyword in line for keyword in room_keywords)
        and not any(keyword in line for keyword in negative_keywords)
    )


def _clean_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def _default_profile_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "browser-profiles" / "ctrip-edge"


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "ctrip-rpa-probes"


def _start_date_from_url(url: str) -> date | None:
    query = parse_qs(urlsplit(url).query)
    value = (query.get("checkIn") or [None])[0]
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _url_with_dates(url: str, check_in: date, check_out: date) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query["checkIn"] = [check_in.isoformat()]
    query["checkOut"] = [check_out.isoformat()]
    encoded = urlencode(query, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded, parts.fragment))


if __name__ == "__main__":
    main()
