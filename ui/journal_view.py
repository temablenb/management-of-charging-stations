"""Журнал сообщений между агентами в виде таблицы с фильтрами."""

import pandas as pd

COLUMNS = ["tick", "type", "sender", "receiver"]


def journal_frame(sim) -> pd.DataFrame:
    """Журнал шины: такт, тип сообщения, отправитель, получатель."""
    rows = [
        {
            "tick": entry.message.tick,
            "type": str(getattr(entry.message.type, "value", entry.message.type)),
            "sender": entry.message.sender,
            "receiver": entry.message.receiver,
        }
        for entry in sim.bus.journal
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def filter_journal(
    frame: pd.DataFrame,
    types=(),
    sender: str = "",
    receiver: str = "",
    tick_range: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Пустое значение фильтра означает «без ограничения»."""
    result = frame
    if types:
        result = result[result["type"].isin(types)]
    if sender:
        result = result[result["sender"] == sender]
    if receiver:
        result = result[result["receiver"] == receiver]
    if tick_range is not None:
        first, last = tick_range
        result = result[(result["tick"] >= first) & (result["tick"] <= last)]
    return result