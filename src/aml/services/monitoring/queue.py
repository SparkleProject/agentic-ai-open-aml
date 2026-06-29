import logging
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class MonitoringQueue:
    def __init__(self, *, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._fallback_queue: deque[dict[str, str]] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._fallback_queue)

    async def publish(self, *, transaction_id: str, tenant_id: str) -> None:
        message = {"transaction_id": transaction_id, "tenant_id": tenant_id}
        self._fallback_queue.append(message)

    async def consume_once(
        self,
        handler: Callable[[dict[str, str]], Coroutine[Any, Any, None]],
    ) -> None:
        if self._fallback_queue:
            message = self._fallback_queue.popleft()
            await handler(message)
