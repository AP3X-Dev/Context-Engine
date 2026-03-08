"use client";

import { motion } from "framer-motion";
import { Section } from "../shared/section";

const steps = [
  {
    number: "01",
    title: "Upload",
    description: "Push your codebase, docs, or data via CLI, API, or drag-and-drop",
    icon: "📤",
  },
  {
    number: "02",
    title: "Connect",
    description: "Add your MCP endpoint URL to Claude Code, Cursor, or any agent",
    icon: "🔗",
  },
  {
    number: "03",
    title: "Query",
    description: "Your agent searches with hybrid retrieval — vectors + lexical + reranking",
    icon: "🔍",
  },
];

export function HowItWorks() {
  return (
    <Section>
      <h2
        className="text-center mb-16"
        style={{
          fontFamily: "'Inter Tight', sans-serif",
          fontSize: "clamp(28px, 4vw, 44px)",
          fontWeight: 800,
          letterSpacing: "-0.03em",
        }}
      >
        How it works
      </h2>
      <div className="grid md:grid-cols-3 gap-4">
        {steps.map((step, i) => (
          <motion.div
            key={step.number}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.1 }}
            className="text-center"
            style={{
              background: "linear-gradient(180deg, #1a1a1c, #111113)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: 28,
            }}
          >
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
                margin: "0 auto 16px",
              }}
            >
              {step.icon}
            </div>
            <span
              style={{
                fontFamily: "'Inter Tight', sans-serif",
                fontSize: 40,
                fontWeight: 800,
                color: "var(--accent)",
                opacity: 0.2,
                lineHeight: 1,
              }}
            >
              {step.number}
            </span>
            <h3
              style={{
                fontFamily: "'Inter Tight', sans-serif",
                fontSize: 18,
                fontWeight: 700,
                marginTop: 8,
                letterSpacing: "-0.02em",
              }}
            >
              {step.title}
            </h3>
            <p style={{ marginTop: 8, color: "var(--text2)", fontSize: 15, lineHeight: 1.6 }}>
              {step.description}
            </p>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
