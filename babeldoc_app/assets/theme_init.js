() => {
    const labels = {system: '🖥️ 跟随系统', light: '☀️ 亮色', dark: '🌙 暗色'};
    const saved = localStorage.getItem('babeldoc-theme') || 'system';
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const shouldBeDark = saved === 'dark' || (saved === 'system' && prefersDark);
    document.documentElement.classList.toggle('dark', shouldBeDark);
    document.body.classList.toggle('dark', shouldBeDark);
    const btn = document.querySelector('.theme-toggle-row button');
    if (btn) btn.textContent = labels[saved];
}
