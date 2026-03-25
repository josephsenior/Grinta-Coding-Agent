"""Aggregate monitoring router that includes all sub-routers."""

from fastapi import APIRouter

from . import cache, cost, health, metrics, prometheus, websocket_stream

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])

# Include sub-routers (no prefix - they use paths relative to this router)
router.include_router(health.router)
router.include_router(metrics.router)
router.include_router(prometheus.router)
router.include_router(cost.router)
router.include_router(cache.router)
router.include_router(websocket_stream.router)
