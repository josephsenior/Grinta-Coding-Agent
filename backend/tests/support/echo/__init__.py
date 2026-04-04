"""Deterministic test agent for end-to-end validation."""

from backend.orchestration.agent import Agent
from backend.tests.support.echo.agent import Echo

Agent.register('Echo', Echo)
