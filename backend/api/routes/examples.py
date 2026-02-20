"""OpenAPI Examples for API Documentation.

Provides example requests/responses for Swagger UI and ReDoc.
Makes API documentation interactive and helpful for developers.
"""

# Settings endpoint examples
SETTINGS_EXAMPLES = {
    "basic_settings": {
        "summary": "Basic configuration",
        "description": "Minimal settings for getting started",
        "value": {
            "llm": {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "api_key": "sk-ant-...",
                "temperature": 0.1,
            },
            "agent": {"name": "Orchestrator"},
        },
    },
    "advanced_settings": {
        "summary": "Advanced configuration",
        "description": "Full settings with all options",
        "value": {
            "llm": {
                "model": "anthropic/claude-3-5-sonnet-20241022",
                "api_key": "sk-ant-...",
                "temperature": 0.1,
                "max_output_tokens": 8192,
                "timeout": 180,
            },
            "agent": {
                "name": "Orchestrator",
                "max_iterations": 100,
                "enable_enhanced_context": True,
            },
            "security": {"confirmation_mode": True, "security_analyzer": "default"},
        },
    },
}

# Conversation creation examples
CONVERSATION_EXAMPLES = {
    "simple_conversation": {
        "summary": "Simple code task",
        "description": "Create a basic conversation for a coding task",
        "value": {
            "initial_query": "Create a Python function to calculate fibonacci numbers"
        },
    },
    "with_repository": {
        "summary": "Repository task",
        "description": "Work with a specific repository",
        "value": {
            "repository": "owner/repo",
            "git_provider_token": "***",
            "initial_query": "Add unit tests to the main.py file",
        },
    },
}

# File operation examples
FILE_UPLOAD_EXAMPLES = {
    "single_file": {
        "summary": "Upload single file",
        "description": "Upload one file to workspace",
        "value": {
            "file": "requirements.txt",
            "content": "flask==3.0.0\nrequests==2.31.0",
        },
    },
    "multiple_files": {
        "summary": "Upload multiple files",
        "description": "Upload multiple files at once",
        "value": {
            "files": [
                {"file": "app.py", "content": "print('Hello')"},
                {"file": "requirements.txt", "content": "flask==3.0.0"},
            ]
        },
    },
}

# Error response examples
ERROR_EXAMPLES = {
    "rate_limit_error": {
        "summary": "Rate limit exceeded",
        "value": {
            "title": "Too many requests",
            "message": "You're sending requests too quickly...",
            "severity": "warning",
            "category": "rate_limit",
            "icon": "⏰",
            "actions": [
                {"label": "Retry", "type": "retry"},
                {"label": "Upgrade", "type": "upgrade"},
            ],
        },
    },
    "authentication_error": {
        "summary": "Authentication required",
        "value": {
            "title": "Please sign in again",
            "message": "Your session has expired...",
            "severity": "warning",
            "category": "authentication",
            "icon": "🔒",
        },
    },
    "validation_error": {
        "summary": "Invalid request",
        "value": {
            "title": "Invalid request data",
            "message": "Some fields are missing or incorrect...",
            "severity": "error",
            "category": "user_input",
            "icon": "📝",
        },
    },
}

# Success response examples
SUCCESS_EXAMPLES = {
    "conversation_created": {
        "summary": "Conversation created successfully",
        "value": {
            "conversation_id": "abc-123-def-456",
            "status": "active",
            "agent_state": "running",
            "created_at": "2025-11-04T12:00:00Z",
        },
    },
    "settings_saved": {
        "summary": "Settings saved successfully",
        "value": {"status": "success", "message": "Settings saved successfully"},
    },
}

# Metrics response example
METRICS_EXAMPLES = {
    "full_metrics": {
        "summary": "Complete system metrics",
        "value": {
            "system": {
                "timestamp": "2025-11-04T12:00:00Z",
                "active_conversations": 15,
                "total_actions_today": 342,
                "avg_response_time_ms": 450.2,
                "cache_stats": {"hit_rate": 0.73, "total_requests": 1234},
            },
            "agents": [
                {
                    "agent_name": "Orchestrator",
                    "total_actions": 500,
                    "successful_actions": 475,
                    "failed_actions": 25,
                    "success_rate": 0.95,
                    "avg_action_time_ms": 623.4,
                }
            ],
        },
    }
}

# Analytics examples
ANALYTICS_EXAMPLES = {
    "usage_stats_week": {
        "summary": "Weekly usage statistics",
        "value": {
            "period": "week",
            "conversations": 45,
            "messages": 678,
            "cost_usd": 12.34,
            "tokens": {"input": 1500000, "output": 500000},
            "models_used": ["claude-sonnet-4", "gpt-4o", "claude-haiku-4.5"],
        },
    },
    "model_usage": {
        "summary": "Model usage breakdown",
        "value": [
            {
                "model": "claude-sonnet-4-20250514",
                "conversations": 30,
                "cost_usd": 8.50,
                "tokens": 1200000,
                "avg_tokens_per_conversation": 40000,
            },
            {
                "model": "claude-haiku-4-5-20251001",
                "conversations": 15,
                "cost_usd": 1.20,
                "tokens": 600000,
                "avg_tokens_per_conversation": 40000,
            },
        ],
    },
}

# Health check examples
HEALTH_EXAMPLES = {
    "healthy": {
        "summary": "System healthy",
        "value": {
            "status": "healthy",
            "version": "1.0.0-beta",
            "uptime_seconds": 86400,
            "database": "connected",
            "redis": "connected",
            "llm_provider": "anthropic",
            "checks": {"database": "pass", "redis": "pass", "disk_space": "pass"},
        },
    },
    "degraded": {
        "summary": "System degraded",
        "value": {
            "status": "degraded",
            "version": "1.0.0-beta",
            "uptime_seconds": 3600,
            "database": "connected",
            "redis": "disconnected",
            "llm_provider": "anthropic",
            "checks": {"database": "pass", "redis": "fail", "disk_space": "warning"},
            "warnings": [
                "Redis connection lost - using in-memory fallback",
                "Disk space at 85% capacity",
            ],
        },
    },
}

# Model list example
MODEL_LIST_EXAMPLES = {
    "available_models": {
        "summary": "All available models (200+)",
        "value": [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-5-20251001",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-5-2025-08-07",
            "openrouter/anthropic/claude-3.5-sonnet",
            "openrouter/x-ai/grok-4-fast",
            "gemini-2.5-pro",
            "o3-mini",
            "devstral-small-2507",
        ],
    }
}

# Agent list example
AGENT_LIST_EXAMPLES = {
    "available_agents": {
        "summary": "Available agent types",
        "value": ["Orchestrator", "PlannerAgent", "BrowseAgent"],
    }
}

# WebSocket message examples
WEBSOCKET_EXAMPLES = {
    "send_message": {
        "summary": "Send message to agent",
        "value": {
            "type": "message",
            "content": "Build a todo app with React and TypeScript",
        },
    },
    "agent_action": {
        "summary": "Agent action event",
        "value": {
            "type": "action",
            "action": "FileEditAction",
            "path": "src/App.tsx",
            "timestamp": "2025-11-04T12:00:00Z",
        },
    },
    "agent_observation": {
        "summary": "Action result event",
        "value": {
            "type": "observation",
            "content": "File edited successfully",
            "timestamp": "2025-11-04T12:00:05Z",
        },
    },
    "state_change": {
        "summary": "Agent state change",
        "value": {
            "type": "state_change",
            "from": "running",
            "to": "paused",
            "reason": "User requested pause",
            "timestamp": "2025-11-04T12:00:10Z",
        },
    },
}
