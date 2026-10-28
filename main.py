import subprocess
import sys
import os


def main():
    os.path.join(os.path.dirname(__file__), "requirements.txt")
    try:
        import streamlit
        import pandas
        import statsmodels
        import pulp
    except ImportError:
        print("\nОтсутствуют обязательные зависимости.")
        print("Выполните установку: pip install -r requirements.txt")
        sys.exit(1)

    print("\nЗапуск системы оптимизации ЭЗС...")
    print("Откройте интерфейс в браузере: http://localhost:8501")

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", "gui.py",
            "--server.port", "8501",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false"
        ], check=True)
    except FileNotFoundError:
        print("Ошибка: Python или Streamlit не найдены в переменных среды.")
    except KeyboardInterrupt:
        print("\nСистема остановлена пользователем.")
    except Exception as e:
        print(f"Критическая ошибка запуска: {e}")


if __name__ == "__main__":
    main()