"""
config_manager.py - XMPP configuration file and preset management
"""

import os
import re
import glob
import shutil
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class XmppConfigManager:
    """Manages xmpp-login.txt configuration and presets"""

    # Valid configuration keys in xmpp-login.txt
    VALID_KEYS = [
        'user',        # XMPP JID (required)
        'pw',          # Password (required)
        'adminbuddy',  # Admin contact JID
        'bosh',        # Use BOSH transport (boolean)
        'boshurl',     # BOSH endpoint URL
        'boshhost',    # BOSH host
        'tlsverify',   # TLS certificate verification (boolean)
        'saslmech'     # SASL mechanism
    ]

    # Keys that should be treated as booleans
    BOOLEAN_KEYS = ['bosh', 'tlsverify']

    def __init__(self, config_file, presets_dir, backup_dir, max_backups=5):
        """
        Initialize config manager.

        Args:
            config_file: Path to xmpp-login.txt
            presets_dir: Directory for preset files
            backup_dir: Directory for backup files
            max_backups: Maximum number of backups to keep
        """
        self.config_file = config_file
        self.presets_dir = presets_dir
        self.backup_dir = backup_dir
        self.max_backups = max_backups

        # Ensure directories exist
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Create required directories if they don't exist"""
        for d in [self.presets_dir, self.backup_dir]:
            if d and not os.path.exists(d):
                try:
                    os.makedirs(d, exist_ok=True)
                    logger.info(f"Created directory: {d}")
                except Exception as e:
                    logger.error(f"Failed to create directory {d}: {e}")

    def parse_config(self, filepath):
        """
        Parse xmpp-login.txt format into dict.

        Format:
            key: value
            # comments are ignored

        Args:
            filepath: Path to config file

        Returns:
            Dict of configuration values
        """
        config = {}

        if not os.path.exists(filepath):
            logger.warning(f"Config file not found: {filepath}")
            return config

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue

                    # Parse key: value
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()

                        if key in self.VALID_KEYS:
                            # Convert boolean strings
                            if key in self.BOOLEAN_KEYS:
                                value = value.lower() in ('true', 'yes', '1')
                            config[key] = value

            logger.debug(f"Loaded config from {filepath}: {list(config.keys())}")
            return config

        except Exception as e:
            logger.error(f"Failed to parse config {filepath}: {e}")
            return {}

    def write_config(self, filepath, config):
        """
        Write config dict to xmpp-login.txt format.

        Args:
            filepath: Path to write to
            config: Dict of configuration values
        """
        try:
            # Ensure parent directory exists
            parent = os.path.dirname(filepath)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            with open(filepath, 'w') as f:
                for key in self.VALID_KEYS:
                    if key in config and config[key] is not None:
                        value = config[key]

                        # Convert booleans to string
                        if isinstance(value, bool):
                            value = 'true' if value else 'false'

                        # Skip empty strings
                        if value == '':
                            continue

                        f.write(f"{key}: {value}\n")

            logger.info(f"Wrote config to {filepath}")

        except Exception as e:
            logger.error(f"Failed to write config to {filepath}: {e}")
            raise

    def load_config(self):
        """
        Load current xmpp-login.txt configuration.

        Returns:
            Dict of configuration values
        """
        return self.parse_config(self.config_file)

    def save_config(self, config, create_backup=True):
        """
        Save config to xmpp-login.txt with optional backup.

        Args:
            config: Dict of configuration values
            create_backup: Whether to backup existing config first
        """
        if create_backup and os.path.exists(self.config_file):
            self._create_backup()

        self.write_config(self.config_file, config)

    def _create_backup(self):
        """Create timestamped backup, enforce max_backups limit"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"xmpp-login_{timestamp}.txt"
            backup_path = os.path.join(self.backup_dir, backup_name)

            shutil.copy2(self.config_file, backup_path)
            logger.info(f"Created backup: {backup_name}")

            # Cleanup old backups (keep only max_backups most recent)
            self._cleanup_old_backups()

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")

    def _cleanup_old_backups(self):
        """Remove old backups exceeding max_backups limit"""
        try:
            pattern = os.path.join(self.backup_dir, 'xmpp-login_*.txt')
            backups = sorted(glob.glob(pattern))

            while len(backups) > self.max_backups:
                oldest = backups.pop(0)
                os.remove(oldest)
                logger.info(f"Removed old backup: {os.path.basename(oldest)}")

        except Exception as e:
            logger.error(f"Failed to cleanup backups: {e}")

    def list_presets(self):
        """
        List all preset names.

        Returns:
            Sorted list of preset names (without .txt extension)
        """
        presets = []

        if not os.path.exists(self.presets_dir):
            return presets

        try:
            for f in glob.glob(os.path.join(self.presets_dir, '*.txt')):
                name = os.path.splitext(os.path.basename(f))[0]
                presets.append(name)
            return sorted(presets)

        except Exception as e:
            logger.error(f"Failed to list presets: {e}")
            return []

    def load_preset(self, name):
        """
        Load a preset by name.

        Args:
            name: Preset name (without extension)

        Returns:
            Dict of configuration values

        Raises:
            FileNotFoundError: If preset doesn't exist
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.txt")

        if not os.path.exists(preset_file):
            raise FileNotFoundError(f"Preset '{name}' not found")

        return self.parse_config(preset_file)

    def save_preset(self, name, config):
        """
        Save config as named preset.

        Args:
            name: Preset name
            config: Dict of configuration values

        Returns:
            Sanitized preset name that was used
        """
        # Sanitize name (only alphanumeric, underscore, hyphen)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        safe_name = safe_name.strip('_')

        if not safe_name:
            safe_name = 'preset'

        preset_file = os.path.join(self.presets_dir, f"{safe_name}.txt")
        self.write_config(preset_file, config)

        logger.info(f"Saved preset: {safe_name}")
        return safe_name

    def delete_preset(self, name):
        """
        Delete a preset by name.

        Args:
            name: Preset name (without extension)

        Returns:
            True if deleted, False if not found
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.txt")

        if os.path.exists(preset_file):
            try:
                os.remove(preset_file)
                logger.info(f"Deleted preset: {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete preset {name}: {e}")
                return False

        return False

    def list_backups(self):
        """
        List all backups with metadata.

        Returns:
            List of dicts with 'name' and 'timestamp' keys, newest first
        """
        backups = []

        if not os.path.exists(self.backup_dir):
            return backups

        try:
            pattern = os.path.join(self.backup_dir, 'xmpp-login_*.txt')
            files = sorted(glob.glob(pattern), reverse=True)

            for f in files:
                name = os.path.basename(f)
                mtime = os.path.getmtime(f)
                backups.append({
                    'name': name,
                    'timestamp': datetime.fromtimestamp(mtime).isoformat()
                })

            return backups

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def restore_backup(self, name):
        """
        Restore a backup file.

        Args:
            name: Backup filename

        Returns:
            True if restored, False if not found
        """
        backup_file = os.path.join(self.backup_dir, name)

        if not os.path.exists(backup_file):
            logger.warning(f"Backup not found: {name}")
            return False

        try:
            # Create backup of current config before restoring
            if os.path.exists(self.config_file):
                self._create_backup()

            shutil.copy2(backup_file, self.config_file)
            logger.info(f"Restored backup: {name}")
            return True

        except Exception as e:
            logger.error(f"Failed to restore backup {name}: {e}")
            return False

    def validate_config(self, config):
        """
        Validate configuration values.

        Args:
            config: Dict of configuration values

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check required fields
        if not config.get('user'):
            return False, "JID (user) is required"

        if not config.get('pw'):
            return False, "Password is required"

        # Validate JID format (user@domain)
        user = config.get('user', '')
        if user and not re.match(r'^[^@]+@[^@]+$', user):
            return False, "Invalid JID format. Expected: user@domain"

        # Validate adminbuddy JID if present
        adminbuddy = config.get('adminbuddy', '')
        if adminbuddy and not re.match(r'^[^@]+@[^@]+$', adminbuddy):
            return False, "Invalid admin buddy JID format"

        # Validate BOSH URL if BOSH is enabled
        if config.get('bosh'):
            boshurl = config.get('boshurl', '')
            if boshurl and not boshurl.startswith(('http://', 'https://')):
                return False, "BOSH URL must start with http:// or https://"

        return True, None
