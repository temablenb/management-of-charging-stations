"""Station Agent: управляет одной станцией, принимает заявки и ведёт очередь."""
from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.charging_queue import ChargingQueue, Order
from mas.grid_agent import GRID_ID
from mas.messages import ChargeRequest, Message
from mas.scenario import StationConfig

REJECT_CONNECTOR = "connector_mismatch"
REJECT_DUPLICATE = "duplicate"


class StationAgent(BaseAgent):
    def __init__(
        self,
        bus: MessageBus,
        config: StationConfig,
        grid_id: str = GRID_ID,
    ) -> None:
        super().__init__(config.station_id, bus)
        self.config = config
        self.grid_id = grid_id
        self.queue = ChargingQueue(config.slots)
        self.current_tick = 0
        # отказы: пары (идентификатор автомобиля, причина); отдельного сообщения-отказа нет,
        # автомобиль заранее выбирает станцию с подходящим разъёмом
        self.rejected: list[tuple[str, str]] = []

    @property
    def max_power_kw(self) -> float:
        return self.config.max_power_kw

    @property
    def connector(self) -> str:
        return self.config.connector

    def begin_tick(self, tick: int) -> None:
        self.current_tick = tick
        self.queue.admit(tick)

    def handle(self, message: Message) -> None:
        if isinstance(message, ChargeRequest):
            self._accept(message)
        else:
            super().handle(message)

    def process_inbox(self) -> int:
        count = super().process_inbox()
        if count:
            # новые заявки одного такта распределяются по местам вместе, по приоритету
            self.queue.admit(self.current_tick)
        return count

    def _accept(self, request: ChargeRequest) -> None:
        if request.tick != self.current_tick:
            raise ValueError(
                f"Заявка от {request.sender} относится к такту {request.tick}, "
                f"а текущий такт {self.current_tick}"
            )
        if request.connector != self.config.connector:
            self.rejected.append((request.sender, REJECT_CONNECTOR))
            return
        if request.sender in self.queue:
            self.rejected.append((request.sender, REJECT_DUPLICATE))
            return
        self.queue.add(Order.from_request(request))