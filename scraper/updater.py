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

BASE_DIR = Path(__file__).resolve().parent.parent


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
