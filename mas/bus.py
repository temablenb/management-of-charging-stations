"""Шина сообщений: доставка сообщений между агентами и журнал обмена."""
from mas.messages import Message


class UnknownAgentError(KeyError):
    """Отправитель или получатель не зарегистрирован на шине."""


class MessageBus:
    def __init__(self) -> None:
        self._inboxes: dict[str, list[Message]] = {}
        self._pending: list[Message] = []

    def register(self, agent_id: str) -> None:
        if agent_id in self._inboxes:
            raise ValueError(f"Агент {agent_id} уже зарегистрирован")
        self._inboxes[agent_id] = []

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._inboxes

    @property
    def agents(self) -> tuple[str, ...]:
        return tuple(self._inboxes)

    def send(self, message: Message) -> None:
        for agent_id in (message.sender, message.receiver):
            if agent_id not in self._inboxes:
                raise UnknownAgentError(agent_id)
        self._pending.append(message)

    def deliver(self) -> int:
        """Переносит ожидающие сообщения в ящики адресатов, возвращает их число."""
        delivered = self._pending
        self._pending = []
        for message in delivered:
            self._inboxes[message.receiver].append(message)
        return len(delivered)

    def receive(self, agent_id: str) -> list[Message]:
        """Отдаёт все сообщения из ящика агента и очищает его."""
        if agent_id not in self._inboxes:
            raise UnknownAgentError(agent_id)
        messages = self._inboxes[agent_id]
        self._inboxes[agent_id] = []
        return messages

    @property
    def pending_count(self) -> int:
        return len(self._pending)