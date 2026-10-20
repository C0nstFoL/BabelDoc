() => {
    if (window.__babeldocHistoryRowSelectionInstalled) return;
    window.__babeldocHistoryRowSelectionInstalled = true;
    document.addEventListener('click', (event) => {
        const cell = event.target.closest('.history-table [data-row]');
        if (!cell) return;
        requestAnimationFrame(() => {
            const table = cell.closest('.history-table');
            const tableWrap = table?.querySelector('.table-wrap');
            tableWrap?.style.setProperty('transition', 'none', 'important');
            tableWrap?.style.setProperty('animation', 'none', 'important');
            tableWrap?.style.setProperty('transform', 'none', 'important');
            tableWrap?.style.setProperty('scale', 'none', 'important');
            const selectedCell = table?.querySelector('.cell-selected[data-row]');
            const selectedRow = selectedCell?.dataset.row;
            const rowCells = [...(table?.querySelectorAll('[data-row]') ?? [])]
                .filter((item) => (
                    item.dataset.row === selectedRow
                    && Number.isFinite(Number(item.dataset.col))
                ))
                .sort((a, b) => Number(a.dataset.col) - Number(b.dataset.col));
            const firstCell = rowCells[0];
            const lastCell = rowCells[rowCells.length - 1];
            table?.querySelectorAll('[data-row]').forEach((rowCell) => {
                const selected = selectedRow !== undefined && rowCell.dataset.row === selectedRow;
                rowCell.classList.toggle(
                    'history-row-selected',
                    selected,
                );
                rowCell.classList.toggle('history-row-first', selected && rowCell === firstCell);
                rowCell.classList.toggle('history-row-last', selected && rowCell === lastCell);
            });
        });
    });
}
