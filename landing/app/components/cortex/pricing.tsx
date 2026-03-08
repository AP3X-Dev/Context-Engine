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
      <h2
        className="text-center mb-2"
        style={{
          fontFamily: "'Inter Tight', sans-serif",
          fontSize: "clamp(28px, 4vw, 44px)",
          fontWeight: 800,
          letterSpacing: "-0.03em",
        }}
      >
        Simple, transparent pricing
      </h2>
      <p className="text-center mb-16" style={{ color: "var(--text2)", fontSize: 16 }}>
        Start free. Scale as your agents grow.
      </p>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {tiers.map((tier, i) => (
          <motion.div
            key={tier.name}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: i * 0.07 }}
            className="flex flex-col"
            style={{
              background: "linear-gradient(180deg, #1a1a1c, #111113)",
              border: `1px solid ${tier.highlight ? "rgba(224, 64, 64, 0.3)" : "var(--border)"}`,
              borderRadius: "var(--radius)",
              padding: 24,
              boxShadow: tier.highlight ? "0 0 24px rgba(224, 64, 64, 0.08)" : "none",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text2)" }}>{tier.name}</span>
            <div style={{ marginTop: 12 }}>
              <span
                style={{
                  fontFamily: "'Inter Tight', sans-serif",
                  fontSize: 32,
                  fontWeight: 800,
                  letterSpacing: "-0.03em",
                }}
              >
                {tier.price}
              </span>
              {tier.period && <span style={{ color: "var(--text3)", fontSize: 14 }}>{tier.period}</span>}
            </div>
            <div className="flex-1" style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontSize: 13, color: "var(--text2)" }}><span style={{ color: "var(--text)" }}>{tier.collections}</span> collections</div>
              <div style={{ fontSize: 13, color: "var(--text2)" }}><span style={{ color: "var(--text)" }}>{tier.vectors}</span> vectors</div>
              <div style={{ fontSize: 13, color: "var(--text2)" }}><span style={{ color: "var(--text)" }}>{tier.queries}</span> queries</div>
            </div>
            <div style={{ marginTop: 20 }}>
              <Button
                href={tier.href}
                variant={tier.highlight ? "primary" : "ghost"}
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
