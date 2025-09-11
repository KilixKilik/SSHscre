import json
import os
import paramiko
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()
CONFIG_FILE = "servers.json"
SESSIONS_FILE = "sessions.json"
VERSION = "v0.1.1"

def load_servers():
    if not os.path.exists(CONFIG_FILE): return []
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_servers(servers):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(servers, f, indent=2, ensure_ascii=False)

def load_sessions():
    if not os.path.exists(SESSIONS_FILE): return {}
    with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_session(name, server, cwd):
    sessions = load_sessions()
    sessions[name] = {"host": server["host"], "user": server["user"], "cwd": cwd}
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)

def get_server_info(ssh):
    cmds = ["hostname", "uptime", "free -h", "df -h /", "lscpu | grep 'Model name\\|CPU(s)'", "cat /etc/os-release | grep PRETTY_NAME"]
    console.print("\n[bold green]📊 Информация о системе:[/bold green]\n")
    for cmd in cmds:
        _, out, _ = ssh.exec_command(cmd)
        console.print(out.read().decode().strip())

def setup_server(ssh, os_type):
    run = lambda c: ssh.exec_command(c)
    run("sudo apt update -y")
    run("sudo apt install -y ufw nginx software-properties-common")
    run("sudo ufw allow 22 && sudo ufw allow 9339 && sudo ufw --force enable")
    run("sudo systemctl enable nginx && sudo systemctl start nginx")
    run("sudo add-apt-repository ppa:catrobat/ppa -y 2>/dev/null || true")
    run("sudo apt update && sudo apt install -y catrobat || true")
    console.print("[green]✅ Настройка завершена[/green]")

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
    except: 
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
    console.print(Panel(t, title=f"[bold yellow]📊 {hostname}[/bold yellow]", border_style="blue", box=box.ROUNDED))
    console.print("[dim]→ Введите команду...[/dim]\n")

def upload_item(sftp, local, remote):
    if os.path.isfile(local):
        console.print(f"📤 Загрузка: {local} → {remote}")
        try:
            sftp.put(local, remote)
        except Exception as e:
            console.print(f"[red]❌ Ошибка загрузки: {e}[/red]")
    elif os.path.isdir(local):
        try:
            sftp.mkdir(remote)
        except: pass
        for item in os.listdir(local):
            l = os.path.join(local, item)
            r = f"{remote.rstrip('/')}/{item}"
            upload_item(sftp, l, r)

def download_item(sftp, remote, local):
    try:
        attrs = sftp.stat(remote)
    except Exception as e:
        console.print(f"[red]❌ Удалённый путь не найден: {remote} ({e})[/red]")
        return

    if not attrs.st_mode & 0o040000:  # не директория
        os.makedirs(os.path.dirname(local), exist_ok=True)
        console.print(f"📥 Скачивание: {remote} → {local}")
        try:
            sftp.get(remote, local)
        except Exception as e:
            console.print(f"[red]❌ Ошибка скачивания: {e}[/red]")
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
                console.print(f"📥 Скачивание: {r} → {l}")
                try:
                    sftp.get(r, l)
                except Exception as e:
                    console.print(f"[red]❌ Ошибка: {e}[/red]")

def handle_file_cmd(ssh, args):
    if len(args) < 3:
        console.print("[red]❌ Использование: file <источник> <назначение>[/red]")
        return
    src, dst = args[1], args[2]
    try:
        sftp = ssh.open_sftp()
        if os.path.exists(src):
            upload_item(sftp, src, dst)
            console.print("[green]✅ Загрузка завершена[/green]")
        else:
            download_item(sftp, src, dst)
            console.print("[green]✅ Скачивание завершено[/green]")
        sftp.close()
    except Exception as e:
        console.print(f"[red]❌ Ошибка SFTP: {e}[/red]")

