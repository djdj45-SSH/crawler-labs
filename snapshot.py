#!/usr/bin/env python
"""抓快照：把"靶场在某一级下返回了什么"冻结到磁盘。

    python snapshot.py --level L3        # 自己起靶场、抓完、关掉 → fixtures/snapshots/l3/
    python snapshot.py --all             # 六个等级各抓一份（约 1 分钟，L2 那趟要等窗口）
    python snapshot.py                   # 抓一个**正在跑**的靶场（默认 127.0.0.1:8000）
    python snapshot.py --base-url http://127.0.0.1:9001 --tag dev
    python snapshot.py --list            # 看已经有哪些

为什么要"自己起靶场"
--------------------
抓快照和防护等级是一一对应的：同一路径在 L0 是真实列表页、在 L3 是假数据、
在 L4 是空壳。所以"抓一份 L3 的快照"这件事本身就意味着"用 L3 起一次靶场"。
让脚本自己起、自己关，而不是让用户开三个终端对着切换 —— 那一定会出错。

抓什么、用谁的身份
------------------
见下面 `CAPTURE` 表。要点是**三种身份都要抓**：同一路径在不同身份下响应不同，
少了任何一列，对照类实验（第 4 章"伪装 vs 声明身份"）就复现不出来。

一个当前等级的坑：**在 L2 下抓快照，抓取动作本身会被限流。**
脚本会按契约算出一个安全间隔自动放慢 —— 否则后面几页会被记成 429，
而那不是靶场的形态，是你抓得太快。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dojo import IdentityError, fetch_contract, headers_for  # noqa: E402
from snapshots import SNAPSHOT_DIR, Snapshot  # noqa: E402

DEFAULT_DOJO_DIR = ROOT.parent / "crawler-dojo"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

#: 六个等级，`--all` 按这个顺序抓。标签就是等级小写；L0 用 "l0"。
ALL_LEVELS = ["none", "L1", "L2", "L3", "L4", "L5"]

# ---------------------------------------------------------------------------
# 抓哪些页
#
#   (名字, 路径, 身份, 为什么抓它)
#
# 路径里的 {slug} 会用**列表接口的第一条记录**解析出来 —— 这样内容改了快照也不用改。
# 分组顺序有讲究：先抓"内容层"，它不受等级影响（白名单跳过全部守卫）；
# 再抓"防护层"，它随等级变。
# ---------------------------------------------------------------------------
CAPTURE: list[tuple[str, str, str, str]] = [
    # ---- 内容层（白名单身份）----------------------------------------------
    ("contract", "contract", "whitelist", "第 1 章：契约本身 —— 离线时它就是靶场"),
    ("list_json", "list_json", "whitelist", "第 2 章：JSON 接口，解析的起点"),
    ("index", "index", "whitelist", "第 3 章：列表页正文，BS4 解析的对象"),
    ("detail", "detail_html", "whitelist", "第 3 章：详情页，字段比列表页多"),
    # ---- 防护层（裸身份 / 伪装身份）--------------------------------------
    ("index_bare", "index", "bare", "第 4–7 章：裸身份看到了什么"),
    ("list_json_bare", "list_json", "bare", "第 4/6/7 章：裸身份拿到的列表"),
    ("list_json_browser", "list_json", "browser", "第 4 章：伪装成浏览器 —— 能过，但不在白名单"),
    ("detail_bare", "first_url", "bare", "第 6 章：F3 链接可达性的探针（L3 下第一条是死链）"),
    ("js_payload", "js_payload", "bare", "第 7 章：L4 的空壳把数据放在了这里"),
]

#: 路径写成端点 key 就用契约里的端点；写成 `first_url` 表示"列表第一条的 url"
_SPECIAL_FIRST_URL = "first_url"


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> None:
    sys.stderr.write(f"\n[snapshot] 错误：{msg}\n")
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# 起靶场
# ---------------------------------------------------------------------------


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 5.0):
    import requests

    return requests.get(url, headers=headers or {}, timeout=timeout)


def wait_health(base: str, expect_levels: list[str], *, timeout: float = 25.0) -> dict:
    """等靶场起来，并且确认**生效等级正是我们要的**。

    只等 200 是不够的：端口上可能跑着另一个等级的旧靶场，
    于是你会安静地抓一份错的快照。所以这里比对 active_levels。
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = http_get(base + "/__dojo/health", timeout=2)
            if r.status_code == 200:
                health = r.json()
                got = list(health.get("active_levels") or [])
                if got == expect_levels:
                    return health
                last = f"端口上有别的靶场：生效等级 {got or ['L0']}，期望 {expect_levels}"
            else:
                last = f"health → {r.status_code}"
        except Exception as exc:  # noqa: BLE001 — 起来之前什么错都可能
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.4)
    raise TimeoutError(last or "超时")


