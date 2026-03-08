"use client";

import { motion } from "framer-motion";
import { Section } from "../shared/section";

const features = [
  {
    title: "MCP-Native",
    description: "Works with every major AI IDE out of the box. No custom SDK — just a URL and an API key.",
    icon: "🔌",
  },
  {
    title: "Hybrid Search",
    description: "Dense vectors + lexical matching + reciprocal rank fusion for precise, relevant results.",
    icon: "🔎",
  },
  {
    title: "AST-Aware Chunking",
    description: "Preserves function and class boundaries. 30% better retrieval precision than naive splitting.",
    icon: "🌳",
  },
  {
    title: "Multi-Tenant",
    description: "Isolated collections per team, per project. Full data separation with shared infrastructure.",
    icon: "🏢",
  },
  {
    title: "Usage Dashboard",
    description: "Real-time query counts, vector usage, and cost tracking. Know exactly what you're using.",
    icon: "📊",
  },
  {
    title: "Universal Upload",
    description: "Code, markdown, PDF, JSON, YAML, CSV, OpenAPI specs. If your agent needs it, Cortex indexes it.",
    icon: "📁",
  },
];

export function Features() {
  return (
    <Section id="features">
      <h2
        className="text-center mb-16"
        style={{
          fontFamily: "'Inter Tight', sans-serif",
          fontSize: "clamp(28px, 4vw, 44px)",
          fontWeight: 800,
          letterSpacing: "-0.03em",
        }}
      >
        Built for agents, not humans
      </h2>
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {features.map((feature, i) => (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.07 }}
            className="group relative overflow-hidden"
            style={{
              background: "linear-gradient(180deg, #1a1a1c, #111113)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: 28,
              transition: "border-color 0.3s, transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.4s",
              animation: `card-enter 0.4s cubic-bezier(0.25, 0.1, 0.25, 1) both`,
              animationDelay: `${0.05 + i * 0.07}s`,
            }}
          >
            {/* Shimmer sweep */}
            <div
              className="absolute top-0 left-[-100%] w-1/2 h-full pointer-events-none transition-[left] duration-600 ease-in-out group-hover:left-[150%]"
              style={{
                background: "linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.03), transparent)",
              }}
            />
            <div
              className="group-hover:border-[rgba(0,212,106,0.25)] group-hover:animate-[icon-glow-pulse_2s_ease-in-out_infinite]"
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
              {feature.icon}
            </div>
            <h3
              style={{
                fontFamily: "'Inter Tight', sans-serif",
                fontSize: 16,
                fontWeight: 700,
                letterSpacing: "-0.02em",
              }}
            >
              {feature.title}
            </h3>
            <p style={{ marginTop: 8, fontSize: 14, color: "var(--text2)", lineHeight: 1.6 }}>
              {feature.description}
            </p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
