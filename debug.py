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
    VERSION = "v0.1.2"
    log(f"=== ЗАПУСК SSHSCRE {VERSION} В РЕЖИМЕ ОТЛАДКИ ===", "BOOT")
    log(f"Python {sys.version}", "ENV")
    log(f"Рабочая директория: {os.getcwd()}", "ENV")

    if not os.path.exists("sshscree.py"):
        log("❌ ОШИБКА: файл sshscree.py не найден", "CRASH")
        sys.exit(1)
    
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

        import sshscree
        if hasattr(sshscree, 'main_menu'):
            inject_sysinfo()
            log("✅ Основной модуль импортирован", "BOOT")
            if os.path.exists("servers.db"):
                import sqlite3
                conn = sqlite3.connect("servers.db")
                c = conn.cursor()
                c.execute("PRAGMA table_info(servers)")
                servers_cols = [col[1] for col in c.fetchall()]
                c.execute("PRAGMA table_info(sessions)")
                sessions_cols = [col[1] for col in c.fetchall()]
                conn.close()
                
                log(f"Структура БД servers: {', '.join(servers_cols)}", "DB")
                log(f"Структура БД sessions: {', '.join(sessions_cols)}", "DB")
                if os.path.exists("UpdateSQL.py"):
                    log("✅ UpdateSQL.py найден", "DB")
                else:
                    log("⚠️ UpdateSQL.py не найден", "DB")
            else:
                log("⚠️ База данных servers.db не найдена", "DB")
            
            sshscree.main_menu()
        else:
            log("❌ main_menu не найден в sshscree.py", "CRASH")
            sys.exit(1)

        duration = time.time() - start_time
        log(f"Сессия завершена. Работал {duration:.2f} сек.", "EXIT")

    except Exception as e:
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "CRASH")
        traceback.print_exc()
        print(f"\033[91m[DEBUG] КРИТ: {e}\033[0m")

    log("=== СЕССИЯ ЗАВЕРШЕНА ===", "EXIT")