class DojoProcess:
    """按等级起一个靶场，用完关掉。"""

    def __init__(self, dojo_dir: pathlib.Path, level: str, port: int) -> None:
        self.dojo_dir = dojo_dir
        self.level = level
        self.port = port
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "DojoProcess":
        if not (self.dojo_dir / "server" / "main.py").exists():
            die(f"{self.dojo_dir} 里没有 server/main.py —— 用 --dojo-dir 指定 crawler-dojo 的位置")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "server.main", "--level", self.level, "--port", str(self.port)],
            cwd=str(self.dojo_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def __exit__(self, *exc: object) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self.proc.kill()


# ---------------------------------------------------------------------------
# 抓
# ---------------------------------------------------------------------------


def ext_for(content_type: str, path: str) -> str:
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if "javascript" in ct:
        return "js"
    if "html" in ct:
        return "html"
    if "text/" in ct:
        return "txt"
    tail = path.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1] if "." in tail else "bin"


def auto_delay(contract) -> float:
    """L2 生效时，抓取动作本身会被限流 —— 按契约算一个安全间隔。

    间隔取 `窗口 / 上限` 再留 15% 余量。契约里没配就退回 0（不睡）。
    """
    if "L2" not in contract.active_levels:
        return 0.0
    cfg = contract.level("L2").config
    limit = max(1, int(cfg.get("requests", 5)))
    window = float(cfg.get("window_seconds", 10))
    # 上限是"窗口内不超过 limit 次"。想一直不被拦，间隔至少要 window/(limit-1)：
    # 留出 1 个名额，否则第 limit 次正好压在窗口边界上。再乘 1.15 留余量。
    return window / max(1, limit - 1) * 1.15


