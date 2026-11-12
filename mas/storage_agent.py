"""Energy Storage Agent: накопитель заряжается ночью и отдаёт энергию в сеть в пик.

КПД относится к каждому направлению: в накопитель попадает мощность * КПД, а для
отдачи из него списывается мощность / КПД (потери в обе стороны).
Единицы измерения: мощность в кВт, энергия в кВт·ч, время в тактах.
"""
from mas.agent import BaseAgent
from mas.bus import MessageBus
from mas.charging_plan import TICK_HOURS
from mas.scenario import StorageConfig
from mas.tariff import NIGHT, PEAK, time_zone

STORAGE_ID = "storage"
MIN_SOC = 0.10
MAX_SOC = 0.95

CHARGE_PRIORITY = 0.5

CHARGE = "charge"
DISCHARGE = "discharge"
IDLE = "idle"


def mode_for_tick(tick: int) -> str:
    """Режим по тарифной зоне: ночью заряд, в пик готовность к отдаче, днём покой."""
    zone = time_zone(tick)
    if zone == NIGHT:
        return CHARGE
    if zone == PEAK:
        return DISCHARGE
    return IDLE


class StorageAgent(BaseAgent):
    def __init__(
        self,
        bus: MessageBus,
        config: StorageConfig,
        agent_id: str = STORAGE_ID,
        min_soc: float = MIN_SOC,
        max_soc: float = MAX_SOC,
    ) -> None:
        if not 0.0 <= min_soc < max_soc <= 1.0:
            raise ValueError("Должно выполняться 0 <= min_soc < max_soc <= 1")
        super().__init__(agent_id, bus)
        self.config = config
        self.min_soc = min_soc
        self.max_soc = max_soc
        self.energy_kwh = min(max(config.initial_soc, min_soc), max_soc) * config.capacity_kwh
        self.charged_kwh = 0.0
        self.discharged_kwh = 0.0

    @property
    def soc(self) -> float:
        return self.energy_kwh / self.config.capacity_kwh

    @property
    def min_energy_kwh(self) -> float:
        return self.min_soc * self.config.capacity_kwh

    @property
    def max_energy_kwh(self) -> float:
        return self.max_soc * self.config.capacity_kwh

    def max_charge_kw(self) -> float:
        """Сколько мощности накопитель может взять из сети в этом такте."""
        room = self.max_energy_kwh - self.energy_kwh
        limit = room / (TICK_HOURS * self.config.efficiency)
        return max(0.0, min(self.config.max_power_kw, limit))

    def max_discharge_kw(self) -> float:
        """Сколько мощности накопитель может отдать в сеть в этом такте."""
        available = self.energy_kwh - self.min_energy_kwh
        limit = available * self.config.efficiency / TICK_HOURS
        return max(0.0, min(self.config.max_power_kw, limit))

    def charge(self, power_kw: float) -> float:
        """Заряжает накопитель за один такт, возвращает принятую из сети мощность."""
        if power_kw < 0:
            raise ValueError("Мощность не может быть отрицательной")
        accepted = min(power_kw, self.max_charge_kw())
        stored = accepted * TICK_HOURS * self.config.efficiency
        self.energy_kwh += stored
        self.charged_kwh += accepted * TICK_HOURS
        return accepted

    def discharge(self, power_kw: float) -> float:
        """Разряжает накопитель за один такт, возвращает отданную в сеть мощность."""
        if power_kw < 0:
            raise ValueError("Мощность не может быть отрицательной")
        delivered = min(power_kw, self.max_discharge_kw())
        self.energy_kwh -= delivered * TICK_HOURS / self.config.efficiency
        self.discharged_kwh += delivered * TICK_HOURS
        return delivered