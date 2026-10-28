"""Verify a reviewed pinned-dataset preview without accessing application databases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.pinned_dataset_preview import (  # noqa: E402
    DEFAULT_LOCK_PATH,
    DEFAULT_MAX_FILE_BYTES,
    validate_reviewed_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="重新校验已审阅预览及固定 JSON 文件；不会连接或写入应用数据库。"
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH, help="来源/文件/SHA-256 锁定清单")
    parser.add_argument("--report", type=Path, required=True, help="只读预览报告 JSON")
    parser.add_argument("--approval", type=Path, required=True, help="人工审阅批准记录 JSON")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    try:
        with httpx.Client(
            timeout=httpx.Timeout(args.timeout),
            follow_redirects=False,
            headers={"User-Agent": "knowledge-agent-dataset-review/1.0"},
        ) as client:
            result = validate_reviewed_manifest(
                args.lock,
                args.report,
                args.approval,
                client,
                max_bytes=args.max_bytes,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("校验通过；本命令未连接或写入应用数据库，也未请求媒体 URL。")
        return 0
    except Exception as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        print("未连接或写入应用数据库；未请求媒体 URL。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
