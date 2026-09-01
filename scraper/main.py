"""通过 CDP 接管已登录的浏览器，批量抓取 Boss 直聘沟通页候选人。"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import random
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

# 交付包用的 embeddable Python 带 ._pth、跑在隔离模式，不会自动把脚本目录
# 加入 sys.path，必须手动加，否则 import config 失败。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config


VERSION = "2026.09.01-8"

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / config.OUTPUT_DIR_NAME
PROGRESS_PATH = OUTPUT_DIR / "progress.json"


class ConversationListNotFoundError(RuntimeError):
    """页面上没有通过时间戳真实性校验的会话列表。"""


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_space(value: Any) -> str:
    return re.sub(config.REGEX_PATTERNS["whitespace"], " ", str(value or "")).strip()


def regex_match(pattern_name: str, text: str) -> re.Match[str] | None:
    return re.search(
        config.REGEX_PATTERNS[pattern_name],
        text or "",
        flags=re.IGNORECASE | re.MULTILINE,
    )


def regex_value(pattern_name: str, text: str, group: str = "value") -> str:
    match = regex_match(pattern_name, text)
    return normalize_space(match.group(group)) if match and match.groupdict().get(group) else ""


def normalize_salary(value: str) -> str:
    return normalize_space(value).replace(" ", "").upper()


def render_matches_item(
    *, changed: bool, rendered_name: str, list_name: str, was_active: bool
) -> bool:
    """拒绝把点击前残留的候选人面板记到另一个会话 key。"""
    rendered = normalize_space(rendered_name).casefold()
    expected = normalize_space(list_name).casefold()
    names_match = bool(rendered and expected) and (
        rendered.startswith(expected) or expected.startswith(rendered)
    )
    if not names_match:
        return False
    return changed or was_active


def missing_candidate_panel_is_system(panel: Any | None) -> bool:
    """右侧没有候选人信息面板时，按业务规则视为系统会话。"""
    return panel is None


def parse_panel_text(panel_text: str) -> dict[str, str]:
    """用 config 中的正则从右侧面板原文解析候选人字段。"""
    result = {column: "" for column in config.CSV_COLUMNS}

    result["年龄"] = regex_value("age", panel_text)
    years = regex_value("work_years", panel_text)
    result["工作年限"] = f"{years}年" if years else ""
    result["学历"] = regex_value("education", panel_text)
    result["期望薪资"] = normalize_salary(regex_value("salary", panel_text))
    result["沟通职位"] = regex_value("communication_role", panel_text)

    expectation = regex_match("expectation", panel_text)
    if expectation:
        result["期望城市"] = normalize_space(expectation.group("city"))
        result["期望职位"] = normalize_space(expectation.group("role"))
        result["期望薪资"] = normalize_salary(expectation.group("salary"))

    education = regex_match("education_entry", panel_text)
    if education:
        result["学校"] = normalize_space(education.group("school"))
        result["专业"] = normalize_space(education.group("major"))
        degree = education.groupdict().get("degree")
        if degree:
            result["学历"] = normalize_space(degree)
    else:
        school = regex_match("school", panel_text)
        if school:
            result["学校"] = normalize_space(school.group("school"))

    work = regex_match("work_entry", panel_text)
    if work:
        result["最近公司"] = normalize_space(work.group("company"))
        result["最近职位/技术栈"] = normalize_space(work.group("role"))

    return result


def make_conversation_key(
    attributes: dict[str, str], name: str, job: str, summary: str
) -> str:
    for attribute in config.KEY_ATTRIBUTES:
        value = normalize_space(attributes.get(attribute, ""))
        if value:
            return f"{attribute}:{value}"
    source = "\x1f".join((normalize_space(name), normalize_space(job), normalize_space(summary)))
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"fallback:{digest}"


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(config.REGEX_PATTERNS["filename_invalid"], "_", normalize_space(value))
    cleaned = cleaned.strip(" ._") or "未知姓名"
    return cleaned[: config.FILENAME_MAX_CHARS]


def is_system_account(name: str) -> bool:
    normalized = normalize_space(name).casefold()
    return normalized in {normalize_space(item).casefold() for item in config.SYSTEM_ACCOUNTS}


def is_nav_item(name: str) -> bool:
    normalized = normalize_space(name).casefold()
    return normalized in {normalize_space(item).casefold() for item in config.NAV_BLOCKLIST}


def has_candidate_evidence(row: dict[str, Any]) -> bool:
    return any(normalize_space(row.get(field, "")) for field in config.CANDIDATE_EVIDENCE_FIELDS)


def dedupe_and_clean(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """先按 key、再按姓名+学校+年限去重，并清除疑似系统消息。"""
    cleaned: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    seen_people: set[tuple[str, str, str]] = set()

    for source in rows:
        name = normalize_space(source.get("姓名", ""))
        if not name or not has_candidate_evidence(source):
            continue

        key = normalize_space(source.get("_key", ""))
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)

        person_key = (
            name.casefold(),
            normalize_space(source.get("学校", "")).casefold(),
            normalize_space(source.get("工作年限", "")).casefold(),
        )
        if person_key in seen_people:
            continue
        seen_people.add(person_key)

        row = {column: normalize_space(source.get(column, "")) for column in config.CSV_COLUMNS}
        cleaned.append(row)

    for index, row in enumerate(cleaned, start=1):
        row["序号"] = str(index)
    return cleaned


def markdown_cell(value: Any, limit: int | None = None) -> str:
    text = normalize_space(value).replace("|", "\\|")
    if limit is not None and len(text) > limit:
        return f"{text[:limit]}…"
    return text


def render_markdown(rows: list[dict[str, str]]) -> str:
    headers = [header for header, _ in config.MARKDOWN_COLUMNS]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = []
        for header, field in config.MARKDOWN_COLUMNS:
            limit = config.MARKDOWN_INTRO_MAX_CHARS if header == "自我介绍摘要" else None
            cells.append(markdown_cell(row.get(field, ""), limit))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def ensure_output_dirs() -> dict[str, Path]:
    paths = {
        "root": OUTPUT_DIR,
        "screenshots": OUTPUT_DIR / "screenshots",
        "raw": OUTPUT_DIR / "raw",
        "debug": OUTPUT_DIR / "debug",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


async def dump_debug_page(
    page: Any,
    paths: dict[str, Path],
    logger: logging.Logger,
    tag: str = "startup",
    browser: Any = None,
) -> None:
    """保存一份完整诊断包（DOM + 截图 + 体检报告）；任何一项失败只记日志，
    不遮蔽原始故障。文件名带 tag，同 tag 覆盖。"""
    try:
        html = await page.content()
        (paths["debug"] / f"{tag}_page.html").write_text(html, encoding="utf-8")
    except Exception:
        logger.exception("写入 debug/%s_page.html 失败", tag)
    try:
        await page.screenshot(path=str(paths["debug"] / f"{tag}_page.png"), full_page=True)
    except Exception:
        logger.exception("写入 debug/%s_page.png 失败", tag)
    try:
        report = await build_diagnostic_report(page, browser=browser)
        (paths["debug"] / f"{tag}_report.txt").write_text(report, encoding="utf-8")
    except Exception:
        logger.exception("写入 debug/%s_report.txt 失败", tag)


def _preview(text: str) -> str:
    return normalize_space(text)[: config.DEBUG_TEXT_PREVIEW_CHARS]


async def conversation_list_candidates(page: Any) -> list[dict[str, Any]]:
    """列出所有会话列表候选容器及其时间戳得分（find/报告共用）。"""
    pattern = config.REGEX_PATTERNS["last_message_time"]
    results: list[dict[str, Any]] = []
    for selector in config.SELECTORS["conversation_list"]:
        try:
            candidates = page.locator(selector)
            count = await candidates.count()
        except Exception:
            continue
        for index in range(min(count, 5)):
            candidate = candidates.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                text = await locator_raw_text(candidate)
            except Exception:
                continue
            score = len(re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE))
            results.append(
                {
                    "selector": selector,
                    "index": index,
                    "locator": candidate,
                    "score": score,
                    "text": text,
                }
            )
    return results


async def build_diagnostic_report(page: Any, browser: Any = None) -> str:
    """生成人读的一次性诊断报告：环境、页面状态、selector 体检、
    容器打分、会话项解析预览。远程只看这一个文件就能定位大多数问题。"""
    lines: list[str] = ["==== Boss抓取工具诊断报告 ====", f"生成时间: {now_text()}"]

    # -- 环境 --
    lines.append(f"Python: {sys.version.split()[0]} ({sys.platform})")
    try:
        import playwright  # noqa: PLC0415

        lines.append(f"Playwright: {getattr(playwright, '__version__', '未知')}")
    except Exception:
        lines.append("Playwright: 导入失败")

    # -- 页面状态 --
    try:
        lines.append(f"URL: {page.url}")
    except Exception:
        lines.append("URL: 读取失败")
    try:
        lines.append(f"标题: {await page.title()}")
    except Exception:
        lines.append("标题: 读取失败")
    try:
        text = await body_text(page)
        hits = [kw for kw in config.SECURITY_KEYWORDS if kw in text]
        lines.append(f"安全/登录关键词命中: {('、'.join(hits)) or '无'}")
        lines.append(f"正文长度: {len(text)} 字符")
    except Exception:
        lines.append("安全/登录关键词命中: 检测失败")

    if browser is not None:
        lines.append("---- 浏览器已打开的标签页 ----")
        try:
            for context in browser.contexts:
                for open_page in context.pages:
                    marker = " <- 当前抓取页" if open_page is page else ""
                    lines.append(f"  {open_page.url}{marker}")
        except Exception:
            lines.append("  (读取标签页失败)")

    # -- 容器打分 --
    lines.append("")
    lines.append(f"---- 会话列表候选容器（时间戳阈值 {config.MIN_TIMED_ITEMS}）----")
    try:
        candidates = await conversation_list_candidates(page)
        if not candidates:
            lines.append("(没有任何 selector 命中可见容器)")
        for entry in candidates:
            lines.append(
                f"{entry['selector']} #{entry['index']} 时间戳数={entry['score']}"
                f" 文本: {_preview(entry['text'])}"
            )
    except Exception as error:
        lines.append(f"容器打分失败: {error.__class__.__name__}: {error}")

    # -- 会话项解析预览 --
    lines.append("")
    lines.append("---- 会话项解析预览 ----")
    try:
        container = await find_conversation_list(page)
        if container is None:
            lines.append("(未选出会话列表容器)")
        else:
            items = await collect_visible_items(container)
            lines.append(f"可见会话项共 {len(items)} 个，前 {config.DEBUG_MAX_ITEMS_IN_REPORT} 个：")
            for item in items[: config.DEBUG_MAX_ITEMS_IN_REPORT]:
                lines.append(
                    f"  name={item['name']!r} job={item['job']!r} time={item['time']!r}"
                    f" active={item['was_active']} key={item['key'][:40]}"
                )
    except Exception as error:
        lines.append(f"会话项解析失败: {error.__class__.__name__}: {error}")

    # -- selector 体检 --
    lines.append("")
    lines.append("---- selector 体检（组名 / 选择器 -> 总数 可见数 首个可见文本）----")
    for group, selectors in config.SELECTORS.items():
        lines.append(f"[{group}]")
        for selector in selectors:
            try:
                candidates = page.locator(selector)
                count = await candidates.count()
            except Exception as error:
                lines.append(f"  {selector} -> 错误 {error.__class__.__name__}")
                continue
            visible = 0
            preview = ""
            for index in range(min(count, 10)):
                candidate = candidates.nth(index)
                try:
                    if not await candidate.is_visible():
                        continue
                    visible += 1
                    if not preview:
                        preview = _preview(await candidate.inner_text(timeout=config.SELECTOR_TIMEOUT_MS))
                except Exception:
                    continue
            lines.append(f"  {selector} -> 总数{count} 可见{visible} 首个文本: {preview}")

    return "\n".join(lines) + "\n"


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("boss_chat_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(OUTPUT_DIR / "log.txt", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def empty_progress() -> dict[str, Any]:
    return {
        "version": 1,
        "processed": {},
        "records": [],
        "failed": [],
        "updated_at": now_text(),
    }


def load_progress(logger: logging.Logger) -> dict[str, Any]:
    if not PROGRESS_PATH.exists():
        return empty_progress()
    try:
        data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data.get("processed"), dict) or not isinstance(data.get("records"), list):
            raise ValueError("progress.json 结构不完整")
        data.setdefault("failed", [])
        return data
    except Exception:
        logger.exception("读取 progress.json 失败，将从空进度开始")
        print("进度文件损坏，已记录到日志；本次从头检查。")
        return empty_progress()


def save_progress(progress: dict[str, Any]) -> None:
    progress["updated_at"] = now_text()
    temporary = PROGRESS_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(PROGRESS_PATH)


def remove_failed_entry(progress: dict[str, Any], key: str) -> None:
    progress["failed"] = [item for item in progress.get("failed", []) if item.get("key") != key]


def record_failure(progress: dict[str, Any], item: dict[str, Any], error: BaseException) -> None:
    remove_failed_entry(progress, item["key"])
    progress["failed"].append(
        {
            "key": item["key"],
            "name": item.get("name", ""),
            "error": normalize_space(error),
            "updated_at": now_text(),
        }
    )
    save_progress(progress)


def write_outputs(progress: dict[str, Any]) -> list[dict[str, str]]:
    rows = dedupe_and_clean(progress.get("records", []))
    csv_path = OUTPUT_DIR / "data.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=config.CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (OUTPUT_DIR / "data.md").write_text(render_markdown(rows), encoding="utf-8")
    return rows


async def locator_text(locator: Any, timeout: int | None = None) -> str:
    try:
        return normalize_space(
            await locator.inner_text(timeout=timeout or config.SELECTOR_TIMEOUT_MS)
        )
    except Exception:
        return ""


async def locator_raw_text(locator: Any, timeout: int | None = None) -> str:
    try:
        return (await locator.inner_text(timeout=timeout or config.SELECTOR_TIMEOUT_MS)).strip()
    except Exception:
        return ""


async def first_locator(root: Any, selector_group: str, visible_only: bool = False) -> Any | None:
    for selector in config.SELECTORS[selector_group]:
        try:
            candidates = root.locator(selector)
            count = await candidates.count()
            if not count:
                continue
            if not visible_only:
                return candidates.first
            for index in range(min(count, 10)):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return None


async def first_locator_group(root: Any, selector_group: str) -> Any | None:
    """返回第一组有匹配结果的完整 Locator（不折叠为 first）。"""
    for selector in config.SELECTORS[selector_group]:
        try:
            candidates = root.locator(selector)
            if await candidates.count():
                return candidates
        except Exception:
            continue
    return None


async def first_text(root: Any, selector_group: str) -> str:
    for selector in config.SELECTORS[selector_group]:
        try:
            candidates = root.locator(selector)
            count = await candidates.count()
            for index in range(min(count, 20)):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    text = await locator_text(candidate)
                    if text:
                        return text
        except Exception:
            continue
    return ""


async def all_texts(root: Any, selector_group: str) -> list[str]:
    for selector in config.SELECTORS[selector_group]:
        try:
            candidates = root.locator(selector)
            count = await candidates.count()
            texts = []
            for index in range(min(count, 100)):
                candidate = candidates.nth(index)
                if await candidate.is_visible():
                    text = await locator_text(candidate)
                    if text:
                        texts.append(text)
            if texts:
                return texts
        except Exception:
            continue
    return []


async def find_conversation_list(page: Any) -> Any | None:
    """在候选容器中选出真实会话列表：以文本中消息时间戳数量打分，
    低于 MIN_TIMED_ITEMS 的容器（如左侧导航菜单）一律拒绝。"""
    best: Any | None = None
    best_score = 0
    for entry in await conversation_list_candidates(page):
        if entry["score"] > best_score:
            best, best_score = entry["locator"], entry["score"]
    if best_score >= config.MIN_TIMED_ITEMS:
        return best
    return None




async def wait_for_list_with_help(
    page: Any, logger: logging.Logger, browser: Any = None
) -> Any | None:
    """纯被动等待列表出现，等到为止。

    铁律（2026-09-01 血泪）：脚本除了点候选人条目，绝不碰页面上任何东西。
    曾经的"自动关弹窗""自动点沟通菜单"都会触发整页跳转，把用户刚切好的
    页面又踢回推荐页，形成用户点一次、脚本踢一次的死循环。
    """
    global CURRENT_ACTION
    CURRENT_ACTION = "纯等待列表出现（不碰页面）"
    container = await find_conversation_list(page)
    if container is not None:
        return container

    for _ in range(config.NO_LIST_RETRY):
        await asyncio.sleep(config.NO_LIST_RETRY_WAIT)
        container = await find_conversation_list(page)
        if container is not None:
            return container

    print("\n" + "=" * 52)
    print("  需要你帮个忙：请在浏览器里点左边的「沟通」")
    print("  （点完这个窗口会自己继续，程序不会再动你的页面）")
    print("=" * 52 + "\n")
    logger.warning("等待用户手动切到沟通页 url=%s", page.url)

    waited = 0.0
    while True:
        await asyncio.sleep(config.HELP_POLL_SECONDS)
        waited += config.HELP_POLL_SECONDS
        container = await find_conversation_list(page)
        if container is not None:
            print("看到会话列表了，继续抓取。\n")
            logger.info("用户已切回沟通页，继续")
            return container
        if browser is not None:
            repicked = await pick_live_page(browser)
            if repicked is not None and repicked is not page:
                container = await find_conversation_list(repicked)
                if container is not None:
                    print("看到会话列表了，继续抓取。\n")
                    return container
        if waited % 60 < config.HELP_POLL_SECONDS:
            print(f"  仍在等待……请在浏览器点左侧「沟通」（已等 {int(waited)} 秒）")


async def is_page_alive(page: Any) -> bool:
    """判断这个页面对象是不是真的活着。

    Chromium 会预渲染隐藏标签页，Playwright 连上时可能优先抓到那种幽灵目标，
    而浏览器随后立刻把它丢弃——表现为连上 30 毫秒后 page 就被关闭
    （2026-09-01 实测）。所以必须真正执行一次 JS 来确认它还在。
    """
    try:
        if page.is_closed():
            return False
        return bool(await page.evaluate("() => true"))
    except Exception:
        return False


async def pick_live_page(browser: Any) -> Any | None:
    """挑出真正活着、且渲染了会话列表的页面。

    顺序：先确认存活（排除预渲染幽灵页），再看有没有会话列表，最后才退而
    求其次按 URL 匹配。
    """
    fallback = None
    for context in browser.contexts:
        for candidate in context.pages:
            try:
                url = candidate.url.casefold()
            except Exception:
                continue
            if config.TARGET_DOMAIN.casefold() not in url:
                continue
            if not await is_page_alive(candidate):
                continue
            try:
                if await find_conversation_list(candidate) is not None:
                    return candidate
            except Exception:
                continue
            if fallback is None and config.CHAT_URL_FRAGMENT.casefold() in url:
                fallback = candidate
    return fallback


async def acquire_page(browser: Any, logger: logging.Logger) -> Any | None:
    """反复扫描直到拿到一个稳定存活的页面。

    预渲染目标会在连接后短时间内被销毁，所以拿到后要停一下再确认一次，
    确认还活着才交出去；否则重新扫描。
    """
    for attempt in range(config.PAGE_ACQUIRE_RETRY):
        page = await pick_live_page(browser)
        if page is None:
            await asyncio.sleep(config.PAGE_ACQUIRE_WAIT)
            continue
        await asyncio.sleep(config.PAGE_ACQUIRE_WAIT)
        if await is_page_alive(page):
            logger.info("已锁定稳定页面 url=%s（第 %s 次尝试）", page.url, attempt + 1)
            return page
        logger.warning("第 %s 次拿到的是瞬时页面（已消失），重新扫描", attempt + 1)
    return None


async def wait_for_page_ready(page: Any, logger: logging.Logger) -> bool:
    """等待 SPA 渲染出会话列表（首次加载可能要十几秒）。
    出现登录/验证关键词时提前返回 False，交给安全检查环节提示用户。"""
    deadline = asyncio.get_running_loop().time() + config.PAGE_READY_TIMEOUT_SECONDS
    announced = False
    polls = 0
    while asyncio.get_running_loop().time() < deadline:
        if await find_conversation_list(page) is not None:
            if announced:
                print("页面加载完成。")
            return True
        try:
            text = await body_text(page)
            if any(keyword in text for keyword in config.SECURITY_KEYWORDS):
                return False
        except Exception:
            pass
        polls += 1
        if not announced:
            print("页面还在加载，等待中……（最长等 90 秒）")
            logger.info("等待沟通页渲染 url=%s", page.url)
            announced = True
        await asyncio.sleep(config.PAGE_READY_POLL_SECONDS)
    logger.warning("等待页面就绪超时 url=%s", page.url)
    return False



async def right_panel_state(page: Any) -> tuple[Any | None, str]:
    right = await first_locator(page, "right_panel", visible_only=True)
    return right, await locator_raw_text(right) if right else ""


async def candidate_panel_state(page: Any, right: Any | None) -> tuple[Any | None, str]:
    roots = [root for root in (right, page) if root is not None]
    for root in roots:
        panel = await first_locator(root, "candidate_panel", visible_only=True)
        if panel is not None:
            name = await first_text(panel, "candidate_name")
            if not name and right is not None:
                name = await first_text(right, "candidate_name")
            return panel, name
    return None, ""


async def wait_for_candidate_render(page: Any, previous_text: str) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + config.RENDER_TIMEOUT_SECONDS
    last_state: dict[str, Any] = {
        "right": None,
        "panel": None,
        "text": "",
        "name": "",
        "changed": False,
    }
    previous_normalized = normalize_space(previous_text)

    while asyncio.get_running_loop().time() < deadline:
        right, text = await right_panel_state(page)
        panel, name = await candidate_panel_state(page, right)
        candidate_text = await locator_raw_text(panel) if panel is not None else ""
        changed = bool(candidate_text) and normalize_space(candidate_text) != previous_normalized
        last_state = {
            "right": right,
            "panel": panel,
            "text": text,
            "name": name,
            "changed": changed,
        }
        if changed and panel is not None and name:
            return last_state
        await asyncio.sleep(0.25)

    return last_state


async def extract_selector_fields(right: Any, panel: Any | None) -> dict[str, str]:
    fields: dict[str, str] = {}
    roots = [root for root in (panel, right) if root is not None]
    for column, selector_group in config.FIELD_SELECTOR_MAP.items():
        value = ""
        for root in roots:
            value = await first_text(root, selector_group)
            if value:
                break
        fields[column] = value
    return fields



ITEM_EXTRACT_JS = """
(container, cfg) => {
  const pick = (root, sels) => {
    for (const s of sels) {
      const el = root.querySelector(s);
      if (el && el.offsetParent !== null) {
        const t = (el.innerText || '').trim();
        if (t) return t;
      }
    }
    return '';
  };
  let items = [];
  for (const s of cfg.itemSelectors) {
    const found = Array.from(container.querySelectorAll(s.replace(/^:scope\\s*/, '')));
    if (found.length) { items = found; break; }
  }
  return items.slice(0, 200).map(el => {
    const attrs = {};
    for (const a of cfg.keyAttributes) attrs[a] = (el.getAttribute(a) || '').trim();
    return {
      attrs,
      raw_text: (el.innerText || '').trim(),
      name: pick(el, cfg.nameSelectors),
      job: pick(el, cfg.jobSelectors),
      summary: pick(el, cfg.summarySelectors),
      time: pick(el, cfg.timeSelectors),
      cls: (el.getAttribute('class') || '') + ' ' +
           cfg.stateAttributes.map(a => el.getAttribute(a) || '').join(' '),
      visible: el.offsetParent !== null,
    };
  });
}
"""


async def collect_visible_items(container: Any) -> list[dict[str, Any]]:
    """一次 JS 调用把整个可见列表读回来。

    绝对不要退回"逐元素、逐字段查询"的写法：40 个会话会产生 200+ 次
    往返、耗时 40 秒以上，期间页面早已切换视图，后续点击必然落空
    （2026-09-01 实测的真实故障）。
    """
    try:
        raw_items = await container.evaluate(
            ITEM_EXTRACT_JS,
            {
                "itemSelectors": list(config.SELECTORS["conversation_item"]),
                "keyAttributes": list(config.KEY_ATTRIBUTES),
                "nameSelectors": list(config.SELECTORS["item_name"]),
                "jobSelectors": list(config.SELECTORS["item_job"]),
                "summarySelectors": list(config.SELECTORS["item_summary"]),
                "timeSelectors": list(config.SELECTORS["item_time"]),
                "stateAttributes": list(config.ACTIVE_STATE_ATTRIBUTES),
            },
        )
    except Exception:
        return []

    collected: list[dict[str, Any]] = []
    for entry in raw_items or []:
        try:
            if not entry.get("visible"):
                continue
            raw_text = entry.get("raw_text", "")
            attributes = {
                key: normalize_space(value)
                for key, value in (entry.get("attrs") or {}).items()
            }
            name = normalize_space(entry.get("name", ""))
            job = normalize_space(entry.get("job", ""))
            summary = normalize_space(entry.get("summary", ""))
            time_text = normalize_space(entry.get("time", ""))
            lines = [normalize_space(line) for line in raw_text.splitlines() if normalize_space(line)]
            if not name and lines:
                name = lines[0]
            if not job and len(lines) > 1:
                job = lines[1]
            if not summary and lines:
                summary = lines[-1]
            if not time_text:
                time_text = regex_value("last_message_time", raw_text)

            class_blob = normalize_space(entry.get("cls", "")).casefold()
            class_parts = class_blob.replace("_", "-").split()
            was_active = any(
                part == token.casefold() or part.endswith(f"-{token.casefold()}")
                for token in config.ACTIVE_CLASS_TOKENS
                for part in class_parts
            ) or any(
                value.casefold() in class_parts
                for value in config.ACTIVE_STATE_VALUES
            )

            collected.append(
                {
                    "key": make_conversation_key(attributes, name, job, summary),
                    "attrs": attributes,
                    "name": name,
                    "job": job,
                    "summary": summary,
                    "time": time_text,
                    "raw_text": raw_text,
                    "was_active": was_active,
                }
            )
        except Exception:
            continue
    return collected


async def locate_item(container: Any, item: dict[str, Any]) -> Any | None:
    """点击前用属性重新定位元素。列表随时会重建，收集时的 locator 会失效，
    必须临用临取（2026-09-01 实测：陈旧 locator 导致每个人都点击超时）。"""
    for attribute in config.KEY_ATTRIBUTES:
        value = (item.get("attrs") or {}).get(attribute, "")
        if not value:
            continue
        try:
            candidate = container.locator(f'[{attribute}="{value}"]').first
            if await candidate.count() and await candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


async def process_item(
    page: Any,
    item: dict[str, Any],
    sequence: int,
    paths: dict[str, Path],
    chat_url: str,
    logger: logging.Logger,
    container: Any = None,
) -> tuple[str, dict[str, Any] | None]:
    previous_right, previous_right_text = await right_panel_state(page)
    previous_panel, _ = await candidate_panel_state(page, previous_right)
    previous_text = await locator_raw_text(previous_panel) if previous_panel is not None else ""

    global CURRENT_ACTION
    CURRENT_ACTION = f"点击候选人条目：{item.get('name', '?')}"
    target = None
    if container is not None:
        target = await locate_item(container, item)
    if target is None:
        return "vanished", None
    try:
        await target.click(timeout=config.CLICK_TIMEOUT_MS)
    except Exception:
        # 常规点击会等元素"稳定"，列表在重排时会一直等到超时；
        # 退化为 JS 直接派发点击，不做可交互性检查。
        try:
            await target.evaluate("el => el.click()")
        except Exception:
            return "vanished", None
    CURRENT_ACTION = f"等待右侧面板渲染：{item.get('name', '?')}"
    state = await wait_for_candidate_render(page, previous_text)

    right = state["right"]
    panel = state["panel"]
    panel_text = state["text"]
    panel_missing = missing_candidate_panel_is_system(panel)
    if right is None:
        raise TimeoutError("右侧沟通面板未渲染")
    if not panel_text:
        if panel_missing:
            return "skipped_system", None
        raise TimeoutError("候选人信息面板内容为空")

    regex_fields = parse_panel_text(panel_text)
    if panel_missing:
        # 没有独立候选人卡片时退化用右侧全文解析；文本没变化（点击无效）
        # 或解析不出任何候选人字段的，才按系统会话跳过。
        if normalize_space(panel_text) == normalize_space(previous_right_text):
            return "skipped_system", None
        if not has_candidate_evidence(regex_fields):
            return "skipped_system", None

    selector_fields = await extract_selector_fields(right, panel)
    row: dict[str, Any] = {column: "" for column in config.CSV_COLUMNS}
    for column in config.FIELD_SELECTOR_MAP:
        row[column] = selector_fields.get(column) or regex_fields.get(column, "")
    rendered_name = row.get("姓名") or state.get("name", "")
    row["姓名"] = rendered_name or item.get("name", "")

    if panel_missing:
        # 退化路径拿不到面板姓名，以列表项姓名为准。
        row["姓名"] = item.get("name", "") or row["姓名"]
    elif not render_matches_item(
        changed=state["changed"],
        rendered_name=rendered_name,
        list_name=item.get("name", ""),
        was_active=bool(item.get("was_active")),
    ):
        raise TimeoutError("点击后候选人面板未更新，拒绝写入旧面板数据")
    if is_system_account(row["姓名"]):
        return "skipped_system", None

    intro_texts = await all_texts(right, "candidate_message")
    if intro_texts:
        row["自我介绍"] = intro_texts[0][: config.SELF_INTRO_MAX_CHARS]
    else:
        row["自我介绍"] = regex_value("self_intro", panel_text)[: config.SELF_INTRO_MAX_CHARS]

    attachment = any(
        keyword.casefold() in item.get("raw_text", "").casefold()
        or keyword.casefold() in panel_text.casefold()
        for keyword in config.ATTACHMENT_KEYWORDS
    )
    if not attachment:
        attachment = await first_locator(right, "resume_attachment", visible_only=True) is not None
    row["有附件简历"] = "是" if attachment else "否"
    row["最后消息时间"] = item.get("time", "")
    row["序号"] = str(sequence)

    safe_name = sanitize_filename(row["姓名"])
    file_stem = f"{sequence:03d}_{safe_name}"
    raw_path = paths["raw"] / f"{file_stem}.txt"
    screenshot_path = paths["screenshots"] / f"{file_stem}.png"
    raw_path.write_text(panel_text, encoding="utf-8")
    CURRENT_ACTION = f"整页截图：{item.get('name', '?')}"
    await page.screenshot(path=str(screenshot_path), full_page=True)
    row["截图文件名"] = screenshot_path.name
    row["_key"] = item["key"]
    return "success", row


async def body_text(page: Any) -> str:
    body = await first_locator(page, "body")
    return await locator_raw_text(body, timeout=config.SELECTOR_TIMEOUT_MS) if body else ""


async def wait_for_manual_security_check(page: Any, logger: logging.Logger) -> None:
    announced = False
    while True:
        if page.is_closed():
            raise RuntimeError("浏览器页面已关闭")
        url_lower = page.url.casefold()
        on_login = any(keyword.casefold() in url_lower for keyword in config.LOGIN_URL_KEYWORDS)
        text = await body_text(page)
        right, _ = await right_panel_state(page)
        panel, _ = await candidate_panel_state(page, right)
        security_text = any(keyword in text for keyword in config.SECURITY_KEYWORDS)
        blocked = on_login or (security_text and panel is None)
        if not blocked:
            if announced:
                print("验证已解除，自动继续抓取。")
                logger.info("登录或安全验证已解除")
            return
        if not announced:
            print("\n*** 检测到登录失效或安全验证，请在浏览器中手动处理 ***")
            logger.warning("检测到登录失效或安全验证，等待用户处理；url=%s", page.url)
            announced = True
        await asyncio.sleep(config.SECURITY_RECHECK_SECONDS)


async def scroll_conversation_list(container: Any) -> dict[str, float]:
    return await container.evaluate(
        """(element, options) => {
            const before = element.scrollTop;
            const step = Math.max(element.clientHeight * options.ratio, options.minimum);
            element.scrollTop = Math.min(element.scrollTop + step, element.scrollHeight);
            return {before, after: element.scrollTop, height: element.scrollHeight};
        }""",
        {"ratio": config.SCROLL_STEP_RATIO, "minimum": config.SCROLL_MIN_PIXELS},
    )


async def pause_after_item(handled: int) -> None:
    if config.LONG_BREAK_EVERY > 0 and handled % config.LONG_BREAK_EVERY == 0:
        duration = random.uniform(config.LONG_BREAK_MIN, config.LONG_BREAK_MAX)
        print(f"已处理 {handled} 个会话，长休约 {int(duration)} 秒。")
    else:
        duration = random.uniform(config.WAIT_MIN, config.WAIT_MAX)
    await asyncio.sleep(duration)


async def scrape_page(
    page: Any,
    logger: logging.Logger,
    paths: dict[str, Path],
    browser: Any = None,
) -> dict[str, Any]:
    progress = load_progress(logger)
    processed_keys = set(progress["processed"])
    failed_this_run: set[str] = set()
    seen_visible: set[str] = set()
    handled_this_run = 0
    scroll_stalls = 0
    stopped_by_limit = False
    failure_dumps = 0
    first_click_dumped = False
    logger.info(
        "加载断点进度 processed=%s records=%s failed=%s",
        len(progress.get("processed", {})),
        len(progress.get("records", [])),
        len(progress.get("failed", [])),
    )

    chat_url = page.url

    while True:
        await wait_for_manual_security_check(page, logger)
        if config.MAX_ITEMS > 0 and handled_this_run >= config.MAX_ITEMS:
            stopped_by_limit = True
            break

        # 找不到列表就自救 + 请用户点一下「沟通」，一直等到列表回来，绝不退出。
        container = await wait_for_list_with_help(page, logger, browser)
        if container is None:
            await dump_debug_page(page, paths, logger, tag="no_list")
            raise ConversationListNotFoundError(
                "无法定位会话列表，请把 输出/debug 文件夹发给交付人员"
            )
        visible_items = await collect_visible_items(container)
        if not visible_items:
            raise RuntimeError("左侧会话列表为空或页面结构已变化，请查看 log.txt")

        visible_keys = {item["key"] for item in visible_items}
        seen_visible.update(visible_keys)
        item = next(
            (
                current
                for current in visible_items
                if current["key"] not in processed_keys and current["key"] not in failed_this_run
            ),
            None,
        )

        if item is not None:
            handled_this_run += 1
            if is_nav_item(item.get("name", "")):
                progress["processed"][item["key"]] = {
                    "name": item.get("name", ""),
                    "status": "skipped_nav",
                    "updated_at": now_text(),
                }
                processed_keys.add(item["key"])
                save_progress(progress)
                print(f"[{handled_this_run}] 跳过导航项：{item.get('name') or '未知'}")
                logger.info("跳过导航项 key=%s name=%s", item["key"], item.get("name", ""))
                continue
            if is_system_account(item.get("name", "")):
                progress["processed"][item["key"]] = {
                    "name": item.get("name", ""),
                    "status": "skipped_system",
                    "updated_at": now_text(),
                }
                processed_keys.add(item["key"])
                save_progress(progress)
                print(f"[{handled_this_run}] 跳过系统消息：{item.get('name') or '未知'}")
                logger.info("跳过系统消息 key=%s name=%s", item["key"], item.get("name", ""))
                await pause_after_item(handled_this_run)
                continue

            final_error: BaseException | None = None
            status = "failed"
            row: dict[str, Any] | None = None
            for attempt in range(config.ITEM_RETRY_COUNT + 1):
                try:
                    await wait_for_manual_security_check(page, logger)
                    status, row = await process_item(
                        page,
                        item,
                        len(progress.get("records", [])) + 1,
                        paths,
                        chat_url,
                        logger,
                        container=container,
                    )
                    if status == "vanished":
                        # 列表刚好重建，元素没了：不算失败，下一轮重新收集即可。
                        raise LookupError("会话项已失效，稍后重试")
                    final_error = None
                    break
                except Exception as error:
                    final_error = error
                    logger.exception(
                        "抓取会话失败 key=%s name=%s attempt=%s",
                        item["key"],
                        item.get("name", ""),
                        attempt + 1,
                    )
                    if attempt < config.ITEM_RETRY_COUNT:
                        await asyncio.sleep(config.WAIT_MIN)

            # 第一次真正点开会话后留一份 DOM 快照，供远程校准右侧面板字段。
            if not first_click_dumped and status != "skipped_nav":
                first_click_dumped = True
                await dump_debug_page(page, paths, logger, tag="first_click")

            if final_error is not None:
                failed_this_run.add(item["key"])
                record_failure(progress, item, final_error)
                print(f"[{handled_this_run}] 失败，已跳过：{item.get('name') or item['key']}")
                logger.error("会话重试耗尽 key=%s name=%s", item["key"], item.get("name", ""))
                if failure_dumps < config.DEBUG_MAX_FAILURE_DUMPS:
                    failure_dumps += 1
                    await dump_debug_page(page, paths, logger, tag=f"fail{failure_dumps}")
            elif status == "skipped_nav":
                progress["processed"][item["key"]] = {
                    "name": item.get("name", ""),
                    "status": "skipped_nav",
                    "updated_at": now_text(),
                }
                processed_keys.add(item["key"])
                remove_failed_entry(progress, item["key"])
                save_progress(progress)
                print(f"[{handled_this_run}] 点击后跳页，按导航项跳过：{item.get('name') or '未知'}")
                logger.info("点击跳页按导航跳过 key=%s name=%s", item["key"], item.get("name", ""))
            elif status == "skipped_system":
                progress["processed"][item["key"]] = {
                    "name": item.get("name", ""),
                    "status": "skipped_system",
                    "updated_at": now_text(),
                }
                processed_keys.add(item["key"])
                remove_failed_entry(progress, item["key"])
                save_progress(progress)
                print(f"[{handled_this_run}] 跳过非候选人会话：{item.get('name') or '未知'}")
                logger.info("跳过非候选人会话 key=%s name=%s", item["key"], item.get("name", ""))
            elif row is not None:
                progress["records"] = [
                    existing
                    for existing in progress.get("records", [])
                    if existing.get("_key") != item["key"]
                ]
                progress["records"].append(row)
                progress["processed"][item["key"]] = {
                    "name": row.get("姓名", ""),
                    "status": "success",
                    "updated_at": now_text(),
                }
                processed_keys.add(item["key"])
                remove_failed_entry(progress, item["key"])
                save_progress(progress)
                print(f"[{handled_this_run}] 已抓取：{row.get('姓名') or '未知姓名'}")
                logger.info("抓取成功 key=%s name=%s", item["key"], row.get("姓名", ""))

            await pause_after_item(handled_this_run)
            continue

        await scroll_conversation_list(container)
        await asyncio.sleep(config.SCROLL_WAIT_SECONDS)
        container = await find_conversation_list(page)
        newly_visible: set[str] = set()
        if container is not None:
            after_items = await collect_visible_items(container)
            after_keys = {current["key"] for current in after_items}
            newly_visible = after_keys - seen_visible
            seen_visible.update(after_keys)
        scroll_stalls = 0 if newly_visible else scroll_stalls + 1
        if scroll_stalls >= config.SCROLL_RETRY:
            break

    rows = write_outputs(progress)
    skipped = sum(
        1
        for item in progress.get("processed", {}).values()
        if item.get("status") in ("skipped_system", "skipped_nav")
    )
    failures = progress.get("failed", [])
    print("\n抓取结束。")
    print(f"成功：{len(rows)}；跳过系统消息：{skipped}；失败：{len(failures)}")
    if stopped_by_limit:
        print(f"已达到试跑上限 MAX_ITEMS={config.MAX_ITEMS}；确认字段后改为 0 可抓取全部。")
    if failures:
        print("失败页：" + "、".join(item.get("name") or item.get("key", "未知") for item in failures))
    logger.info(
        "抓取结束 success=%s skipped=%s failed=%s max_items_stop=%s",
        len(rows),
        skipped,
        len(failures),
        stopped_by_limit,
    )
    return {
        "success": len(rows),
        "skipped": skipped,
        "failed": len(failures),
        "stopped_by_limit": stopped_by_limit,
    }


async def find_target_page(browser: Any) -> Any | None:
    domain_pages = []
    for context in browser.contexts:
        for page in context.pages:
            if config.TARGET_DOMAIN.casefold() in page.url.casefold():
                domain_pages.append(page)
    for page in domain_pages:
        if config.CHAT_URL_FRAGMENT.casefold() in page.url.casefold():
            return page
    return domain_pages[0] if domain_pages else None


CURRENT_ACTION = "启动"


async def url_watchdog(page: Any, logger: logging.Logger) -> None:
    """每秒记录一次网址，一变就写日志并标明脚本当时在干什么。

    用来判定"页面自己跳到推荐页"到底是脚本造成的，还是 Boss 主动踢的：
    如果跳转发生时 CURRENT_ACTION 是"纯等待"，那就与脚本无关。
    """
    last = None
    while True:
        try:
            if page.is_closed():
                logger.error("监视器：页面已被关闭！当时脚本在做：%s", CURRENT_ACTION)
                return
            now = page.url
            if last is not None and now != last:
                logger.warning(
                    "监视器：网址变了 %s -> %s（当时脚本在做：%s）", last, now, CURRENT_ACTION
                )
            last = now
        except Exception:
            logger.exception("监视器：读取网址失败（当时：%s）", CURRENT_ACTION)
            return
        await asyncio.sleep(1)


async def run(logger: logging.Logger, paths: dict[str, Path]) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("缺少 Playwright 依赖，请联系交付人员检查运行包。")
        logger.exception("导入 Playwright 失败")
        return 1

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(
                config.CDP_ENDPOINT,
                timeout=config.CDP_TIMEOUT_MS,
            )
            page = await acquire_page(browser, logger)
            if page is None:
                page = await find_target_page(browser)
            if page is None or not await is_page_alive(page):
                print("没找到稳定的 Boss 页面。请确认浏览器停在沟通页后重试。")
                logger.error("未能锁定稳定页面")
                return 2

            logger.info("已连接 CDP，当前 url=%s", page.url)
            watcher = asyncio.create_task(url_watchdog(page, logger))

            await wait_for_manual_security_check(page, logger)
            # 不再自动跳转：任何 goto 都会整页刷新，把页面踢回推荐页。
            # 不在沟通页就直接告诉用户，由用户自己点。
            await wait_for_page_ready(page, logger)
            await wait_for_manual_security_check(page, logger)
            # 开跑前先确保拿到列表（必要时请用户点「沟通」），避免空转失败。
            if await wait_for_list_with_help(page, logger, browser) is None:
                await dump_debug_page(page, paths, logger, tag="no_list")
                print("始终没有看到会话列表，请把 输出\\debug 文件夹发给交付人员。")
                return 3
            await dump_debug_page(page, paths, logger, browser=browser)
            print("已连接浏览器，开始抓取。请勿操作该浏览器窗口。")
            # 页面可能中途被浏览器回收（预渲染目标被丢弃等），重新锁定一个再继续，
            # 而不是直接崩溃退出——进度已存盘，重连后无缝接着抓。
            for attempt in range(config.PAGE_ACQUIRE_RETRY):
                try:
                    await scrape_page(page, logger, paths, browser=browser)
                    return 0
                except RuntimeError as error:
                    if "页面已关闭" not in str(error):
                        raise
                    logger.warning("页面失效，重新锁定后继续（第 %s 次）", attempt + 1)
                    print("页面被浏览器回收了，正在重新连接……")
                    page = await acquire_page(browser, logger)
                    if page is None:
                        break
            print("多次重连仍失败，请把 输出\\log.txt 发给交付人员。")
            return 4
    except ConversationListNotFoundError as error:
        logger.exception("会话列表定位失败")
        print(str(error))
        return 3
    except Exception:
        logger.exception("抓取程序异常退出")
        print("抓取遇到问题，详细信息已写入 输出/log.txt。")
        return 1


def main() -> int:
    paths = ensure_output_dirs()
    logger = setup_logger()
    print(f"程序版本：{VERSION}")
    logger.info("程序版本 %s", VERSION)
    try:
        return asyncio.run(run(logger, paths))
    except KeyboardInterrupt:
        logger.info("用户中断抓取")
        print("已中断；进度已经保存，下次运行会继续。")
        return 130
    except Exception:
        logger.error("入口异常\n%s", traceback.format_exc())
        print("程序异常，详细信息已写入 输出/log.txt。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
