"""
launcher.py -- DorianCoin (DRN) Project Launcher
=================================================
One-click initialiser and control panel for the DorianCoin project.

  - Verifies Python version
  - Installs / upgrades pip dependencies
  - Creates the data/ directory
  - Interactive menu: start node, run demos, open explorer, manage wallets
  - Gracefully shuts down any running node on exit

Compile to EXE:
    pip install pyinstaller
    pyinstaller --onefile --console --name DorianCoinLauncher launcher.py
"""

import os
import sys
import time
import shutil
import signal
import platform
import subprocess
import threading
import webbrowser

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(HERE, "data")
REQ_FILE   = os.path.join(HERE, "requirements.txt")
NODE_SCRIPT  = os.path.join(HERE, "node.py")
PYTHON = sys.executable

# ---------------------------------------------------------------------------
# ANSI colour helpers (work on Windows 10+ with ENABLE_VIRTUAL_TERMINAL)
# ---------------------------------------------------------------------------

def _enable_ansi():
    """Enable ANSI escape codes on Windows."""
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
        except Exception:
            pass

_enable_ansi()

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
MAGENTA = "\033[95m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BG_DARK = "\033[48;5;234m"
BG_BLUE = "\033[48;5;17m"

def c(text, colour): return f"{colour}{text}{RESET}"
def bold(t): return c(t, BOLD)
def dim(t):  return c(t, DIM)
def red(t):  return c(t, RED)
def green(t): return c(t, GREEN)
def yellow(t): return c(t, YELLOW)
def cyan(t): return c(t, CYAN)
def magenta(t): return c(t, MAGENTA)
def blue(t): return c(t, BLUE)

W = 66   # terminal width

def divider(ch="═"):  print(cyan(ch * W))
def thin(ch="─"):     print(dim(ch * W))
def blank():          print()

def header():
    os.system("cls" if platform.system() == "Windows" else "clear")
    divider()
    print(cyan("║") + " " * 12 +
          bold(yellow(" ◈  DorianCoin (DRN) Launcher  ◈ ")) +
          " " * 12 + cyan("║"))
    print(cyan("║") + dim(" " * 64) + cyan("║"))
    print(cyan("║") + dim("  Stages 1-9 · PoW · ECDSA · P2P · UTXO · MultiSig · TimeLock  ") + cyan("║"))
    divider()
    blank()

def section(title):
    blank()
    thin()
    print(f"  {bold(cyan(title))}")
    thin()

def ok(msg):    print(f"  {green('✔')}  {msg}")
def warn(msg):  print(f"  {yellow('⚠')}  {msg}")
def err(msg):   print(f"  {red('✖')}  {msg}")
def info(msg):  print(f"  {dim('·')}  {dim(msg)}")

def kv(label, value):
    print(f"  {dim(label+':'):<22}{value}")

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_node_proc: subprocess.Popen = None
_node_port: int = 5000
_node_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Setup / initialisation
# ---------------------------------------------------------------------------

def check_python():
    major, minor = sys.version_info[:2]
    ver = f"Python {major}.{minor}.{sys.version_info[2]}"
    if (major, minor) < (3, 8):
        err(f"{ver}  --  Python 3.8+ required")
        return False
    ok(f"{ver}  {dim('(3.8+ ✓)')}")
    return True


def check_pip():
    try:
        import pip  # noqa
        ok("pip is available")
        return True
    except ImportError:
        err("pip is not importable — install it first")
        return False


def install_requirements():
    section("Installing / verifying dependencies")
    if not os.path.exists(REQ_FILE):
        warn("requirements.txt not found — skipping")
        return True
    with open(REQ_FILE) as f:
        pkgs = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    info(f"Requirements: {', '.join(pkgs)}")
    result = subprocess.run(
        [PYTHON, "-m", "pip", "install", "--quiet", "--upgrade"] + pkgs,
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        ok("All dependencies satisfied")
        return True
    else:
        err("pip install failed:")
        print(result.stderr[-1000:])
        return False


def create_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        ok(f"Created  {dim(DATA_DIR)}")
    else:
        ok(f"data/    {dim(DATA_DIR)}  {dim('(exists)')}")


def initialise():
    """Run once at startup: check env, install deps, create dirs."""
    header()
    section("Environment check")
    py_ok = check_python()
    pip_ok = check_pip()
    if not (py_ok and pip_ok):
        blank()
        err("Cannot continue — fix the issues above and re-run.")
        _pause()
        return False

    install_requirements()

    section("Project structure")
    create_data_dir()
    kv("Root", HERE)
    kv("Node script", NODE_SCRIPT)
    kv("Requirements", REQ_FILE)
    return True

# ---------------------------------------------------------------------------
# Node management
# ---------------------------------------------------------------------------

def _node_running() -> bool:
    global _node_proc
    with _node_lock:
        return _node_proc is not None and _node_proc.poll() is None


def start_node(port: int = 5000, difficulty: int = 3):
    global _node_proc, _node_port
    if _node_running():
        warn(f"Node already running on port {_node_port}  (PID {_node_proc.pid})")
        return
    _node_port = port
    cmd = [PYTHON, "-u", NODE_SCRIPT, "--port", str(port),
           "--difficulty", str(difficulty)]
    with _node_lock:
        _node_proc = subprocess.Popen(
            cmd,
            cwd=HERE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            if platform.system() == "Windows" else 0,
        )
    ok(f"Node started on  {cyan(f'http://localhost:{port}')}  "
       f"PID={_node_proc.pid}  difficulty={difficulty}")
    info("Block explorer: " + f"http://localhost:{port}/explorer")


def stop_node():
    global _node_proc
    with _node_lock:
        if _node_proc is None:
            warn("No node is running.")
            return
        pid = _node_proc.pid
        try:
            if platform.system() == "Windows":
                _node_proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                _node_proc.terminate()
            _node_proc.wait(timeout=6)
        except Exception:
            try:
                _node_proc.kill()
            except Exception:
                pass
        ok(f"Node (PID {pid}) stopped.")
        _node_proc = None


def node_status():
    if _node_running():
        ok(f"Node is  {green('RUNNING')}  on port {_node_port}  "
           f"(PID {_node_proc.pid})")
        info(f"Explorer: http://localhost:{_node_port}/explorer")
        info(f"Chain:    http://localhost:{_node_port}/chain")
    else:
        warn(f"Node is  {red('STOPPED')}")

# ---------------------------------------------------------------------------
# Demo runners
# ---------------------------------------------------------------------------

def run_script(script_name: str, extra_args=None):
    script = os.path.join(HERE, script_name)
    if not os.path.exists(script):
        err(f"Script not found: {script}")
        return
    cmd = [PYTHON, "-u", script] + (extra_args or [])
    info(f"Running: {' '.join(cmd)}")
    blank()
    thin()
    subprocess.run(cmd, cwd=HERE)
    thin()


# ---------------------------------------------------------------------------
# Wallet helpers
# ---------------------------------------------------------------------------

def run_wallet(sub_args):
    wallet_cli = os.path.join(HERE, "drn_wallet.py")
    if not os.path.exists(wallet_cli):
        err("drn_wallet.py not found")
        return
    subprocess.run([PYTHON, wallet_cli] + sub_args, cwd=HERE)


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def _pause():
    blank()
    input(dim("  Press Enter to continue…"))


def _ask(prompt, default=""):
    try:
        val = input(f"  {cyan('?')}  {prompt} [{dim(str(default))}]: ").strip()
        return val if val else str(default)
    except (EOFError, KeyboardInterrupt):
        return str(default)


def _choice(prompt, options):
    """Return selected index (0-based) or -1 on cancel."""
    blank()
    for i, opt in enumerate(options, 1):
        print(f"  {cyan(str(i))}.  {opt}")
    blank()
    raw = _ask(prompt, "0")
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return idx
    except ValueError:
        pass
    return -1

# ---------------------------------------------------------------------------
# Sub-menus
# ---------------------------------------------------------------------------

def menu_node():
    while True:
        header()
        section("Node Control")
        node_status()
        blank()
        print(f"  {cyan('1')}.  Start node")
        print(f"  {cyan('2')}.  Stop node")
        print(f"  {cyan('3')}.  Open block explorer in browser")
        print(f"  {cyan('4')}.  Node status")
        print(f"  {cyan('0')}.  Back")
        blank()
        choice = _ask("Select", "0")

        if choice == "1":
            section("Start Node")
            port = int(_ask("Port", "5000"))
            diff = int(_ask("Difficulty (2=fast, 4=realistic)", "3"))
            start_node(port, diff)
            _pause()

        elif choice == "2":
            section("Stop Node")
            stop_node()
            _pause()

        elif choice == "3":
            if _node_running():
                url = f"http://localhost:{_node_port}/explorer"
                ok(f"Opening {url}")
                webbrowser.open(url)
            else:
                warn("Start the node first.")
            _pause()

        elif choice == "4":
            section("Node Status")
            node_status()
            _pause()

        elif choice == "0":
            break


def menu_demos():
    while True:
        header()
        section("Stage Demos")
        blank()
        print(f"  {cyan('1')}.  {bold('9A')} Fee Prioritisation Demo")
        print(f"  {cyan('2')}.  {bold('9B')} Multi-Node P2P Consensus Demo")
        print(f"  {cyan('3')}.  {bold('9C')} TimeLock + MultiSig Scripting Demo")
        print(f"  {cyan('4')}.  Double-Spend Protection Demo")
        print(f"  {cyan('5')}.  Difficulty Retargeting Demo")
        print(f"  {cyan('6')}.  Persistent Storage Demo")
        print(f"  {cyan('7')}.  Wallet Signing Demo")
        print(f"  {cyan('0')}.  Back")
        blank()
        choice = _ask("Select", "0")

        if choice == "1":
            section("9A — Fee Prioritisation")
            run_script("fee_demo.py")
            _pause()
        elif choice == "2":
            section("9B — Multi-Node P2P Consensus")
            warn("This will start 3 local nodes on ports 5200-5202 and stop them when done.")
            if _ask("Continue? (y/n)", "y").lower() == "y":
                run_script("p2p_demo.py")
            _pause()
        elif choice == "3":
            section("9C — Transaction Scripting")
            run_script("scripting_demo.py")
            _pause()
        elif choice == "4":
            section("Double-Spend Protection Demo")
            run_script("double_spend_demo.py")
            _pause()
        elif choice == "5":
            section("Difficulty Retargeting Demo")
            run_script("retarget_demo.py")
            _pause()
        elif choice == "6":
            section("Persistent Storage Demo")
            run_script("storage_demo.py")
            _pause()
        elif choice == "7":
            section("Wallet Signing Demo")
            run_script("wallet_demo.py")
            _pause()
        elif choice == "0":
            break


def menu_wallet():
    while True:
        header()
        section("Wallet Manager")
        blank()
        print(f"  {cyan('1')}.  Create new wallet")
        print(f"  {cyan('2')}.  Check balance")
        print(f"  {cyan('3')}.  Send DRN")
        print(f"  {cyan('4')}.  Show wallet info")
        print(f"  {cyan('5')}.  List wallet files in data/")
        print(f"  {cyan('0')}.  Back")
        blank()
        choice = _ask("Select", "0")

        if choice == "1":
            section("Create Wallet")
            name = _ask("Key filename (saved to data/)", "my_wallet")
            out  = os.path.join(DATA_DIR, name + ".pem")
            run_wallet(["new", "--output", out])
            _pause()

        elif choice == "2":
            section("Check Balance")
            key = _ask("Key PEM file path", os.path.join(DATA_DIR, "my_wallet.pem"))
            port = _ask("Node port", str(_node_port))
            run_wallet(["balance", "--key", key, "--node", f"http://localhost:{port}"])
            _pause()

        elif choice == "3":
            section("Send DRN")
            key    = _ask("Sender key PEM", os.path.join(DATA_DIR, "my_wallet.pem"))
            to     = _ask("Recipient address", "")
            amount = _ask("Amount (DRN)", "1.0")
            fee    = _ask("Fee (DRN)", "0.0")
            lock   = _ask("Lock until block (0=none)", "0")
            port   = _ask("Node port", str(_node_port))
            args   = ["send", "--key", key, "--to", to,
                      "--amount", amount, "--fee", fee,
                      "--lock-until-block", lock,
                      "--node", f"http://localhost:{port}"]
            run_wallet(args)
            _pause()

        elif choice == "4":
            section("Wallet Info")
            key = _ask("Key PEM file path", os.path.join(DATA_DIR, "my_wallet.pem"))
            run_wallet(["info", "--key", key])
            _pause()

        elif choice == "5":
            section("Wallet files in data/")
            pems = [f for f in os.listdir(DATA_DIR) if f.endswith(".pem")]
            if pems:
                for p in pems:
                    full = os.path.join(DATA_DIR, p)
                    size = os.path.getsize(full)
                    print(f"  {cyan('·')}  {p}  {dim(str(size) + 'B')}")
            else:
                warn("No .pem files found in data/")
            _pause()

        elif choice == "0":
            break


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def main_menu():
    while True:
        header()

        # Status bar
        if _node_running():
            status = green(f"● Node running  :  http://localhost:{_node_port}/explorer")
        else:
            status = dim("○ Node stopped")
        print(f"  {status}")
        blank()
        divider("─")
        blank()

        print(f"  {cyan('1')}.  {bold('Node Control')}        "
              f"{dim('start · stop · explorer')}")
        print(f"  {cyan('2')}.  {bold('Stage Demos')}         "
              f"{dim('fee · p2p · scripting · double-spend · …')}")
        print(f"  {cyan('3')}.  {bold('Wallet Manager')}      "
              f"{dim('create · balance · send · list')}")
        print(f"  {cyan('4')}.  {bold('Quick Mine')}          "
              f"{dim('mine next block via running node')}")
        print(f"  {cyan('5')}.  {bold('Open Explorer')}       "
              f"{dim('launch block explorer in browser')}")
        print(f"  {cyan('6')}.  {bold('Re-run Setup')}        "
              f"{dim('re-check deps and directories')}")
        blank()
        print(f"  {cyan('0')}.  {bold('Exit')}")
        blank()
        divider("─")

        choice = _ask("Select option", "0")

        if choice == "1":
            menu_node()

        elif choice == "2":
            menu_demos()

        elif choice == "3":
            menu_wallet()

        elif choice == "4":
            section("Quick Mine")
            if not _node_running():
                warn("No node running — start one first (option 1).")
                _pause()
                continue
            port = _node_port
            try:
                import urllib.request, json
                url = f"http://localhost:{port}/"
                with urllib.request.urlopen(url, timeout=3) as r:
                    data = json.loads(r.read())
                miner = data.get("miner_address", "")
            except Exception:
                miner = ""
            if not miner:
                miner = _ask("Miner address (DRN1…)", "")
            if miner:
                info(f"Mining to {miner[:28]}...")
                try:
                    import urllib.request, json
                    url = f"http://localhost:{port}/mine?miner={miner}"
                    with urllib.request.urlopen(url, timeout=60) as r:
                        blk = json.loads(r.read()).get("block", {})
                    ok(f"Block #{blk.get('index')} mined!  "
                       f"hash={str(blk.get('hash',''))[:16]}...")
                except Exception as e:
                    err(f"Mining failed: {e}")
            _pause()

        elif choice == "5":
            if _node_running():
                url = f"http://localhost:{_node_port}/explorer"
                ok(f"Opening {url}")
                webbrowser.open(url)
            else:
                warn("Start the node first (option 1).")
            _pause()

        elif choice == "6":
            initialise()
            _pause()

        elif choice == "0":
            section("Shutdown")
            if _node_running():
                warn("Stopping running node…")
                stop_node()
            ok("Goodbye!")
            blank()
            sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        ok_init = initialise()
        if not ok_init:
            sys.exit(1)
        _pause()
        main_menu()
    except KeyboardInterrupt:
        blank()
        if _node_running():
            stop_node()
        ok("Exited.")
        sys.exit(0)
