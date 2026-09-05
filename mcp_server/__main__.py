"""MCP 服务器入口（python -m mcp_server stdio|http）。

与旧 `python mcp_server.py stdio` 等价：argparse 参数与行为保持一致。
"""

from . import main

if __name__ == "__main__":
    main()