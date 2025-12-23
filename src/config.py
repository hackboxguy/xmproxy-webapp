"""
config.py - Path constants and configuration for xmproxy-webapp
"""

import os
import json

# Application identity
APP_NAME = "xmproxy-webapp"

# Determine APP_ROOT (parent of src directory)
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Runtime directories (from environment or defaults)
APP_DATA_DIR = os.environ.get('APP_DATA_DIR', f'/data/app-data/{APP_NAME}')
APP_CONFIG_DIR = os.environ.get('APP_CONFIG_DIR', f'/data/app-config/{APP_NAME}')
APP_LOG_FILE = os.environ.get('APP_LOG_FILE', f'/var/log/app/{APP_NAME}.log')

# Static files directory
STATIC_DIR = os.path.join(APP_ROOT, 'share', 'www')

# xmproxysrv config paths (managed by jsonrpc-tcp-srv)
XMPROXY_CONFIG_DIR = '/data/app-config/jsonrpc-tcp-srv'
XMPP_LOGIN_FILE = os.path.join(XMPROXY_CONFIG_DIR, 'xmpp-login.txt')
PRESETS_DIR = os.path.join(XMPROXY_CONFIG_DIR, 'presets')

# Backup settings
BACKUP_DIR = os.path.join(APP_DATA_DIR, 'backups')
MAX_BACKUPS = 5

# xmproxysrv connection settings
XMPROXY_HOST = '127.0.0.1'
XMPROXY_PORT = 40005
XMPROXY_TIMEOUT = 5

# Restart script location
RESTART_SCRIPT = '/app/jsonrpc-tcp-srv/scripts/restart-xmproxy.sh'

# Default webapp configuration
DEFAULT_CONFIG = {
    "port": 8006,
    "host": "0.0.0.0",
    "status_poll_interval": 5000,
    "restart_timeout": 30
}


def load_webapp_config():
    """Load webapp configuration from config.json or defaults"""
    config_file = os.path.join(APP_CONFIG_DIR, 'config.json')
    default_file = os.path.join(APP_ROOT, 'etc', 'config.json.default')

    config = DEFAULT_CONFIG.copy()

    # Try loading from config directory first
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                config.update(user_config)
        except Exception:
            pass
    # Fall back to default config in app directory
    elif os.path.exists(default_file):
        try:
            with open(default_file, 'r') as f:
                default_config = json.load(f)
                config.update(default_config)
        except Exception:
            pass

    return config


def ensure_directories():
    """Ensure all required directories exist"""
    dirs = [
        APP_DATA_DIR,
        APP_CONFIG_DIR,
        BACKUP_DIR,
        PRESETS_DIR,
        os.path.dirname(APP_LOG_FILE)
    ]

    for d in dirs:
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
