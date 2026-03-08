"use client";

import { motion } from "framer-motion";
import { Section } from "../shared/section";

const steps = [
  {
    number: "01",
    title: "Upload",
    description: "Push your codebase, docs, or data via CLI, API, or drag-and-drop",
  },
  {
    number: "02",
    title: "Connect",
    description: "Add your MCP endpoint URL to Claude Code, Cursor, or any agent",
  },
  {
    number: "03",
    title: "Query",
    description: "Your agent searches with hybrid retrieval — vectors + lexical + reranking",
  },
];

export function HowItWorks() {
  return (
    <Section>
      <h2 className="text-3xl font-bold text-center mb-16">How it works</h2>
      <div className="grid md:grid-cols-3 gap-12">
        {steps.map((step, i) => (
          <motion.div
            key={step.number}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: i * 0.15 }}
            className="text-center"
          >
            <span className="text-5xl font-bold text-[var(--accent)]/20">{step.number}</span>
            <h3 className="mt-4 text-xl font-semibold">{step.title}</h3>
            <p className="mt-3 text-[var(--text-secondary)] leading-relaxed">{step.description}</p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
