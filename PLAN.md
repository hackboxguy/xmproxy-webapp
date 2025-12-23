# xmproxy-webapp Implementation Plan

## Overview

A Flask-based web application for managing the XMPP proxy service (xmproxysrv) settings in the vmbox Alpine-based VM framework.

**Port**: 8006
**Startup Priority**: 75 (after jsonrpc-tcp-srv which is 70)
**Technology Stack**: Python + Flask/Jinja2
**Build System**: CMake

---

## Table of Contents

1. [Architecture](#architecture)
2. [Directory Structure](#directory-structure)
3. [Backend Modules](#backend-modules)
4. [API Endpoints](#api-endpoints)
5. [JSON-RPC Integration](#json-rpc-integration)
6. [Configuration Management](#configuration-management)
7. [Service Restart Strategy](#service-restart-strategy)
8. [Frontend Design](#frontend-design)
9. [Build Configuration](#build-configuration)
10. [Implementation Checklist](#implementation-checklist)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         xmproxy-webapp (port 8006)                       │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────────────┐  │
│  │  Browser    │───>│  Flask Server    │───>│  xmproxy_client.py     │  │
│  │  (JS/HTML)  │<───│  (server.py)     │<───│  (JSON-RPC TCP)        │  │
│  └─────────────┘    └──────────────────┘    └───────────┬─────────────┘  │
│                              │                          │                │
│                              │                          │                │
│                     ┌────────▼────────┐         ┌───────▼───────┐        │
│                     │ config_manager  │         │  xmproxysrv   │        │
│                     │ - xmpp-login.txt│         │  (port 40005) │        │
│                     │ - presets/      │         └───────────────┘        │
│                     │ - backups/      │                                  │
│                     └─────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
apps/xmproxy-webapp/
├── CMakeLists.txt                    # Build configuration
├── manifest.template.json            # App manifest template
├── PLAN.md                           # This file
├── src/
│   ├── server.py                     # Flask application (main entry point)
│   ├── config.py                     # Path constants, webapp configuration
│   ├── xmproxy_client.py             # JSON-RPC TCP client for xmproxysrv
│   └── config_manager.py             # XMPP config file & preset management
├── share/www/
│   ├── index.html                    # Main UI template (Jinja2)
│   ├── css/
│   │   └── style.css                 # Dark theme using design tokens
│   └── js/
│       └── app.js                    # Frontend JavaScript logic
└── etc/
    └── config.json.default           # Default webapp configuration
```

---

## Backend Modules

### 1. config.py

Path constants and webapp configuration management.

```python
# Path constants
APP_NAME = "xmproxy-webapp"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DATA_DIR = os.environ.get('APP_DATA_DIR', f'/data/app-data/{APP_NAME}')
APP_CONFIG_DIR = os.environ.get('APP_CONFIG_DIR', f'/data/app-config/{APP_NAME}')
APP_LOG_FILE = os.environ.get('APP_LOG_FILE', f'/var/log/app/{APP_NAME}.log')

# xmproxysrv config paths (in jsonrpc-tcp-srv config dir)
XMPROXY_CONFIG_DIR = '/data/app-config/jsonrpc-tcp-srv'
XMPP_LOGIN_FILE = os.path.join(XMPROXY_CONFIG_DIR, 'xmpp-login.txt')
PRESETS_DIR = os.path.join(XMPROXY_CONFIG_DIR, 'presets')

# Backup settings
BACKUP_DIR = os.path.join(APP_DATA_DIR, 'backups')
MAX_BACKUPS = 5

# xmproxysrv connection
XMPROXY_HOST = '127.0.0.1'
XMPROXY_PORT = 40005
XMPROXY_TIMEOUT = 5

# Webapp defaults
DEFAULT_CONFIG = {
    "port": 8006,
    "host": "0.0.0.0",
    "status_poll_interval": 5000,  # ms
    "restart_timeout": 30          # seconds
}
```

### 2. xmproxy_client.py

JSON-RPC TCP client for communicating with xmproxysrv.

```python
class XmproxyClient:
    """JSON-RPC 2.0 TCP client for xmproxysrv"""

    def __init__(self, host='127.0.0.1', port=40005, timeout=5):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._id_counter = 0

    def _next_id(self):
        self._id_counter += 1
        return self._id_counter

    def call(self, method, params=None):
        """Send JSON-RPC request and receive response"""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_id()
        }

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect((self.host, self.port))
            sock.sendall(json.dumps(request).encode('utf-8') + b'\n')

            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b'\n' in response_data:
                    break

            response = json.loads(response_data.decode('utf-8').strip())

            if 'error' in response:
                raise XmproxyError(response['error'])

            return response.get('result', {})
        finally:
            sock.close()

    def is_connected(self):
        """Check if xmproxysrv is reachable"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((self.host, self.port))
            sock.close()
            return True
        except:
            return False

    def get_online_status(self):
        """Get XMPP connection status"""
        try:
            result = self.call("get_online_status")
            return result.get("status", "unknown")
        except:
            return "disconnected"

    def shutdown(self):
        """Request graceful shutdown of xmproxysrv"""
        try:
            return self.call("shutdown")
        except:
            return None


class XmproxyError(Exception):
    """Exception for xmproxysrv errors"""
    pass
```

### 3. config_manager.py

XMPP configuration file and preset management.

```python
class XmppConfigManager:
    """Manages xmpp-login.txt and presets"""

    VALID_KEYS = [
        'user', 'pw', 'adminbuddy',
        'bosh', 'boshurl', 'boshhost',
        'tlsverify', 'saslmech'
    ]

    def __init__(self, config_file, presets_dir, backup_dir, max_backups=5):
        self.config_file = config_file
        self.presets_dir = presets_dir
        self.backup_dir = backup_dir
        self.max_backups = max_backups

        # Ensure directories exist
        os.makedirs(presets_dir, exist_ok=True)
        os.makedirs(backup_dir, exist_ok=True)

    def parse_config(self, filepath):
        """Parse xmpp-login.txt format into dict"""
        config = {}
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        if key in self.VALID_KEYS:
                            # Convert boolean strings
                            if value.lower() in ('true', 'false'):
                                value = value.lower() == 'true'
                            config[key] = value
        return config

    def write_config(self, filepath, config):
        """Write config dict to xmpp-login.txt format"""
        with open(filepath, 'w') as f:
            for key in self.VALID_KEYS:
                if key in config and config[key] is not None:
                    value = config[key]
                    if isinstance(value, bool):
                        value = 'true' if value else 'false'
                    f.write(f"{key}: {value}\n")

    def load_config(self):
        """Load current xmpp-login.txt"""
        return self.parse_config(self.config_file)

    def save_config(self, config, create_backup=True):
        """Save config to xmpp-login.txt with optional backup"""
        if create_backup and os.path.exists(self.config_file):
            self._create_backup()
        self.write_config(self.config_file, config)

    def _create_backup(self):
        """Create timestamped backup, enforce max_backups limit"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"xmpp-login_{timestamp}.txt"
        backup_path = os.path.join(self.backup_dir, backup_name)

        shutil.copy2(self.config_file, backup_path)

        # Cleanup old backups (keep only max_backups most recent)
        backups = sorted(glob.glob(os.path.join(self.backup_dir, 'xmpp-login_*.txt')))
        while len(backups) > self.max_backups:
            os.remove(backups.pop(0))

    def list_presets(self):
        """List all preset names"""
        presets = []
        for f in glob.glob(os.path.join(self.presets_dir, '*.txt')):
            name = os.path.splitext(os.path.basename(f))[0]
            presets.append(name)
        return sorted(presets)

    def load_preset(self, name):
        """Load a preset by name"""
        preset_file = os.path.join(self.presets_dir, f"{name}.txt")
        if not os.path.exists(preset_file):
            raise FileNotFoundError(f"Preset '{name}' not found")
        return self.parse_config(preset_file)

    def save_preset(self, name, config):
        """Save config as named preset"""
        # Sanitize name
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        preset_file = os.path.join(self.presets_dir, f"{safe_name}.txt")
        self.write_config(preset_file, config)
        return safe_name

    def delete_preset(self, name):
        """Delete a preset by name"""
        preset_file = os.path.join(self.presets_dir, f"{name}.txt")
        if os.path.exists(preset_file):
            os.remove(preset_file)
            return True
        return False

    def list_backups(self):
        """List all backups with timestamps"""
        backups = []
        for f in sorted(glob.glob(os.path.join(self.backup_dir, 'xmpp-login_*.txt')), reverse=True):
            name = os.path.basename(f)
            mtime = os.path.getmtime(f)
            backups.append({
                'name': name,
                'timestamp': datetime.fromtimestamp(mtime).isoformat()
            })
        return backups

    def restore_backup(self, name):
        """Restore a backup file"""
        backup_file = os.path.join(self.backup_dir, name)
        if os.path.exists(backup_file):
            self._create_backup()  # Backup current before restore
            shutil.copy2(backup_file, self.config_file)
            return True
        return False
```

### 4. server.py

Flask application with all API routes.

```python
#!/usr/bin/env python3
"""
xmproxy-webapp - XMPP Proxy Configuration Web Application
"""

import os
import sys
import time
import signal
import logging
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory

from config import *
from xmproxy_client import XmproxyClient, XmproxyError
from config_manager import XmppConfigManager

# Initialize Flask app
app = Flask(__name__,
            template_folder=os.path.join(APP_ROOT, 'share/www'),
            static_folder=os.path.join(APP_ROOT, 'share/www'))

# Initialize components
xmproxy = XmproxyClient(XMPROXY_HOST, XMPROXY_PORT, XMPROXY_TIMEOUT)
config_mgr = XmppConfigManager(XMPP_LOGIN_FILE, PRESETS_DIR, BACKUP_DIR, MAX_BACKUPS)

# Track startup time
START_TIME = time.time()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(APP_LOG_FILE) if os.path.exists(os.path.dirname(APP_LOG_FILE)) else logging.StreamHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# Static files and main page
# ============================================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory(os.path.join(app.static_folder, 'css'), filename)

@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory(os.path.join(app.static_folder, 'js'), filename)


# ============================================================================
# Health check
# ============================================================================

@app.route('/health')
def health():
    uptime = int(time.time() - START_TIME)
    return jsonify({
        'status': 'healthy',
        'uptime_seconds': uptime,
        'service': APP_NAME
    })


# ============================================================================
# Status API - xmproxysrv connection status
# ============================================================================

@app.route('/api/status')
def get_status():
    """Get xmproxysrv connection status for LED indicator"""
    try:
        if not xmproxy.is_connected():
            return jsonify({
                'status': 'disconnected',
                'service_running': False,
                'message': 'xmproxysrv not reachable'
            })

        online_status = xmproxy.get_online_status()
        return jsonify({
            'status': online_status,
            'service_running': True,
            'message': f'XMPP status: {online_status}'
        })
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({
            'status': 'error',
            'service_running': False,
            'message': str(e)
        }), 500


# ============================================================================
# Config API - xmpp-login.txt management
# ============================================================================

@app.route('/api/config', methods=['GET'])
def get_config():
    """Load current xmpp-login.txt configuration"""
    try:
        config = config_mgr.load_config()
        # Mask password for security
        if 'pw' in config:
            config['pw_masked'] = '*' * len(str(config.get('pw', '')))
        return jsonify({'status': 'ok', 'config': config})
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/config', methods=['POST'])
def save_config():
    """Save configuration to xmpp-login.txt"""
    try:
        data = request.get_json()
        config = data.get('config', {})
        restart = data.get('restart', False)

        # Validate required fields
        if not config.get('user'):
            return jsonify({'status': 'error', 'message': 'JID (user) is required'}), 400
        if not config.get('pw'):
            return jsonify({'status': 'error', 'message': 'Password is required'}), 400

        # Save with backup
        config_mgr.save_config(config, create_backup=True)
        logger.info("Configuration saved successfully")

        result = {'status': 'ok', 'message': 'Configuration saved'}

        # Restart service if requested
        if restart:
            restart_result = restart_xmproxy_service()
            result['restart'] = restart_result

        return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# Presets API
# ============================================================================

@app.route('/api/presets', methods=['GET'])
def list_presets():
    """List all saved presets"""
    try:
        presets = config_mgr.list_presets()
        return jsonify({'status': 'ok', 'presets': presets})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/presets', methods=['POST'])
def save_preset():
    """Save current config as a new preset"""
    try:
        data = request.get_json()
        name = data.get('name')
        config = data.get('config')

        if not name:
            return jsonify({'status': 'error', 'message': 'Preset name is required'}), 400
        if not config:
            return jsonify({'status': 'error', 'message': 'Config data is required'}), 400

        saved_name = config_mgr.save_preset(name, config)
        logger.info(f"Preset saved: {saved_name}")
        return jsonify({'status': 'ok', 'name': saved_name})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/presets/<name>', methods=['GET'])
def load_preset(name):
    """Load a preset (returns config without applying)"""
    try:
        config = config_mgr.load_preset(name)
        return jsonify({'status': 'ok', 'config': config})
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': f"Preset '{name}' not found"}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/presets/<name>', methods=['DELETE'])
def delete_preset(name):
    """Delete a preset"""
    try:
        if config_mgr.delete_preset(name):
            logger.info(f"Preset deleted: {name}")
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Preset not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# Backups API
# ============================================================================

@app.route('/api/backups', methods=['GET'])
def list_backups():
    """List all configuration backups"""
    try:
        backups = config_mgr.list_backups()
        return jsonify({'status': 'ok', 'backups': backups})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/backups/<name>/restore', methods=['POST'])
def restore_backup(name):
    """Restore a backup"""
    try:
        if config_mgr.restore_backup(name):
            logger.info(f"Backup restored: {name}")
            return jsonify({'status': 'ok', 'message': 'Backup restored'})
        return jsonify({'status': 'error', 'message': 'Backup not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============================================================================
# Service restart API
# ============================================================================

@app.route('/api/service/restart', methods=['POST'])
def api_restart_service():
    """Restart xmproxysrv service"""
    try:
        result = restart_xmproxy_service()
        if result['success']:
            return jsonify({'status': 'ok', 'message': result['message']})
        return jsonify({'status': 'error', 'message': result['message']}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def restart_xmproxy_service():
    """
    Restart xmproxysrv service.
    Uses the restart script in jsonrpc-tcp-srv.
    """
    logger.info("Restarting xmproxysrv service...")

    try:
        # Use the restart script
        restart_script = '/app/jsonrpc-tcp-srv/scripts/restart-xmproxy.sh'

        if os.path.exists(restart_script):
            result = subprocess.run(
                [restart_script],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                logger.info("xmproxysrv restarted successfully")
                return {'success': True, 'message': 'Service restarted successfully'}
            else:
                logger.error(f"Restart failed: {result.stderr}")
                return {'success': False, 'message': f'Restart failed: {result.stderr}'}

        # Fallback: Try JSON-RPC shutdown + wait for auto-restart
        logger.info("Using JSON-RPC shutdown method...")
        xmproxy.shutdown()

        # Wait for service to restart (startup script should restart it)
        time.sleep(3)

        # Poll for service to come back
        for i in range(10):
            if xmproxy.is_connected():
                logger.info("xmproxysrv is back online")
                return {'success': True, 'message': 'Service restarted successfully'}
            time.sleep(1)

        return {'success': False, 'message': 'Service did not restart within timeout'}

    except subprocess.TimeoutExpired:
        return {'success': False, 'message': 'Restart script timed out'}
    except Exception as e:
        logger.error(f"Restart failed: {e}")
        return {'success': False, 'message': str(e)}


# ============================================================================
# Main entry point
# ============================================================================

def main():
    """Main entry point"""
    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal, exiting...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Load webapp config
    webapp_config = load_webapp_config()
    host = webapp_config.get('host', '0.0.0.0')
    port = webapp_config.get('port', 8006)

    logger.info(f"Starting {APP_NAME} on {host}:{port}")

    # Run Flask app
    app.run(host=host, port=port, debug=False, threaded=True)


def load_webapp_config():
    """Load webapp configuration from config.json"""
    config_file = os.path.join(APP_CONFIG_DIR, 'config.json')
    default_config = os.path.join(APP_ROOT, 'etc/config.json.default')

    if os.path.exists(config_file):
        with open(config_file) as f:
            return json.load(f)
    elif os.path.exists(default_config):
        with open(default_config) as f:
            return json.load(f)

    return DEFAULT_CONFIG


if __name__ == '__main__':
    main()
```

---

## API Endpoints

| Endpoint | Method | Description | Request Body | Response |
|----------|--------|-------------|--------------|----------|
| `/health` | GET | Health check | - | `{status, uptime_seconds}` |
| `/api/status` | GET | XMPP connection status | - | `{status, service_running, message}` |
| `/api/config` | GET | Load current config | - | `{status, config}` |
| `/api/config` | POST | Save config | `{config, restart?}` | `{status, message}` |
| `/api/presets` | GET | List presets | - | `{status, presets[]}` |
| `/api/presets` | POST | Save preset | `{name, config}` | `{status, name}` |
| `/api/presets/<name>` | GET | Load preset | - | `{status, config}` |
| `/api/presets/<name>` | DELETE | Delete preset | - | `{status}` |
| `/api/backups` | GET | List backups | - | `{status, backups[]}` |
| `/api/backups/<name>/restore` | POST | Restore backup | - | `{status, message}` |
| `/api/service/restart` | POST | Restart xmproxysrv | - | `{status, message}` |

### Status Values

| Status | LED Color | Meaning |
|--------|-----------|---------|
| `online` | Green | Connected to XMPP server |
| `offline` | Red | Not connected |
| `disconnected` | Red | xmproxysrv not reachable |
| `unknown` | Yellow | Status unknown / connecting |
| `error` | Red | Error occurred |

---

## JSON-RPC Integration

### xmproxysrv Methods (port 40005)

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `get_online_status` | - | `{status}` | Get XMPP connection status |
| `set_online_status` | `{status}` | - | Force online/offline |
| `send_message` | `{to, msg}` | - | Send XMPP message |
| `get_inbox_count` | - | `{count}` | Get inbox message count |
| `get_inbox_message` | `{index}` | `{message}` | Read message by index |
| `empty_inbox` | - | - | Clear inbox |
| `shutdown` | - | - | Graceful shutdown |

### JSON-RPC 2.0 Protocol

```json
// Request
{
  "jsonrpc": "2.0",
  "method": "get_online_status",
  "params": {},
  "id": 1
}

// Response
{
  "jsonrpc": "2.0",
  "result": {"status": "online"},
  "id": 1
}
```

---

## Configuration Management

### xmpp-login.txt Format

```
user: bot@server.example.org
pw: secretpassword
adminbuddy: admin@server.example.org
bosh: true
boshurl: https://server:443/http-bind
boshhost: server.example.org
tlsverify: false
saslmech: scram-sha-1
```

### Configuration Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `user` | Yes | string | XMPP JID (user@domain) |
| `pw` | Yes | string | Password |
| `adminbuddy` | No | string | Admin contact JID |
| `bosh` | No | boolean | Use BOSH transport |
| `boshurl` | No | string | BOSH endpoint URL |
| `boshhost` | No | string | BOSH host |
| `tlsverify` | No | boolean | Verify TLS certificates |
| `saslmech` | No | string | SASL mechanism (scram-sha-1, plain) |

### File Locations

```
/data/app-config/jsonrpc-tcp-srv/
├── xmpp-login.txt              # Current config
└── presets/
    ├── production.txt
    ├── staging.txt
    └── local-test.txt

/data/app-data/xmproxy-webapp/
└── backups/
    ├── xmpp-login_20250122_103045.txt
    ├── xmpp-login_20250122_093012.txt
    └── ...                      # Max 5 backups
```

---

## Service Restart Strategy

### New Script: restart-xmproxy.sh

Add to `/app/jsonrpc-tcp-srv/scripts/restart-xmproxy.sh`:

```bash
#!/bin/sh
#
# restart-xmproxy.sh - Restart only xmproxysrv service
#
# This script is called by xmproxy-webapp to restart xmproxysrv
# after configuration changes.
#

APP_DIR="/app/jsonrpc-tcp-srv"
CONFIG_DIR="/data/app-config/jsonrpc-tcp-srv"
LOG_DIR="/var/log/app"
RUN_DIR="/run/app"

XMPROXY_PORT=40005
XMPROXY_BIN="${APP_DIR}/bin/xmproxysrv"
XMPROXY_PID="${RUN_DIR}/xmproxysrv.pid"
XMPROXY_LOG="${LOG_DIR}/xmproxysrv.log"
XMPP_LOGIN="${CONFIG_DIR}/xmpp-login.txt"

log_info() {
    echo "[INFO] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
}

# Stop xmproxysrv
stop_xmproxy() {
    if [ -f "${XMPROXY_PID}" ]; then
        PID=$(cat "${XMPROXY_PID}")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "Stopping xmproxysrv (PID: $PID)..."
            kill -TERM "$PID" 2>/dev/null

            # Wait for process to exit
            for i in $(seq 1 10); do
                if ! kill -0 "$PID" 2>/dev/null; then
                    break
                fi
                sleep 0.5
            done

            # Force kill if still running
            if kill -0 "$PID" 2>/dev/null; then
                log_info "Force killing xmproxysrv..."
                kill -KILL "$PID" 2>/dev/null
            fi
        fi
        rm -f "${XMPROXY_PID}"
    fi
}

# Start xmproxysrv
start_xmproxy() {
    log_info "Starting xmproxysrv on port ${XMPROXY_PORT}..."

    if [ ! -x "${XMPROXY_BIN}" ]; then
        log_error "xmproxysrv binary not found: ${XMPROXY_BIN}"
        return 1
    fi

    # Build arguments
    XMPROXY_ARGS="--port=${XMPROXY_PORT}"

    if [ -f "${XMPP_LOGIN}" ]; then
        XMPROXY_ARGS="${XMPROXY_ARGS} --loginfile=${XMPP_LOGIN}"
    fi

    if [ -f "${CONFIG_DIR}/xmpp-alias-list.txt" ]; then
        XMPROXY_ARGS="${XMPROXY_ARGS} --aliaslist=${CONFIG_DIR}/xmpp-alias-list.txt"
    fi

    if [ -f "${CONFIG_DIR}/xmpp-bot-name.txt" ]; then
        XMPROXY_ARGS="${XMPROXY_ARGS} --botname=${CONFIG_DIR}/xmpp-bot-name.txt"
    fi

    # Set library path
    export LD_LIBRARY_PATH="${APP_DIR}/lib:${LD_LIBRARY_PATH}"

    # Start in background
    "${XMPROXY_BIN}" ${XMPROXY_ARGS} >> "${XMPROXY_LOG}" 2>&1 &
    echo $! > "${XMPROXY_PID}"

    # Wait for port to be available
    for i in $(seq 1 10); do
        if nc -z 127.0.0.1 "${XMPROXY_PORT}" 2>/dev/null; then
            log_info "xmproxysrv started successfully"
            return 0
        fi
        sleep 1
    done

    log_error "xmproxysrv failed to start within timeout"
    return 1
}

# Main
main() {
    stop_xmproxy
    sleep 1
    start_xmproxy
}

main "$@"
```

### Modifications to start-services.sh

Update the main loop to support external restart:

```bash
# In the monitoring loop, check for restart signal file
while true; do
    # ... existing health checks ...

    # Check for restart request
    if [ -f "${RUN_DIR}/restart-xmproxy.flag" ]; then
        rm -f "${RUN_DIR}/restart-xmproxy.flag"
        log_info "Restart requested for xmproxysrv"

        # Stop xmproxysrv
        if [ -f "${XMPROXY_PID}" ]; then
            PID=$(cat "${XMPROXY_PID}")
            kill -TERM "$PID" 2>/dev/null
            sleep 2
        fi

        # Restart it
        start_xmproxy
    fi

    sleep 5
done
```

---

## Frontend Design

### UI Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  XMPP Proxy Configuration                                    [●] Status │
│  Configure xmproxysrv XMPP connection settings                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ PRESETS ──────────────────────────────────────────────────────────┐ │
│  │  [Select preset...              ▼]  [Load] [Save As...] [Delete]   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─ XMPP CREDENTIALS ─────────────────────────────────────────────────┐ │
│  │  JID (User)      [_________________________________]               │ │
│  │  Password        [_________________________________] [👁]          │ │
│  │  Admin Buddy     [_________________________________]               │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ☐ Use BOSH Transport                                                   │
│                                                                         │
│  ┌─ BOSH SETTINGS ────────────────────────────────────────────────────┐ │
│  │  BOSH URL        [_________________________________]               │ │
│  │  BOSH Host       [_________________________________]               │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─ ADVANCED SETTINGS ────────────────────────────────────────────────┐ │
│  │  TLS Verify      [Enabled         ▼]                               │ │
│  │  SASL Mechanism  [scram-sha-1     ▼]                               │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─ BACKUPS ──────────────────────────────────────────────────────────┐ │
│  │  • xmpp-login_20250122_103045.txt  [Restore]                       │ │
│  │  • xmpp-login_20250122_093012.txt  [Restore]                       │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  [Save]  [Save & Restart Service]                        [Restart Only] │
│                                                                         │
│  ┌─ STATUS ───────────────────────────────────────────────────────────┐ │
│  │  Last saved: 2025-01-22 10:30:45                                   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### LED Status Indicator

```javascript
// Status polling every 5 seconds
async function pollStatus() {
    const response = await fetch(getBasePath() + 'api/status');
    const data = await response.json();

    const led = document.getElementById('status-led');
    led.className = 'status-led';

    switch(data.status) {
        case 'online':
            led.classList.add('online');    // Green
            break;
        case 'offline':
        case 'disconnected':
        case 'error':
            led.classList.add('offline');   // Red
            break;
        default:
            led.classList.add('connecting'); // Yellow
    }
}
```

### CSS Status LED

```css
.status-led {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--status-error);
    animation: pulse 2s infinite;
}

.status-led.online {
    background: var(--status-success);
}

.status-led.offline {
    background: var(--status-error);
}

.status-led.connecting {
    background: var(--status-warning);
}
```

### Form Validation

```javascript
function validateForm() {
    const user = document.getElementById('user').value;
    const pw = document.getElementById('pw').value;

    // JID format: user@domain
    const jidRegex = /^[^@]+@[^@]+$/;
    if (!jidRegex.test(user)) {
        showError('Invalid JID format. Expected: user@domain');
        return false;
    }

    if (!pw) {
        showError('Password is required');
        return false;
    }

    // Validate BOSH URL if enabled
    if (document.getElementById('bosh').checked) {
        const boshurl = document.getElementById('boshurl').value;
        if (boshurl && !isValidUrl(boshurl)) {
            showError('Invalid BOSH URL format');
            return false;
        }
    }

    return true;
}
```

---

## Build Configuration

### CMakeLists.txt

```cmake
cmake_minimum_required(VERSION 3.10)
project(xmproxy-webapp VERSION 1.0.0)

# Install Python server and modules
install(PROGRAMS src/server.py
        DESTINATION bin
        RENAME xmproxy-webapp-server)

install(FILES
        src/config.py
        src/xmproxy_client.py
        src/config_manager.py
        DESTINATION bin)

# Install web assets
install(DIRECTORY share/www/
        DESTINATION share/www)

# Install default config
install(FILES etc/config.json.default
        DESTINATION etc)

# Generate and install manifest
configure_file(manifest.template.json
               ${CMAKE_CURRENT_BINARY_DIR}/manifest.json
               @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/manifest.json
        DESTINATION .)
```

### manifest.template.json

```json
{
  "name": "@PROJECT_NAME@",
  "version": "@PROJECT_VERSION@",
  "description": "XMPP Proxy Configuration",
  "type": "webapp",
  "port": 8006,
  "url": "/",

  "health": {
    "type": "http",
    "endpoint": "/health",
    "port": 8006,
    "interval": 10,
    "timeout": 5
  },

  "startup": {
    "command": "/app/@PROJECT_NAME@/bin/xmproxy-webapp-server",
    "args": [],
    "working_dir": "/app/@PROJECT_NAME@",
    "priority": 75,
    "depends_on": ["jsonrpc-tcp-srv"]
  },

  "shutdown": {
    "timeout": 10,
    "signal": "SIGTERM"
  },

  "data_dirs": ["backups"],

  "config_files": [
    {"source": "etc/config.json.default", "dest": "config.json"}
  ],

  "env": {
    "APP_DATA_DIR": "/data/app-data/@PROJECT_NAME@",
    "APP_CONFIG_DIR": "/data/app-config/@PROJECT_NAME@",
    "APP_LOG_FILE": "/var/log/app/@PROJECT_NAME@.log"
  }
}
```

### etc/config.json.default

```json
{
  "port": 8006,
  "host": "0.0.0.0",
  "status_poll_interval": 5000,
  "restart_timeout": 30
}
```

### packages.txt Entry

```
xmproxy-webapp|file://${PROJECT_ROOT}/apps/xmproxy-webapp|HEAD||cmake,python3|8006|75|webapp|XMPP Proxy Configuration
```

---

## Implementation Checklist

### Phase 1: Project Setup
- [ ] Create directory structure
- [ ] Create CMakeLists.txt
- [ ] Create manifest.template.json
- [ ] Create etc/config.json.default

### Phase 2: Backend Implementation
- [ ] Implement config.py (path constants)
- [ ] Implement xmproxy_client.py (JSON-RPC TCP client)
- [ ] Implement config_manager.py (config file management)
- [ ] Implement server.py (Flask application)

### Phase 3: Frontend Implementation
- [ ] Create index.html (UI template)
- [ ] Create css/style.css (dark theme)
- [ ] Create js/app.js (frontend logic)

### Phase 4: Service Integration
- [ ] Create restart-xmproxy.sh script
- [ ] Update start-services.sh for restart support
- [ ] Add entry to packages.txt

### Phase 5: Testing
- [ ] Test JSON-RPC communication
- [ ] Test config save/load
- [ ] Test preset management
- [ ] Test backup/restore
- [ ] Test service restart
- [ ] Test UI functionality

---

## Notes

1. **Credential Testing**: Uses save-restart-poll approach. After saving config, restart service and poll status to verify connection.

2. **Service Restart**: Modified startup script supports external restart via dedicated restart-xmproxy.sh script.

3. **Backups**: Keeps 5 most recent backups with timestamps.

4. **Security**: Password is masked in UI with reveal toggle. Config file contains plaintext password (same as current implementation).

5. **Dependencies**:
   - Runtime: Python 3, Flask
   - Build: CMake

---

*Last Updated: 2025-01-22*
