"""
Member 1: Event Publisher Entrypoint Wrapper.
Re-exports EventOutput from member1.events.event_output.
"""

from member1.events.event_output import EventOutput

__all__ = ["EventOutput"]
