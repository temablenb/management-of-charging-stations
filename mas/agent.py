"""Базовый класс агента."""
from mas.bus import MessageBus
from mas.messages import Message


class BaseAgent:
    """Агент регистрируется на шине и общается только через неё."""

    def __init__(self, agent_id: str, bus: MessageBus) -> None:
        self.agent_id = agent_id
        self.bus = bus
        bus.register(agent_id)

    def send(self, message: Message) -> None:
        if message.sender != self.agent_id:
            raise ValueError("Агент может отправлять сообщения только от своего имени")
        self.bus.send(message)

    def begin_tick(self, tick: int) -> None:
        """Начало такта: агент проявляет инициативу. Переопределяется наследниками."""

    def handle(self, message: Message) -> None:
        """Обработка одного входящего сообщения."""
        raise NotImplementedError(
            f"{type(self).__name__} не умеет обрабатывать {message.type.value}"
        )

    def process_inbox(self) -> int:
        """Обрабатывает все сообщения из ящика, возвращает их число."""
        messages = self.bus.receive(self.agent_id)
        for message in messages:
            self.handle(message)
        return len(messages)

    def end_tick(self, tick: int) -> None:
        """Конец такта: подведение итогов. Переопределяется наследниками."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.agent_id!r})"