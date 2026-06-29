# Memo MCP Server 启动脚本
# 用法: python scripts/run_mcp.py

import sys
from pathlib import Path

# 确保项目路径在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from memo.mcp.server import main

if __name__ == "__main__":
    main()
