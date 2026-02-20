"""Feature flags API endpoint for clients."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.features import get_feature_flags
from backend.api.shared import config

router = APIRouter(prefix="/api/v1")


@router.get("/features")
async def get_features() -> JSONResponse:
    """Get feature flags status for clients.

    Returns:
        JSONResponse with feature flags information including enabled status
        and "coming_soon" indicators for UI display

    Example response:
        {
            "security_risk_assessment": {
                "enabled": false,
                "coming_soon": true,
                "tier": "pro",
                "description": "Security risk assessment for agent actions"
            }
        }
    """
    feature_flags = get_feature_flags(config)
    flags_for_ui = feature_flags.get_flags_for_ui()
    return JSONResponse(flags_for_ui)
