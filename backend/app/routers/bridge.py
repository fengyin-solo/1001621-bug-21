"""廊桥对接接口：维护对接任务，覆盖开始对接、确认撤离、取消对接等动作。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.bridge import ISSUE_FIELD, BridgeService, describe_issues

router = APIRouter(prefix="/api/bridge", tags=["廊桥对接"])

service = BridgeService()

LIST_FIELDS = ["对接单号", "关联航班", "廊桥编号", "对接时刻", "撤桥时刻", "操作人员", "对接结果", "对接状态"]
STATUSES = ["待对接", "对接中", "已撤离", "已取消"]

# 导出全量时放开列表分页的单页上限；数据都在内存仓库里，不会取不全
EXPORT_SIZE = 100_000
EXPORT_FIELDS = LIST_FIELDS + [ISSUE_FIELD]


def _filters_from_request(request: Request) -> dict[str, str | None]:
    """汇总筛选条件：同时认接口参数名与页面上的中文字段名，口径与列表查询保持一致。"""
    query = request.query_params
    keyword = query.get("keyword") or query.get("对接单号")
    status = query.get("status")
    flight = query.get("flight") or query.get("关联航班")
    bridge_no = query.get("bridge_no") or query.get("廊桥编号")
    return {
        "keyword": keyword or None,
        "status": status or None,
        "flight": flight or None,
        "bridge_no": bridge_no or None,
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按对接单号检索"),
    status: str | None = Query(default=None, description="待对接、对接中、已撤离、已取消"),
    flight: str | None = Query(default=None, description="按关联航班检索"),
    bridge_no: str | None = Query(default=None, description="按廊桥编号检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按对接单号、关联航班、廊桥编号与状态过滤廊桥对接列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    # 页面直接把中文字段名作为查询参数提交，这里合并成统一口径
    raw = _filters_from_request(request)
    items, total = service.list_entries(
        keyword=keyword or raw["keyword"],
        status=status or raw["status"],
        flight=flight or raw["flight"],
        bridge_no=bridge_no or raw["bridge_no"],
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：导出是固定路径，必须放在 /{entry_id} 之前，
# 否则 "export" 会被当成对接单号 id 解析，直接回参数解析错误。
@router.get("/export")
def export_entries(request: Request) -> Response:
    """按当前筛选条件导出全量廊桥对接清单，另存为带 BOM 的 CSV 文件。"""
    filters = _filters_from_request(request)
    items, total = service.list_entries(page=1, size=EXPORT_SIZE, **filters)

    buffer = io.StringIO()
    # UTF-8 BOM，Excel 直接打开中文不乱码
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_FIELDS)
    for item in items:
        writer.writerow([
            "" if item.get(field) is None else item.get(field, "")
            for field in EXPORT_FIELDS
        ])

    headers = {
        "Content-Disposition": "attachment; filename=bridge_export.csv; filename*=UTF-8''%E5%BB%8A%E6%A1%A5%E5%AF%B9%E6%8E%A5%E6%B8%85%E5%8D%95.csv",
        # X-Total 与文件内行数、列表条数使用同一套筛选口径，方便调用方核对
        "X-Total": str(total),
    }
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条对接任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"对接任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条对接任务，缺字段或时刻颠倒时逐条说明原因而不是静默丢弃。"""
    entry, issues = service.create_entry(payload.values)
    if issues:
        return ActionResult(ok=False, message=f"登记被拦截：{describe_issues(issues)}")
    return ActionResult(ok=True, message="对接任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条对接任务执行开始对接、确认撤离、取消对接；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message, ok = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=ok, message=message, entry=entry)
