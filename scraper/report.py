"""把脱敏后的诊断信息回传，便于远程排查。

隐私红线（务必遵守）：
- 只回传排查所需的技术信息：版本号、报错类型、页面网址、计数、结论。
- 绝不回传候选人姓名、简历内容、聊天原文、截图、CSV 等任何业务数据。
- 上传前统一过一遍 redact()，把中文人名、手机号、邮箱等抹成占位符。
- 上传失败一律静默忽略，绝不影响抓取本身。
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

CHANNEL = "https://ntfy.sh/boss-diag-69b634bc48350605"
TIMEOUT = 8
MAX_CHARS = 12000

# 日志里出现人名的固定句式，直接换成占位符。
NAME_PATTERNS = (
    re.compile(r"(name=)[^\s]+"),
    re.compile(r"(姓名[=:：])\s*\S+"),
    re.compile(r"(跳过系统消息：)\S+"),
    re.compile(r"(已抓取：)\S+"),
    re.compile(r"(跳过导航项：)\S+"),
    re.compile(r"(失败，已跳过：)\S+"),
    re.compile(r"(候选人条目：)\S+"),
    re.compile(r"(整页截图：)\S+"),
    re.compile(r"(等待右侧面板渲染：)\S+"),
)
PHONE_RE = re.compile(r"1[3-9]\d{9}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# 兜底：任何连续 2-4 个汉字若紧跟在冒号/等号后，视为可能的人名。
CJK_AFTER_MARK_RE = re.compile(r"([：:=])\s*[一-鿿]{2,4}(?=\s|$)")


def redact(text: str) -> str:
    """抹掉一切可能的个人信息。宁可多抹，不可漏抹。"""
    for pattern in NAME_PATTERNS:
        text = pattern.sub(r"\1[已隐去]", text)
    text = PHONE_RE.sub("[手机号]", text)
    text = EMAIL_RE.sub("[邮箱]", text)
    text = CJK_AFTER_MARK_RE.sub(r"\1[已隐去]", text)
    return text


def ascii_title(title: str) -> str:
    """HTTP 头只能放 latin-1 字符，中文标题会让请求直接失败（实测踩过）。"""
    return title.encode("ascii", "ignore").decode("ascii") or "boss-diag"


def send(title: str, body: str) -> bool:
    payload = redact(body)[-MAX_CHARS:]
    try:
        request = urllib.request.Request(
            CHANNEL,
            data=payload.encode("utf-8"),
            headers={"Title": ascii_title(title), "Content-Type": "text/plain; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT):
            return True
    except Exception:
        return False


def send_log_tail(log_path: Path, version: str, lines: int = 120) -> bool:
    """回传日志末尾若干行（已脱敏）。"""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    tail = "\n".join(text.splitlines()[-lines:])
    return send(f"boss {version}", tail)


def self_test() -> None:
    """脱敏自检：确保典型日志行里的人名全被抹掉。"""
    sample = (
        "抓取成功 key=key:98040707-0 name=谢耀东\n"
        "[3] 已抓取：雷媛\n"
        "点击候选人条目：郭泽鹏\n"
        "姓名：王思佳 手机 13812345678 邮箱 a.b@qq.com\n"
        "url=https://www.zhipin.com/web/chat/index\n"
    )
    out = redact(sample)
    for leaked in ("谢耀东", "雷媛", "郭泽鹏", "王思佳", "13812345678", "a.b@qq.com"):
        assert leaked not in out, f"脱敏失败，泄漏了：{leaked}\n{out}"
    assert "zhipin.com/web/chat/index" in out, "技术信息不该被误伤"
    print("脱敏自检通过：\n" + out)


if __name__ == "__main__":
    self_test()
