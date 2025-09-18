import os
import paramiko
import sqlite3
from cryptography.fernet import Fernet
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()
DB_FILE = "servers.db"
HISTORY_FILE = "local_history.txt"
VERSION = "v0.1.2"

# ключ шифрования
def get_encryption_key():
    key_file = "secret.key"
    if os.path.exists(key_file):
        with open(key_file, "rb") as f: return f.read()
    key = Fernet.generate_key()
    with open(key_file, "wb") as f: f.write(key)
    return key

# шифрование пароля
def encrypt_password(password):
    key = get_encryption_key()
    return Fernet(key).encrypt(password.encode()).decode()

# дешифрование пароля
def decrypt_password(encrypted):
    key = get_encryption_key()
    return Fernet(key).decrypt(encrypted.encode()).decode()

# инициализация БД
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            host TEXT,
            user TEXT,
            password TEXT,
            os TEXT,
            setup_done INTEGER,
            auth_type TEXT,
            key_path TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            server_id INTEGER,
            cwd TEXT,
            FOREIGN KEY(server_id) REFERENCES servers(id)
        )
    ''')
    conn.commit()
    conn.close()

# проверка структуры БД
def check_db_structure():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # проверка таблицы servers
    c.execute("PRAGMA table_info(servers)")
    columns = [col[1] for col in c.fetchall()]
    desired = ["id", "name", "host", "user", "password", "os", "setup_done", "auth_type", "key_path"]
    if sorted(columns) != sorted(desired):
        conn.close()
        return False
    
    # проверка таблицы sessions
    c.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in c.fetchall()]
    desired = ["id", "name", "server_id", "cwd"]
    if sorted(columns) != sorted(desired):
        conn.close()
        return False
    
    conn.close()
    return True

# загрузка серверов
def load_servers():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM servers")
    servers = []
    for row in c.fetchall():
        server = {
            "id": row[0],
            "name": row[1],
            "host": row[2],
            "user": row[3],
            "password": decrypt_password(row[4]) if row[4] else None,
            "os": row[5],
            "setup_done": bool(row[6]),
            "auth_type": row[7],
            "key_path": row[8]
        }
        servers.append(server)
    conn.close()
    return servers

# сохранение серверов
def save_servers(servers):
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM servers")
    for server in servers:
        encrypted_pass = encrypt_password(server["password"]) if server.get("password") else None
        c.execute('''
            INSERT INTO servers (name, host, user, password, os, setup_done, auth_type, key_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            server["name"],
            server["host"],
            server["user"],
            encrypted_pass,
            server["os"],
            int(server["setup_done"]),
            server["auth_type"],
            server.get("key_path", "")
        ))
    conn.commit()
    conn.close()

# загрузка сессий
def load_sessions():
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT sessions.name, servers.id, sessions.cwd FROM sessions JOIN servers ON sessions.server_id = servers.id")
    sessions = {}
    for row in c.fetchall():
        sessions[row[0]] = {"server_id": row[1], "cwd": row[2]}
    conn.close()
    return sessions

# сохранение сессии
def save_session(name, server, cwd):
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM sessions WHERE name = ?", (name,))
    if c.fetchone():
        c.execute("UPDATE sessions SET server_id = ?, cwd = ? WHERE name = ?", (server["id"], cwd, name))
    else:
        c.execute("INSERT INTO sessions (name, server_id, cwd) VALUES (?, ?, ?)", (name, server["id"], cwd))
    conn.commit()
    conn.close()

# настройка сервера
def setup_server(ssh, os_type):
    run = lambda c: ssh.exec_command(c)
    run("sudo apt update -y")
    run("sudo apt install -y ufw nginx software-properties-common git")
    run("sudo ufw allow 22 && sudo ufw allow 9339 && sudo ufw --force enable")
    run("sudo systemctl enable nginx && sudo systemctl start nginx")
    run("sudo add-apt-repository ppa:catrobat/ppa -y 2>/dev/null || true")
    run("sudo apt update && sudo apt install -y catrobat || true")
    run("git clone https://github.com/justflyne/KSD-Brawl-V28 v28")
    console.print("✅ Репозиторий KSD-Brawl-V28 склонирован в папку v28", style="green")
    console.print("✅ Настройка завершена", style="green")

