import sys
import os
import time
import traceback
from datetime import datetime

LOG_FILE = "debug.log"

def log(msg, tag="DEBUG"):
    now = datetime.now().strftime("%H:%M:%S")
    line = f"[{now}] [{tag}] {msg}"
    print(f"\033[90m{line}\033[0m") 
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

_original_print = print
def debug_print(*args, **kwargs):
    _original_print(*args, **kwargs)
    msg = " ".join(str(arg) for arg in args)
    log(msg, "PRINT")

print = debug_print

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)), "CRASH")

sys.excepthook = handle_exception

def inject_sysinfo():
    import platform
    import socket
    info = f"""
    🖥️  Локальная система:
    OS: {platform.system()} {platform.release()}
    Host: {socket.gethostname()}
    Python: {platform.python_version()}
    """
    print(f"\033[94m{info}\033[0m")

if __name__ == "__main__":
    log("=== ЗАПУСК В РЕЖИМЕ ОТЛАДКИ ===", "BOOT")
    log(f"Python {sys.version}", "ENV")
    log(f"Рабочая директория: {os.getcwd()}", "ENV")

    try:
        from rich.prompt import Prompt
        _original_ask = Prompt.ask
        def debug_ask(*args, **kwargs):
            result = _original_ask(*args, **kwargs)
            log(f"Ввод: {result}", "INPUT")
            return result
        Prompt.ask = debug_ask

        start_time = time.time()
        log("Запуск SSHscre...", "BOOT")

        import main 
        if hasattr(main, 'main_menu'):
            inject_sysinfo()
            main.main_menu()
        else:
            log("main_menu не найден. Запускаю как модуль.", "WARN")
            inject_sysinfo()
            exec(open("main.py").read())

        duration = time.time() - start_time
        log(f"Сессия завершена. Работал {duration:.2f} сек.", "EXIT")

    except Exception as e:
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "CRASH")
        traceback.print_exc()
        print(f"\033[91m[DEBUG] КРИТ: {e}\033[0m")

    log("=== СЕССИЯ ЗАВЕРШЕНА ===", "EXIT")
