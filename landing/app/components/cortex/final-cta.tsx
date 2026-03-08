"use client";

import { motion } from "framer-motion";
import { Button } from "../shared/button";

export function FinalCta() {
  return (
    <section id="signup" style={{ padding: "100px 32px", textAlign: "center" }}>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
      >
        <h2
          style={{
            fontFamily: "'Inter Tight', sans-serif",
            fontSize: "clamp(32px, 5vw, 56px)",
            fontWeight: 800,
            letterSpacing: "-0.04em",
            lineHeight: 1.06,
          }}
        >
          Ready to give your agent a{" "}
          <span className="gradient-text">brain</span>?
        </h2>
        <p style={{ marginTop: 16, fontSize: 18, color: "var(--text2)", lineHeight: 1.6 }}>
          Free tier. No credit card required. Set up in 5 minutes.
        </p>
        <div style={{ marginTop: 32 }}>
          <Button href="#signup" size="lg">Get Started Free</Button>
        </div>
      </motion.div>
    </section>
  );
}
