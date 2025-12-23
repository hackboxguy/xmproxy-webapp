#!/usr/bin/env python3
"""
server.py - XMPP Proxy Configuration Web Application

Flask-based webapp for managing xmproxysrv XMPP settings.
"""

import os
import sys
import time
import signal
import logging
import subprocess
import json

from flask import Flask, request, jsonify, render_template, send_from_directory

# Import local modules
from config import (
    APP_NAME, APP_ROOT, APP_DATA_DIR, APP_CONFIG_DIR, APP_LOG_FILE,
    STATIC_DIR, XMPP_LOGIN_FILE, PRESETS_DIR, BACKUP_DIR, MAX_BACKUPS,
    XMPROXY_HOST, XMPROXY_PORT, XMPROXY_TIMEOUT, RESTART_SCRIPT,
    load_webapp_config, ensure_directories
)
from xmproxy_client import XmproxyClient, XmproxyError
from config_manager import XmppConfigManager

# Track startup time for health endpoint
START_TIME = time.time()

# Initialize Flask app
app = Flask(__name__,
            template_folder=STATIC_DIR,
            static_folder=STATIC_DIR)

# Initialize components (after ensure_directories)
xmproxy = None
config_mgr = None
logger = None


def setup_logging():
    """Configure logging"""
    global logger

    handlers = [logging.StreamHandler()]

    # Add file handler if log directory exists
    log_dir = os.path.dirname(APP_LOG_FILE)
    if os.path.exists(log_dir):
        try:
            handlers.append(logging.FileHandler(APP_LOG_FILE))
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=handlers
    )

    logger = logging.getLogger(APP_NAME)


def init_components():
    """Initialize global components"""
    global xmproxy, config_mgr

    ensure_directories()

    xmproxy = XmproxyClient(XMPROXY_HOST, XMPROXY_PORT, XMPROXY_TIMEOUT)
    config_mgr = XmppConfigManager(XMPP_LOGIN_FILE, PRESETS_DIR, BACKUP_DIR, MAX_BACKUPS)


# ============================================================================
# Static files and main page
# ============================================================================

@app.route('/')
def index():
    """Serve main page"""
    return render_template('index.html')


@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files"""
    return send_from_directory(os.path.join(STATIC_DIR, 'css'), filename)


@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files"""
    return send_from_directory(os.path.join(STATIC_DIR, 'js'), filename)


# ============================================================================
# Health check
# ============================================================================

@app.route('/health')
def health():
    """Health check endpoint for app manager"""
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
    """
    Get xmproxysrv connection status for LED indicator.

    Returns:
        status: online, offline, disconnected, unknown, error
        service_running: boolean
        message: human-readable status
    """
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
    """
    Load current xmpp-login.txt configuration.

    Returns:
        config: dict of configuration values (password masked)
    """
    try:
        config = config_mgr.load_config()

        # Create response with masked password info
        response_config = config.copy()
        if 'pw' in response_config:
            response_config['pw_length'] = len(str(response_config.get('pw', '')))

        return jsonify({
            'status': 'ok',
            'config': response_config
        })

    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/config', methods=['POST'])
