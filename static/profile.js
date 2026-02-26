document.addEventListener('DOMContentLoaded', async () => {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = '/login';
        return;
    }

    const profileForm = document.getElementById('profile-form');
    const usernameInput = document.getElementById('profile-username');
    const jiraUrlInput = document.getElementById('profile-jira-url');
    const jiraEmailInput = document.getElementById('profile-jira-email');
    const jiraTokenInput = document.getElementById('profile-jira-token');
    const newPasswordInput = document.getElementById('profile-new-password');
    const confirmPasswordInput = document.getElementById('profile-confirm-password');
    const currentPasswordInput = document.getElementById('profile-current-password');

    // Fetch current profile data
    async function fetchProfile() {
        try {
            const response = await fetch('/api/auth/profile', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                const data = await response.json();
                usernameInput.value = data.username;
                jiraUrlInput.value = data.jira_base_url;
                jiraEmailInput.value = data.jira_email;
            } else {
                console.error('Failed to fetch profile');
                if (response.status === 401) window.location.href = '/login';
            }
        } catch (error) {
            console.error('Error fetching profile:', error);
        }
    }

    fetchProfile();

    profileForm.onsubmit = async (e) => {
        e.preventDefault();

        const currentPassword = currentPasswordInput.value;
        const newPassword = newPasswordInput.value;
        const confirmPassword = confirmPasswordInput.value;

        if (newPassword && newPassword !== confirmPassword) {
            alert('New passwords do not match');
            return;
        }

        const profileData = {
            current_password: currentPassword,
            jira_base_url: jiraUrlInput.value,
            jira_email: jiraEmailInput.value
        };

        if (newPassword) profileData.new_password = newPassword;
        if (jiraTokenInput.value) profileData.jira_api_token = jiraTokenInput.value;

        try {
            const response = await fetch('/api/auth/profile', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(profileData)
            });

            if (response.ok) {
                alert('Profile updated successfully!');
                // We might need to handle token refresh if username changed, 
                // but username change is not implemented in PUT yet for simplicity.
                currentPasswordInput.value = '';
                newPasswordInput.value = '';
                confirmPasswordInput.value = '';
                fetchProfile();
            } else {
                const err = await response.json();
                alert('Update failed: ' + (err.detail || 'Unknown error'));
            }
        } catch (error) {
            alert('Error updating profile: ' + error.message);
        }
    };
});
