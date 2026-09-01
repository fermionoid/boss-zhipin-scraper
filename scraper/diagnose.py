"""一次性诊断器：列出浏览器所有页面/所有 frame 的真实状态。

用于定位"页面肉眼可见正常、脚本却查不到列表"的根因：
列表到底在哪个 target、哪个 frame 里。结果写 输出/debug/targets.txt。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / config.OUTPUT_DIR_NAME / "debug" / "targets.txt"

PROBES = (".user-list", "[role='listitem']", ".geek-name", ".chat-conversation")


async def probe_frame(frame) -> list[str]:
    lines = [f"    frame: {frame.url}"]
    try:
        body = await frame.locator("body").inner_text(timeout=2000)
        lines.append(f"      正文长度: {len(body.strip())}  首40字: {body.strip()[:40]!r}")
    except Exception as error:
        lines.append(f"      正文读取失败: {error.__class__.__name__}")
    for selector in PROBES:
        try:
            count = await frame.locator(selector).count()
        except Exception as error:
            lines.append(f"      {selector} -> 错误 {error.__class__.__name__}")
            continue
        lines.append(f"      {selector} -> {count}")
    return lines


async def main() -> int:
    from playwright.async_api import async_playwright

    lines: list[str] = ["==== 浏览器目标诊断 ===="]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(
            config.CDP_ENDPOINT, timeout=config.CDP_TIMEOUT_MS
        )
        for ci, context in enumerate(browser.contexts):
            lines.append(f"context[{ci}] pages={len(context.pages)}")
            for pi, page in enumerate(context.pages):
                try:
                    title = await page.title()
                except Exception:
                    title = "(读取失败)"
                lines.append(f"  page[{pi}] url={page.url}")
                lines.append(f"  page[{pi}] title={title!r} frames={len(page.frames)}")
                for frame in page.frames:
                    lines.extend(await probe_frame(frame))
    report = "\n".join(lines) + "\n"
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"已写入 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
