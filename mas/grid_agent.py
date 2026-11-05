"""Grid Agent: знает лимит подстанции и распределяет мощность между станциями."""
from mas.agent import BaseAgent
from mas.allocation import (
    MIN_SHARE,
    AllocationInfeasible,
    AllocationResult,
    allocate_power,
    allocate_proportional,
)
from mas.bus import MessageBus
from mas.messages import Message, PowerRequest, StorageOffer

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
        self._storage_offer: StorageOffer | None = None

    def handle(self, message: Message) -> None:
        if isinstance(message, (PowerRequest, StorageOffer)) and message.tick != self.current_tick:
            raise ValueError(
                f"Сообщение от {message.sender} относится к такту {message.tick}, "
                f"а текущий такт {self.current_tick}"
            )
        if isinstance(message, PowerRequest):
            # если станция прислала несколько запросов за такт, учитывается последний
            self._requests[message.sender] = message
        elif isinstance(message, StorageOffer):
            self._storage_offer = message
        else:
            super().handle(message)

    def compute_allocation(self) -> AllocationResult:
        """Делит лимит подстанции между станциями, приславшими запрос в этом такте.

        Если задача линейного программирования неразрешима, мощность делится
        пропорционально запросам, чтобы сеть продолжала работать.
        """
        demands = {s: r.demand_kw for s, r in self._requests.items()}
        max_powers = {s: r.max_power_kw for s, r in self._requests.items()}
        weights = {s: r.priority for s, r in self._requests.items()}
        limit_kw = self.effective_limit_kw
        try:
            return allocate_power(
                demands, max_powers, limit_kw, self.min_share, weights
            )
        except AllocationInfeasible:
            return allocate_proportional(demands, max_powers, limit_kw)

    @property
    def requests(self) -> dict[str, PowerRequest]:
        """Запросы, полученные в текущем такте, по идентификатору станции."""
        return dict(self._requests)

    @property
    def storage_kw(self) -> float:
        """Мощность накопителя, предложенная в этом такте."""
        return self._storage_offer.available_kw if self._storage_offer else 0.0

    @property
    def effective_limit_kw(self) -> float:
        """Лимит подстанции плюс мощность, которую готов отдать накопитель."""
        return self.limit_kw + self.storage_kw

    def begin_tick(self, tick: int) -> None:
        self.current_tick = tick
        self._requests.clear()
        self._storage_offer = None