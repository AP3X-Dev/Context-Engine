import type { Metadata } from "next";
import { Nav } from "../components/shared/nav";
import { Footer } from "../components/shared/footer";

export const metadata: Metadata = {
  title: "ONI — The Agent Infrastructure Company",
};

export default function BrandLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav
        brand="ONI"
        links={[
          { label: "Products", href: "#products" },
          { label: "GitHub", href: "https://github.com/m1rl0k/Context-Engine" },
        ]}
      />
      <main className="pt-16">{children}</main>
      <Footer />
    </>
  );
}
