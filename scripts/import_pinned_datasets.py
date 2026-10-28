"""Preview or explicitly apply the approved pinned fitness/nutrition catalog."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.pinned_dataset_import_service import (  # noqa: E402
    build_approved_import_plan,
    import_catalog,
)
from utils.pinned_dataset_preview import DEFAULT_LOCK_PATH, DEFAULT_MAX_FILE_BYTES  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预览或正式导入已批准的固定版本健身/饮食目录。")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--report", type=Path, required=True, help="已审阅的只读预览报告")
    parser.add_argument("--approval", type=Path, required=True, help="人工批准记录")
    parser.add_argument("--apply", action="store_true", help="明确写入 PostgreSQL 目录；默认只构建计划")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


async def _apply(plan, batch_size: int) -> dict:
    from core.database import SessionLocal

    async with SessionLocal() as session:
        return await import_catalog(session, plan, batch_size=batch_size)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size < 1:
        print("错误：--batch-size 必须大于 0", file=sys.stderr)
        return 2
    database_apply_started = False
    try:
        with httpx.Client(
            timeout=httpx.Timeout(args.timeout),
            follow_redirects=False,
            headers={"User-Agent": "knowledge-agent-dataset-import/1.0"},
        ) as client:
            plan = build_approved_import_plan(
                args.lock, args.report, args.approval, client, max_bytes=args.max_bytes
            )
        print(json.dumps({
            "locked_on": plan.locked_on,
            "files": plan.files,
            "importable_records": plan.importable_count,
            "quarantined_or_unapproved_records": plan.skipped_count,
            "database_written": False,
            "media_urls_requested": 0,
        }, ensure_ascii=False, indent=2))
        if not args.apply:
            print("当前为目录导入预览：未连接或写入数据库。需要明确增加 --apply 才会写入 PostgreSQL 目录。")
            return 0
        if plan.importable_count == 0:
            print("错误：没有可正式导入的已批准目录记录；未连接或写入数据库。", file=sys.stderr)
            return 1
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        database_apply_started = True
        result = asyncio.run(_apply(plan, args.batch_size))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("目录导入完成；知识文档和媒体进度仍由后续 3.3/3.4 处理。")
        return 0
    except Exception as exc:
        print(f"导入前置校验失败：{exc}", file=sys.stderr)
        if database_apply_started:
            print("正式写入阶段发生错误；可能已有已提交批次。请查看 kh_dataset_import_progress 后使用相同锁定版本重试。", file=sys.stderr)
        else:
            print("本次没有连接或写入数据库，也没有请求媒体 URL。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
