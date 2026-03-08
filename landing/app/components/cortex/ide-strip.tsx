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
    <section className="py-16 border-y border-[var(--border)]">
      <p className="text-center text-sm text-[var(--text-secondary)] mb-8">
        Works with your stack
      </p>
      <motion.div
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        className="flex flex-wrap items-center justify-center gap-8 md:gap-12 px-6"
      >
        {ides.map((ide) => (
          <span
            key={ide}
            className="text-lg font-medium text-[var(--text-secondary)]/60 hover:text-[var(--text-primary)] transition-colors"
          >
            {ide}
          </span>
        ))}
      </motion.div>
    </section>
  );
}
