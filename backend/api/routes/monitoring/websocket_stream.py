"""WebSocket metrics stream for monitoring."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .metrics import get_metrics

router = APIRouter()


@router.websocket("/ws/metrics")
async def live_metrics_stream(websocket: WebSocket):
    """Real-time metrics stream via WebSocket."""
    await websocket.accept()
    try:
        while True:
            try:
                metrics = await get_metrics()
                await websocket.send_json(metrics.model_dump(mode="json"))
            except Exception as e:
                if isinstance(e, asyncio.CancelledError):
                    raise e
                await websocket.send_json({"error": str(e)})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        try:
            await websocket.close()
        except Exception:
            pass
        raise
    except Exception:
        pass