# показ информации о сервере
def show_infovds(ssh):
    run = lambda c: ssh.exec_command(c)[1].read().decode().strip()
    try:
        cpu_model = run('lscpu | grep "Model name" | cut -d ":" -f2 | xargs') or "N/A"
        cpu_cores = run('nproc') or "N/A"
        mem_used = run('free -h | awk \'/Mem/ {print $3}\'') or "N/A"
        mem_total = run('free -h | awk \'/Mem/ {print $2}\'') or "N/A"
        disk = run('df -h / | tail -1 | awk \'{print $3" / "$2" ("$5")"}\'') or "N/A"
        load = run("uptime | awk -F'load average:' '{print $2}'").strip() or "N/A"
        ip = run("hostname -I | awk '{print $1}'") or "N/A"
        os_name = run('cat /etc/os-release | grep PRETTY_NAME | cut -d \'"\' -f2') or "N/A"
        hostname = run("hostname") or "N/A"
    except Exception as e:
        console.print(f"❌ Ошибка получения данных: {e}", style="red")
        cpu_model = cpu_cores = mem_used = mem_total = disk = load = ip = os_name = hostname = "ERR"
    
    data = {
        "Имя": hostname,
        "IP": ip,
        "ОС": os_name,
        "Аптайм": run("uptime -p"),
        "ЦПУ": f"{cpu_model} ({cpu_cores} ядер)",
        "Память": f"{mem_used} / {mem_total}",
        "Диск": disk,
        "Нагрузка": load
    }
    t = Table.grid(padding=(0, 2))
    t.add_column(style="cyan", justify="right")
    t.add_column(style="green")
    for k, v in data.items(): t.add_row(f"🔹 {k}:", v)
    console.print(Panel(t, title="[bold yellow]📊 Сервер информация[/bold yellow]", border_style="blue", box=box.ROUNDED))
    console.print("→ Введите команду...", style="dim")

# загрузка файла/директории
def upload_item(sftp, local, remote):
    if os.path.isfile(local):
        console.print(f"📤 Загрузка: {local} → {remote}", style="cyan")
        try: sftp.put(local, remote)
        except Exception as e: console.print(f"❌ Ошибка загрузки: {e}", style="red")
    elif os.path.isdir(local):
        try: sftp.mkdir(remote)
        except: pass
        for item in os.listdir(local):
            l = os.path.join(local, item)
            r = f"{remote.rstrip('/')}/{item}"
            upload_item(sftp, l, r)

# скачивание файла/директории
def download_item(sftp, remote, local):
    try: attrs = sftp.stat(remote)
    except Exception as e: 
        console.print(f"❌ Удалённый путь не найден: {remote} ({e})", style="red")
        return
    
    if not attrs.st_mode & 0o040000:
        os.makedirs(os.path.dirname(local), exist_ok=True)
        console.print(f"📥 Скачивание: {remote} → {local}", style="cyan")
        try: sftp.get(remote, local)
        except Exception as e: console.print(f"❌ Ошибка скачивания: {e}", style="red")
    else:
        os.makedirs(local, exist_ok=True)
        for item in sftp.listdir(remote):
            r = f"{remote.rstrip('/')}/{item}"
            l = os.path.join(local, item)
            try:
                sftp.stat(r + "/")
                download_item(sftp, r, l)
            except:
                os.makedirs(os.path.dirname(l), exist_ok=True)
                console.print(f"📥 Скачивание: {r} → {l}", style="cyan")
                try: sftp.get(r, l)
                except Exception as e: console.print(f"❌ Ошибка: {e}", style="red")

# обработка команды file
def handle_file_cmd(ssh, src, dst):
    try:
        sftp = ssh.open_sftp()
        if os.path.exists(src):
            upload_item(sftp, src, dst)
            console.print("✅ Загрузка завершена", style="green")
        else:
            download_item(sftp, src, dst)
            console.print("✅ Скачивание завершено", style="green")
        sftp.close()
    except Exception as e:
        console.print(f"❌ Ошибка SFTP: {e}", style="red")

