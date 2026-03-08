"use client";

import { motion } from "framer-motion";
import { Button } from "../shared/button";

export function CortexHero() {
  return (
    <section className="px-6 pt-32 pb-24 text-center">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <span className="inline-block px-3 py-1 text-xs font-medium rounded-full border border-[var(--border)] text-[var(--accent)] mb-6">
          MCP-Native Retrieval Service
        </span>
        <h1 className="text-5xl md:text-7xl font-bold tracking-tight max-w-4xl mx-auto leading-[1.1]">
          Plug your agent into everything it needs to know
        </h1>
        <p className="mt-6 text-xl text-[var(--text-secondary)] max-w-2xl mx-auto">
          Managed MCP retrieval for AI agents. Upload your code, docs, and data — query it from any MCP-compatible IDE.
        </p>
        <div className="mt-10 flex items-center justify-center gap-4">
          <Button href="#signup" size="lg">Get Started Free</Button>
          <Button href="/docs" variant="ghost" size="lg">View Docs →</Button>
        </div>
      </motion.div>
    </section>
  );
}
