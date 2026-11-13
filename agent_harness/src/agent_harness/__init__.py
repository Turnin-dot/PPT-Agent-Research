"""Reusable runtime foundation for the PPT Agent backend."""

from .core import Agent, ContextManager, Event, ImageContent, Tool, tool
from .runtime import Harness, HarnessConfig

__all__ = [
    "Agent",
    "ContextManager",
    "Event",
    "Harness",
    "HarnessConfig",
    "ImageContent",
    "Tool",
    "tool",
]

__version__ = "0.1.0"
