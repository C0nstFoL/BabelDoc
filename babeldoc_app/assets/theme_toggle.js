() => {
    const order = ['system', 'light', 'dark'];
    const labels = {system: '🖥️ 跟随系统', light: '☀️ 亮色', dark: '🌙 暗色'};
    const current = localStorage.getItem('babeldoc-theme') || 'system';
    const next = order[(order.indexOf(current) + 1) % order.length];
    localStorage.setItem('babeldoc-theme', next);
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const shouldBeDark = next === 'dark' || (next === 'system' && prefersDark);
    document.documentElement.classList.toggle('dark', shouldBeDark);
    document.body.classList.toggle('dark', shouldBeDark);
    const btn = document.querySelector('.theme-toggle-row button');
    if (btn) btn.textContent = labels[next];
}
