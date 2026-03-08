import type { Metadata } from "next";
import { Nav } from "../components/shared/nav";
import { Footer } from "../components/shared/footer";

export const metadata: Metadata = {
  title: "ONI Cortex — MCP Retrieval for AI Agents",
  description:
    "Scalable retrieval infrastructure for AI agents. Ingest, embed, and query documents via the Model Context Protocol.",
  openGraph: {
    title: "ONI Cortex — MCP Retrieval for AI Agents",
    description:
      "Scalable retrieval infrastructure for AI agents. Ingest, embed, and query documents via the Model Context Protocol.",
    url: "https://cortex.oni.bot",
    images: [{ url: "https://oni.bot/api/og?variant=cortex", width: 1200, height: 630 }],
  },
};

export default function CortexLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav
        brand="ONI Cortex"
        links={[
          { label: "Features", href: "#features" },
          { label: "Pricing", href: "#pricing" },
          { label: "Docs", href: "/docs" },
        ]}
        cta={{ label: "Get Started Free", href: "#signup" }}
      />
      <main className="pt-16">{children}</main>
      <Footer />
    </>
  );
}
