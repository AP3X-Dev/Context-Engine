"use client";

import { motion } from "framer-motion";

export function BrandHero() {
  return (
    <section style={{ padding: "100px 24px 60px", textAlign: "center" }}>
      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        style={{
          fontFamily: "'Inter Tight', sans-serif",
          fontSize: "clamp(40px, 7vw, 78px)",
          fontWeight: 800,
          letterSpacing: "-0.04em",
          lineHeight: 1.06,
          maxWidth: "900px",
          margin: "0 auto",
        }}
      >
        The Agent Infrastructure{" "}
        <span className="gradient-text">Company</span>
      </motion.h1>
      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.2 }}
        style={{
          marginTop: 24,
          fontSize: "clamp(16px, 2vw, 20px)",
          color: "var(--text2)",
          maxWidth: 520,
          margin: "24px auto 0",
          lineHeight: 1.6,
        }}
      >
        Tools for building, running, and scaling AI agents
      </motion.p>
    </section>
  );
}
