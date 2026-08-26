document.getElementById('taskForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const taskInput = document.getElementById('taskInput');
    const apiKeyInput = document.getElementById('apiKeyInput');
    const submitBtn = document.getElementById('submitBtn');
    const btnText = document.getElementById('btnText');
    const btnLoader = document.getElementById('btnLoader');
    const timeline = document.getElementById('timeline');
    
    const task = taskInput.value.trim();
    const apiKey = apiKeyInput.value.trim();
    if (!task || !apiKey) return;
    
    // UI Loading State
    submitBtn.disabled = true;
    btnText.classList.add('hidden');
    btnLoader.classList.remove('hidden');
    
    // Reset timeline
    timeline.innerHTML = '';
    
    try {
        const response = await fetch('/api/orchestrate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiKey
            },
            body: JSON.stringify({ task })
        });
        
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        if (data.history && data.history.length > 0) {
            data.history.forEach(item => {
                const el = document.createElement('div');
                el.className = `timeline-item ${item.role}`;
                
                const role = document.createElement('div');
                role.className = 'role';
                role.textContent = item.role;
                
                const content = document.createElement('div');
                content.className = 'content';
                content.textContent = item.content;
                
                el.appendChild(role);
                el.appendChild(content);
                timeline.appendChild(el);
            });
        } else {
            const placeholder = document.createElement('div');
            placeholder.className = 'placeholder';
            placeholder.textContent = 'No history returned. Final Result:\n' + data.result;
            timeline.appendChild(placeholder);
        }
        
    } catch (error) {
        const el = document.createElement('div');
        el.className = 'timeline-item';
        
        const role = document.createElement('div');
        role.className = 'role';
        role.style.color = '#ef4444';
        role.textContent = 'Error';
        
        const content = document.createElement('div');
        content.className = 'content';
        content.textContent = error.message;
        
        el.appendChild(role);
        el.appendChild(content);
        timeline.appendChild(el);
    } finally {
        submitBtn.disabled = false;
        btnText.classList.remove('hidden');
        btnLoader.classList.add('hidden');
    }
});
