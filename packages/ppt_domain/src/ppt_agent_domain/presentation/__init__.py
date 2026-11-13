"""Versioned PPT task state, HTML rendering, review and editable export."""

from .config import PresentationConfig
from .service import PresentationService
from .tools import make_presentation_tools

__all__ = ["PresentationConfig", "PresentationService", "make_presentation_tools"]
