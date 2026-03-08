"use client";

import { motion } from "framer-motion";
import { Section } from "../shared/section";

const features = [
  {
    title: "MCP-Native",
    description: "Works with every major AI IDE out of the box. No custom SDK — just a URL and an API key.",
  },
  {
    title: "Hybrid Search",
    description: "Dense vectors + lexical matching + reciprocal rank fusion for precise, relevant results.",
  },
  {
    title: "AST-Aware Chunking",
    description: "Preserves function and class boundaries. 30% better retrieval precision than naive splitting.",
  },
  {
    title: "Multi-Tenant",
    description: "Isolated collections per team, per project. Full data separation with shared infrastructure.",
  },
  {
    title: "Usage Dashboard",
    description: "Real-time query counts, vector usage, and cost tracking. Know exactly what you're using.",
  },
  {
    title: "Universal Upload",
    description: "Code, markdown, PDF, JSON, YAML, CSV, OpenAPI specs. If your agent needs it, Cortex indexes it.",
  },
];

export function Features() {
  return (
    <Section id="features">
      <h2 className="text-3xl font-bold text-center mb-16">Built for agents, not humans</h2>
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
        {features.map((feature, i) => (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.08 }}
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6"
          >
            <h3 className="text-lg font-semibold">{feature.title}</h3>
            <p className="mt-2 text-sm text-[var(--text-secondary)] leading-relaxed">
              {feature.description}
            </p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
