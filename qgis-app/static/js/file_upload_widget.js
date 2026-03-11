/**
 * File Upload Drop Zone
 *
 * Enhances every .file-upload-zone element with drag-and-drop support and
 * visual feedback.  Works with the file_input_widget.html partial.
 */
(function () {
  'use strict';

  function initFileUploadZone(zone) {
    var input = zone.querySelector('input[type="file"]');
    var selectedEl = zone.querySelector('.file-upload-selected');
    var selectedName = zone.querySelector('.file-upload-selected-name');

    if (!input) return;

    function setFile(fileName) {
      if (fileName) {
        zone.classList.add('has-file');
        if (selectedName) selectedName.textContent = fileName;
      } else {
        zone.classList.remove('has-file');
        if (selectedName) selectedName.textContent = '';
      }
    }

    // Native file picker selection
    input.addEventListener('change', function () {
      if (input.files && input.files.length > 0) {
        setFile(input.files[0].name);
      } else {
        setFile(null);
      }
    });

    // Drag-and-drop support
    ['dragenter', 'dragover'].forEach(function (eventName) {
      zone.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.add('is-dragover');
      });
    });

    ['dragleave', 'dragend'].forEach(function (eventName) {
      zone.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.remove('is-dragover');
      });
    });

    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.remove('is-dragover');

      var files = e.dataTransfer && e.dataTransfer.files;
      if (!files || files.length === 0) return;

      // Only accept the first file; rely on the accept attribute for filtering
      var accept = input.getAttribute('accept');
      if (accept) {
        var accepted = accept.split(',').map(function (a) { return a.trim().toLowerCase(); });
        var file = files[0];
        var ext = '.' + file.name.split('.').pop().toLowerCase();
        var mime = file.type.toLowerCase();
        var allowed = accepted.some(function (pattern) {
          return pattern === ext || pattern === mime || (pattern.endsWith('/*') && mime.startsWith(pattern.slice(0, -1)));
        });
        if (!allowed) return;
      }

      // Transfer file to the real input via DataTransfer
      try {
        var dt = new DataTransfer();
        dt.items.add(files[0]);
        input.files = dt.files;
        setFile(files[0].name);
        input.dispatchEvent(new Event('change', { bubbles: true }));
      } catch (err) {
        // DataTransfer not supported — silently ignore
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.file-upload-zone').forEach(function (zone) {
      initFileUploadZone(zone);
    });
  });
})();