def connect_to_server(server):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server["host"], username=server["user"], password=server["password"], timeout=10)
        _, out, _ = ssh.exec_command("hostname")
        real_host = out.read().decode().strip() or server["host"]
        server["real_hostname"] = real_host

        _, out, _ = ssh.exec_command("pwd")
        current_dir = out.read().decode().strip() or "/"

        short_dir = current_dir.split("/")[-1] if current_dir != "/" else "~"
        console.print(f"[blue]✅ Подключено к {server['name']} → {real_host}[/blue]")
        get_server_info(ssh)

        if not server.get("setup_done"):
            if Confirm.ask("[yellow]🔧 Первый запуск. Настроить сервер?[/yellow]"):
                setup_server(ssh, server["os"])
                server["setup_done"] = True
                servers = load_servers()
                for s in servers:
                    if s["host"] == server["host"] and s["user"] == server["user"]:
                        s.update(server)
                save_servers(servers)

        console.print("\n[bold cyan]→ Команды: exit, infovds, file, clear, cls, cd, local ls[/bold cyan]")

        use_dash_prompt = False
        last_cwd = current_dir

        while True:
            prompt_symbol = "#" if use_dash_prompt else "$"
            prompt_display = last_cwd.split("/")[-1] if last_cwd != "/" else "~"
            cmd = Prompt.ask(f"[green]{server['user']}@{real_host}/{prompt_display}[/green] {prompt_symbol} ").strip()

            if not cmd:
                continue
            elif cmd == "exit" or cmd == "quit":
                break
            elif cmd == "infovds":
                show_infovds(ssh)
                continue
            elif cmd == "dash":
                use_dash_prompt = True
                console.print("[dim]→ Переключён на dash-стиль промпта[/dim]")
                continue
            elif cmd == "clear" or cmd == "cls":
                os.system('cls' if os.name == 'nt' else 'clear')
                continue
            elif cmd.startswith("cd "):
                target = cmd[3:].strip() or "/"
                full_cmd = f"cd {target} && pwd"
                _, out, err = ssh.exec_command(full_cmd)
                output = out.read().decode().strip()
                error = err.read().decode().strip()
                if error:
                    console.print(f"[red]{error}[/red]")
                else:
                    last_cwd = output
                continue
            elif cmd.startswith("file "):
                handle_file_cmd(ssh, cmd.split(" ", 3))
                continue
            elif cmd.startswith("local ls"):
                path = cmd[8:].strip() or "."
                try:
                    items = os.listdir(path)
                    for item in items:
                        console.print(f"  {item}")
                except Exception as e:
                    console.print(f"[red]❌ local ls: {e}[/red]")
                continue

            full_cmd = f"cd {last_cwd} 2>/dev/null && {cmd}"
            _, out, err = ssh.exec_command(full_cmd)
            output = out.read().decode()
            error = err.read().decode()
            if output:
                console.print(output)
            if error:
                console.print(f"[red]{error}[/red]")

        ssh.close()
        console.print("[red]🔌 Отключено[/red]")

        if Confirm.ask("[yellow]💾 Сохранить сессию?[/yellow]"):
            sess_name = Prompt.ask("📁 Название сессии")
            save_session(sess_name, server, last_cwd)
            console.print(f"[green]✅ Сессия '{sess_name}' сохранена[/green]")

    except Exception as e:
        console.print(f"[red]❌ Ошибка подключения: {e}[/red]")

def add_server():
    name = Prompt.ask("Имя сервера")
    host = Prompt.ask("IP")
    user = Prompt.ask("Пользователь", default="root")
    pwd = Prompt.ask("Пароль", password=True)
    os_choice = Prompt.ask("ОС", choices=["debian", "ubuntu"], default="ubuntu")
    server = {"name": name, "host": host, "user": user, "password": pwd, "os": os_choice, "setup_done": False}
    servers = load_servers()
    servers.append(server)
    save_servers(servers)
    console.print(f"[green]✅ Сервер {name} добавлен[/green]")

def list_servers():
    servers = load_servers()
    if not servers:
        console.print("[yellow]Нет серверов[/yellow]")
        return
    t = Table(title="Серверы")
    for col in ["#", "Имя", "IP", "Пользователь", "ОС", "Настроено?"]: t.add_column(col)
    for i, s in enumerate(servers, 1):
        setup = "✅" if s.get("setup_done") else "❌"
        t.add_row(str(i), s["name"], s["host"], s["user"], s["os"], setup)
    console.print(t)

def restore_session():
    sessions = load_sessions()
    if not sessions:
        console.print("[yellow]Нет сохранённых сессий[/yellow]")
        return None
    t = Table(title="Сессии")
    t.add_column("#"); t.add_column("Имя"); t.add_column("Сервер"); t.add_column("Путь")
    for i, (name, data) in enumerate(sessions.items(), 1):
        t.add_row(str(i), name, f"{data['user']}@{data['host']}", data.get("cwd", "/"))
    console.print(t)
    try:
        idx = int(Prompt.ask("Номер сессии")) - 1
        name = list(sessions.keys())[idx]
        data = sessions[name]
        servers = load_servers()
        for s in servers:
            if s["host"] == data["host"] and s["user"] == data["user"]:
                s["session_cwd"] = data["cwd"]
                return s
        console.print("[red]Сервер для сессии не найден[/red]")
    except:
        console.print("[red]Ошибка выбора сессии[/red]")
    return None

def main_menu():
    console.print(f"[red]🚀 SSHSCRE {VERSION} — замена Termius (консоль)[/red]")
    console.print("[dim]→ Создатель: KilixKilik | GitHub: @KilixKilik[/dim]\n")

    while True:
        console.print("\n[bold]Меню:[/bold]\n1. Подключиться\n2. Восстановить сессию\n3. Добавить\n4. Список\n5. Выход")
        choice = Prompt.ask("→", choices=["1", "2", "3", "4", "5"])
        if choice == "1":
            servers = load_servers()
            if not servers: console.print("[red]Добавьте сервер[/red]"); continue
            list_servers()
            try:
                idx = int(Prompt.ask("Номер")) - 1
                if 0 <= idx < len(servers): connect_to_server(servers[idx])
                else: console.print("[red]Неверный номер[/red]")
            except: console.print("[red]Введите число[/red]")
        elif choice == "2":
            server = restore_session()
            if server: connect_to_server(server)
        elif choice == "3": add_server()
        elif choice == "4": list_servers()
        elif choice == "5": console.print("[red]👋 Пока[/red]"); break

if __name__ == "__main__":
    main_menu()

# Created by KilixKilik | GitHub: @KilixKilik
