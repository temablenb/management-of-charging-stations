## Запуск в Docker

Требуются Docker и Docker Compose.

```bash
git clone https://github.com/temablenb/management-of-charging-stations.git
cd management-of-charging-stations
docker compose up --build
```

Интерфейс открывается на http://localhost:8501.
База данных хранится в папке `data/` и сохраняется между перезапусками.
Остановка: `docker compose down`.