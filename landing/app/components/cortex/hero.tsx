"use client";

import { motion } from "framer-motion";
import { Button } from "../shared/button";

export function CortexHero() {
  return (
    <section style={{ padding: "100px 24px 60px", textAlign: "center" }}>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <span className="shimmer-label" style={{ marginBottom: 24, display: "inline-block" }}>
          MCP-Native Retrieval Service
        </span>
        <h1
          style={{
            fontFamily: "'Inter Tight', sans-serif",
            fontSize: "clamp(40px, 7vw, 78px)",
            fontWeight: 800,
            letterSpacing: "-0.04em",
            lineHeight: 1.06,
            maxWidth: 900,
            margin: "0 auto",
          }}
        >
          Plug your agent into everything it{" "}
          <span className="gradient-text">needs to know</span>
        </h1>
        <p
          style={{
            marginTop: 24,
            fontSize: "clamp(16px, 2vw, 20px)",
            color: "var(--text2)",
            maxWidth: 520,
            margin: "24px auto 0",
            lineHeight: 1.6,
          }}
        >
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
