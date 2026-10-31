#!/usr/bin/env python3
"""公开树敏感信息扫描。

扫描 Git 跟踪的文件，命中以下任一模式即以非零码退出：

* 真实生产 wxid / 微信号 / 群号；
* 厂商域名与内网地址；
* 生产密钥前缀；
* 本机绝对路径与内部主机名；
* 内部运维文档名。

占位符（``your-vendor.example``、``wxid_replace_me`` 等）不会命中。
CI 与本地共用；只读，不修改文件。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# 允许的文件：扫描器自身、示例账号、env 范例
SELF = Path(__file__).resolve()
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz"}

#: 通用形态 —— 可以公开的部分（不含任何真实标识）。
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("真实 wxid 形态", re.compile(r"wxid_(?!test|self|dummy|sample|example|replace|your)[a-z0-9]{11,}")),
    ("厂商域名", re.compile(r"\b(?:wx|oss|adm)\.juhe\.chat\b|juhe\.chat")),
    ("生产密钥前缀", re.compile(r"\bwxa_[A-Za-z0-9]{24,}\b")),
    ("私钥", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
    ("内网主机", re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d+\.\d+\b")),
    ("本机绝对路径", re.compile(r"/root/")),
    ("内部运维文档", re.compile(r"DEVELOPMENT_RULES")),
)


def _load_denylist() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """加载本机专属的真实标识黑名单（**不入库**）。

    真实 wxid / 群号 / 手机号 / 生产域名 / 密钥前缀写进公开仓等于又泄漏一次，
    所以它们放在 ``public_tree_denylist.txt``（一行一个正则，``#`` 注释），
    该文件已在 ``.gitignore`` 里。路径可用 ``WPP_PUBLIC_TREE_DENYLIST`` 覆盖。
    文件不存在时只跑通用形态（CI/外部贡献者场景）。
    """
    path = Path(os.environ.get("WPP_PUBLIC_TREE_DENYLIST")
                or Path(__file__).resolve().parents[1] / "public_tree_denylist.txt")
    if not path.exists():
        return ()
    rules: list[tuple[str, re.Pattern[str]]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rules.append((f"本机黑名单:{lineno}", re.compile(line)))
        except re.error as exc:
            print(f"public_tree_denylist.txt:{lineno} 正则无效（{exc}），已跳过",
                  file=sys.stderr)
    return tuple(rules)


PATTERNS = PATTERNS + _load_denylist()


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            check=True, capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"无法读取 git 文件列表：{exc}", file=sys.stderr)
        return []
    return [Path(p) for p in out.decode("utf-8", "replace").split("\0") if p]


def _iter_lines(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for lineno, line in enumerate(text.splitlines(), 1):
        yield lineno, line


def scan(files: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in files:
        if path.resolve() == SELF:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        for lineno, line in _iter_lines(path):
            for label, pattern in PATTERNS:
                # .gitignore 里出现内部文档名是「忽略规则」，不是泄漏。
                if path.name == ".gitignore" and label == "内部运维文档":
                    continue
                if pattern.search(line):
                    hits.append(f"{path}:{lineno}: [{label}] {line.strip()[:200]}")
    return hits


def main() -> int:
    files = _tracked_files()
    if not files:
        print("没有可扫描的 Git 跟踪文件", file=sys.stderr)
        return 2
    hits = scan(files)
    if hits:
        print(f"发现 {len(hits)} 处疑似敏感信息：\n", file=sys.stderr)
        for hit in hits:
            print(hit, file=sys.stderr)
        return 1
    print(f"公开树扫描通过：{len(files)} 个文件，未发现敏感信息")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
