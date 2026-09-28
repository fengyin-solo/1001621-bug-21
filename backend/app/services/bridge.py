"""廊桥对接业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "bridge"
REQUIRED_FIELDS = ["对接单号", "关联航班", "廊桥编号"]
LIST_FIELDS = ["对接单号", "关联航班", "廊桥编号", "对接时刻", "撤桥时刻", "操作人员", "对接结果", "对接状态"]
# 列表上允许按列检索的字段（对接时刻等不做模糊检索）
FILTER_FIELDS = ["对接单号", "关联航班", "廊桥编号"]
STATUS_ORDER = ["待对接", "对接中", "已撤离", "已取消"]
ACTION_RULES = {"开始对接": "对接中", "确认撤离": "已撤离", "取消对接": "已取消"}
NEGATIVE_ACTIONS = []

TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d")


def clean_text(value: Any) -> str:
    """把任意字段值归一成去空白的字符串，None 也算缺失。"""
    if value is None:
        return ""
    return str(value).strip()


def parse_time(value: Any) -> datetime | None:
    """尝试把时刻字段解析成可比较的时间；无法解析时返回 None，由调用方决定是否算问题。"""
    text = clean_text(value)
    if not text:
        return None
    for pattern in TIME_FORMATS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def check_row(row: dict[str, Any]) -> list[str]:
    """逐条体检：字段缺失、撤桥时刻早于对接时刻都点出来；没解析成时间的样例文本不误报。"""
    issues: list[str] = []
    for field in REQUIRED_FIELDS:
        if not clean_text(row.get(field)):
            issues.append(f"{field}缺失")
    start_at = parse_time(row.get("对接时刻"))
    end_at = parse_time(row.get("撤桥时刻"))
    if start_at is not None and end_at is not None and end_at < start_at:
        issues.append("撤桥时刻早于对接时刻")
    return issues


def decorate(row: dict[str, Any]) -> dict[str, Any]:
    """返回带体检结论的浅拷贝，原记录不改动，列表、明细、导出口径保持一致。"""
    view = dict(row)
    issues = check_row(view)
    view["数据异常"] = "；".join(issues)
    return view


def matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    for field, keyword in filters.items():
        if field not in FILTER_FIELDS:
            continue
        keyword = clean_text(keyword)
        if not keyword:
            continue
        if keyword not in clean_text(row.get(field)):
            return False
    return True


class BridgeService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        filters: dict[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        active_filters: dict[str, str] = {}
        if filters:
            active_filters.update({k: clean_text(v) for k, v in filters.items() if clean_text(v)})
        if keyword:  # 兼容旧的单关键字参数
            active_filters.setdefault("对接单号", clean_text(keyword))
        if active_filters:
            rows = [row for row in rows if matches(row, active_filters)]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        views = [decorate(row) for row in rows]
        start = max(page - 1, 0) * size
        return views[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return decorate(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记对接任务：必填字段缺失或时刻颠倒都拒绝，并逐条给出原因，绝不悄悄丢数据。"""
        missing = [f"{field}缺失" for field in REQUIRED_FIELDS if not clean_text(values.get(field))]
        time_issues: list[str] = []
        start_at = parse_time(values.get("对接时刻"))
        end_at = parse_time(values.get("撤桥时刻"))
        start_text = clean_text(values.get("对接时刻"))
        end_text = clean_text(values.get("撤桥时刻"))
        if start_text and start_at is None:
            time_issues.append(f"对接时刻无法识别：{start_text}")
        if end_text and end_at is None:
            time_issues.append(f"撤桥时刻无法识别：{end_text}")
        if start_at is not None and end_at is not None and end_at < start_at:
            time_issues.append("撤桥时刻早于对接时刻")
        issues = missing + time_issues
        if issues:
            return None, issues
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return decorate(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"对接任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于廊桥对接可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return decorate(entry), f"对接任务已{action}"
