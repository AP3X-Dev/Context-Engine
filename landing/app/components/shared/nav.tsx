import { Button } from "./button";

interface NavProps {
  brand: string;
  links: { label: string; href: string }[];
  cta?: { label: string; href: string };
}

export function Nav({ brand, links, cta }: NavProps) {
  return (
    <nav className="fixed top-0 w-full z-50 border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl">
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <span className="text-lg font-semibold tracking-tight">{brand}</span>
        <div className="flex items-center gap-8">
          {links.map((link) => (
            <a key={link.href} href={link.href} className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors">
              {link.label}
            </a>
          ))}
          {cta && <Button href={cta.href} size="sm">{cta.label}</Button>}
        </div>
      </div>
    </nav>
  );
}
