"""启动前自动更新：从国内可直连的 GitHub 镜像拉取最新 main.py / config.py。

设计原则：更新失败绝不阻塞抓取——任何异常都静默跳过，用本地现有版本继续。
下载内容先做语法编译检查，通过才原子替换，避免拉到坏文件把工具搞瘫。
"""

from __future__ import annotations

import py_compile
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "fermionoid/boss-zhipin-scraper"
FILES = ("scraper/main.py", "scraper/config.py")
# 国内可直连的镜像前缀。注意：jsDelivr 的 @main 会缓存很久，即使已经 purge
# 也可能继续吐旧版（2026-09-01 实测卡了十几分钟），所以绝不能"谁先响应用谁"，
# 必须比较各镜像的 VERSION，取最新的那个（见 pick_freshest）。
MIRRORS = (
    "https://cdn.jsdelivr.net/gh/{repo}@main/{path}",
    "https://fastly.jsdelivr.net/gh/{repo}@main/{path}",
    "https://gcore.jsdelivr.net/gh/{repo}@main/{path}",
    "https://ghproxy.net/https://raw.githubusercontent.com/{repo}/main/{path}",
    "https://raw.githubusercontent.com/{repo}/main/{path}",
)
TIMEOUT = 8
VERSION_RE = re.compile(rb'^VERSION\s*=\s*"([^"]+)"', re.M)
TAG_RE = re.compile(r"^v?\d{4}\.\d{2}\.\d{2}-\d+$")

BASE_DIR = Path(__file__).resolve().parent.parent


def latest_tag() -> str | None:
    """查 jsDelivr 的数据 API 拿最新发布标签。

    为什么必须用标签：jsDelivr 对 @main 这种分支引用的缓存刷不掉——即使调用
    purge 接口返回成功，边缘节点仍会持续吐旧版几十分钟（2026-09-01 实测）。
    而 @<tag> 是不可变引用，首次请求即回源，永远拿到对的内容。
    """
    data = get("https://data.jsdelivr.com/v1/packages/gh/" + REPO)
    if not data:
        return None
    try:
        import json

        versions = json.loads(data).get("versions") or []
        best = None
        for entry in versions:
            tag = entry.get("version", "")
            # 只认 2026.09.01-6 这种严格格式，避免老式标签（如 20260901）
            # 被解析成一个巨大的数字而永远"最新"。
            if not TAG_RE.match(tag):
                continue
            parsed = tuple(int(c) for c in re.split(r"[.\-]", tag.lstrip("vV")))
            if best is None or parsed > best[1]:
                best = (tag, parsed)
        return best[0] if best else None
    except Exception:
        return None


def get(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            data = response.read()
            return data if data and len(data) > 200 else None
    except Exception:
        return None


def version_of(data: bytes) -> tuple[int, ...]:
    match = VERSION_RE.search(data or b"")
    if not match:
        return ()
    parts: list[int] = []
    for chunk in re.split(rb"[.\-]", match.group(1)):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def pick_freshest() -> tuple[str, tuple[int, ...]] | None:
    """比较各镜像上 main.py 的 VERSION，返回最新的那个镜像模板。

    绝不能"谁先响应用谁"：CDN 可能长时间吐旧版，那样会把本地已经修好的
    文件覆盖回去（2026-09-01 踩过）。
    """
    best: tuple[str, tuple[int, ...]] | None = None

    # 首选：不可变的标签引用，绕开分支缓存。
    tag = latest_tag()
    if tag:
        tagged = "https://cdn.jsdelivr.net/gh/{repo}@" + tag + "/{path}"
        data = get(tagged.format(repo=REPO, path="scraper/main.py"))
        version = version_of(data) if data else ()
        if version:
            best = (tagged, version)

    for mirror in MIRRORS:
        data = get(mirror.format(repo=REPO, path="scraper/main.py"))
        if data is None:
            continue
        version = version_of(data)
        if not version:
            continue
        if best is None or version > best[1]:
            best = (mirror, version)
    return best


def local_version() -> tuple[int, ...]:
    try:
        return version_of((BASE_DIR / "scraper" / "main.py").read_bytes())
    except Exception:
        return ()


def update_one(path: str, mirror: str) -> bool:
    target = BASE_DIR / path
    data = get(mirror.format(repo=REPO, path=path))
    if data is None:
        return False
    try:
        if target.read_bytes() == data:
            return False
    except Exception:
        pass
    try:
        with tempfile.NamedTemporaryFile(
            "wb", suffix=".py", dir=str(target.parent), delete=False
        ) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        py_compile.compile(str(temp_path), doraise=True)
        temp_path.replace(target)
        return True
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def main() -> int:
    print("检查程序更新……")
    here = local_version()
    best = pick_freshest()
    if best is None:
        print("联网检查失败，使用本地版本继续。")
        return 0
    mirror, remote = best
    if here and remote <= here:
        print("当前已是最新版。")
        return 0
    updated = [path for path in FILES if update_one(path, mirror)]
    if updated:
        print(f"已更新到 {'.'.join(str(n) for n in remote)}：{', '.join(updated)}")
    else:
        print("当前已是最新版。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
