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

    python main.py --snapshot auto  # 离线跑：每个实验用自己那一级的快照
    python main.py --snapshot l3    # 离线跑：全部实验都对着 l3 那一份
    python main.py --snapshot none  # 走网络（默认）

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

不想开靶场
----------
先抓一次快照（快照自己会把靶场起起来、抓完关掉）：

    python snapshot.py --all          # 六个等级各抓一份，约 1 分钟
    python main.py --snapshot auto    # 之后全都能离线跑

离线模式**不降低严格程度**：快照里冻结了抓取时的契约，所以
"这一页是不是真的来自 L3"这类判断照旧生效，跳过原因照旧给得出来。
真正离不开实时请求的实验（限流、浏览器耗时、签名验证、真实站点）
会明确跳过并说明为什么 —— 它们的数量是 4 个，不是"剩下的都没做"。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import unicodedata

import snapshots
from dojo import Contract, ContractError, Dojo, fetch_contract
from labs import LabContext, all_labs, find_lab
from labs.base import FALLBACK_LEVEL, LabSkip, Outcome

DEFAULT_DOJO = os.environ.get("DOJO_BASE_URL", "http://127.0.0.1:8000")

#: 契约里的等级全集。用来把 lab.level（可能是 "—"）折成一个快照标签。
KNOWN_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
CYAN = "\033[36m"


def dwidth(s: str) -> int:
    """显示宽度：中日韩字符算 2 列。不处理的话表格会歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dwidth(s))


def snapshot_tag_for(lab) -> str:
    """这个实验在离线模式下该用哪一份快照。

    绝大多数实验用它自己针对的等级（lab.level）。少数不针对任何等级的实验
    （第 1、9 章的实验，`level` 是 "—"）取 L0 —— 它们用的是白名单身份，
    内容层不随等级变，L0 那份就够。
    """
    lv = str(lab.snapshot_level or lab.level or "").upper()
    if lv not in KNOWN_LEVELS:
        lv = FALLBACK_LEVEL
    return lv.lower()


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
    ap.add_argument(
        "--snapshot",
        default="none",
        metavar="auto|l0|l3|...|none",
        help="离线跑快照：auto（每个实验用自己那一级）/ 标签 / none（走网络，默认）",
    )
    args = ap.parse_args(argv)

    labs = all_labs()
    if args.lab:
        one = find_lab(args.lab)
        if one is None:
            sys.stderr.write(f"\n找不到实验 {args.lab!r}。用 --list 看清单。\n")
            return 2
        labs = [one]

    offline = args.snapshot != "none"

    # ---------------------------------------------------------------- 快照
    avail: list[snapshots.Snapshot] = []
    fixed_snap = None
    if offline:
        avail = snapshots.available()
        if not avail:
            sys.stderr.write(
                f"\n[错误] {snapshots.SNAPSHOT_DIR} 里还没有快照。\n\n"
                "  抓一份：python snapshot.py --level L3\n"
                "  抓全套：python snapshot.py --all（推荐，之后 --snapshot auto 所有实验都能跑）\n\n"
            )
            return 2
        if args.snapshot != "auto":
            fixed_snap = snapshots.find(args.snapshot)
            if fixed_snap is None:
                sys.stderr.write(
                    f"\n[错误] 没有名为 {args.snapshot!r} 的快照。"
                    f"现有：{'、'.join(s.tag for s in avail)}\n\n"
                )
                return 2

    # ---------------------------------------------------------------- 拉契约
    if offline:
        # 离线模式下契约来自快照 —— 它冻结的正是"抓取那一刻靶场的状态"，
        # 所以 require()/ensure_level() 这些判断不用改一个字就能继续工作。
        base = fixed_snap or avail[0]
        contract = Contract.from_json(base.contract_json)
    else:
        try:
            contract = fetch_contract(args.dojo)
        except ContractError as exc:
            sys.stderr.write(f"\n[错误] {exc}\n\n")
            sys.stderr.write(
                "  想离线看实验清单：python main.py --list\n"
                "  想离线跑实验：     python snapshot.py --all && python main.py --snapshot auto\n"
            )
            return 2

    if not args.json:
        source = contract.runtime.get("source", "live")
        print(f"crawler-dojo 契约 v{contract.version}（来源：{source}）")
        if offline:
            how = "auto（每个实验用自己那一级）" if fixed_snap is None else fixed_snap.tag
            print(f"离线模式    快照 {how}")
            print(f"可用快照    {'、'.join(s.describe() for s in avail)}")
        else:
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
                if not offline:
                    note = ""
                elif lab.live_only:
                    note = f"{DIM}（离线不可用）{RESET}"
                else:
                    note = f"{DIM}（离线：用快照 {snapshot_tag_for(lab)}）{RESET}"
                print(f"{pad(lab.chapter, 4)}{pad(f'{lab.id} {lab.title}', 44)}"
                      f"{pad(lab.level, 6)}{lab.teaches}{note}")
            return 0
        print()

    ctx = LabContext(Dojo(args.dojo, contract), verbose=args.verbose,
                     offline=offline, snapshot=fixed_snap)

    # ---------------------------------------------------------------- 跑
    results: list[tuple] = []
    used_tags: set[str] = set()

    for lab in labs:
        if offline:
            snap = fixed_snap or snapshots.find(snapshot_tag_for(lab))
            ctx.use_snapshot(snap)

            if lab.live_only:
                results.append((lab, Outcome.skip(
                    f"离线模式：{lab.live_only_reason}", lab.level)))
                continue
            if snap is None:
                tag = snapshot_tag_for(lab)
                results.append((lab, Outcome.skip(
                    f"离线模式：没有 {tag} 快照 —— python snapshot.py --level {tag}"
                    f"（或 python snapshot.py --all 一次抓全）", lab.level)))
                continue
            used_tags.add(snap.tag)

        try:
            out = lab.run(ctx)
        except LabSkip as exc:      # 实验跑到一半发现前提不成立 —— 算跳过
            out = Outcome.skip(str(exc), lab.level)
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

        # --verbose：通过的实验也把过程打出来。
        # 默认只看结论是为了矩阵能一眼扫完；但那些"过程本身就是内容"的实验
        # （第 4 章三种身份的对照、第 7 章 L0/L4 并列、第 6 章检出的破绽清单）
        # 结论那一行装不下 —— 不看细节等于白跑。
        if args.verbose:
            for lab, out in results:
                if out.ok and not out.skipped and out.detail:
                    print(f"\n{CYAN}── {lab.id} {lab.title} ──{RESET}")
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
        if offline and used_tags:
            print(f"{DIM}用了快照：{'、'.join(sorted(used_tags))}"
                  f" · 目录 {snapshots.SNAPSHOT_DIR}{RESET}")

    return 1 if any(not o.ok for _, o in results) else 0


def lab_outcome_from_exc(tb: str):
    return Outcome.fail("实验抛出异常", tb)


if __name__ == "__main__":
    raise SystemExit(main())
