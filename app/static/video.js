// theme toggle for the /video page (the first screen wires its own in home.js)
(function () {
  var b = document.getElementById("themebtn");
  if (!b) return;
  function cur() { var t = document.documentElement.dataset.theme; return t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
  function label() { b.textContent = cur() === "dark" ? "◑ Light" : "◑ Dark"; }
  label();
  b.addEventListener("click", function () {
    var n = cur() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = n;
    try { localStorage.setItem("theme", n); } catch (e) {}
    label();
  });
})();
