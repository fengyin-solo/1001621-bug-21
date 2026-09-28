"""廊桥对接接口：维护对接任务，覆盖开始对接、确认撤离、取消对接等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.bridge import (
    FILTER_FIELDS,
    LIST_FIELDS,
    BridgeService,
)

router = APIRouter(prefix="/api/bridge", tags=["廊桥对接"])

service = BridgeService()


def _collect_filters(params: dict[str, str | None]) -> dict[str, str]:
    """收拢页面筛选条上的字段参数，空串直接忽略，保证列表与导出口径一致。"""
    return {field: value for field in FILTER_FIELDS if (value := (params.get(field) or "").strip())}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按对接单号检索"),
    status: str | None = Query(default=None, description="待对接、对接中、已撤离、已取消"),
    对接单号: str | None = Query(default=None, description="按对接单号检索"),
    关联航班: str | None = Query(default=None, description="按关联航班检索"),
    廊桥编号: str | None = Query(default=None, description="按廊桥编号检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按对接单号、关联航班、廊桥编号与状态过滤廊桥对接列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    filters = _collect_filters({"对接单号": 对接单号, "关联航班": 关联航班, "廊桥编号": 廊桥编号})
    items, total = service.list_entries(keyword=keyword, status=status, filters=filters, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：/export 必须排在 /{entry_id} 前面，否则会被当成 entry_id 解析失败。
@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按对接单号检索"),
    status: str | None = Query(default=None, description="待对接、对接中、已撤离、已取消"),
    对接单号: str | None = Query(default=None, description="按对接单号检索"),
    关联航班: str | None = Query(default=None, description="按关联航班检索"),
    廊桥编号: str | None = Query(default=None, description="按廊桥编号检索"),
) -> dict[str, Any]:
    """导出廊桥对接清单：与列表使用同一套筛选口径，返回当前过滤条件下的全量数据。"""
    filters = _collect_filters({"对接单号": 对接单号, "关联航班": 关联航班, "廊桥编号": 廊桥编号})
    items, total = service.list_entries(keyword=keyword, status=status, filters=filters, page=1, size=10000)
    return {"module": "bridge", "total": total, "fields": LIST_FIELDS, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条对接任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"对接任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条对接任务，字段缺失或时刻颠倒时逐条说明原因而不是静默丢弃。"""
    entry, issues = service.create_entry(payload.values)
    if issues:
        return ActionResult(ok=False, message="对接任务登记失败：" + "、".join(issues))
    return ActionResult(ok=True, message="对接任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条对接任务执行开始对接、确认撤离、取消对接；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
