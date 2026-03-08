"use client";

import { motion } from "framer-motion";

export function BrandHero() {
  return (
    <section className="px-6 pt-32 pb-24 text-center">
      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="text-5xl md:text-7xl font-bold tracking-tight max-w-4xl mx-auto"
      >
        The Agent Infrastructure Company
      </motion.h1>
      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.2 }}
        className="mt-6 text-xl text-[var(--text-secondary)] max-w-2xl mx-auto"
      >
        Tools for building, running, and scaling AI agents
      </motion.p>
    </section>
  );
}
