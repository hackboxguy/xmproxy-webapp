/**
 * xmproxy-webapp - Frontend Application
 * Manages XMPP proxy configuration UI
 */

(function() {
    'use strict';

    // ========================================================================
    // Configuration
    // ========================================================================

    const CONFIG = {
        statusPollInterval: 5000,  // Poll status every 5 seconds
        alertDuration: 5000,       // Auto-hide alerts after 5 seconds
        apiTimeout: 15000          // API request timeout
    };

    // ========================================================================
    // State
    // ========================================================================

    const state = {
        currentConfig: null,
        presets: [],
        backups: [],
        statusPollTimer: null,
        isDirty: false,
        currentStatus: 'unknown'
    };

    // ========================================================================
    // Utility Functions
    // ========================================================================

    /**
     * Get base path for API calls (handles proxy access)
     */
    function getBasePath() {
        const path = window.location.pathname;
        return path.endsWith('/') ? path : path + '/';
    }

    /**
     * Make API request with timeout
     */
    async function fetchAPI(endpoint, options = {}) {
        const url = getBasePath() + endpoint.replace(/^\//, '');

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CONFIG.apiTimeout);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });

            clearTimeout(timeoutId);

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            return data;

        } catch (error) {
            clearTimeout(timeoutId);

            if (error.name === 'AbortError') {
                throw new Error('Request timed out');
            }
            throw error;
        }
    }

    /**
     * Show alert message
     */
    function showAlert(message, type = 'success') {
        const container = document.getElementById('alert-container');

        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.innerHTML = `
            <span>${message}</span>
            <button class="alert-close" onclick="this.parentElement.remove()">&times;</button>
        `;

        container.appendChild(alert);

        // Auto-remove after duration
        setTimeout(() => {
            if (alert.parentElement) {
                alert.remove();
            }
        }, CONFIG.alertDuration);
    }

    /**
     * Format timestamp for display
     */
    function formatTimestamp(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleString();
        } catch {
            return isoString;
        }
    }

    // ========================================================================
    // Status Polling
    // ========================================================================

    async function pollStatus() {
        try {
            const data = await fetchAPI('api/status');

            const led = document.getElementById('status-led');
            const text = document.getElementById('status-text');

            // Remove all status classes
            led.className = 'status-led';

            // Add appropriate class
            led.classList.add(data.status);

            // Update text
            const statusMap = {
                'online': 'Connected',
                'offline': 'Offline',
                'disconnected': 'Service Down',
                'unknown': 'Connecting...',
                'error': 'Error'
            };
            text.textContent = statusMap[data.status] || data.status;

            // Track status and update connection button
            state.currentStatus = data.status;
            updateConnectionButton();

        } catch (error) {
            console.error('Status poll failed:', error);
            const led = document.getElementById('status-led');
            const text = document.getElementById('status-text');
            led.className = 'status-led error';
            text.textContent = 'Error';
            state.currentStatus = 'error';
            updateConnectionButton();
        }
    }

    /**
     * Update the connect/disconnect button based on current status
     */
    function updateConnectionButton() {
        const btn = document.getElementById('btn-connection-toggle');
        if (!btn) return;

        switch (state.currentStatus) {
            case 'online':
                btn.textContent = 'Disconnect';
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-secondary');
                btn.disabled = false;
                btn.title = 'Disconnect XMPP connection';
                break;
            case 'offline':
                btn.textContent = 'Connect';
                btn.classList.remove('btn-secondary');
                btn.classList.add('btn-primary');
                btn.disabled = false;
                btn.title = 'Connect XMPP connection';
                break;
            case 'disconnected':
            case 'error':
                btn.textContent = 'Connect';
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-secondary');
                btn.disabled = true;
                btn.title = 'Service not available';
                break;
            default:
                btn.textContent = 'Connect';
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-secondary');
                btn.disabled = true;
                btn.title = 'Checking status...';
        }
    }

    /**
     * Toggle XMPP connection (connect if offline, disconnect if online)
     */
    async function toggleConnection() {
        const btn = document.getElementById('btn-connection-toggle');
        const isConnected = state.currentStatus === 'online';
        const endpoint = isConnected ? 'api/connection/disconnect' : 'api/connection/connect';
        const action = isConnected ? 'Disconnecting' : 'Connecting';

        try {
            btn.disabled = true;
            btn.classList.add('loading');
            btn.textContent = action + '...';

            const data = await fetchAPI(endpoint, {
                method: 'POST'
            });

            showAlert(data.message, 'success');

            // Poll status immediately to update UI
            setTimeout(pollStatus, 500);

        } catch (error) {
            console.error('Connection toggle failed:', error);
            showAlert('Failed to ' + (isConnected ? 'disconnect' : 'connect') + ': ' + error.message, 'error');
            updateConnectionButton();

        } finally {
            btn.classList.remove('loading');
            // Button state will be updated by next status poll
        }
    }

    function startStatusPolling() {
        // Poll immediately
        pollStatus();

        // Then poll at interval
        state.statusPollTimer = setInterval(pollStatus, CONFIG.statusPollInterval);
    }

    function stopStatusPolling() {
        if (state.statusPollTimer) {
            clearInterval(state.statusPollTimer);
            state.statusPollTimer = null;
        }
    }

    // ========================================================================
    // Configuration Management
    // ========================================================================

    async function loadConfig() {
        try {
            const data = await fetchAPI('api/config');
            state.currentConfig = data.config;
            populateForm(data.config);
            updateLastUpdate();

        } catch (error) {
            console.error('Failed to load config:', error);
            showAlert('Failed to load configuration: ' + error.message, 'error');
        }
    }

    function populateForm(config) {
        // Text fields
        document.getElementById('user').value = config.user || '';
        document.getElementById('pw').value = config.pw || '';
        document.getElementById('adminbuddy').value = config.adminbuddy || '';
        document.getElementById('boshurl').value = config.boshurl || '';
        document.getElementById('boshhost').value = config.boshhost || '';

        // BOSH checkbox
        const boshCheckbox = document.getElementById('bosh');
        boshCheckbox.checked = config.bosh === true || config.bosh === 'true';
        toggleBoshSettings();

        // TLS verify select
        const tlsSelect = document.getElementById('tlsverify');
        if (config.tlsverify === false || config.tlsverify === 'false') {
            tlsSelect.value = 'false';
        } else {
            tlsSelect.value = 'true';
        }

        // SASL mechanism
        document.getElementById('saslmech').value = config.saslmech || '';

        state.isDirty = false;
    }

    function getFormData() {
        const config = {
            user: document.getElementById('user').value.trim(),
            pw: document.getElementById('pw').value,
            adminbuddy: document.getElementById('adminbuddy').value.trim(),
            bosh: document.getElementById('bosh').checked,
            boshurl: document.getElementById('boshurl').value.trim(),
            boshhost: document.getElementById('boshhost').value.trim(),
            tlsverify: document.getElementById('tlsverify').value === 'true',
            saslmech: document.getElementById('saslmech').value
        };

        // Remove empty optional fields
        if (!config.adminbuddy) delete config.adminbuddy;
        if (!config.bosh) {
            delete config.bosh;
            delete config.boshurl;
            delete config.boshhost;
        } else {
            if (!config.boshurl) delete config.boshurl;
            if (!config.boshhost) delete config.boshhost;
        }
        if (!config.saslmech) delete config.saslmech;

        return config;
    }

    function validateForm() {
        const user = document.getElementById('user').value.trim();
        const pw = document.getElementById('pw').value;

        if (!user) {
            showAlert('JID (User) is required', 'error');
            document.getElementById('user').focus();
            return false;
        }

        if (!user.includes('@')) {
            showAlert('Invalid JID format. Expected: user@domain', 'error');
            document.getElementById('user').focus();
            return false;
        }

        if (!pw) {
            showAlert('Password is required', 'error');
            document.getElementById('pw').focus();
            return false;
        }

        // Validate BOSH URL if enabled
        if (document.getElementById('bosh').checked) {
            const boshurl = document.getElementById('boshurl').value.trim();
            if (boshurl && !boshurl.match(/^https?:\/\//)) {
                showAlert('BOSH URL must start with http:// or https://', 'error');
                document.getElementById('boshurl').focus();
                return false;
            }
        }

        return true;
    }

    async function saveConfig(restart = false) {
        if (!validateForm()) {
            return;
        }

        const config = getFormData();
        const btn = restart ? document.getElementById('btn-save-restart') : document.getElementById('btn-save');

        try {
            btn.disabled = true;
            btn.classList.add('loading');

            const data = await fetchAPI('api/config', {
                method: 'POST',
                body: JSON.stringify({ config, restart })
            });

            state.currentConfig = config;
            state.isDirty = false;
            updateLastUpdate();

            if (restart && data.restart) {
                if (data.restart.success) {
                    showAlert('Configuration saved and service restarted', 'success');
                } else {
                    showAlert('Configuration saved, but restart failed: ' + data.restart.message, 'warning');
                }
            } else {
                showAlert('Configuration saved successfully', 'success');
            }

            // Reload backups list
            loadBackups();

        } catch (error) {
            console.error('Save failed:', error);
            showAlert('Failed to save: ' + error.message, 'error');

        } finally {
            btn.disabled = false;
            btn.classList.remove('loading');
        }
    }

    async function restartService() {
        const btn = document.getElementById('btn-restart');

        try {
            btn.disabled = true;
            btn.classList.add('loading');

            const data = await fetchAPI('api/service/restart', {
                method: 'POST'
            });

            showAlert('Service restarted successfully', 'success');

            // Poll status immediately
            setTimeout(pollStatus, 1000);

        } catch (error) {
            console.error('Restart failed:', error);
            showAlert('Restart failed: ' + error.message, 'error');

        } finally {
            btn.disabled = false;
            btn.classList.remove('loading');
        }
    }

    function updateLastUpdate() {
        const el = document.getElementById('last-update');
        if (el) el.textContent = new Date().toLocaleString();
    }

    // ========================================================================
    // Presets Management
    // ========================================================================

    async function loadPresets() {
        try {
            const data = await fetchAPI('api/presets');
            state.presets = data.presets || [];
            updatePresetDropdown();

        } catch (error) {
            console.error('Failed to load presets:', error);
        }
    }

    function updatePresetDropdown() {
        const select = document.getElementById('preset-select');
        const currentValue = select.value;

        // Clear existing options (keep first)
        while (select.options.length > 1) {
            select.remove(1);
        }

        // Add preset options
        state.presets.forEach(name => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            select.appendChild(option);
        });

        // Restore selection if still valid
        if (state.presets.includes(currentValue)) {
            select.value = currentValue;
        }

        updatePresetButtons();
    }

    function updatePresetButtons() {
        const select = document.getElementById('preset-select');
        const hasSelection = select.value !== '';

        document.getElementById('btn-load-preset').disabled = !hasSelection;
        document.getElementById('btn-delete-preset').disabled = !hasSelection;
    }

    async function loadPreset() {
        const select = document.getElementById('preset-select');
        const name = select.value;

        if (!name) return;

        try {
            const data = await fetchAPI(`api/presets/${encodeURIComponent(name)}`);
            populateForm(data.config);
            showAlert(`Loaded preset: ${name}`, 'success');
            state.isDirty = true;

        } catch (error) {
            console.error('Failed to load preset:', error);
            showAlert('Failed to load preset: ' + error.message, 'error');
        }
    }

    function showSavePresetModal() {
        document.getElementById('preset-name-input').value = '';
        document.getElementById('save-preset-modal').classList.add('active');
        document.getElementById('preset-name-input').focus();
    }

    function hideSavePresetModal() {
        document.getElementById('save-preset-modal').classList.remove('active');
    }

    async function savePreset() {
        const name = document.getElementById('preset-name-input').value.trim();

        if (!name) {
            showAlert('Please enter a preset name', 'error');
            return;
        }

        const config = getFormData();

        try {
            const data = await fetchAPI('api/presets', {
                method: 'POST',
                body: JSON.stringify({ name, config })
            });

            hideSavePresetModal();
            await loadPresets();
            showAlert(`Preset saved: ${data.name}`, 'success');

            // Select the new preset
            document.getElementById('preset-select').value = data.name;
            updatePresetButtons();

        } catch (error) {
            console.error('Failed to save preset:', error);
            showAlert('Failed to save preset: ' + error.message, 'error');
        }
    }

    async function deletePreset() {
        const select = document.getElementById('preset-select');
        const name = select.value;

        if (!name) return;

        showConfirmModal(
            'Delete Preset',
            `Are you sure you want to delete the preset "${name}"?`,
            async () => {
                try {
                    await fetchAPI(`api/presets/${encodeURIComponent(name)}`, {
                        method: 'DELETE'
                    });

                    await loadPresets();
                    showAlert(`Preset deleted: ${name}`, 'success');

                } catch (error) {
                    console.error('Failed to delete preset:', error);
                    showAlert('Failed to delete preset: ' + error.message, 'error');
                }
            }
        );
    }

    // ========================================================================
    // Backups Management
    // ========================================================================

    async function loadBackups() {
        try {
            const data = await fetchAPI('api/backups');
            state.backups = data.backups || [];
            renderBackupsList();

        } catch (error) {
            console.error('Failed to load backups:', error);
        }
    }

    function renderBackupsList() {
        const container = document.getElementById('backups-list');

        if (state.backups.length === 0) {
            container.innerHTML = '<p class="empty-state">No backups available</p>';
            return;
        }

        container.innerHTML = state.backups.map(backup => `
            <div class="backup-item">
                <div class="backup-info">
                    <div class="backup-name">${backup.name}</div>
                    <div class="backup-time">${formatTimestamp(backup.timestamp)}</div>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="app.restoreBackup('${backup.name}')">
                    Restore
                </button>
            </div>
        `).join('');
    }

    async function restoreBackup(name) {
        showConfirmModal(
            'Restore Backup',
            `Are you sure you want to restore the backup "${name}"? Current configuration will be backed up first.`,
            async () => {
                try {
                    await fetchAPI(`api/backups/${encodeURIComponent(name)}/restore`, {
                        method: 'POST'
                    });

                    await loadConfig();
                    await loadBackups();
                    showAlert('Backup restored successfully', 'success');

                } catch (error) {
                    console.error('Failed to restore backup:', error);
                    showAlert('Failed to restore backup: ' + error.message, 'error');
                }
            }
        );
    }

    // ========================================================================
    // UI Helpers
    // ========================================================================

    function toggleBoshSettings() {
        const boshSettings = document.getElementById('bosh-settings');
        const boshCheckbox = document.getElementById('bosh');

        if (boshCheckbox.checked) {
            boshSettings.classList.remove('hidden');
        } else {
            boshSettings.classList.add('hidden');
        }
    }

    function togglePasswordVisibility() {
        const pwInput = document.getElementById('pw');
        const btn = document.getElementById('toggle-password');

        if (pwInput.type === 'password') {
            pwInput.type = 'text';
            btn.title = 'Hide password';
        } else {
            pwInput.type = 'password';
            btn.title = 'Show password';
        }
    }

    // ========================================================================
    // Confirm Modal
    // ========================================================================

    let confirmCallback = null;

    function showConfirmModal(title, message, onConfirm) {
        document.getElementById('confirm-title').textContent = title;
        document.getElementById('confirm-message').textContent = message;
        confirmCallback = onConfirm;
        document.getElementById('confirm-modal').classList.add('active');
    }

    function hideConfirmModal() {
        document.getElementById('confirm-modal').classList.remove('active');
        confirmCallback = null;
    }

    function handleConfirm() {
        if (confirmCallback) {
            confirmCallback();
        }
        hideConfirmModal();
    }

    // ========================================================================
    // Event Handlers
    // ========================================================================

    function setupEventListeners() {
        // Form change tracking
        const form = document.getElementById('config-form');
        form.addEventListener('input', () => {
            state.isDirty = true;
        });

        // BOSH toggle
        document.getElementById('bosh').addEventListener('change', toggleBoshSettings);

        // Password toggle
        document.getElementById('toggle-password').addEventListener('click', togglePasswordVisibility);

        // Action buttons
        document.getElementById('btn-save').addEventListener('click', () => saveConfig(false));
        document.getElementById('btn-save-restart').addEventListener('click', () => saveConfig(true));
        document.getElementById('btn-restart').addEventListener('click', restartService);

        // Connection toggle button
        document.getElementById('btn-connection-toggle').addEventListener('click', toggleConnection);

        // Preset controls
        document.getElementById('preset-select').addEventListener('change', updatePresetButtons);
        document.getElementById('btn-load-preset').addEventListener('click', loadPreset);
        document.getElementById('btn-save-preset').addEventListener('click', showSavePresetModal);
        document.getElementById('btn-delete-preset').addEventListener('click', deletePreset);

        // Save preset modal
        document.getElementById('btn-cancel-preset').addEventListener('click', hideSavePresetModal);
        document.getElementById('btn-confirm-preset').addEventListener('click', savePreset);
        document.getElementById('preset-name-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                savePreset();
            }
        });

        // Confirm modal
        document.getElementById('btn-confirm-cancel').addEventListener('click', hideConfirmModal);
        document.getElementById('btn-confirm-ok').addEventListener('click', handleConfirm);

        // Close modals on backdrop click
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.classList.remove('active');
                }
            });
        });

        // Warn before leaving with unsaved changes
        window.addEventListener('beforeunload', (e) => {
            if (state.isDirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    }

    // ========================================================================
    // Initialization
    // ========================================================================

    async function init() {
        console.log('Initializing xmproxy-webapp...');

        setupEventListeners();

        // Load initial data
        await Promise.all([
            loadConfig(),
            loadPresets(),
            loadBackups()
        ]);

        // Start status polling
        startStatusPolling();

        console.log('Initialization complete');
    }

    // ========================================================================
    // Public API
    // ========================================================================

    window.app = {
        restoreBackup
    };

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
