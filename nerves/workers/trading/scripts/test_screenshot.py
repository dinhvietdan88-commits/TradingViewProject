import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from mcp_client import get_mcp_client
import config


async def main():
    print(f"MCP_ENABLED config: {config.MCP_ENABLED}")
    client = get_mcp_client()
    print("Capturing screenshot...")
    result = await client.capture_screenshot("BTCUSDT", "240", "chart")
    print(f"Screenshot result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
