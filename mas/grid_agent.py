"""Grid Agent: знает лимит подстанции и распределяет мощность между станциями."""
from dataclasses import dataclass
from mas.agent import BaseAgent
from mas.allocation import (
    MIN_SHARE,
    AllocationInfeasible,
    AllocationResult,
    allocate_power,
    allocate_proportional,
)
from mas.bus import MessageBus
from mas.messages import (
    Message,
    PowerAllocation,
    PowerRequest,
    StorageDispatch,
    StorageOffer,
)
from mas.tariff import (
    DEFAULT_MAX_MULT,
    DEFAULT_MIN_MULT,
    pressure_from_forecast,
    tariff_multiplier,
)

GRID_ID = "grid"


@dataclass(frozen=True)
class GridDecision:
    """Решение Grid Agent за один такт (для журнала и визуализации)."""

    tick: int
    substation_limit_kw: float
    storage_kw: float
    requested_kw: float
    allocated_kw: dict[str, float]
    multipliers: dict[str, float]
    deficit: bool
    fallback: bool

    @property
    def total_allocated_kw(self) -> float:
        return sum(self.allocated_kw.values())

    @property
    def storage_used_kw(self) -> float:
        """Часть мощности, которую покрыл накопитель сверх лимита подстанции."""
        excess = max(0.0, self.total_allocated_kw - self.substation_limit_kw)
        return min(self.storage_kw, excess)


class GridAgent(BaseAgent):
    def __init__(
        self,
        bus: MessageBus,
        limit_kw: float,
        agent_id: str = GRID_ID,
            min_share: float = MIN_SHARE,
            tariff_min_mult: float = DEFAULT_MIN_MULT,
            tariff_max_mult: float = DEFAULT_MAX_MULT,
    ) -> None:
        if limit_kw <= 0:
            raise ValueError("Лимит подстанции должен быть положительным")
        if not 0.0 <= min_share <= 1.0:
            raise ValueError("Гарантированная доля должна быть от 0 до 1")
        if not 0 < tariff_min_mult < tariff_max_mult:
            raise ValueError("Должно выполняться 0 < минимальный множитель < максимальный")
        super().__init__(agent_id, bus)
        self.limit_kw = limit_kw
        self.min_share = min_share
        self.tariff_min_mult = tariff_min_mult
        self.tariff_max_mult = tariff_max_mult
        self.current_tick = 0
        self._requests: dict[str, PowerRequest] = {}
        self._storage_offer: StorageOffer | None = None
        self._decisions: list[GridDecision] = []

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
    def decisions(self) -> tuple[GridDecision, ...]:
        """Журнал решений по тактам."""
        return tuple(self._decisions)

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

    def send_allocations(
        self,
        result: AllocationResult,
        multipliers: dict[str, float] | None = None,
    ) -> None:
        """Отправляет каждой станции выделенную мощность и тарифный множитель.

        Если множитель станции не задан, используется 1.0 (базовый тариф).
        """
        multipliers = multipliers or {}
        for station, power in result.allocated_kw.items():
            self.send(PowerAllocation(
                sender=self.agent_id,
                receiver=station,
                tick=self.current_tick,
                allocated_kw=power,
                tariff_multiplier=multipliers.get(station, 1.0),
            ))

    def compute_multipliers(self, result: AllocationResult) -> dict[str, float]:
        """Тарифный множитель каждой станции: нагрузка, прогноз, недопоставка и время суток."""
        total_demand = sum(r.demand_kw for r in self._requests.values())
        network_ratio = total_demand / self.effective_limit_kw
        multipliers = {}
        for station, request in self._requests.items():
            cap = min(request.demand_kw, request.max_power_kw)
            allocated = result.allocated_kw.get(station, 0.0)
            curtailment = 1.0 - allocated / cap if cap > 0 else 0.0
            multipliers[station] = tariff_multiplier(
                self.current_tick,
                cap / request.max_power_kw,
                network_ratio,
                pressure_from_forecast(request.forecast_kw, request.max_power_kw),
                curtailment,
                self.tariff_min_mult,
                self.tariff_max_mult,
            )
        return multipliers

    def run_allocation(self) -> AllocationResult:
        """Рассчитывает распределение, рассылает его станциям и пишет решение в журнал.

        Вызывается один раз за такт, когда все запросы уже получены.
        """
        result = self.compute_allocation()
        multipliers = self.compute_multipliers(result)
        self.send_allocations(result, multipliers)
        if self._storage_offer is not None:
            used_kw = min(self.storage_kw, max(0.0, result.total_kw - self.limit_kw))
            self.send(StorageDispatch(
                sender=self.agent_id, receiver=self._storage_offer.sender,
                tick=self.current_tick, discharge_kw=used_kw,
            ))
        self._decisions.append(GridDecision(
            tick=self.current_tick,
            substation_limit_kw=self.limit_kw,
            storage_kw=self.storage_kw,
            requested_kw=sum(r.demand_kw for r in self._requests.values()),
            allocated_kw=dict(result.allocated_kw),
            multipliers=multipliers,
            deficit=result.deficit,
            fallback=result.fallback,
        ))
        return result