"""决定性实验：判定标签页到底是被谁关掉的。

阶段一：只用 HTTP 查询目标列表（不挂调试器），观察 15 秒。
阶段二：用 Playwright 挂上调试器，再观察 15 秒。
如果页面只在阶段二消失，就说明是"被调试器接管"触发的，与脚本动作无关。
结论直接写在 输出/debug/结论.txt。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

BASE_DIR = Path(__file__).resolve().parent.parent
OUT = BASE_DIR / config.OUTPUT_DIR_NAME / "debug" / "结论.txt"
WATCH_SECONDS = 15


def list_targets() -> list[dict]:
    url = config.CDP_ENDPOINT.rstrip("/") + "/json"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return [t for t in json.loads(response.read()) if t.get("type") == "page"]
    except Exception:
        return []


def boss_targets() -> list[dict]:
    return [t for t in list_targets() if config.TARGET_DOMAIN in t.get("url", "")]


def watch(label: str, lines: list[str]) -> bool:
    """观察 WATCH_SECONDS 秒，返回 Boss 页面是否全程存活。"""
    start = time.time()
    survived = True
    while time.time() - start < WATCH_SECONDS:
        found = boss_targets()
        if not found:
            lines.append(f"  [{label}] 第 {time.time()-start:.1f} 秒：Boss 页面消失了！")
            survived = False
            break
        time.sleep(1)
    if survived:
        lines.append(f"  [{label}] {WATCH_SECONDS} 秒内页面一直存活（共 {len(boss_targets())} 个）")
    return survived


async def main() -> int:
    lines = ["==== 标签页存活实验 ===="]
    OUT.parent.mkdir(parents=True, exist_ok=True)

    initial = boss_targets()
    lines.append(f"开始时找到 {len(initial)} 个 Boss 页面")
    for t in initial:
        lines.append(f"  - {t.get('url','')}")
    if not initial:
        lines.append("一开始就没有 Boss 页面，请先让浏览器停在沟通页。")
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 2

    print("阶段一：只观察，不接管（15 秒）……")
    lines.append("阶段一：只用 HTTP 查询，不挂调试器")
    phase1 = watch("只观察", lines)

    print("阶段二：挂上调试器再观察（15 秒）……")
    lines.append("阶段二：用 Playwright 挂上调试器")
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        await playwright.chromium.connect_over_cdp(
            config.CDP_ENDPOINT, timeout=config.CDP_TIMEOUT_MS
        )
        lines.append("  调试器已接管")
    except Exception as error:
        lines.append(f"  接管失败：{error.__class__.__name__}: {error}")
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 1
    phase2 = watch("已接管", lines)

    lines.append("")
    lines.append("==== 结论 ====")
    if phase1 and not phase2:
        verdict = "页面只在『被调试器接管』后消失 → 是 Boss 的反自动化在关标签页，当前方案走不通。"
    elif not phase1:
        verdict = "还没接管页面就自己没了 → 与脚本无关，是浏览器或页面自身的问题。"
    else:
        verdict = "两个阶段页面都活着 → 关页面另有原因，可以继续排查抓取流程。"
    lines.append(verdict)

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n结论已写入 {OUT}")
    import os

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
