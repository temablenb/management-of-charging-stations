"""Сохранение и загрузка прогонов: итоги и состояние сети по тактам в JSON."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mas.metrics import RunSummary, TickRecord

FORMAT_VERSION = 1
DEFAULT_RUNS_DIR = "runs"
MODES = ("mas", "baseline")


@dataclass(frozen=True)
class SavedRun:
    """Загруженный прогон."""

    mode: str
    scenario: str
    seed: int
    days: int
    summary: RunSummary
    records: list[TickRecord]


@dataclass(frozen=True)
class RunInfo:
    """Краткие сведения о сохранённом прогоне для списка."""

    path: Path
    mode: str
    scenario: str
    seed: int
    days: int


def run_filename(scenario: str, mode: str, seed: int, days: int) -> str:
    """Имя файла прогона: одни и те же параметры дают одно и то же имя."""
    if mode not in MODES:
        raise ValueError(f"Режим должен быть одним из {MODES}")
    return f"{scenario}_{mode}_s{seed}_d{days}.json"


def save_run(
    directory: str | Path,
    mode: str,
    scenario: str,
    seed: int,
    days: int,
    summary: RunSummary,
    records,
) -> Path:
    """Сохраняет прогон в папку (создаётся при необходимости), возвращает путь к файлу."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    target = path / run_filename(scenario, mode, seed, days)
    payload = {
        "format": FORMAT_VERSION,
        "mode": mode,
        "scenario": scenario,
        "seed": seed,
        "days": days,
        "summary": summary.to_dict(),
        "records": [asdict(record) for record in records],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def load_run(path: str | Path) -> SavedRun:
    """Читает сохранённый прогон."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != FORMAT_VERSION:
        raise ValueError("Неизвестный формат файла прогона")
    return SavedRun(
        mode=data["mode"],
        scenario=data["scenario"],
        seed=data["seed"],
        days=data["days"],
        summary=RunSummary.from_dict(data["summary"]),
        records=[TickRecord(**item) for item in data["records"]],
    )


def list_runs(directory: str | Path) -> list[RunInfo]:
    """Сохранённые прогоны в папке, отсортированные по сценарию, режиму и seed."""
    path = Path(directory)
    if not path.is_dir():
        return []
    infos = []
    for file in path.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if data.get("format") != FORMAT_VERSION:
                continue
            infos.append(RunInfo(file, data["mode"], data["scenario"], data["seed"], data["days"]))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(infos, key=lambda info: (info.scenario, info.mode, info.seed, info.days))