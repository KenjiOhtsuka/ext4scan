# ext4scan/utils/logger.py

import sys
import os
from datetime import datetime

# Global flag for debug mode
DEBUG_ENABLED = False

# ANSI colors
COLOR_RESET = "\033[0m"
COLOR_DEBUG = "\033[36m"   # Cyan


def enable_debug():
    """Enable debug logging globally."""
    global DEBUG_ENABLED
    DEBUG_ENABLED = True
    log_debug("Debug mode enabled")


def log_debug(message: str):
    """Print debug message if debug mode is enabled."""
    if not DEBUG_ENABLED:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"{COLOR_DEBUG}[DEBUG {timestamp}] {message}{COLOR_RESET}"

    print(formatted, file=sys.stderr)
