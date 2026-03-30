import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("port", "3003")))
    uvicorn.run(
        "app.server.listen:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        loop="asyncio",
        http="h11",  # avoid optional httptools dep for quick local run
        ws="websockets-sansio",
        access_log=False,
    )
