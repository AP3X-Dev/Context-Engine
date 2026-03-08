import Image from "next/image";

export function Footer() {
  return (
    <footer
      style={{
        padding: "40px 32px",
        borderTop: "1px solid transparent",
        borderImage: "linear-gradient(90deg, transparent, var(--border2), rgba(224, 64, 64, 0.15), var(--border2), transparent) 1",
      }}
    >
      <div
        className="max-w-[1100px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm"
        style={{ color: "var(--text2)" }}
      >
        <a href="/" className="flex items-center gap-2">
          <Image src="/oni-logo.png" alt="ONI" width={20} height={20} className="rounded-[5px]" />
          <span style={{ fontWeight: 600, color: "var(--text2)" }}>ONI</span>
        </a>
        <div className="flex gap-6">
          <a href="https://github.com/m1rl0k/Context-Engine" className="transition-colors duration-200 hover:text-white" style={{ color: "var(--text2)" }}>GitHub</a>
          <a href="/terms" className="transition-colors duration-200 hover:text-white" style={{ color: "var(--text2)" }}>Terms</a>
          <a href="/privacy" className="transition-colors duration-200 hover:text-white" style={{ color: "var(--text2)" }}>Privacy</a>
        </div>
        <span>&copy; {new Date().getFullYear()} ONI</span>
      </div>
    </footer>
  );
}
