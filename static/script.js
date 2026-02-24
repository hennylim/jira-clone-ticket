document.addEventListener('DOMContentLoaded', () => {
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

    const configSchema = [
        { key: 'jql', label: 'JQL Query', type: 'text', fullWidth: true },
        { key: 'clone_project_key', label: 'Clone Project Key', type: 'text' },
        { key: 'issue_type', label: 'Issue Type', type: 'text' },
        { key: 'due_date', label: 'Due Date / Delay (e.g. 1W, 2D)', type: 'text' },
        { key: 'clone_label', label: 'Clone Labels (space separated)', type: 'text' },
        { key: 'clone_models', label: 'Clone Models (space separated)', type: 'text' },
        { key: 'parent_key', label: 'Parent Issue Key (optional)', type: 'text' },
        { key: 'env', label: '.env Path', type: 'text' }
    ];

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

            let value = config[field.key] || '';
            if (Array.isArray(value)) {
                value = value.join(' ');
            }
            input.value = value;

            group.appendChild(label);
            group.appendChild(input);
            configForm.appendChild(group);
        });
    }

    function getConfigFromForm() {
        const config = {};
        configSchema.forEach(field => {
            const input = document.getElementById(`input-${field.key}`);
            let value = input.value.trim();

            if (field.key === 'clone_label' || field.key === 'clone_models') {
                value = value.split(/\s+/).filter(v => v);
            }

            if (value !== '') {
                config[field.key] = value;
            }
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

    // Initial render
    renderConfigForm(exampleConfig);

    loadFileBtn.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const json = JSON.parse(e.target.result);
                renderConfigForm(json);
                // Clear the file input so the same file can be loaded again if needed
                event.target.value = '';
            } catch (error) {
                alert('Error parsing JSON file: ' + error.message);
            }
        };
        reader.readAsText(file);
    });

    loadExampleBtn.addEventListener('click', () => {
        renderConfigForm(exampleConfig);
    });

    saveConfigBtn.addEventListener('click', async () => {
        const config = getConfigFromForm();
        const filename = prompt("Enter filename to save as (e.g., config.json):", "config.json");
        if (!filename) return;

        saveConfigBtn.disabled = true;
        saveConfigBtn.textContent = 'Saving...';

        try {
            const response = await fetch('/api/config/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config, filename })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Save failed');
            }

            const data = await response.json();
            alert(data.message);
        } catch (error) {
            alert('Error: ' + error.message);
        } finally {
            saveConfigBtn.disabled = false;
            saveConfigBtn.textContent = 'Save Config';
        }
    });

    searchBtn.addEventListener('click', async () => {
        const config = getConfigFromForm();

        searchBtn.disabled = true;
        searchBtn.textContent = 'Searching...';

        try {
            const response = await fetch('/api/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Search failed');
            }

            const data = await response.json();
            displayIssues(data.issues);
        } catch (error) {
            alert('Error: ' + error.message);
        } finally {
            searchBtn.disabled = false;
            searchBtn.textContent = 'Search Issues';
        }
    });

    function displayIssues(issues) {
        issueBody.innerHTML = '';
        if (issues.length === 0) {
            issueBody.innerHTML = '<tr><td colspan="4" style="text-align: center;">No issues found.</td></tr>';
            cloneBtn.disabled = true;
        } else {
            issues.forEach(issue => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><input type="checkbox" class="issue-checkbox" value="${issue.key}"></td>
                    <td>${issue.key}</td>
                    <td>${issue.key} - ${issue.summary}</td>
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

        if (!confirm(`Are you sure you want to clone ${selectedKeys.length} tickets?`)) {
            return;
        }

        cloneBtn.disabled = true;
        cloneBtn.textContent = 'Cloning...';
        progressSection.classList.remove('hidden');
        progressLog.innerHTML = `<div class="log-entry log-info">Starting clone process for ${selectedKeys.length} tickets...</div>`;
        progressSection.scrollIntoView({ behavior: 'smooth' });

        try {
            const response = await fetch('/api/clone', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    config,
                    selected_issue_keys: selectedKeys
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Cloning failed');
            }

            const data = await response.json();
            data.results.forEach(res => {
                const entry = document.createElement('div');
                entry.className = 'log-entry';
                if (res.status === 'success') {
                    entry.classList.add('log-success');
                    entry.textContent = `[SUCCESS] ${res.summary} - ${res.issue} cloned as ${res.new_issue_key}`;
                } else if (res.status === 'skipped') {
                    entry.classList.add('log-warning');
                    entry.textContent = `[SKIPPED] ${res.summary} - ${res.issue}: ${res.message}`;
                } else {
                    entry.classList.add('log-error');
                    entry.textContent = `[FAILED] ${res.summary} - ${res.issue}: ${res.message}`;
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
});
