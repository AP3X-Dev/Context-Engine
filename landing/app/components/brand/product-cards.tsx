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
    icon: "🧠",
  },
  {
    name: "AG3NT",
    category: "Local-First AI Agent",
    description: "An agent that actually does things on your machine",
    href: "#",
    status: "soon" as const,
    cta: "Coming Soon",
    icon: "⚡",
  },
  {
    name: "ONI Swarm",
    category: "Multi-Agent Mission Control",
    description: "Orchestrate 16 parallel AI agents from one screen",
    href: "#",
    status: "soon" as const,
    cta: "Coming Soon",
    icon: "🕸️",
  },
];

export function ProductCards() {
  return (
    <section id="products" className="max-w-[1100px] mx-auto" style={{ padding: "0 32px 100px" }}>
      <div className="grid md:grid-cols-3 gap-4">
        {products.map((product, i) => (
          <motion.a
            key={product.name}
            href={product.status === "live" ? product.href : undefined}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.05 + i * 0.07 }}
            className="group relative overflow-hidden"
            style={{
              background: "linear-gradient(180deg, #1a1a1c, #111113)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: 28,
              cursor: product.status === "live" ? "pointer" : "default",
              opacity: product.status === "soon" ? 0.7 : 1,
              transition: "border-color 0.3s, transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.4s",
            }}
            whileHover={product.status === "live" ? {
              y: -4,
              borderColor: "rgba(224, 64, 64, 0.2)",
            } : undefined}
          >
            {/* Shimmer sweep */}
            <div
              className="absolute top-0 left-[-100%] w-1/2 h-full pointer-events-none transition-[left] duration-600 ease-in-out group-hover:left-[150%]"
              style={{
                background: "linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.03), transparent)",
              }}
            />
            <div
              style={{
                width: 48,
                height: 48,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "var(--surface2)",
                borderRadius: 10,
                border: "1px solid var(--border)",
                fontSize: 26,
                marginBottom: 16,
                transition: "all 0.3s",
              }}
            >
              {product.icon}
            </div>
            <span
              className="shimmer-label"
              style={{ fontSize: 11, letterSpacing: 2 }}
            >
              {product.category}
            </span>
            <h3
              style={{
                fontFamily: "'Inter Tight', sans-serif",
                fontSize: 22,
                fontWeight: 700,
                marginTop: 8,
                letterSpacing: "-0.02em",
              }}
            >
              {product.name}
            </h3>
            <p style={{ color: "var(--text2)", marginTop: 8, fontSize: 15, lineHeight: 1.6 }}>
              {product.description}
            </p>
            <span
              style={{
                marginTop: 16,
                display: "inline-block",
                fontSize: 14,
                fontWeight: 600,
                color: product.status === "live" ? "var(--accent)" : "var(--text3)",
              }}
            >
              {product.cta}
            </span>
            {product.status === "soon" && (
              <span
                style={{
                  position: "absolute",
                  top: 16,
                  right: 16,
                  padding: "4px 10px",
                  fontSize: 11,
                  borderRadius: 30,
                  border: "1px solid var(--border)",
                  color: "var(--text3)",
                }}
              >
                Soon
              </span>
            )}
          </motion.a>
        ))}
      </div>
    </section>
  );
}
