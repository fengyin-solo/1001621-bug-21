"""廊桥对接业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "bridge"
REQUIRED_FIELDS = ["对接单号", "关联航班", "廊桥编号"]
STATUS_ORDER = ["待对接", "对接中", "已撤离", "已取消"]
ACTION_RULES = {"开始对接": "对接中", "确认撤离": "已撤离", "取消对接": "已取消"}
NEGATIVE_ACTIONS = []

# 列表/导出附带的问题说明字段名
ISSUE_FIELD = "数据问题"

# 现场时间可能出现的几种写法，逐个尝试解析
_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def _parse_time(value: Any) -> datetime | None:
    """尽量把字段值解析成时刻；无法识别的返回 None，交由调用方决定怎么提示。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def row_issues(row: dict[str, Any]) -> list[str]:
    """逐条检查一条对接记录：缺哪些必填字段、时刻是否颠倒。

    只做只读检查，不改原数据，保证每次刷新得到的结论一致。
    """
    issues: list[str] = []
    for field in REQUIRED_FIELDS:
        if not str(row.get(field) or "").strip():
            issues.append(f"{field}为空")
    start = _parse_time(row.get("对接时刻"))
    end = _parse_time(row.get("撤桥时刻"))
    if start is not None and end is not None and end < start:
        issues.append("撤桥时刻早于对接时刻")
    return issues


def describe_issues(issues: list[str]) -> str:
    return "；".join(issues)


def annotate(row: dict[str, Any]) -> dict[str, Any]:
    """返回带「数据问题」标注的副本；检查结果不回写仓库，刷新后仍是同一份结论。"""
    view = dict(row)
    view[ISSUE_FIELD] = describe_issues(row_issues(row))
    return view


class BridgeService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        flight: str | None = None,
        bridge_no: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("对接单号", ""))]
        if flight:
            rows = [row for row in rows if flight in str(row.get("关联航班", ""))]
        if bridge_no:
            rows = [row for row in rows if bridge_no in str(row.get("廊桥编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 字段缺失或时刻颠倒的记录照常留在结果里，只逐条标注问题，不静默丢弃
        total = len(rows)
        start = max(page - 1, 0) * size
        return [annotate(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return annotate(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        # 登记前把字段缺失与时刻颠倒都点出来，问题数据不入库、不静默丢弃
        candidate = {field: values.get(field) for field in REQUIRED_FIELDS}
        candidate["对接时刻"] = values.get("对接时刻")
        candidate["撤桥时刻"] = values.get("撤桥时刻")
        issues = row_issues(candidate)
        if issues:
            return None, issues
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update(candidate)
        for extra in ("操作人员", "对接结果"):
            if str(values.get(extra) or "").strip():
                entry[extra] = values.get(extra)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return annotate(entry), []

    def run_action(
        self, entry_id: int, action: str
    ) -> tuple[dict[str, Any] | None, str, bool]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"对接任务 {entry_id} 不存在或已归档", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于廊桥对接可执行范围", False
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里", False
        # 数据本身有问题的记录一律拦住状态流转，先把问题修掉再操作
        issues = row_issues(entry)
        if issues:
            return annotate(entry), f"数据存在问题（{describe_issues(issues)}），不能{action}", False
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return annotate(entry), f"对接任务已{action}", True
