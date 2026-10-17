import asyncio
import logging
import sys

from .app import login, main

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
logging.getLogger("telethon").setLevel(logging.WARNING)

if len(sys.argv) > 1 and sys.argv[1] == "login":
    asyncio.run(login())
else:
    asyncio.run(main())
