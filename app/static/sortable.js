/**
 * Auto-sortable tables: add class="sortable" to any <th> to make its column sortable.
 * Attach to all data-table elements on DOMContentLoaded.
 */
(function(){
  function initSortable(root) {
    (root || document).querySelectorAll('table.data-table').forEach(function(table){
      if (table.dataset.sortableInit) return;
      table.dataset.sortableInit = 'true';
      var headers = table.querySelectorAll('th.sortable');
      if (!headers.length) return;
      var tbody = table.querySelector('tbody');
      if (!tbody) return;

      var sortCol = null, sortAsc = true;

      headers.forEach(function(th, idx){
        // Determine actual column index from data-col or position among all ths
        var colIdx = th.dataset.col !== undefined ? parseInt(th.dataset.col) : th.cellIndex;
        th.style.cursor = 'pointer';

        // Add arrow span if not already present
        if (!th.querySelector('.sort-arrow')) {
          var arrow = document.createElement('span');
          arrow.className = 'sort-arrow';
          th.appendChild(arrow);
        }

        th.addEventListener('click', function(){
          if (sortCol === colIdx) sortAsc = !sortAsc;
          else { sortCol = colIdx; sortAsc = true; }

          // Update arrows
          headers.forEach(function(h){ h.querySelector('.sort-arrow').textContent = ''; });
          th.querySelector('.sort-arrow').textContent = sortAsc ? ' \u25B2' : ' \u25BC';

          var rows = Array.from(tbody.querySelectorAll('tr'));
          rows.sort(function(a, b){
            var cellA = (a.cells[colIdx] || {textContent:''}).textContent.trim().toLowerCase();
            var cellB = (b.cells[colIdx] || {textContent:''}).textContent.trim().toLowerCase();
            // Try numeric sort first
            var numA = parseFloat(cellA), numB = parseFloat(cellB);
            if (!isNaN(numA) && !isNaN(numB)) {
              return sortAsc ? numA - numB : numB - numA;
            }
            if (cellA < cellB) return sortAsc ? -1 : 1;
            if (cellA > cellB) return sortAsc ? 1 : -1;
            return 0;
          });
          rows.forEach(function(r){ tbody.appendChild(r); });
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function(){ initSortable(); });
  document.addEventListener('htmx:afterSwap', function(e){ initSortable(e.detail.target); });
})();
