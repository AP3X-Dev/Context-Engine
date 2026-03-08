import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy — ONI Cortex",
  description:
    "Privacy Policy for ONI Cortex, a managed MCP retrieval SaaS product. Learn how we collect, use, and protect your data.",
  openGraph: {
    title: "Privacy Policy — ONI Cortex",
    description:
      "Privacy Policy for ONI Cortex. Learn how we collect, use, and protect your data.",
    url: "https://oni.bot/privacy",
    siteName: "ONI",
    type: "website",
  },
  alternates: {
    canonical: "https://oni.bot/privacy",
  },
};

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xl font-semibold text-[var(--text-primary)] mt-12 mb-4 tracking-tight">
      {children}
    </h2>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-base font-medium text-[var(--text-primary)] mt-6 mb-2">
      {children}
    </h3>
  );
}

function Paragraph({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[var(--text-secondary)] leading-7 mb-4">{children}</p>
  );
}

function List({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc list-outside pl-5 text-[var(--text-secondary)] leading-7 mb-4 space-y-1">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

export default function PrivacyPolicy() {
  const effectiveDate = "March 8, 2026";

  return (
    <div className="min-h-screen bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link
            href="/"
            className="text-lg font-semibold tracking-tight text-[var(--text-primary)] hover:opacity-80 transition-opacity"
          >
            ONI
          </Link>
          <Link
            href="https://cortex.oni.bot"
            className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            Back to Cortex
          </Link>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-3xl mx-auto px-6 py-16 pb-24">
        <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)] mb-2">
          Privacy Policy
        </h1>
        <p className="text-sm text-[var(--text-secondary)] mb-12 border-b border-[var(--border)] pb-8">
          Effective date: {effectiveDate}
        </p>

        <Paragraph>
          ONI (&quot;we,&quot; &quot;us,&quot; or &quot;our&quot;) operates ONI
          Cortex, a managed MCP (Model Context Protocol) retrieval service
          available at{" "}
          <a
            href="https://cortex.oni.bot"
            className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
          >
            cortex.oni.bot
          </a>
          . This Privacy Policy describes how we collect, use, store, and
          protect your information when you use our service.
        </Paragraph>
        <Paragraph>
          By using ONI Cortex, you agree to the practices described in this
          policy. If you do not agree, please do not use our service.
        </Paragraph>

        {/* 1. Information We Collect */}
        <SectionHeading>1. Information We Collect</SectionHeading>

        <SubHeading>Account Information</SubHeading>
        <Paragraph>
          When you create an ONI Cortex account, we collect:
        </Paragraph>
        <List
          items={[
            "Name and email address",
            "Password (hashed; we never store plaintext credentials)",
            "Organization or team name (if applicable)",
          ]}
        />

        <SubHeading>Payment Information</SubHeading>
        <Paragraph>
          Payment processing is handled entirely by Stripe. We do not store
          credit card numbers, bank account details, or other sensitive payment
          data on our servers. We retain only a Stripe customer identifier and
          basic transaction metadata (plan type, billing dates, invoice amounts)
          necessary for account management.
        </Paragraph>

        <SubHeading>Uploaded Content</SubHeading>
        <Paragraph>
          ONI Cortex lets you upload code, documentation, and other data
          (&quot;Content&quot;) for indexing and retrieval. This Content is
          stored in our systems so we can provide the service. We treat your
          uploaded Content as confidential and do not access it except as
          necessary to operate, maintain, or improve the service, or as required
          by law.
        </Paragraph>

        <SubHeading>Usage and Technical Data</SubHeading>
        <Paragraph>We automatically collect:</Paragraph>
        <List
          items={[
            "API usage logs (endpoints called, request timestamps, response status codes)",
            "IP addresses",
            "API key identifiers (e.g., oni_live_*, oni_test_*) associated with requests",
            "Browser user-agent strings when accessing the dashboard",
            "Error logs and performance metrics",
          ]}
        />

        {/* 2. How We Use Your Information */}
        <SectionHeading>2. How We Use Your Information</SectionHeading>
        <Paragraph>We use the information we collect to:</Paragraph>
        <List
          items={[
            "Provide, operate, and maintain ONI Cortex",
            "Index your uploaded Content into vector embeddings for MCP-based retrieval",
            "Process billing and manage your subscription via Stripe",
            "Authenticate API requests and enforce per-tenant data isolation",
            "Monitor service health, debug issues, and improve performance",
            "Communicate with you about your account, service updates, or security notices",
            "Comply with legal obligations",
          ]}
        />
        <Paragraph>
          We do not sell your personal information. We do not use your uploaded
          Content to train machine learning models.
        </Paragraph>

        {/* 3. Data Storage and Security */}
        <SectionHeading>3. Data Storage and Security</SectionHeading>
        <Paragraph>
          Your data is stored across the following systems, all hosted on Oracle
          Cloud Infrastructure in the United States:
        </Paragraph>
        <List
          items={[
            <span key="pg">
              <strong className="text-[var(--text-primary)]">PostgreSQL</strong>{" "}
              — user accounts, subscription data, and usage records
            </span>,
            <span key="qd">
              <strong className="text-[var(--text-primary)]">
                Qdrant vector database
              </strong>{" "}
              — indexed vector embeddings of your uploaded Content
            </span>,
            <span key="sl">
              <strong className="text-[var(--text-primary)]">
                Server logs
              </strong>{" "}
              — API access logs and application logs
            </span>,
          ]}
        />
        <Paragraph>
          We implement industry-standard security measures including
          encryption in transit (TLS), API key authentication, per-tenant data
          isolation (multi-tenant architecture with strict collection scoping),
          and regular security reviews. However, no method of transmission or
          storage is 100% secure, and we cannot guarantee absolute security.
        </Paragraph>

        {/* 4. Data Retention */}
        <SectionHeading>4. Data Retention</SectionHeading>
        <Paragraph>
          We retain your data for as long as your account is active or as needed
          to provide the service. Specifically:
        </Paragraph>
        <List
          items={[
            <span key="acct">
              <strong className="text-[var(--text-primary)]">
                Account data
              </strong>{" "}
              — retained until you delete your account
            </span>,
            <span key="content">
              <strong className="text-[var(--text-primary)]">
                Uploaded Content and vector embeddings
              </strong>{" "}
              — retained until you delete the content or your account
            </span>,
            <span key="usage">
              <strong className="text-[var(--text-primary)]">
                API usage logs
              </strong>{" "}
              — retained for up to 90 days for operational purposes
            </span>,
            <span key="billing">
              <strong className="text-[var(--text-primary)]">
                Billing records
              </strong>{" "}
              — retained as required by applicable tax and financial regulations
            </span>,
          ]}
        />
        <Paragraph>
          When you delete your account, we will delete or anonymize your
          personal data within 30 days, except where retention is required by
          law.
        </Paragraph>

        {/* 5. Third-Party Services */}
        <SectionHeading>5. Third-Party Services</SectionHeading>
        <Paragraph>
          We use the following third-party services to operate ONI Cortex:
        </Paragraph>
        <List
          items={[
            <span key="stripe">
              <strong className="text-[var(--text-primary)]">Stripe</strong> —
              payment processing. Stripe collects and processes your payment
              information under its own{" "}
              <a
                href="https://stripe.com/privacy"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
              >
                Privacy Policy
              </a>
              .
            </span>,
            <span key="oracle">
              <strong className="text-[var(--text-primary)]">
                Oracle Cloud Infrastructure
              </strong>{" "}
              — cloud hosting (US region). Oracle acts as a data processor under
              its{" "}
              <a
                href="https://www.oracle.com/legal/privacy/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
              >
                Privacy Policy
              </a>
              .
            </span>,
          ]}
        />
        <Paragraph>
          We do not currently use third-party analytics, advertising, or
          tracking services. If this changes, we will update this policy
          accordingly.
        </Paragraph>

        {/* 6. Cookies */}
        <SectionHeading>6. Cookies and Local Storage</SectionHeading>
        <Paragraph>
          ONI Cortex uses only essential cookies and local storage necessary for
          the service to function:
        </Paragraph>
        <List
          items={[
            "Session cookies for authentication and maintaining your login state",
            "CSRF tokens for security",
          ]}
        />
        <Paragraph>
          We do not use advertising cookies, third-party tracking cookies, or
          analytics cookies. Because we only use strictly necessary cookies, no
          cookie consent banner is required under most jurisdictions.
        </Paragraph>

        {/* 7. Your Rights */}
        <SectionHeading>7. Your Rights</SectionHeading>
        <Paragraph>
          Depending on your jurisdiction, you may have the following rights
          regarding your personal data:
        </Paragraph>

        <SubHeading>Access</SubHeading>
        <Paragraph>
          You can request a copy of the personal data we hold about you.
        </Paragraph>

        <SubHeading>Correction</SubHeading>
        <Paragraph>
          You can update your account information at any time through the ONI
          Cortex dashboard, or by contacting us.
        </Paragraph>

        <SubHeading>Deletion</SubHeading>
        <Paragraph>
          You can request deletion of your account and all associated data. You
          may also delete individual collections and uploaded Content at any time
          through the API or dashboard.
        </Paragraph>

        <SubHeading>Data Portability</SubHeading>
        <Paragraph>
          You can request an export of your data in a structured,
          machine-readable format.
        </Paragraph>

        <SubHeading>Objection and Restriction</SubHeading>
        <Paragraph>
          You can object to or request restriction of certain processing
          activities where applicable under law.
        </Paragraph>

        <Paragraph>
          To exercise any of these rights, contact us at{" "}
          <a
            href="mailto:privacy@oni.bot"
            className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
          >
            privacy@oni.bot
          </a>
          . We will respond to verified requests within 30 days.
        </Paragraph>

        {/* 8. GDPR Compliance */}
        <SectionHeading>
          8. GDPR Compliance (European Economic Area)
        </SectionHeading>
        <Paragraph>
          If you are located in the European Economic Area (EEA), we process
          your personal data under the following legal bases:
        </Paragraph>
        <List
          items={[
            <span key="contract">
              <strong className="text-[var(--text-primary)]">
                Contract performance
              </strong>{" "}
              — processing necessary to provide the ONI Cortex service you
              signed up for
            </span>,
            <span key="interest">
              <strong className="text-[var(--text-primary)]">
                Legitimate interests
              </strong>{" "}
              — service security, fraud prevention, and service improvement
            </span>,
            <span key="legal">
              <strong className="text-[var(--text-primary)]">
                Legal obligations
              </strong>{" "}
              — compliance with applicable laws and regulations
            </span>,
            <span key="consent">
              <strong className="text-[var(--text-primary)]">Consent</strong> —
              where required, such as for optional communications
            </span>,
          ]}
        />
        <Paragraph>
          Your data is transferred to and stored in the United States. We rely
          on Standard Contractual Clauses and other appropriate safeguards for
          cross-border data transfers where required.
        </Paragraph>
        <Paragraph>
          You may lodge a complaint with your local data protection authority if
          you believe your rights under the GDPR have been violated.
        </Paragraph>

        {/* 9. CCPA Compliance */}
        <SectionHeading>
          9. CCPA Compliance (California Residents)
        </SectionHeading>
        <Paragraph>
          If you are a California resident, the California Consumer Privacy Act
          (CCPA) grants you additional rights:
        </Paragraph>
        <List
          items={[
            <span key="know">
              <strong className="text-[var(--text-primary)]">
                Right to know
              </strong>{" "}
              — you can request details about the categories and specific pieces
              of personal information we have collected
            </span>,
            <span key="delete">
              <strong className="text-[var(--text-primary)]">
                Right to delete
              </strong>{" "}
              — you can request deletion of your personal information
            </span>,
            <span key="opt-out">
              <strong className="text-[var(--text-primary)]">
                Right to opt-out
              </strong>{" "}
              — we do not sell personal information, so this right does not
              apply. We also do not &quot;share&quot; personal information for
              cross-context behavioral advertising
            </span>,
            <span key="nondiscrimination">
              <strong className="text-[var(--text-primary)]">
                Right to non-discrimination
              </strong>{" "}
              — we will not discriminate against you for exercising your privacy
              rights
            </span>,
          ]}
        />

        {/* 10. Children's Privacy */}
        <SectionHeading>10. Children&apos;s Privacy</SectionHeading>
        <Paragraph>
          ONI Cortex is not directed at children under the age of 16. We do not
          knowingly collect personal information from children. If we learn that
          we have collected data from a child under 16, we will take steps to
          delete that information promptly. If you believe a child has provided
          us with personal data, please contact us at{" "}
          <a
            href="mailto:privacy@oni.bot"
            className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
          >
            privacy@oni.bot
          </a>
          .
        </Paragraph>

        {/* 11. Data Breach Notification */}
        <SectionHeading>11. Data Breach Notification</SectionHeading>
        <Paragraph>
          In the event of a data breach that affects your personal information,
          we will notify affected users via email and, where required by law,
          the relevant supervisory authorities within 72 hours of becoming aware
          of the breach.
        </Paragraph>

        {/* 12. Changes to This Policy */}
        <SectionHeading>12. Changes to This Policy</SectionHeading>
        <Paragraph>
          We may update this Privacy Policy from time to time. When we make
          material changes, we will notify you by email or by posting a notice
          on our website prior to the change becoming effective. The
          &quot;Effective date&quot; at the top of this page indicates when this
          policy was last revised.
        </Paragraph>
        <Paragraph>
          Continued use of ONI Cortex after changes take effect constitutes
          acceptance of the revised policy.
        </Paragraph>

        {/* 13. Contact Us */}
        <SectionHeading>13. Contact Us</SectionHeading>
        <Paragraph>
          If you have any questions about this Privacy Policy or our data
          practices, please contact us:
        </Paragraph>
        <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg p-6 mt-2">
          <div className="space-y-2 text-[var(--text-secondary)]">
            <p>
              <strong className="text-[var(--text-primary)]">Email:</strong>{" "}
              <a
                href="mailto:privacy@oni.bot"
                className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
              >
                privacy@oni.bot
              </a>
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">Website:</strong>{" "}
              <a
                href="https://oni.bot"
                className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors underline underline-offset-2"
              >
                oni.bot
              </a>
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--border)] py-12 px-6">
        <div className="max-w-3xl mx-auto flex items-center justify-between text-sm text-[var(--text-secondary)]">
          <span>&copy; {new Date().getFullYear()} ONI</span>
          <div className="flex gap-6">
            <Link
              href="/"
              className="hover:text-[var(--text-primary)] transition-colors"
            >
              Home
            </Link>
            <Link
              href="https://cortex.oni.bot"
              className="hover:text-[var(--text-primary)] transition-colors"
            >
              Cortex
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
