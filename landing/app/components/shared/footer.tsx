export function Footer() {
  return (
    <footer className="border-t border-[var(--border)] py-12 px-6">
      <div className="max-w-6xl mx-auto flex items-center justify-between text-sm text-[var(--text-secondary)]">
        <span>&copy; {new Date().getFullYear()} ONI</span>
        <div className="flex gap-6">
          <a href="https://github.com" className="hover:text-[var(--text-primary)] transition-colors">GitHub</a>
          <a href="https://discord.gg" className="hover:text-[var(--text-primary)] transition-colors">Discord</a>
        </div>
      </div>
    </footer>
  );
}
