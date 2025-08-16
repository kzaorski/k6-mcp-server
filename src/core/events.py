"""
Event system for K6 MCP Server.

Provides a simple event-driven architecture for loose coupling
between components and enabling extensibility.
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, TypeVar
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

T = TypeVar('T')


class EventType(str, Enum):
    """Event types in the system."""
    TEST_PREPARED = "test_prepared"
    TEST_STARTED = "test_started"
    TEST_COMPLETED = "test_completed"
    TEST_FAILED = "test_failed"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    RESULT_SAVED = "result_saved"
    HEALTH_CHECK = "health_check"
    CONFIGURATION_LOADED = "configuration_loaded"


@dataclass
class Event:
    """Event data structure."""
    event_type: EventType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def __post_init__(self):
        """Ensure event has a correlation ID."""
        if not self.correlation_id:
            import uuid
            self.correlation_id = str(uuid.uuid4())


class EventBus:
    """
    Simple event bus for publishing and subscribing to events.
    
    Provides async event handling with error isolation to prevent
    one subscriber's failure from affecting others.
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._event_history: List[Event] = []
        self._max_history = 1000
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], Any]) -> None:
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], Any]) -> None:
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass  # Handler not found
    
    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Add to history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        # Notify subscribers
        if event.event_type in self._subscribers:
            tasks = []
            for handler in self._subscribers[event.event_type]:
                # Create task for each handler to prevent blocking
                task = asyncio.create_task(self._safe_call_handler(handler, event))
                tasks.append(task)
            
            # Wait for all handlers to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _safe_call_handler(self, handler: Callable[[Event], Any], event: Event) -> None:
        """Safely call an event handler with error isolation."""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
        except Exception as e:
            # Log error but don't propagate to prevent affecting other handlers
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in event handler {handler.__name__}: {e}", exc_info=True)
    
    def get_recent_events(self, event_type: EventType = None, limit: int = 100) -> List[Event]:
        """Get recent events, optionally filtered by type."""
        events = self._event_history
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return events[-limit:]
    
    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()
    
    def get_subscriber_count(self, event_type: EventType) -> int:
        """Get number of subscribers for an event type."""
        return len(self._subscribers.get(event_type, []))


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


async def publish_event(event_type: EventType, data: Dict[str, Any] = None, source: str = None) -> None:
    """Convenience function to publish an event."""
    event = Event(
        event_type=event_type,
        data=data or {},
        source=source
    )
    await get_event_bus().publish(event)


def subscribe_to_event(event_type: EventType):
    """Decorator for subscribing to events."""
    def decorator(func: Callable[[Event], Any]):
        get_event_bus().subscribe(event_type, func)
        return func
    return decorator