"""启动前自动更新：从国内可直连的 GitHub 镜像拉取最新 main.py / config.py。

设计原则：更新失败绝不阻塞抓取——任何异常都静默跳过，用本地现有版本继续。
下载内容先做语法编译检查，通过才原子替换，避免拉到坏文件把工具搞瘫。
"""

from __future__ import annotations

import py_compile
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "fermionoid/boss-zhipin-scraper"
FILES = ("scraper/main.py", "scraper/config.py")
# 国内可直连的镜像前缀，依次尝试；最后一个是 GitHub 原始地址兜底。
MIRRORS = (
    "https://cdn.jsdelivr.net/gh/{repo}@main/{path}",
    "https://fastly.jsdelivr.net/gh/{repo}@main/{path}",
    "https://gcore.jsdelivr.net/gh/{repo}@main/{path}",
    "https://raw.githubusercontent.com/{repo}/main/{path}",
)
TIMEOUT = 8

BASE_DIR = Path(__file__).resolve().parent.parent


def fetch(path: str) -> bytes | None:
    for mirror in MIRRORS:
        url = mirror.format(repo=REPO, path=path)
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                data = response.read()
                if data and len(data) > 200:
                    return data
        except Exception:
            continue
    return None


def update_one(path: str) -> bool:
    target = BASE_DIR / path
    data = fetch(path)
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
    updated = [path for path in FILES if update_one(path)]
    if updated:
        print(f"已自动更新到最新版：{', '.join(updated)}")
    else:
        print("当前已是最新版（或网络不可用，使用本地版本）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
