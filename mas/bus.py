"""Шина сообщений: доставка сообщений между агентами и журнал обмена."""
from dataclasses import dataclass

from mas.messages import Message, MessageType


@dataclass(frozen=True)
class JournalEntry:
    """Запись журнала: порядковый номер доставки и само сообщение."""

    seq: int
    message: Message


class UnknownAgentError(KeyError):
    """Отправитель или получатель не зарегистрирован на шине."""


class MessageBus:
    def __init__(self) -> None:
        self._inboxes: dict[str, list[Message]] = {}
        self._pending: list[Message] = []
        self._journal: list[JournalEntry] = []

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
            self._journal.append(JournalEntry(len(self._journal) + 1, message))
        return len(delivered)

    def receive(self, agent_id: str) -> list[Message]:
        """Отдаёт все сообщения из ящика агента и очищает его."""
        if agent_id not in self._inboxes:
            raise UnknownAgentError(agent_id)
        messages = self._inboxes[agent_id]
        self._inboxes[agent_id] = []
        return messages

    def filter_journal(
        self,
        *,
        sender: str | None = None,
        receiver: str | None = None,
        message_type: MessageType | None = None,
        from_tick: int | None = None,
        to_tick: int | None = None,
    ) -> list[JournalEntry]:
        """Записи журнала, удовлетворяющие всем заданным условиям."""
        result = []
        for entry in self._journal:
            message = entry.message
            if sender is not None and message.sender != sender:
                continue
            if receiver is not None and message.receiver != receiver:
                continue
            if message_type is not None and message.type != message_type:
                continue
            if from_tick is not None and message.tick < from_tick:
                continue
            if to_tick is not None and message.tick > to_tick:
                continue
            result.append(entry)
        return result

    def count_by_type(self) -> dict[MessageType, int]:
        """Сколько сообщений каждого типа было доставлено."""
        counts: dict[MessageType, int] = {}
        for entry in self._journal:
            message_type = entry.message.type
            counts[message_type] = counts.get(message_type, 0) + 1
        return counts

    def reset(self) -> None:
        """Очищает ящики, очередь и журнал; регистрация агентов сохраняется."""
        for agent_id in self._inboxes:
            self._inboxes[agent_id] = []
        self._pending = []
        self._journal = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def journal(self) -> tuple[JournalEntry, ...]:
        return tuple(self._journal)