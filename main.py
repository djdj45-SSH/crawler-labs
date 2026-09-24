#!/usr/bin/env python
"""crawler-labs 运行器。

用法
----
    python main.py                  # 按章节顺序跑全部
    python main.py --lab 04         # 只跑实验 04
    python main.py --list           # 只看清单，不跑
    python main.py --verbose        # 打印每个实验的内部步骤
    python main.py --json           # 输出 JSON（便于二次处理）
    python main.py --dojo URL       # 指定靶场地址（默认 http://127.0.0.1:8000）

前置
----
靶场要先在另一个终端起着：

    cd ../crawler-dojo && python -m server.main --level all

防护是叠加的：`--level all` 下裸 UA 会在 L1 就停下，到不了 L2/L3/L5。
所以观察后面几级时要单独开：

    python -m server.main --level L2      # 第 5 章
    python -m server.main --level L3      # 第 6 章
    ...

这不是缺陷，是真实世界的样子 —— 前一级生效，后一级就永远收不到那个请求。
跑不动的实验会**跳过并告诉你该开哪一级**，不会假装通过。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import unicodedata

from dojo import ContractError, Dojo, fetch_contract
from labs import LabContext, all_labs, find_lab

DEFAULT_DOJO = os.environ.get("DOJO_BASE_URL", "http://127.0.0.1:8000")

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"


def dwidth(s: str) -> int:
    """显示宽度：中日韩字符算 2 列。不处理的话表格会歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dwidth(s))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="crawler-labs",
        description="零基础 Python 爬虫：跟随 crawler-dojo 靶场逐级做实验。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("前置")[-1],
    )
    ap.add_argument("--dojo", default=DEFAULT_DOJO, help=f"靶场地址（默认 {DEFAULT_DOJO}）")
    ap.add_argument("--lab", help="只跑指定实验，例如 04 或 UaWhitelist")
    ap.add_argument("--list", action="store_true", help="只列出实验清单")
    ap.add_argument("--verbose", action="store_true", help="打印内部步骤")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args(argv)

    labs = all_labs()
    if args.lab:
        one = find_lab(args.lab)
        if one is None:
            sys.stderr.write(f"\n找不到实验 {args.lab!r}。用 --list 看清单。\n")
            return 2
        labs = [one]

    # ---------------------------------------------------------------- 拉契约
    try:
        contract = fetch_contract(args.dojo)
    except ContractError as exc:
        sys.stderr.write(f"\n[错误] {exc}\n\n")
        sys.stderr.write("  想离线看实验清单：python main.py --list\n")
        return 2

    source = contract.runtime.get("source", "live")
    if not args.json:
        print(f"crawler-dojo 契约 v{contract.version}（来源：{source}）")
        print(f"靶场        {args.dojo}")
        active = contract.active_levels
        print(f"生效等级    {', '.join(active) if active else 'L0（无防护）'}")
        if contract.runtime.get("stale_warning"):
            print(f"{YELLOW}警告        {contract.runtime['stale_warning']}{RESET}")
        if args.list:
            print()
            print(f"{pad('章', 4)}{pad('实验', 44)}{pad('等级', 6)}学什么")
            print("─" * 96)
            for lab in labs:
                print(f"{pad(lab.chapter, 4)}{pad(f'{lab.id} {lab.title}', 44)}"
                      f"{pad(lab.level, 6)}{lab.teaches}")
            return 0
        print()

    ctx = LabContext(Dojo(args.dojo, contract), verbose=args.verbose)

    # ---------------------------------------------------------------- 跑
    results: list[tuple] = []
    for lab in labs:
        try:
            out = lab.run(ctx)
        except Exception:  # noqa: BLE001 — 环境问题面很广，兜住并完整报出来
            out = lab_outcome_from_exc(traceback.format_exc())
        results.append((lab, out))

    # ---------------------------------------------------------------- 报表
    if args.json:
        print(json.dumps(
            [
                {
                    "id": lab.id,
                    "title": lab.title,
                    "chapter": lab.chapter,
                    "level": lab.level,
                    "ok": out.ok,
                    "skipped": out.skipped,
                    "summary": out.summary,
                    "skip_reason": out.skip_reason,
                    "facts": out.facts,
                }
                for lab, out in results
            ],
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(f"{pad('章', 4)}{pad('实验', 44)}{pad('等级', 6)}{pad('结果', 6)}结论")
        print("─" * 108)
        for lab, out in results:
            if out.skipped:
                mark = f"{YELLOW}跳过{RESET}"
            elif out.ok:
                mark = f"{GREEN}通过{RESET}"
            else:
                mark = f"{RED}失败{RESET}"
            print(f"{pad(lab.chapter, 4)}{pad(f'{lab.id} {lab.title}', 44)}"
                  f"{pad(lab.level, 6)}{pad(mark, 6 + 9)}{out.summary}")

        # 失败详情
        failures = [(lab, out) for lab, out in results if not out.ok]
        for lab, out in failures:
            print(f"\n{RED}── 失败：{lab.id} {lab.title} ──{RESET}")
            if out.detail:
                print(out.detail)

        # 跳过原因（合并同因，避免刷屏）
        skips = [(lab, out) for lab, out in results if out.skipped]
        if skips:
            print(f"\n{DIM}── 跳过 {len(skips)} 项 ──{RESET}")
            for lab, out in skips:
                print(f"{DIM}  {lab.id} {out.skip_reason}{RESET}")

        passed = sum(1 for _, o in results if o.ok and not o.skipped)
        skipped = len(skips)
        print()
        print("─" * 108)
        print(f"通过 {GREEN}{passed}{RESET} · 跳过 {YELLOW}{skipped}{RESET} · "
              f"失败 {RED if failures else DIM}{len(failures)}{RESET}")

    return 1 if any(not o.ok for _, o in results) else 0


def lab_outcome_from_exc(tb: str):
    from labs.base import Outcome

    return Outcome.fail("实验抛出异常", tb)


if __name__ == "__main__":
    raise SystemExit(main())