def save_config():
    """
    Save configuration to xmpp-login.txt.

    Request body:
        config: dict of configuration values
        restart: boolean - whether to restart service after save

    Returns:
        status: ok or error
        message: result message
        restart: restart result (if requested)
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No data provided'
            }), 400

        config = data.get('config', {})
        restart = data.get('restart', False)

        # Validate configuration
        is_valid, error_msg = config_mgr.validate_config(config)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'message': error_msg
            }), 400

        # Save with backup
        config_mgr.save_config(config, create_backup=True)
        logger.info("Configuration saved successfully")

        result = {
            'status': 'ok',
            'message': 'Configuration saved'
        }

        # Restart service if requested
        if restart:
            restart_result = restart_xmproxy_service()
            result['restart'] = restart_result

        return jsonify(result)

    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ============================================================================
# Presets API
# ============================================================================

@app.route('/api/presets', methods=['GET'])
def list_presets():
    """
    List all saved presets.

    Returns:
        presets: list of preset names
    """
    try:
        presets = config_mgr.list_presets()
        return jsonify({
            'status': 'ok',
            'presets': presets
        })

    except Exception as e:
        logger.error(f"Failed to list presets: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/presets', methods=['POST'])
def save_preset():
    """
    Save current form data as a new preset.

    Request body:
        name: preset name
        config: configuration dict

    Returns:
        name: sanitized preset name that was saved
    """
    try:
        data = request.get_json()
        name = data.get('name')
        config = data.get('config')

        if not name:
            return jsonify({
                'status': 'error',
                'message': 'Preset name is required'
            }), 400

        if not config:
            return jsonify({
                'status': 'error',
                'message': 'Config data is required'
            }), 400

        saved_name = config_mgr.save_preset(name, config)
        logger.info(f"Preset saved: {saved_name}")

        return jsonify({
            'status': 'ok',
            'name': saved_name
        })

    except Exception as e:
        logger.error(f"Failed to save preset: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/presets/<name>', methods=['GET'])
def load_preset(name):
    """
    Load a preset (returns config without applying).

    Args:
        name: preset name

    Returns:
        config: preset configuration dict
    """
    try:
        config = config_mgr.load_preset(name)
        return jsonify({
            'status': 'ok',
            'config': config
        })

    except FileNotFoundError:
        return jsonify({
            'status': 'error',
            'message': f"Preset '{name}' not found"
        }), 404

    except Exception as e:
        logger.error(f"Failed to load preset {name}: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/presets/<name>', methods=['DELETE'])
def delete_preset(name):
    """
    Delete a preset.

    Args:
        name: preset name

    Returns:
        status: ok or error
    """
    try:
        if config_mgr.delete_preset(name):
            logger.info(f"Preset deleted: {name}")
            return jsonify({'status': 'ok'})

        return jsonify({
            'status': 'error',
            'message': 'Preset not found'
        }), 404

    except Exception as e:
        logger.error(f"Failed to delete preset {name}: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ============================================================================
# Backups API
# ============================================================================

@app.route('/api/backups', methods=['GET'])
def list_backups():
    """
    List all configuration backups.

    Returns:
        backups: list of {name, timestamp}
    """
    try:
        backups = config_mgr.list_backups()
        return jsonify({
            'status': 'ok',
            'backups': backups
        })

    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/backups/<name>/restore', methods=['POST'])
def restore_backup(name):
    """
    Restore a backup file.

    Args:
        name: backup filename

    Returns:
        status: ok or error
    """
    try:
        if config_mgr.restore_backup(name):
            logger.info(f"Backup restored: {name}")
            return jsonify({
                'status': 'ok',
                'message': 'Backup restored'
            })

        return jsonify({
            'status': 'error',
            'message': 'Backup not found'
        }), 404

    except Exception as e:
        logger.error(f"Failed to restore backup {name}: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ============================================================================
# Connection Control API - manual connect/disconnect
# ============================================================================

@app.route('/api/connection/connect', methods=['POST'])
def api_connect():
    """
    Manually connect XMPP (set online status).

    Returns:
        status: ok or error
        xmpp_status: resulting XMPP status
    """
    try:
        result = xmproxy.set_online_status("online")
        logger.info(f"XMPP connect requested, result: {result}")

        # Get current status after command
        current_status = xmproxy.get_online_status()

        return jsonify({
            'status': 'ok',
            'message': 'Connect command sent',
            'xmpp_status': current_status
        })

    except XmproxyError as e:
        logger.error(f"Connect failed: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

    except Exception as e:
        logger.error(f"Connect failed unexpectedly: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/connection/disconnect', methods=['POST'])
def api_disconnect():
    """
    Manually disconnect XMPP (set offline status).

    Returns:
        status: ok or error
        xmpp_status: resulting XMPP status
    """
    try:
        result = xmproxy.set_online_status("offline")
        logger.info(f"XMPP disconnect requested, result: {result}")

        # Get current status after command
        current_status = xmproxy.get_online_status()

        return jsonify({
            'status': 'ok',
            'message': 'Disconnect command sent',
            'xmpp_status': current_status
        })

    except XmproxyError as e:
        logger.error(f"Disconnect failed: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

    except Exception as e:
        logger.error(f"Disconnect failed unexpectedly: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


# ============================================================================
# Service restart API
# ============================================================================

@app.route('/api/service/restart', methods=['POST'])
def api_restart_service():
    """
    Restart xmproxysrv service.

    Returns:
        status: ok or error
        message: result description
    """
    try:
        result = restart_xmproxy_service()

        if result['success']:
            return jsonify({
                'status': 'ok',
                'message': result['message']
            })

        return jsonify({
            'status': 'error',
            'message': result['message']
        }), 500

    except Exception as e:
        logger.error(f"Restart API failed: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


def restart_xmproxy_service():
    """
    Restart xmproxysrv service.

    Tries restart script first, falls back to shutdown RPC + poll.

    Returns:
        dict with 'success' and 'message' keys
    """
    logger.info("Restarting xmproxysrv service...")

    try:
        # Method 1: Use dedicated restart script if available
        if os.path.exists(RESTART_SCRIPT) and os.access(RESTART_SCRIPT, os.X_OK):
            logger.info(f"Using restart script: {RESTART_SCRIPT}")

            result = subprocess.run(
                [RESTART_SCRIPT],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info("xmproxysrv restarted successfully via script")
                return {
                    'success': True,
                    'message': 'Service restarted successfully'
                }
            else:
                logger.error(f"Restart script failed: {result.stderr}")
                return {
                    'success': False,
                    'message': f'Restart script failed: {result.stderr}'
                }

        # Method 2: JSON-RPC shutdown + wait for auto-restart
        logger.info("Using JSON-RPC shutdown method...")

        # Send shutdown command
        xmproxy.shutdown()

        # Wait a moment for service to stop
        time.sleep(2)

        # Poll for service to come back up
        timeout = 15
        start = time.time()

        while (time.time() - start) < timeout:
            if xmproxy.is_connected():
                # Give it a moment to fully initialize
                time.sleep(1)

                # Check if XMPP connection is being established
                status = xmproxy.get_online_status()
                logger.info(f"xmproxysrv is back, XMPP status: {status}")

                return {
                    'success': True,
                    'message': f'Service restarted (XMPP: {status})'
                }

            time.sleep(1)

        logger.warning("Service did not restart within timeout")
        return {
            'success': False,
            'message': 'Service did not restart within timeout'
        }

    except subprocess.TimeoutExpired:
        logger.error("Restart script timed out")
        return {
            'success': False,
            'message': 'Restart script timed out'
        }

    except Exception as e:
        logger.error(f"Restart failed: {e}")
        return {
            'success': False,
            'message': str(e)
        }


# ============================================================================
# Main entry point
# ============================================================================

def main():
    """Main entry point"""
    # Setup logging first
    setup_logging()

    # Initialize components
    init_components()

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Load webapp configuration
    webapp_config = load_webapp_config()
    host = webapp_config.get('host', '0.0.0.0')
    port = webapp_config.get('port', 8006)

    logger.info(f"Starting {APP_NAME} on {host}:{port}")
    logger.info(f"Static files: {STATIC_DIR}")
    logger.info(f"Config file: {XMPP_LOGIN_FILE}")
    logger.info(f"xmproxysrv: {XMPROXY_HOST}:{XMPROXY_PORT}")

    # Run Flask app
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
