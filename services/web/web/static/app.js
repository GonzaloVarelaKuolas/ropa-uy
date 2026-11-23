// Small conveniences. The site works without this file.
(function () {
  var form = document.getElementById('filtros');
  if (form) {
    // Apply filters as soon as a box or the sort order changes.
    document.addEventListener('change', function (event) {
      var el = event.target;
      if (el.form !== form) return;
      if (el.type === 'checkbox' || el.tagName === 'SELECT') form.requestSubmit();
    });
    // Don't send empty price fields, so URLs stay clean.
    form.addEventListener('submit', function () {
      form.querySelectorAll('input[type=number]').forEach(function (input) {
        if (!input.value) input.disabled = true;
      });
      var sort = document.querySelector('select[form=filtros]');
      if (sort && sort.value === 'nuevo') sort.disabled = true;
    });
  }
  // Back/forward cache can restore disabled fields: re-enable them.
  window.addEventListener('pageshow', function () {
    document.querySelectorAll('#filtros input:disabled, select[form=filtros]:disabled').forEach(function (el) {
      el.disabled = false;
    });
  });
})();
