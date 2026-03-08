"use client";

import { useEffect, useState } from "react";
import Image from "next/image";

interface NavProps {
  brand: string;
  links: { label: string; href: string }[];
  cta?: { label: string; href: string };
}

export function Nav({ brand, links, cta }: NavProps) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className="fixed top-0 w-full z-50 transition-all duration-300"
      style={{
        height: 60,
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        background: scrolled ? "rgba(10, 10, 10, 0.92)" : "rgba(10, 10, 10, 0.75)",
        borderBottom: `1px solid ${scrolled ? "var(--border)" : "transparent"}`,
      }}
    >
      <div className="max-w-[1100px] mx-auto px-8 h-full flex items-center justify-between">
        <a href="/" className="flex items-center gap-2">
          <Image src="/oni-logo.png" alt="ONI" width={28} height={28} className="rounded-[7px]" />
          <span
            className="text-lg font-bold tracking-[-0.02em]"
            style={{ fontFamily: "'Inter Tight', sans-serif" }}
          >
            {brand}
          </span>
        </a>
        <div className="flex items-center gap-8">
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-sm transition-colors duration-200"
              style={{ color: "var(--text2)", fontWeight: 500 }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text2)")}
            >
              {link.label}
            </a>
          ))}
          {cta && (
            <a
              href={cta.href}
              className="text-sm font-bold rounded-[var(--radius-sm)] cursor-pointer"
              style={{
                background: "var(--accent)",
                color: "#0a0a0a",
                padding: "8px 18px",
                boxShadow: "0 4px 20px rgba(0, 212, 106, 0.15), var(--depth-shadow), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.2)",
                transition: "all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--accent2)";
                e.currentTarget.style.transform = "translateY(-3px)";
                e.currentTarget.style.boxShadow = "0 12px 40px rgba(0, 212, 106, 0.4), var(--depth-shadow-hover), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.2)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "0 4px 20px rgba(0, 212, 106, 0.15), var(--depth-shadow), inset 0px 2px 3px rgba(255,255,255,0.35), inset 0px -1.5px 0px rgba(0,0,0,0.2)";
              }}
            >
              {cta.label}
            </a>
          )}
        </div>
      </div>
    </nav>
  );
}
