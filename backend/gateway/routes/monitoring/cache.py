"""Cache and stats routes for monitoring."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/cache/stats")
async def get_cache_stats():
    """Statistics for internal caches."""
    return {
        "hits": 0,
        "misses": 0,
        "hit_rate": 0.0,
        "size": 0,
    }


@router.get("/failures/taxonomy")
async def get_failure_taxonomy():
    """Distribution of failure types encountered by agents."""
    return {
        "schema_validation": 0,
        "timeout": 0,
        "llm_error": 0,
        "runtime_error": 0,
    }


@router.get("/parallel/stats")
async def get_parallel_stats():
    """Statistics for parallel execution features."""
    return {
        "enabled": True,
        "active_tasks": 0,
        "completed_tasks": 0,
        "avg_concurrency": 0.0,
    }
