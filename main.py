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
VERSION = "v0.1.0"

# ядро: загрузка/сохранение серверов
def load_servers():
    if not os.path.exists(CONFIG_FILE): return []
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_servers(servers):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(servers, f, indent=2, ensure_ascii=False)

# инфо: базовая статистика сервера
def get_server_info(ssh):
    cmds = [
        "hostname", "uptime", "free -h", "df -h /",
        "lscpu | grep 'Model name\\|CPU(s)'",
        "cat /etc/os-release | grep PRETTY_NAME"
    ]
    console.print("\n[bold green]📊 Информация о системе:[/bold green]\n")
    for cmd in cmds:
        _, out, _ = ssh.exec_command(cmd)
        console.print(out.read().decode().strip())

# настройка: первый запуск
def setup_server(ssh, os_type):
    run = lambda c: ssh.exec_command(c)
    run("sudo apt update -y")
    run("sudo apt install -y ufw nginx software-properties-common")
    run("sudo ufw allow 22 && sudo ufw allow 9339 && sudo ufw --force enable")
    run("sudo systemctl enable nginx && sudo systemctl start nginx")
    run("sudo add-apt-repository ppa:catrobat/ppa -y 2>/dev/null || true")
    run("sudo apt update && sudo apt install -y catrobat || true")
    console.print("[green]✅ Настройка завершена[/green]")

# интерфейс: красивая панель infovds
def show_infovds(ssh):
    run = lambda c: ssh.exec_command(c)[1].read().decode().strip()
    data = {
        "Имя": run("hostname"),
        "IP": run("hostname -I | awk '{print $1}'"),
        "ОС": run("cat /etc/os-release | grep PRETTY_NAME | cut -d '\"' -f2"),
        "Аптайм": run("uptime -p"),
        "ЦПУ": f"{run('lscpu | grep \"Model name\" | cut -d \":\" -f2 | xargs')} ({run('nproc')} ядер)",
        "Память": f"{run('free -h | grep Mem | awk \"{print $3}\"')} / {run('free -h | grep Mem | awk \"{print $2}\"')}",
        "Диск": run("df -h / | tail -1 | awk '{print $2\" / \"$3\" занято\"}'"),
        "Нагрузка": run("uptime | awk -F'load average:' '{print $2}'")
    }
    t = Table.grid(padding=(0, 2))
    t.add_column(style="cyan", justify="right")
    t.add_column(style="green")
    for k, v in data.items(): t.add_row(f"🔹 {k}:", v)
    console.print(Panel(t, title=f"[bold yellow]📊 {data['Имя']}[/bold yellow]", border_style="blue", box=box.ROUNDED))
    console.print("[dim]→ Введите команду...[/dim]\n")

# sftp: загрузка файла/папки
def upload_item(sftp, local, remote):
    if os.path.isfile(local):
        console.print(f"📤 Загрузка: {local} → {remote}")
        sftp.put(local, remote)
    elif os.path.isdir(local):
        try: sftp.mkdir(remote)
        except: pass
        for item in os.listdir(local):
            l = os.path.join(local, item)
            r = f"{remote.rstrip('/')}/{item}"
            upload_item(sftp, l, r)

# sftp: скачивание файла/папки
def download_item(sftp, remote, local):
    try:
        sftp.stat(remote)
    except:
        console.print(f"[red]❌ Удалённый путь не найден: {remote}[/red]")
        return
    if '.' in os.path.basename(remote) or '/' not in remote:
        console.print(f"📥 Скачивание: {remote} → {local}")
        sftp.get(remote, local)
    else:
        os.makedirs(local, exist_ok=True)
        for item in sftp.listdir(remote):
            r = f"{remote.rstrip('/')}/{item}"
            l = os.path.join(local, item)
            try:
                sftp.stat(r + "/")
                download_item(sftp, r, l)
            except:
                console.print(f"📥 Скачивание: {r} → {l}")
                sftp.get(r, l)

