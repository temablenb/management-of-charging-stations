"""Шина сообщений: доставка сообщений между агентами и журнал обмена."""
from mas.messages import Message


class UnknownAgentError(KeyError):
    """Отправитель или получатель не зарегистрирован на шине."""


class MessageBus:
    def __init__(self) -> None:
        self._inboxes: dict[str, list[Message]] = {}

    def register(self, agent_id: str) -> None:
        if agent_id in self._inboxes:
            raise ValueError(f"Агент {agent_id} уже зарегистрирован")
        self._inboxes[agent_id] = []

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._inboxes

    @property
    def agents(self) -> tuple[str, ...]:
        return tuple(self._inboxes)