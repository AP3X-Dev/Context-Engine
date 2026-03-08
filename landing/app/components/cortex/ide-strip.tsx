"use client";

import { motion } from "framer-motion";

const ides = [
  "Claude Code",
  "Cursor",
  "Windsurf",
  "Cline",
  "Qodo",
  "Any MCP Client",
];

export function IdeStrip() {
  return (
    <section
      style={{
        padding: "48px 32px",
        borderTop: "1px solid var(--border)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <p className="text-center mb-8" style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, textTransform: "uppercase", color: "var(--text3)" }}>
        Works with your stack
      </p>
      <motion.div
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        className="flex flex-wrap items-center justify-center gap-8 md:gap-12"
      >
        {ides.map((ide) => (
          <span
            key={ide}
            className="transition-colors duration-200 hover:text-white"
            style={{
              fontFamily: "'Inter Tight', sans-serif",
              fontSize: 16,
              fontWeight: 600,
              color: "var(--text3)",
              letterSpacing: "-0.01em",
            }}
          >
            {ide}
          </span>
        ))}
      </motion.div>
    </section>
  );
}
