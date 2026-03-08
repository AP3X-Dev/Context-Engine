"use client";

import { motion } from "framer-motion";
import { Button } from "../shared/button";

export function FinalCta() {
  return (
    <section id="signup" className="px-6 py-32 text-center">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
      >
        <h2 className="text-4xl md:text-5xl font-bold tracking-tight">
          Ready to give your agent a brain?
        </h2>
        <p className="mt-4 text-lg text-[var(--text-secondary)]">
          Free tier. No credit card required. Set up in 5 minutes.
        </p>
        <div className="mt-8">
          <Button href="#signup" size="lg">Get Started Free</Button>
        </div>
      </motion.div>
    </section>
  );
}
