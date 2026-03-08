"use client";

import { motion } from "framer-motion";

const products = [
  {
    name: "ONI Cortex",
    category: "Managed MCP Retrieval",
    description: "Plug your agent into everything it needs to know",
    href: "https://cortex.oni.bot",
    status: "live" as const,
    cta: "Get Started →",
  },
  {
    name: "AG3NT",
    category: "Local-First AI Agent",
    description: "An agent that actually does things on your machine",
    href: "#",
    status: "soon" as const,
    cta: "Coming Soon",
  },
  {
    name: "ONI Swarm",
    category: "Multi-Agent Mission Control",
    description: "Orchestrate 16 parallel AI agents from one screen",
    href: "#",
    status: "soon" as const,
    cta: "Coming Soon",
  },
];

export function ProductCards() {
  return (
    <section id="products" className="px-6 pb-32 max-w-6xl mx-auto">
      <div className="grid md:grid-cols-3 gap-6">
        {products.map((product, i) => (
          <motion.a
            key={product.name}
            href={product.status === "live" ? product.href : undefined}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 + i * 0.1 }}
            className={`group relative rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-8 transition-all duration-300 ${
              product.status === "live" ? "hover:border-[var(--accent)] cursor-pointer" : "opacity-70"
            }`}
          >
            <span className="text-xs font-medium uppercase tracking-wider text-[var(--text-secondary)]">
              {product.category}
            </span>
            <h3 className="mt-3 text-2xl font-semibold">{product.name}</h3>
            <p className="mt-3 text-[var(--text-secondary)] leading-relaxed">
              {product.description}
            </p>
            <span className={`mt-6 inline-block text-sm font-medium ${
              product.status === "live"
                ? "text-[var(--accent)] group-hover:text-[var(--accent-hover)]"
                : "text-[var(--text-secondary)]"
            }`}>
              {product.cta}
            </span>
            {product.status === "soon" && (
              <span className="absolute top-4 right-4 px-2 py-1 text-xs rounded-full border border-[var(--border)] text-[var(--text-secondary)]">
                Soon
              </span>
            )}
          </motion.a>
        ))}
      </div>
    </section>
  );
}