# подключение к серверу
def connect_to_server(server):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        if server["auth_type"] == "password":
            ssh.connect(server["host"], username=server["user"], password=server["password"], timeout=10)
        elif server["auth_type"] == "key":
            ssh.connect(server["host"], username=server["user"], key_filename=server["key_path"], timeout=10)
        
        _, out, _ = ssh.exec_command("hostname")
        real_host = out.read().decode().strip() or server["host"]
        server["real_hostname"] = real_host

        _, out, _ = ssh.exec_command("pwd")
        current_dir = out.read().decode().strip() or "/"
        
        last_cwd = current_dir
        if "session_cwd" in server:
            full_cmd = f"cd {server['session_cwd']} && pwd"
            _, out, err = ssh.exec_command(full_cmd)
            output = out.read().decode().strip()
            error = err.read().decode().strip()
            if error: console.print(f"❌ Ошибка перехода в {server['session_cwd']}: {error}", style="red")
            else: last_cwd = output
            del server["session_cwd"]
        
        short_dir = last_cwd.split("/")[-1] if last_cwd != "/" else "~"
        console.print(f"✅ Подключено к {server['name']} → {real_host}", style="blue")
        show_infovds(ssh)
        
        if not server.get("setup_done"):
            if Confirm.ask("🔧 Первый запуск. Настроить сервер?"):
                setup_server(ssh, server["os"])
                server["setup_done"] = True
                servers = load_servers()
                for s in servers:
                    if s["id"] == server["id"]:
                        s.update(server)
                save_servers(servers)
        
        console.print("\n→ Команды: exit, infovds, file, clear, cls, cd, local ls, local history, dash, undash", style="bold cyan")
        
        use_dash_prompt = False
        while True:
            prompt_symbol = "#" if use_dash_prompt else "$"
            prompt_display = last_cwd.split("/")[-1] if last_cwd != "/" else "~"
            cmd = Prompt.ask(f"{server['user']}@{real_host}/{prompt_display} {prompt_symbol} ", style="green").strip()
            
            if cmd and cmd != "local history":
                with open(HISTORY_FILE, "a") as f: f.write(cmd + "\n")
            
            if not cmd: continue
            elif cmd in ("exit", "quit", "q"): break
            elif cmd == "infovds": show_infovds(ssh)
            elif cmd == "dash": 
                use_dash_prompt = True
                console.print("→ Переключён на dash-стиль промпта", style="dim")
            elif cmd == "undash": 
                use_dash_prompt = False
                console.print("→ Стандартный промпт активирован", style="dim")
            elif cmd == "clear" or cmd == "cls": os.system('cls' if os.name == 'nt' else 'clear')
            elif cmd.startswith("cd "):
                target = cmd[3:].strip()
                if not target: full_cmd = "cd && pwd"
                else: full_cmd = f"cd {target} && pwd"
                _, out, err = ssh.exec_command(full_cmd)
                output = out.read().decode().strip()
                error = err.read().decode().strip()
                if error: console.print(error, style="red")
                else: last_cwd = output
            elif cmd.startswith("file "):
                parts = cmd.split(maxsplit=2)
                if len(parts) < 3: console.print("❌ Использование: file <источник> <назначение>", style="red")
                else: handle_file_cmd(ssh, parts[1], parts[2])
            elif cmd.startswith("local ls"):
                path = cmd[8:].strip() or "."
                try: 
                    for item in os.listdir(path): console.print(f"  {item}")
                except Exception as e: console.print(f"❌ local ls: {e}", style="red")
            elif cmd == "local history":
                if os.path.exists(HISTORY_FILE):
                    with open(HISTORY_FILE, "r") as f: history = f.read().splitlines()
                    if history:
                        for i, line in enumerate(history, 1): console.print(f"{i}. {line}")
                    else: console.print("История команд пуста", style="yellow")
                else: console.print("История команд пуста", style="yellow")
            else:
                full_cmd = f"cd {last_cwd} 2>/dev/null && {cmd}"
                _, out, err = ssh.exec_command(full_cmd)
                output = out.read().decode()
                error = err.read().decode()
                if output: console.print(output)
                if error: console.print(error, style="red")
        
        ssh.close()
        console.print("🔌 Отключено", style="red")
        
        if Confirm.ask("💾 Сохранить сессию?"):
            sess_name = Prompt.ask("📁 Название сессии")
            save_session(sess_name, server, last_cwd)
            console.print(f"✅ Сессия '{sess_name}' сохранена", style="green")
    
    except Exception as e:
        console.print(f"❌ Ошибка подключения: {e}", style="red")

