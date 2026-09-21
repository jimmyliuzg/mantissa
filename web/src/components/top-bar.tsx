export function TopBar() {
  return (
    <header class="topbar">
      {/* Hash route, not "/": on GitHub Pages (base /mantissa/) a root
          href would leave the app. */}
      <a href="#/" class="brand">
        <span class="logo">M</span>
        <span class="brand-text">Mantissa</span>
        <span class="brand-sub">Plan Viewer</span>
      </a>
      <nav>
        <a href="https://github.com/jimmyliuzg/mantissa" rel="noopener noreferrer" target="_blank">
          GitHub
        </a>
      </nav>
    </header>
  );
}
