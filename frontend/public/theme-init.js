// Runs before first paint so the page never flashes the wrong theme.
// Kept as a file, not inline, so the Content-Security-Policy needs no exceptions.
(function () {
  try {
    var saved = localStorage.getItem("vidhi_theme");
    var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (dark) document.documentElement.classList.add("dark");
  } catch (e) {}
})();
