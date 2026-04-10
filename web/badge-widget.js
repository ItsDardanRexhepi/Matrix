/**
 * Glasswing Security Badge Widget
 *
 * Self-contained, zero-dependency embeddable widget.
 * Projects include:
 *   <script src="https://api.openmatrix.io/badge/widget.js"
 *           data-badge="GLASSWING-2026-0001"></script>
 *
 * The widget renders an inline badge that links to the full
 * verification page. All styles are scoped to avoid leaking
 * into the host page.
 */
(function () {
  "use strict";

  // ── Locate the current script tag ────────────────────────────

  var scripts = document.getElementsByTagName("script");
  var currentScript = null;
  for (var i = scripts.length - 1; i >= 0; i--) {
    if (scripts[i].getAttribute("data-badge")) {
      currentScript = scripts[i];
      break;
    }
  }
  if (!currentScript) return;

  var badgeId = currentScript.getAttribute("data-badge");
  if (!badgeId) return;

  var apiBase =
    currentScript.getAttribute("data-api-base") ||
    "https://api.openmatrix.io";
  var verifyBase =
    currentScript.getAttribute("data-verify-base") ||
    "https://openmatrix.io";

  // ── Create a scoped container ────────────────────────────────

  var container = document.createElement("div");
  container.className = "glasswing-badge-widget-" + sanitize(badgeId);
  currentScript.parentNode.insertBefore(container, currentScript.nextSibling);

  // ── Render loading state ─────────────────────────────────────

  container.innerHTML = buildBadge("loading", badgeId, null);

  // ── Fetch badge status ───────────────────────────────────────

  var url = apiBase + "/badge/" + encodeURIComponent(badgeId) + "/status";

  fetch(url)
    .then(function (resp) {
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return resp.json();
    })
    .then(function (data) {
      var status = data.status || "valid";
      container.innerHTML = buildBadge(status, badgeId, data);
    })
    .catch(function () {
      container.innerHTML = buildBadge("error", badgeId, null);
    });

  // ── Badge builder ────────────────────────────────────────────

  function buildBadge(status, id, data) {
    var colors = {
      valid: { bg: "#001a00", border: "#00ff41", text: "#00ff41", label: "Glasswing Verified" },
      expired: { bg: "#1a1000", border: "#ff9944", text: "#ff9944", label: "Expired" },
      revoked: { bg: "#1a0000", border: "#ff4444", text: "#ff4444", label: "Revoked" },
      loading: { bg: "#0e0e0e", border: "#333", text: "#666", label: "Verifying..." },
      error: { bg: "#0e0e0e", border: "#333", text: "#666", label: "Verification unavailable" },
    };
    var c = colors[status] || colors.error;

    var verifyUrl = verifyBase + "/badge/" + encodeURIComponent(id);
    var isClickable = status !== "loading";
    var tag = isClickable ? "a" : "span";
    var linkAttrs = isClickable
      ? ' href="' + esc(verifyUrl) + '" target="_blank" rel="noopener noreferrer"'
      : "";

    // Shield SVG (inline, no external images)
    var shieldSvg;
    if (status === "revoked") {
      shieldSvg =
        '<svg width="18" height="20" viewBox="0 0 18 20" fill="none" xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;margin-right:6px">' +
        '<path d="M9 1L2 4v5c0 5.25 3.15 10.15 7 11.25C12.85 19.15 16 14.25 16 9V4L9 1z" stroke="' + c.border + '" stroke-width="1.5" fill="' + c.bg + '"/>' +
        '<line x1="6" y1="7.5" x2="12" y2="12.5" stroke="' + c.text + '" stroke-width="1.5" stroke-linecap="round"/>' +
        '<line x1="12" y1="7.5" x2="6" y2="12.5" stroke="' + c.text + '" stroke-width="1.5" stroke-linecap="round"/>' +
        "</svg>";
    } else {
      shieldSvg =
        '<svg width="18" height="20" viewBox="0 0 18 20" fill="none" xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;margin-right:6px">' +
        '<path d="M9 1L2 4v5c0 5.25 3.15 10.15 7 11.25C12.85 19.15 16 14.25 16 9V4L9 1z" stroke="' + c.border + '" stroke-width="1.5" fill="' + c.bg + '"/>' +
        '<polyline points="6,10 8.5,12.5 12.5,7.5" stroke="' + c.text + '" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' +
        "</svg>";
    }

    // Scoped styles (prefixed to avoid leaking)
    var uid = "gw-" + sanitize(id);
    var styles =
      "<style>" +
      "." + uid + "{display:inline-block;font-family:'SF Mono','Fira Code','Cascadia Code','Courier New',monospace;font-size:0;line-height:1}" +
      "." + uid + " a,." + uid + " span{" +
        "display:inline-flex;align-items:center;" +
        "padding:6px 14px 6px 10px;" +
        "background:" + c.bg + ";" +
        "border:1px solid " + c.border + ";" +
        "border-radius:6px;" +
        "color:" + c.text + ";" +
        "font-family:inherit;font-size:12px;font-weight:600;" +
        "text-decoration:none;" +
        "transition:border-color .2s,box-shadow .2s;" +
        "cursor:" + (isClickable ? "pointer" : "default") + ";" +
      "}" +
      "." + uid + " a:hover{box-shadow:0 0 10px " + c.border + "40;text-decoration:none}" +
      "</style>";

    return (
      styles +
      '<div class="' + uid + '">' +
      "<" + tag + linkAttrs + ">" +
      shieldSvg +
      '<span style="font-size:12px">' + esc(c.label) + "</span>" +
      "</" + tag + ">" +
      "</div>"
    );
  }

  // ── Utilities ────────────────────────────────────────────────

  function esc(s) {
    if (!s) return "";
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function sanitize(s) {
    return s.replace(/[^a-zA-Z0-9-]/g, "-").toLowerCase();
  }
})();
