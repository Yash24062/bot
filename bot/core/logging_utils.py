"""
Logging and debug utilities for TRAMA Modular Bot
Author: Jarvis 2.0 (for Boss)
"""

import sys
import os
from datetime import datetime
from colorama import Fore, Style, init

# Initialize colorama (safe even if already called)
init(autoreset=True)

# ------------------ Tee Logger ------------------

class Tee:
    """
    Duplicates output to both console and file.
    Example:
        log_file, original = setup_file_logging("my_log.txt")
        print("This prints to both console and log file")
        restore_stdout(log_file, original)
    """
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()

# ------------------ File Logging Setup ------------------

def setup_file_logging(log_file_path: str):
    """
    Redirect stdout to a file (while still showing console output).
    Returns: (log_file, original_stdout)
    """
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    log_file = open(log_file_path, "w", encoding="utf-8")
    original_stdout = sys.stdout
    sys.stdout = Tee(original_stdout, log_file)
    return log_file, original_stdout

def restore_stdout(log_file, original_stdout):
    """
    Restore stdout to its original state.
    """
    sys.stdout = original_stdout
    log_file.close()

# ------------------ Color Printing ------------------

def log_info(msg: str):
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} {msg}")

def log_success(msg: str):
    print(f"{Fore.GREEN}[SUCCESS]{Style.RESET_ALL} {msg}")

def log_warning(msg: str):
    print(f"{Fore.YELLOW}[WARNING]{Style.RESET_ALL} {msg}")

def log_error(msg: str):
    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {msg}")

# ------------------ Debug Helper ------------------

def debug_print(enabled: bool, msg: str):
    """
    Print debug info only if enabled.
    """
    if enabled:
        print(f"{Fore.MAGENTA}[DEBUG]{Style.RESET_ALL} {msg}")

# ------------------ Timestamped Filenames ------------------

def timestamped_filename(prefix: str, ext: str = ".txt") -> str:
    """
    Generate a unique timestamped filename.
    Example: logs/trades_BTCUSDT_5m_20251012_182045.txt
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}{ext}"

# ------------------ Example ------------------

if __name__ == "__main__":
    log_info("System initialized.")
    log_warning("This is a test warning.")
    log_error("Error example.")
    log_success("All systems functional.")
    debug_print(True, "Debug test active.")
