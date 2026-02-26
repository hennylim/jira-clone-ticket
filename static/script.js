document.addEventListener('DOMContentLoaded', () => {
    const isLoginPage = window.location.pathname.includes('/login');
    let token = localStorage.getItem('token');
    let currentUser = null;

    async function checkAuth() {
        if (!token) {
            if (!isLoginPage) window.location.href = '/login';
            return;
        }
        try {
            const response = await fetch('/api/auth/me', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                const data = await response.json();
                currentUser = data.username;
                if (isLoginPage) {
                    window.location.href = '/';
                } else {
                    initMainPage();
                }
            } else {
                logout();
            }
        } catch (error) {
            console.error('Auth check failed:', error);
            if (!isLoginPage) window.location.href = '/login';
        }
    }

    function logout() {
        localStorage.removeItem('token');
        token = null;
        currentUser = null;
        window.location.href = '/login';
    }

    if (isLoginPage) {
        initLoginPage();
    }

    checkAuth();

    // --- Login Page Logic ---
    function initLoginPage() {
        const loginFormLanding = document.getElementById('login-form-landing');
        const registerFormLanding = document.getElementById('register-form-landing');
        const showRegister = document.getElementById('show-register');
        const showLogin = document.getElementById('show-login');

        if (!loginFormLanding) return;

        showRegister.onclick = (e) => {
            e.preventDefault();
            loginFormLanding.classList.add('hidden');
            registerFormLanding.classList.remove('hidden');
        };

        showLogin.onclick = (e) => {
            e.preventDefault();
            registerFormLanding.classList.add('hidden');
            loginFormLanding.classList.remove('hidden');
        };

        loginFormLanding.onsubmit = async (e) => {
            e.preventDefault();
            const username = document.getElementById('login-username-landing').value;
            const password = document.getElementById('login-password-landing').value;
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                if (!response.ok) throw new Error('Login failed. Please check your credentials.');
                const data = await response.json();
                localStorage.setItem('token', data.access_token);
                window.location.href = '/';
            } catch (error) {
                alert(error.message);
            }
        };

        registerFormLanding.onsubmit = async (e) => {
            e.preventDefault();
            const username = document.getElementById('reg-username-landing').value;
            const password = document.getElementById('reg-password-landing').value;
            const jira_base_url = document.getElementById('reg-jira-url-landing').value;
            const jira_email = document.getElementById('reg-jira-email-landing').value;
            const jira_api_token = document.getElementById('reg-jira-token-landing').value;
            try {
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password, jira_base_url, jira_email, jira_api_token })
                });
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.detail || 'Registration failed');
                }
                alert('Registration successful! Please login.');
                registerFormLanding.classList.add('hidden');
                loginFormLanding.classList.remove('hidden');
            } catch (error) {
                alert(error.message);
            }
        };
    }

    // --- Main Page Logic ---
    function initMainPage() {
        // UI elements
        const logoutBtn = document.getElementById('logout-btn');
        const userDisplay = document.getElementById('user-display');
        const usernameSpan = document.getElementById('username-span');
        const configForm = document.getElementById('config-form');
        const saveConfigBtn = document.getElementById('save-config-btn');
        const loadFileBtn = document.getElementById('load-file-btn');
        const fileInput = document.getElementById('file-input');
        const loadExampleBtn = document.getElementById('load-example');
        const searchBtn = document.getElementById('search-btn');
        const resultsSection = document.getElementById('results-section');
        const issueBody = document.getElementById('issue-body');
        const selectAllCheckbox = document.getElementById('select-all');
        const cloneBtn = document.getElementById('clone-btn');
        const progressSection = document.getElementById('progress-section');
        const progressLog = document.getElementById('progress-log');

        let jiraBaseUrl = '';

        const configSchema = [
            { key: 'jql', label: 'JQL Query', type: 'text', fullWidth: true },
            { key: 'clone_project_key', label: 'Clone Project Key', type: 'text' },
            { key: 'issue_type', label: 'Issue Type', type: 'text' },
            { key: 'due_date', label: 'Due Date / Delay (e.g. 1W, 2D)', type: 'text' },
            { key: 'clone_label', label: 'Clone Labels (space separated)', type: 'text' },
            { key: 'clone_models', label: 'Clone Models (space separated)', type: 'text' },
            { key: 'parent_key', label: 'Parent Issue Key (optional)', type: 'text' }
        ];

        // --- Configuration Management (Database) ---
        const presetsContainer = document.getElementById('presets-container');
        const presetsSelect = document.getElementById('config-presets');
        const configNameInput = document.getElementById('config-name');
        const saveDbBtn = document.getElementById('save-db-btn');
        const updateDbBtn = document.getElementById('update-db-btn');
        const deleteDbBtn = document.getElementById('delete-db-btn');

        let currentPresetId = null;
        let originalPresetContent = null;

        function checkChanges() {
            if (!currentPresetId || !originalPresetContent) {
                updateDbBtn.disabled = true;
                return;
            }
            const currentConfig = getConfigFromForm();
            const isChanged = JSON.stringify(currentConfig) !== JSON.stringify(originalPresetContent);
            updateDbBtn.disabled = !isChanged;
        }

        async function fetchPresets() {
            try {
                const response = await fetch('/api/configs', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (response.ok) {
                    const configs = await response.json();
                    if (configs.length > 0) {
                        presetsContainer.classList.remove('hidden');
                        presetsSelect.innerHTML = '<option value="">-- Select a preset --</option>';
                        configs.forEach(config => {
                            const option = document.createElement('option');
                            option.value = config.id;
                            option.textContent = config.name;
                            presetsSelect.appendChild(option);
                        });
                        // Keep current selection if refreshing
                        if (currentPresetId) presetsSelect.value = currentPresetId;
                    } else {
                        presetsContainer.classList.add('hidden');
                    }
                }
            } catch (error) {
                console.error('Failed to fetch presets:', error);
            }
        }

        saveDbBtn.addEventListener('click', async () => {
            const name = configNameInput.value.trim();
            if (!name) {
                alert('Please enter a configuration name.');
                return;
            }

            const config = getConfigFromForm();

            try {
                const response = await fetch('/api/configs', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ name, content: config })
                });

                if (response.ok) {
                    configNameInput.value = '';
                    const newConfig = await response.json();
                    await fetchPresets();
                    // Auto-select the newly saved config
                    presetsSelect.value = newConfig.id;
                    currentPresetId = newConfig.id;
                    originalPresetContent = newConfig.content;
                    updateDbBtn.disabled = true;
                    alert('Configuration saved to database.');
                } else {
                    const err = await response.json();
                    alert('Failed to save configuration: ' + (err.detail || 'Unknown error'));
                }
            } catch (error) {
                alert('Error saving configuration: ' + error.message);
            }
        });

        presetsSelect.addEventListener('change', async () => {
            const configId = presetsSelect.value;
            if (!configId) {
                currentPresetId = null;
                originalPresetContent = null;
                updateDbBtn.disabled = true;
                return;
            }

            try {
                const response = await fetch(`/api/configs/${configId}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.ok) {
                    const configData = await response.json();
                    currentPresetId = configId;
                    originalPresetContent = configData.content;
                    renderConfigForm(configData.content);
                    updateDbBtn.disabled = true;
                } else {
                    const err = await response.json();
                    alert('Failed to load configuration: ' + (err.detail || 'Unknown error'));
                }
            } catch (error) {
                alert('Error auto-loading configuration: ' + error.message);
            }
        });

        updateDbBtn.addEventListener('click', async () => {
            if (!currentPresetId) return;

            const selectedOption = presetsSelect.options[presetsSelect.selectedIndex];
            const name = selectedOption.textContent;
            const config = getConfigFromForm();

            try {
                const response = await fetch(`/api/configs/${currentPresetId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ name, content: config })
                });

                if (response.ok) {
                    const updatedConfig = await response.json();
                    originalPresetContent = updatedConfig.content;
                    updateDbBtn.disabled = true;
                    alert('Configuration updated successfully.');
                } else {
                    const err = await response.json();
                    alert('Failed to update configuration: ' + (err.detail || 'Unknown error'));
                }
            } catch (error) {
                alert('Error updating configuration: ' + error.message);
            }
        });

        deleteDbBtn.addEventListener('click', async () => {
            const configId = presetsSelect.value;
            if (!configId) return;

            if (!confirm('Are you sure you want to delete this configuration?')) return;

            try {
                const response = await fetch(`/api/configs/${configId}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.ok) {
                    currentPresetId = null;
                    originalPresetContent = null;
                    updateDbBtn.disabled = true;
                    await fetchPresets();
                }
            } catch (error) {
                alert('Error deleting configuration: ' + error.message);
            }
        });

        // Initialize presets
        fetchPresets();

        if (currentUser) {
            logoutBtn.classList.remove('hidden');
            userDisplay.classList.remove('hidden');
            usernameSpan.textContent = currentUser;
        }

        logoutBtn.onclick = logout;

        function renderConfigForm(config) {
            configForm.innerHTML = '';
            configSchema.forEach(field => {
                const group = document.createElement('div');
                group.className = 'form-group' + (field.fullWidth ? ' full-width' : '');

                const label = document.createElement('label');
                label.textContent = field.label;

                const input = document.createElement('input');
                input.type = field.type;
                input.id = `input-${field.key}`;

                // Add input listener for change detection
                input.addEventListener('input', checkChanges);

                let value = config[field.key] || '';
                if (Array.isArray(value)) {
                    value = value.join(' ');
                }
                input.value = value;

                group.appendChild(label);
                group.appendChild(input);
                configForm.appendChild(group);
            });
            checkChanges();
        }

        function getConfigFromForm() {
            const config = {};
            configSchema.forEach(field => {
                const input = document.getElementById(`input-${field.key}`);
                let value = input.value.trim();
                if (field.key === 'clone_label' || field.key === 'clone_models') {
                    value = value.split(/\s+/).filter(v => v);
                }
                if (value !== '') config[field.key] = value;
            });
            return config;
        }

        const exampleConfig = {
            "jql": "project = HP920 AND status IN (Open, Reopened) AND summary ~ \"[SXEP210W]\" ORDER BY created DESC",
            "clone_project_key": "JPNSW",
            "clone_label": ["HP920_SYNC"],
            "due_date": "1W",
            "issue_type": "Bug",
            "clone_models": ["HP920"]
        };

        renderConfigForm(exampleConfig);

        loadFileBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const json = JSON.parse(e.target.result);
                    renderConfigForm(json);
                    event.target.value = '';
                } catch (error) {
                    alert('Error parsing JSON file: ' + error.message);
                }
            };
            reader.readAsText(file);
        });

        loadExampleBtn.addEventListener('click', () => renderConfigForm(exampleConfig));

        saveConfigBtn.addEventListener('click', () => {
            const config = getConfigFromForm();
            const filename = prompt("Enter filename to save as:", "config.json");
            if (!filename) return;
            try {
                const dataStr = JSON.stringify(config, null, 4);
                const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
                const linkElement = document.createElement('a');
                linkElement.setAttribute('href', dataUri);
                linkElement.setAttribute('download', filename);
                linkElement.click();
            } catch (error) {
                alert('Error generating download: ' + error.message);
            }
        });

        searchBtn.addEventListener('click', async () => {
            const config = getConfigFromForm();
            searchBtn.disabled = true;
            searchBtn.textContent = 'Searching...';
            try {
                const response = await fetch('/api/search', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ config })
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Search failed');
                }
                const data = await response.json();
                jiraBaseUrl = data.base_url;
                displayIssues(data.issues, jiraBaseUrl);
            } catch (error) {
                alert('Error: ' + error.message);
            } finally {
                searchBtn.disabled = false;
                searchBtn.textContent = 'Search Issues';
            }
        });

        function displayIssues(issues, baseUrl) {
            issueBody.innerHTML = '';
            if (issues.length === 0) {
                issueBody.innerHTML = '<tr><td colspan="4" style="text-align: center;">No issues found.</td></tr>';
                cloneBtn.disabled = true;
            } else {
                issues.forEach(issue => {
                    const tr = document.createElement('tr');
                    const jiraLink = baseUrl ? `${baseUrl.replace(/\/$/, '')}/browse/${issue.key}` : '#';
                    tr.innerHTML = `
                        <td><input type="checkbox" class="issue-checkbox" value="${issue.key}"></td>
                        <td><a href="${jiraLink}" target="_blank" class="jira-link">${issue.key}</a></td>
                        <td><a href="${jiraLink}" target="_blank" class="jira-link">${issue.key} - ${issue.summary}</a></td>
                        <td><span class="status-tag">${issue.status}</span></td>
                    `;
                    issueBody.appendChild(tr);
                });
                cloneBtn.disabled = false;
            }
            resultsSection.classList.remove('hidden');
            resultsSection.scrollIntoView({ behavior: 'smooth' });
        }

        selectAllCheckbox.addEventListener('change', () => {
            const checkboxes = document.querySelectorAll('.issue-checkbox');
            checkboxes.forEach(cb => cb.checked = selectAllCheckbox.checked);
        });

        cloneBtn.addEventListener('click', async () => {
            const selectedCheckboxes = document.querySelectorAll('.issue-checkbox:checked');
            if (selectedCheckboxes.length === 0) {
                alert('Please select at least one issue.');
                return;
            }
            const selectedKeys = Array.from(selectedCheckboxes).map(cb => cb.value);
            const config = getConfigFromForm();
            if (!confirm(`Are you sure you want to clone ${selectedKeys.length} tickets?`)) return;

            cloneBtn.disabled = true;
            cloneBtn.textContent = 'Cloning...';
            progressSection.classList.remove('hidden');
            progressLog.innerHTML = `<div class="log-entry log-info">Starting clone process for ${selectedKeys.length} tickets...</div>`;
            progressSection.scrollIntoView({ behavior: 'smooth' });

            try {
                const response = await fetch('/api/clone', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ config, selected_issue_keys: selectedKeys })
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Cloning failed');
                }
                const data = await response.json();
                if (data.base_url) jiraBaseUrl = data.base_url;
                const baseUrl = jiraBaseUrl.replace(/\/$/, '');

                data.results.forEach(res => {
                    const entry = document.createElement('div');
                    entry.className = 'log-entry';
                    const orgLink = `${baseUrl}/browse/${res.issue}`;
                    const newLink = res.new_issue_key ? `${baseUrl}/browse/${res.new_issue_key}` : '#';
                    if (res.status === 'success') {
                        entry.classList.add('log-success');
                        entry.innerHTML = `[SUCCESS] ${res.summary} - <a href="${orgLink}" target="_blank" class="jira-link-log">${res.issue}</a> cloned as <a href="${newLink}" target="_blank" class="jira-link-log">${res.new_issue_key}</a>`;
                    } else if (res.status === 'skipped') {
                        entry.classList.add('log-warning');
                        entry.innerHTML = `[SKIPPED] ${res.summary} - <a href="${orgLink}" target="_blank" class="jira-link-log">${res.issue}</a>: ${res.message}`;
                    } else {
                        entry.classList.add('log-error');
                        entry.innerHTML = `[FAILED] ${res.summary} - <a href="${orgLink}" target="_blank" class="jira-link-log">${res.issue}</a>: ${res.message}`;
                    }
                    progressLog.appendChild(entry);
                    progressLog.scrollTop = progressLog.scrollHeight;
                });
                const finalEntry = document.createElement('div');
                finalEntry.className = 'log-entry log-info';
                finalEntry.style.marginTop = '10px';
                finalEntry.textContent = 'Cloning process finished.';
                progressLog.appendChild(finalEntry);
            } catch (error) {
                const entry = document.createElement('div');
                entry.className = 'log-entry log-error';
                entry.textContent = 'Error: ' + error.message;
                progressLog.appendChild(entry);
            } finally {
                cloneBtn.disabled = false;
                cloneBtn.textContent = 'Clone Selected';
            }
        });
    }
});
