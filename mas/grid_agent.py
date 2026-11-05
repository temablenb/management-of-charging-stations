"""Grid Agent: знает лимит подстанции и распределяет мощность между станциями."""
from mas.agent import BaseAgent
from mas.allocation import MIN_SHARE
from mas.bus import MessageBus
from mas.messages import Message, PowerRequest

GRID_ID = "grid"


class GridAgent(BaseAgent):
    def __init__(
        self,
        bus: MessageBus,
        limit_kw: float,
        agent_id: str = GRID_ID,
        min_share: float = MIN_SHARE,
    ) -> None:
        if limit_kw <= 0:
            raise ValueError("Лимит подстанции должен быть положительным")
        if not 0.0 <= min_share <= 1.0:
            raise ValueError("Гарантированная доля должна быть от 0 до 1")
        super().__init__(agent_id, bus)
        self.limit_kw = limit_kw
        self.min_share = min_share
        self.current_tick = 0
        self._requests: dict[str, PowerRequest] = {}

    def handle(self, message: Message) -> None:
        if not isinstance(message, PowerRequest):
            super().handle(message)
            return
        if message.tick != self.current_tick:
            raise ValueError(
                f"Запрос от {message.sender} относится к такту {message.tick}, "
                f"а текущий такт {self.current_tick}"
            )
        # если станция прислала несколько запросов за такт, учитывается последний
        self._requests[message.sender] = message

    @property
    def requests(self) -> dict[str, PowerRequest]:
        """Запросы, полученные в текущем такте, по идентификатору станции."""
        return dict(self._requests)

    def begin_tick(self, tick: int) -> None:
        self.current_tick = tick
        self._requests.clear()