# команда: обработка file
def handle_file_cmd(ssh, args):
    if len(args) < 3:
        console.print("[red]❌ Использование: file <источник> <назначение>[/red]")
        return
    src, dst = args[1], args[2]
    try:
        sftp = ssh.open_sftp()
        if src.startswith("./") or os.path.exists(src):
            upload_item(sftp, src, dst)
            console.print("[green]✅ Загрузка завершена[/green]")
        else:
            download_item(sftp, src, dst)
            console.print("[green]✅ Скачивание завершено[/green]")
        sftp.close()
    except Exception as e:
        console.print(f"[red]❌ Ошибка SFTP: {e}[/red]")

# сессия: основной цикл
def connect_to_server(server):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server["host"], username=server["user"], password=server["password"], timeout=10)
        _, out, _ = ssh.exec_command("hostname")
        real_host = out.read().decode().strip() or server["host"]
        server["real_hostname"] = real_host

        # получаем начальную директорию
        _, out, _ = ssh.exec_command("pwd")
        current_dir = out.read().decode().strip()
        # укорачиваем: /home/user → user
        short_dir = current_dir.split("/")[-1] if current_dir != "/" else ""

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

        console.print("\n[bold cyan]→ Команды: exit, infovds, file <источник> <назначение>[/bold cyan]")

        # флаг: используем ли dash-стиль (# вместо $)
        use_dash_prompt = False

        while True:
            # формируем промпт: root@hostname/dir #
            prompt_symbol = "#" if use_dash_prompt else "$"
            prompt_display = short_dir if short_dir else "~"
            cmd = Prompt.ask(f"[green]{server['user']}@{real_host}/{prompt_display}[/green] {prompt_symbol} ")

            if cmd.strip() == "exit" or cmd.strip() == "quit":
                break
            elif cmd.strip() == "infovds":
                show_infovds(ssh)
                continue
            elif cmd.strip() == "dash":
                use_dash_prompt = True  # переключаем на # промпт
                console.print("[dim]→ Переключён на dash-стиль промпта[/dim]")
                continue
            elif cmd.startswith("cd "):
                # выполняем cd и обновляем текущую директорию
                _, _, err = ssh.exec_command(cmd)
                error = err.read().decode().strip()
                if error:
                    console.print(f"[red]{error}[/red]")
                else:
                    # обновляем short_dir
                    _, out, _ = ssh.exec_command("pwd")
                    current_dir = out.read().decode().strip()
                    short_dir = current_dir.split("/")[-1] if current_dir != "/" else ""
                continue
            elif cmd.startswith("file "):
                handle_file_cmd(ssh, cmd.split(" ", 2))
                continue

            # выполняем любую другую команду
            _, out, err = ssh.exec_command(cmd)
            output = out.read().decode()
            error = err.read().decode()
            if output:
                console.print(output)
            if error:
                console.print(f"[red]{error}[/red]")

        ssh.close()
        console.print("[red]🔌 Отключено[/red]")
    except Exception as e:
        console.print(f"[red]❌ Ошибка подключения: {e}[/red]")

# интерфейс: добавить сервер
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

# интерфейс: список серверов
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

# точка входа: главное меню
def main_menu():
    console.print(f"[red]🚀 SSHSCRE {VERSION} — замена Termius (консоль)[/red]")
    console.print("[dim]→ Создатель: KilixKilik | GitHub: @KilixKilik[/dim]\n")  # 👈 ДОБАВИЛ СТРОКУ СОЗДАТЕЛЯ
    while True:
        console.print("\n[bold]Меню:[/bold]\n1. Подключиться\n2. Добавить\n3. Список\n4. Выход")
        choice = Prompt.ask("→", choices=["1", "2", "3", "4"])
        if choice == "1":
            servers = load_servers()
            if not servers: console.print("[red]Добавьте сервер[/red]"); continue
            list_servers()
            try:
                idx = int(Prompt.ask("Номер")) - 1
                if 0 <= idx < len(servers): connect_to_server(servers[idx])
                else: console.print("[red]Неверный номер[/red]")
            except: console.print("[red]Введите число[/red]")
        elif choice == "2": add_server()
        elif choice == "3": list_servers()
        elif choice == "4": console.print("[red]👋 Пока[/red]"); break

if __name__ == "__main__":
    main_menu()

# Created by KilixKilik | GitHub: @KilixKilik
