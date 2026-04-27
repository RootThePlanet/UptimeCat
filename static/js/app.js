/* UptimeCat — app.js
   Progressive enhancement: auto-refresh dashboard status every 60 s.
*/
(function () {
  "use strict";

  // How often (in milliseconds) the dashboard reloads to show fresh status.
  var DASHBOARD_REFRESH_MS = 60_000;

  // Auto-refresh the dashboard so statuses stay current.
  var isDashboard = document.querySelector(".sites-grid") !== null;
  if (isDashboard) {
    setTimeout(function () { window.location.reload(); }, DASHBOARD_REFRESH_MS);
  }
})();
