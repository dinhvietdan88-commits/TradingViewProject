import asyncio
import sys
from pathlib import Path

# Add server to path
sys.path.append(str(Path(__file__).parent.parent))

import config
from mcp_client import get_mcp_client


async def main():
    print(f"MCP_ENABLED config: {config.MCP_ENABLED}")
    client = get_mcp_client()
    print("Checking health...")
    result = await client.health_check()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