def capture_run(base_url: str, tag: str, *, force: bool, level_note: str) -> Snapshot:
    contract = fetch_contract(base_url)
    if contract.runtime.get("source") != "live":
        die(f"{base_url} 上没有活着的靶场，拿到的是本地缓存 —— 快照必须抓活的")

    delay = auto_delay(contract)
    out_dir = SNAPSHOT_DIR / tag
    if out_dir.exists() and not force:
        die(f"{out_dir} 已存在。要覆盖加 --force（先想清楚是不是想覆盖别人在用的那份）")

    log(f"  契约 v{contract.version} · 生效等级 "
        f"{'、'.join(contract.active_levels) or 'L0（无防护）'} · 身份 {', '.join(('bare', 'browser', 'whitelist'))}")
    if delay:
        log(f"  L2 生效：每页之间等 {delay:.2f}s，否则抓取动作本身会被限流")

    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []

    # ---- 带缓存的取页 ------------------------------------------------------
    # 同一个 (路径, 身份) 只请求一次。两个理由：
    #   1. 详情页的探针要知道"这个身份下列表第一条是什么"，而列表本身也在抓取表里 ——
    #      不缓存就会把同一个 URL 打两遍；
    #   2. 在 L2 下每个多余请求都在烧配额，而配额是按窗口算的。
    cache: dict[tuple[str, str], object] = {}
    last_call = [0.0]

    def get(path: str, identity: str):
        key = (path, identity)
        if key in cache:
            return cache[key]
        if delay:
            gap = time.time() - last_call[0]
            if gap < delay:
                time.sleep(delay - gap)
        r = http_get(base_url + path, headers=headers_for(identity, contract), timeout=8)
        last_call[0] = time.time()
        cache[key] = r
        return r

    def first_url_for(identity: str) -> str:
        """用**这个条目自己的身份**去取列表，拿第一条的 url。

        为什么不能统一用白名单：L3 下裸身份拿到的是蜜罐，它的第一条 url 是个死链 ——
        那正是第 6 章 F3 要探的东西。用白名单取会拿到真文章，探针就失去了意义。
        """
        try:
            rows = get(contract.endpoints["list_json"], identity).json()
        except Exception:  # noqa: BLE001 — 拿不到就是拿不到，后面按"跳过"记录
            return ""
        if not isinstance(rows, list) or not rows:
            return ""
        row = rows[0]
        return row.get("url") or (f"/posts/{row['slug']}.html" if row.get("slug") else "")

    # 详情页的路径是 `/posts/{slug}.html`，要拿一条真实的 slug 去填。
    # 用白名单身份取列表 —— 内容层不受等级影响，任何等级下都拿得到。
    detail_path = contract.endpoints.get("detail_html", "")
    first_slug = ""
    if "{slug}" in detail_path:
        try:
            rows = get(contract.endpoints["list_json"], "whitelist").json()
            if isinstance(rows, list) and rows:
                first_slug = rows[0].get("slug", "")
        except Exception as exc:  # noqa: BLE001
            log(f"  ⚠ 详情页的 slug 没解析出来（{type(exc).__name__}），详情页会跳过")

    for name, spec, identity, why in CAPTURE:
        # ---- 把 spec 解析成真实路径 ----
        if spec == _SPECIAL_FIRST_URL:
            path = first_url_for(identity)
            if not path:
                pages.append(_skipped(name, spec, identity, why,
                                      "该身份下的列表拿不到第一条（这一级可能关了接口）"))
                continue
        else:
            if spec not in contract.endpoints:
                # 端点 key 写错会安静地变成一个不存在的路径，最后表现成"抓到了 404"——
                # 排查起来要绕一大圈。这里直接炸。
                die(f"CAPTURE 里的 {name!r} 用了未知端点 {spec!r}；"
                    f"契约里的端点是：{'、'.join(contract.endpoints)}")
            path = contract.endpoints[spec]

        if "{slug}" in path:
            if not first_slug:
                pages.append(_skipped(name, spec, identity, why, "没有可用的 slug"))
                continue
            path = path.format(slug=first_slug)

        url = base_url + (path if path.startswith("/") else "/" + path)
        entry: dict = {"name": name, "path": path, "identity": identity, "reason": why,
                       "url": url}
        try:
            r = get(path, identity)
        except IdentityError as exc:
            die(str(exc))
        except Exception as exc:  # noqa: BLE001
            log(f"  ✗ {name:<18} {identity:<9} {type(exc).__name__}: {exc}")
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["file"] = ""
            pages.append(entry)
            continue

        ctype = r.headers.get("content-type", "")
        ext = ext_for(ctype, path)
        fname = f"{name}__{identity}.{ext}"
        (out_dir / fname).write_bytes(r.content)

        entry.update(
            file=fname,
            status=r.status_code,
            content_type=ctype,
            bytes=len(r.content),
            sha256=hashlib.sha256(r.content).hexdigest(),
            encoding=r.encoding,
            apparent_encoding=r.apparent_encoding,
            headers={k.lower(): v for k, v in r.headers.items()},
        )
        pages.append(entry)

        signal = r.headers.get("x-dojo-block") or r.headers.get("x-dojo-signal") or ""
        mark = f"{r.status_code}"
        log(f"  · {name:<18} {identity:<9} {mark:>3}  {len(r.content):>6}B  {signal}")

    manifest = {
        "tag": tag,
        "captured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": base_url,
        "level_spec": level_note,
        "active_levels": contract.active_levels,
        "contract_version": contract.version,
        "note": (
            "content 层（whitelist 身份）不受等级影响；guard 层（bare/browser）"
            "随等级变化。所以判断一份快照能不能跑某个实验，看 active_levels，"
            "而不是看抓取时间。"
        ),
        "contract": json.loads(json.dumps(_contract_with_runtime(contract, level_note))),
        "pages": pages,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    snap = Snapshot(out_dir)
    ok = len(snap._by_key)
    fail = len(pages) - ok
    log(f"  → {out_dir}")
    log(f"     {snap.describe()}")
    if fail:
        log(f"     ⚠ {fail} 页没抓到（已记进 manifest，不算进可用快照）")
    return snap


def _contract_with_runtime(contract, level_note: str) -> dict:
    """把契约序列化，并把 runtime 补成"抓取时的状态"。

    离线模式直接拿它当契约用 —— 于是 `require("L3")` 检查的"当前生效等级"
    就是这份快照抓取时的等级，语义完全对得上，不需要给离线模式写第二套逻辑。

    手写序列化而不是 `asdict()`：`Level.config` 与 `whitelist` 要原样保留，
    而 Contract 的 dataclass 字段名和磁盘格式不一定永远一致 —— 这里显式列出，
    格式变了会在 diff 里立刻看见。
    """
    return {
        "version": contract.version,
        "name": contract.name,
        "whitelist": contract.whitelist,
        "endpoints": contract.endpoints,
        "levels": [
            {
                "id": lv.id,
                "name": lv.name,
                "guard": lv.guard,
                "expect_status": lv.expect_status,
                "signal": lv.signal,
                "teaches": lv.teaches,
                "note": lv.note,
                "config": lv.config,
            }
            for lv in contract.levels.values()
        ],
        "runtime": {
            "level_spec": level_note,
            "active_levels": contract.active_levels,
            "source": "snapshot",
        },
    }


def _skipped(name: str, spec: str, identity: str, why: str, reason: str) -> dict:
    return {
        "name": name, "path": spec, "identity": identity,
        "reason": why, "file": "", "error": reason,
    }


def list_snapshots() -> None:
    from snapshots import available

    snaps = available()
    if not snaps:
        log(f"{SNAPSHOT_DIR} 里还没有快照。抓一份：python snapshot.py --level L3")
        return
    log(f"{SNAPSHOT_DIR}")
    for s in snaps:
        lv = "、".join(s.active_levels) or "L0（无防护）"
        log(f"  {s.tag:<8} {s.captured_at[:16]}  {lv:<14} {len(s._by_key)} 页")


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="snapshot",
        description="把靶场在某一级下返回的响应抓成本地快照，供离线跑实验。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("为什么要")[-1],
    )
    ap.add_argument("--level", help="用这一级起靶场再抓（none / L1 / L3 / all ...）")
    ap.add_argument("--all", action="store_true", help="六个等级各抓一份")
    ap.add_argument("--base-url", default=None,
                    help=f"抓一个已经在跑的靶场（默认 {DEFAULT_BASE_URL}）")
    ap.add_argument("--tag", default=None, help="快照标签（默认取等级名）")
    ap.add_argument("--port", type=int, default=8000, help="自起靶场时的端口（默认 8000）")
    ap.add_argument("--dojo-dir", default=str(DEFAULT_DOJO_DIR), help="crawler-dojo 的位置")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的同名快照")
    ap.add_argument("--list", action="store_true", help="列出已有的快照")
    args = ap.parse_args(argv)

    if args.list:
        list_snapshots()
        return 0

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dojo_dir = pathlib.Path(args.dojo_dir).resolve()

    # ---- 自己起靶场逐级抓 ----
    if args.all:
        log(f"抓全部 {len(ALL_LEVELS)} 个等级 → {SNAPSHOT_DIR}")
        for spec in ALL_LEVELS:
            tag = tag_for(spec)
            if (SNAPSHOT_DIR / tag).exists() and not args.force:
                log(f"\n[{tag}] 已存在，跳过（要重抓加 --force）")
                continue
            log(f"\n[{tag}] 起靶场 --level {spec} …")
            with DojoProcess(dojo_dir, spec, args.port) as dp:
                try:
                    wait_health(dp.base_url, expect_levels_for(spec))
                except TimeoutError as exc:
                    die(f"靶场没起来（{exc}）")
                capture_run(dp.base_url, tag, force=True, level_note=spec)
        log("")
        list_snapshots()
        return 0

    if args.level:
        tag = args.tag or tag_for(args.level)
        if (SNAPSHOT_DIR / tag).exists() and not args.force:
            die(f"{SNAPSHOT_DIR / tag} 已存在。要覆盖加 --force")
        log(f"[{tag}] 起靶场 --level {args.level} …")
        with DojoProcess(dojo_dir, args.level, args.port) as dp:
            try:
                wait_health(dp.base_url, expect_levels_for(args.level))  # may raise
            except TimeoutError as exc:
                die(
                    f"靶场没起来（{exc}）\n"
                    f"  手动试一次：cd {dojo_dir} && python -m server.main --level {args.level}"
                )
            capture_run(dp.base_url, tag, force=True, level_note=args.level)
        return 0

    # ---- 抓一个正在跑的 ----
    base = args.base_url or DEFAULT_BASE_URL
    try:
        health = http_get(base + "/__dojo/health", timeout=3).json()
    except Exception as exc:  # noqa: BLE001
        die(
            f"{base} 上没有活着的靶场（{type(exc).__name__}）\n"
            "  要么指定等级让本脚本自己起：python snapshot.py --level L3\n"
            "  要么先起靶场再跑本脚本（不带参数）"
        )
    levels = list(health.get("active_levels") or [])
    tag = args.tag or (tag_for(levels[0]) if len(levels) == 1 else
                       ("all" if levels else "l0"))
    log(f"[{tag}] 抓正在跑的靶场 {base}（生效等级 {'、'.join(levels) or 'L0'}）")
    capture_run(base, tag, force=args.force, level_note="、".join(levels) or "none")
    return 0


def tag_for(spec: str) -> str:
    s = (spec or "").strip().lower()
    if s in ("none", "l0", "", "0"):
        return "l0"
    if s in ("all", "*"):
        return "all"
    return s.replace(",", "-")


def expect_levels_for(spec: str) -> list[str]:
    """`--level` 的写法 → 期望的 active_levels 列表。用于校验端口上跑的是不是我们起的那台。"""
    s = (spec or "").strip().upper()
    if s in ("ALL", "*", ""):
        return ["L1", "L2", "L3", "L4", "L5"]
    if s in ("NONE", "L0", "0"):
        return []
    got = [x.strip().upper() for x in s.split(",") if x.strip()]
    order = {lv: i for i, lv in enumerate(["L1", "L2", "L3", "L4", "L5"])}
    return sorted([g for g in got if g in order], key=lambda g: order[g])


if __name__ == "__main__":
    raise SystemExit(main())