# добавление сервера
def add_server():
    name = Prompt.ask("Имя сервера")
    host = Prompt.ask("IP")
    user = Prompt.ask("Пользователь", default="root")
    auth_type = Prompt.ask("Тип аутентификации", choices=["password", "key"], default="password")
    os_choice = Prompt.ask("ОС", choices=["debian", "ubuntu"], default="ubuntu")
    
    if auth_type == "password":
        pwd = Prompt.ask("Пароль", password=True)
        key_path = None
    else:
        pwd = None
        key_path = Prompt.ask("Путь к приватному ключу")
    
    server = {
        "name": name,
        "host": host,
        "user": user,
        "password": pwd,
        "os": os_choice,
        "setup_done": False,
        "auth_type": auth_type,
        "key_path": key_path
    }
    
    servers = load_servers()
    servers.append(server)
    save_servers(servers)
    console.print(f"✅ Сервер {name} добавлен", style="green")

# список серверов
def list_servers():
    servers = load_servers()
    if not servers:
        console.print("Нет серверов", style="yellow")
        return
    t = Table(title="Серверы")
    for col in ["#", "Имя", "IP", "Пользователь", "ОС", "Аутентификация", "Настроено?"]: 
        t.add_column(col)
    for i, s in enumerate(servers, 1):
        auth_type = "🔑 Ключ" if s["auth_type"] == "key" else "🔑 Пароль"
        setup = "✅" if s.get("setup_done") else "❌"
        t.add_row(str(i), s["name"], s["host"], s["user"], s["os"], auth_type, setup)
    console.print(t)

# восстановление сессии
def restore_session():
    sessions = load_sessions()
    if not sessions:
        console.print("Нет сохранённых сессий", style="yellow")
        return None
    t = Table(title="Сессии")
    t.add_column("#"); t.add_column("Имя"); t.add_column("Сервер"); t.add_column("Путь")
    servers = load_servers()
    for i, (name, data) in enumerate(sessions.items(), 1):
        server = next((s for s in servers if s["id"] == data["server_id"]), None)
        if server:
            t.add_row(str(i), name, f"{server['user']}@{server['host']}", data["cwd"])
        else:
            t.add_row(str(i), name, "Сервер не найден", data["cwd"])
    console.print(t)
    try:
        idx = int(Prompt.ask("Номер сессии")) - 1
        session_names = list(sessions.keys())
        if idx < 0 or idx >= len(session_names):
            console.print("Неверный номер", style="red")
            return None
        name = session_names[idx]
        data = sessions[name]
        server = next((s for s in servers if s["id"] == data["server_id"]), None)
        if not server:
            console.print("Сервер для сессии не найден", style="red")
            return None
        server["session_cwd"] = data["cwd"]
        return server
    except Exception as e:
        console.print(f"Ошибка выбора сессии: {e}", style="red")
        return None

# главное меню
def main_menu():
    console.print(f"🚀 SSHSCRE {VERSION} — замена Termius (консоль)", style="red")
    console.print("→ Создатель: KilixKilik | GitHub: @KilixKilik", style="dim")
    
    while True:
        console.print("\nМеню:\n1. Подключиться\n2. Восстановить сессию\n3. Добавить\n4. Список\n5. Выход", style="bold")
        choice = Prompt.ask("→", choices=["1", "2", "3", "4", "5"])
        if choice == "1":
            servers = load_servers()
            if not servers: 
                console.print("Добавьте сервер", style="red")
                continue
            list_servers()
            try:
                idx = int(Prompt.ask("Номер")) - 1
                if 0 <= idx < len(servers): connect_to_server(servers[idx])
                else: console.print("Неверный номер", style="red")
            except: console.print("Введите число", style="red")
        elif choice == "2":
            server = restore_session()
            if server: connect_to_server(server)
        elif choice == "3": add_server()
        elif choice == "4": list_servers()
        elif choice == "5": 
            console.print("👋 Пока", style="red")
            break

if __name__ == "__main__":
    # проверка структуры БД
    if not os.path.exists(DB_FILE):
        init_db()
        console.print("✅ База данных создана", style="green")
    else:
        if not check_db_structure():
            console.print("⚠️ Структура базы данных не соответствует требуемой. Запустите UpdateSQL.py для обновления.", style="yellow")
            console.print("❌ Программа завершена", style="red")
            exit(1)
    
    main_menu()

# Github: @KilikKilix
