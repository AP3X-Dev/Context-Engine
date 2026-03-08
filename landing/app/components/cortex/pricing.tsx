"use client";

import { motion } from "framer-motion";
import { Section } from "../shared/section";
import { Button } from "../shared/button";

const tiers = [
  {
    name: "Free",
    price: "$0",
    period: "",
    collections: "1",
    vectors: "10K",
    queries: "500/day",
    cta: "Get Started",
    href: "#signup",
    highlight: false,
  },
  {
    name: "Pro",
    price: "$49",
    period: "/mo",
    collections: "5",
    vectors: "250K",
    queries: "10K/day",
    cta: "Get Started",
    href: "#signup",
    highlight: false,
  },
  {
    name: "Team",
    price: "$149",
    period: "/mo",
    collections: "25",
    vectors: "1M",
    queries: "50K/day",
    cta: "Get Started",
    href: "#signup",
    highlight: true,
  },
  {
    name: "Business",
    price: "$499",
    period: "/mo",
    collections: "100",
    vectors: "5M",
    queries: "200K/day",
    cta: "Get Started",
    href: "#signup",
    highlight: false,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    collections: "Unlimited",
    vectors: "Unlimited",
    queries: "Unlimited",
    cta: "Contact Us",
    href: "mailto:hello@oni.bot",
    highlight: false,
  },
];

export function Pricing() {
  return (
    <Section id="pricing">
      <h2 className="text-3xl font-bold text-center mb-4">Simple, transparent pricing</h2>
      <p className="text-center text-[var(--text-secondary)] mb-16">Start free. Scale as your agents grow.</p>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {tiers.map((tier, i) => (
          <motion.div
            key={tier.name}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.08 }}
            className={`rounded-xl border p-6 flex flex-col ${
              tier.highlight
                ? "border-[var(--accent)] bg-[var(--bg-card)]"
                : "border-[var(--border)] bg-[var(--bg-card)]"
            }`}
          >
            <span className="text-sm font-medium text-[var(--text-secondary)]">{tier.name}</span>
            <div className="mt-3">
              <span className="text-3xl font-bold">{tier.price}</span>
              {tier.period && <span className="text-[var(--text-secondary)]">{tier.period}</span>}
            </div>
            <div className="mt-6 space-y-3 text-sm text-[var(--text-secondary)] flex-1">
              <div><span className="text-[var(--text-primary)]">{tier.collections}</span> collections</div>
              <div><span className="text-[var(--text-primary)]">{tier.vectors}</span> vectors</div>
              <div><span className="text-[var(--text-primary)]">{tier.queries}</span> queries</div>
            </div>
            <div className="mt-6">
              <Button
                href={tier.href}
                variant={tier.highlight ? "primary" : "secondary"}
                size="sm"
              >
                {tier.cta}
              </Button>
            </div>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
