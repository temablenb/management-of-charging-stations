"""Station Agent: управляет одной станцией, принимает заявки и ведёт очередь."""
from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.charging_plan import (
    EPS,
    build_schedule,
    energy_per_tick,
    expected_finish_tick,
    max_useful_power,
    split_power,
)
from mas.charging_queue import ChargingQueue, Order
from mas.clock import TICKS_PER_HOUR, hour_of_tick
from mas.forecast import DEFAULT_HORIZON, forecast_load, peak_hours
from mas.grid_agent import GRID_ID
from mas.messages import ChargePlan, ChargeRequest, Message, PowerRequest
from mas.scenario import StationConfig

REJECT_CONNECTOR = "connector_mismatch"
REJECT_DUPLICATE = "duplicate"


class StationAgent(BaseAgent):
    def __init__(
            self,
            bus: MessageBus,
            config: StationConfig,
            grid_id: str = GRID_ID,
            base_tariff_rub: float = 10.0,
    ) -> None:
        if base_tariff_rub <= 0:
            raise ValueError("Базовый тариф должен быть положительным")
        super().__init__(config.station_id, bus)
        self.config = config
        self.grid_id = grid_id
        self.queue = ChargingQueue(config.slots)
        self.current_tick = 0
        # отказы: пары (идентификатор автомобиля, причина); отдельного сообщения-отказа нет,
        # автомобиль заранее выбирает станцию с подходящим разъёмом
        self.rejected: list[tuple[str, str]] = []
        self.last_powers: dict[str, float] = {}
        self.delivered_kwh = 0.0
        self.completed: list[Order] = []
        self.base_tariff_rub = base_tariff_rub
        self.tariff_multiplier = 1.0
        self.hourly_history: list[float] = []
        self._hour_buffer: list[float] = []

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

    def allocate(self, available_kw: float) -> dict[str, float]:
        """Делит доступную мощность между заряжающимися автомобилями."""
        available_kw = min(available_kw, self.config.max_power_kw)
        self.last_powers = split_power(self.queue.active, available_kw)
        return dict(self.last_powers)

    def make_plans(self, available_kw: float) -> list[ChargePlan]:
        """Планы для всех автомобилей станции: заряжающиеся получают расписание, ждущие нет."""
        powers = self.allocate(available_kw)
        plans = []
        for order in self.queue.active:
            power = powers[order.ev_id]
            plans.append(ChargePlan(
                sender=self.agent_id, receiver=order.ev_id, tick=self.current_tick,
                schedule_kw=build_schedule(order.remaining_kwh, power),
                expected_finish_tick=expected_finish_tick(
                    order.remaining_kwh, power, self.current_tick
                ),
                queue_position=0,
            ))
        for order in self.queue.waiting(self.current_tick):
            plans.append(ChargePlan(
                sender=self.agent_id, receiver=order.ev_id, tick=self.current_tick,
                schedule_kw=(), expected_finish_tick=None,
                queue_position=self.queue.position(order.ev_id, self.current_tick),
            ))
        return plans

    def send_plans(self, available_kw: float) -> list[ChargePlan]:
        plans = self.make_plans(available_kw)
        for plan in plans:
            self.send(plan)
        return plans

    def advance(self, powers: dict[str, float] | None = None,
                price_per_kwh: float = 0.0) -> list[Order]:
        """Один такт зарядки: списывает энергию, начисляет стоимость, убирает завершивших."""
        powers = self.last_powers if powers is None else powers
        completed = []
        for order in self.queue.active:
            energy = min(energy_per_tick(powers.get(order.ev_id, 0.0)), order.remaining_kwh)
            order.remaining_kwh = max(0.0, order.remaining_kwh - energy)
            order.cost_rub += energy * price_per_kwh
            self.delivered_kwh += energy
            if order.remaining_kwh <= EPS:
                order.remaining_kwh = 0.0
                order.finish_tick = self.current_tick + 1
                completed.append(order)
        for order in completed:
            self.queue.remove(order.ev_id)
            self.completed.append(order)
        return completed

    def record_load(self, tick: int, load_kw: float) -> None:
        """Записывает нагрузку такта; по окончании часа в историю идёт среднее за час."""
        if load_kw < 0:
            raise ValueError("Нагрузка не может быть отрицательной")
        self._hour_buffer.append(load_kw)
        if (tick + 1) % TICKS_PER_HOUR == 0:
            self.hourly_history.append(sum(self._hour_buffer) / len(self._hour_buffer))
            self._hour_buffer.clear()

    def seed_history(self, hourly_kw) -> None:
        """Добавляет предысторию (почасовые значения, кВт) перед началом симуляции.

        Последнее значение должно относиться к часу, предшествующему первому часу симуляции.
        """
        values = [float(value) for value in hourly_kw]
        if any(value < 0 for value in values):
            raise ValueError("Нагрузка не может быть отрицательной")
        self.hourly_history.extend(values)

    def build_forecast(self, horizon: int = DEFAULT_HORIZON,
                       temperatures=None) -> tuple[float, ...]:
        """Прогноз нагрузки станции на horizon часов, начиная с текущего часа."""
        return forecast_load(
            self.hourly_history, horizon, self.config.max_power_kw, temperatures
        )

    def forecast_peak_hours(self, forecast: tuple[float, ...]) -> tuple[int, ...]:
        """Часы суток, в которые ожидается пик нагрузки по переданному прогнозу."""
        return peak_hours(forecast, hour_of_tick(self.current_tick))

    @property
    def price_per_kwh(self) -> float:
        """Текущая цена, руб/кВт·ч: базовый тариф на множитель от Grid Agent."""
        return self.base_tariff_rub * self.tariff_multiplier

    def station_priority(self) -> float:
        """Вес станции для Grid Agent: от 1 (очереди нет) до 2 (очередь не меньше числа мест)."""
        return 1.0 + min(1.0, self.queue.waiting_count / self.config.slots)

    def demand_kw(self) -> float:
        """Потребность станции: сумма полезных мощностей заряжающихся, но не больше мощности станции."""
        total = sum(max_useful_power(order) for order in self.queue.active)
        return min(total, self.config.max_power_kw)

    def send_power_request(self, forecast_horizon: int = DEFAULT_HORIZON) -> PowerRequest:
        """Отправляет Grid Agent потребность, прогноз нагрузки и приоритет станции."""
        request = PowerRequest(
            sender=self.agent_id,
            receiver=self.grid_id,
            tick=self.current_tick,
            demand_kw=self.demand_kw(),
            max_power_kw=self.config.max_power_kw,
            forecast_kw=self.build_forecast(forecast_horizon),
            priority=self.station_priority(),
        )
        self.send(request)
        return request