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
