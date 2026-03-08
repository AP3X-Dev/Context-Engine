import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service — ONI Cortex",
  description:
    "Terms of Service for ONI Cortex, a managed MCP retrieval SaaS product by ONI.",
  openGraph: {
    title: "Terms of Service — ONI Cortex",
    description:
      "Terms of Service for ONI Cortex, a managed MCP retrieval SaaS product by ONI.",
    url: "https://oni.bot/terms",
    siteName: "ONI",
    type: "website",
  },
  alternates: {
    canonical: "https://oni.bot/terms",
  },
};

/* ------------------------------------------------------------------ */
/*  Section helper                                                     */
/* ------------------------------------------------------------------ */

function Section({
  id,
  heading,
  children,
}: {
  id: string;
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
        {heading}
      </h2>
      <div className="space-y-4 text-[var(--text-secondary)] leading-relaxed">
        {children}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function TermsOfService() {
  return (
    <div className="min-h-screen bg-[var(--bg-primary)]">
      {/* Minimal top bar */}
      <nav className="fixed top-0 w-full z-50 border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl">
        <div className="max-w-3xl mx-auto px-6 h-16 flex items-center justify-between">
          <a
            href="/"
            className="text-lg font-semibold tracking-tight text-[var(--text-primary)] hover:opacity-80 transition-opacity"
          >
            ONI
          </a>
          <a
            href="https://cortex.oni.bot"
            className="text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
          >
            cortex.oni.bot
          </a>
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-3xl mx-auto px-6 pt-32 pb-24">
        {/* Header */}
        <header className="mb-16">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-[var(--text-primary)] mb-3">
            Terms of Service
          </h1>
          <p className="text-[var(--text-secondary)]">
            Effective date: March 8, 2026 &middot; Last updated: March 8, 2026
          </p>
        </header>

        {/* Table of Contents */}
        <nav className="mb-16 p-6 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]">
          <p className="text-sm font-medium text-[var(--text-primary)] mb-3">
            Contents
          </p>
          <ol className="columns-1 sm:columns-2 gap-x-8 list-decimal list-inside text-sm text-[var(--text-secondary)] space-y-1.5">
            {[
              ["#overview", "Overview"],
              ["#definitions", "Definitions"],
              ["#account-registration", "Account Registration"],
              ["#acceptable-use", "Acceptable Use"],
              ["#data-handling", "Data Handling & Privacy"],
              ["#intellectual-property", "Intellectual Property"],
              ["#billing", "Billing, Plans & Refunds"],
              ["#availability", "Service Availability"],
              ["#liability", "Limitation of Liability"],
              ["#indemnification", "Indemnification"],
              ["#termination", "Termination"],
              ["#changes", "Changes to These Terms"],
              ["#governing-law", "Governing Law"],
              ["#contact", "Contact"],
            ].map(([href, label]) => (
              <li key={href}>
                <a
                  href={href}
                  className="hover:text-[var(--text-primary)] transition-colors"
                >
                  {label}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        {/* Sections */}
        <div className="space-y-14 text-sm sm:text-base">
          {/* 1 */}
          <Section id="overview" heading="1. Overview">
            <p>
              These Terms of Service (&ldquo;Terms&rdquo;) are a legal agreement
              between you (&ldquo;Customer,&rdquo; &ldquo;you&rdquo;) and ONI
              (&ldquo;we,&rdquo; &ldquo;us,&rdquo; &ldquo;our&rdquo;),
              operating at oni.bot. They govern your access to and use of ONI
              Cortex (&ldquo;the Service&rdquo;), a managed retrieval platform
              available at cortex.oni.bot.
            </p>
            <p>
              ONI Cortex is a software-as-a-service product that lets developers
              upload code, documentation, and structured data, then query that
              data from AI agents through the Model Context Protocol (MCP). By
              creating an account, generating an API key, or otherwise using the
              Service, you agree to be bound by these Terms. If you do not agree,
              do not use the Service.
            </p>
          </Section>

          {/* 2 */}
          <Section id="definitions" heading="2. Definitions">
            <ul className="list-disc list-inside space-y-2">
              <li>
                <strong className="text-[var(--text-primary)]">Service</strong>{" "}
                &mdash; The ONI Cortex platform, including all APIs, dashboards,
                documentation, and related infrastructure.
              </li>
              <li>
                <strong className="text-[var(--text-primary)]">
                  Customer Data
                </strong>{" "}
                &mdash; Any content, files, code, documents, or other material
                you upload, submit, or transmit through the Service.
              </li>
              <li>
                <strong className="text-[var(--text-primary)]">API Key</strong>{" "}
                &mdash; A unique credential issued to you for authenticating
                requests to the Service.
              </li>
              <li>
                <strong className="text-[var(--text-primary)]">Tenant</strong>{" "}
                &mdash; An isolated workspace within the Service associated with
                your account.
              </li>
              <li>
                <strong className="text-[var(--text-primary)]">Plan</strong>{" "}
                &mdash; The pricing tier you have selected (Free, Pro, Team,
                Business, or Enterprise).
              </li>
            </ul>
          </Section>

          {/* 3 */}
          <Section id="account-registration" heading="3. Account Registration">
            <p>
              To use the Service you must create an account and provide accurate,
              complete information. You are responsible for safeguarding your API
              keys and account credentials. Do not share API keys with
              unauthorized parties. You must notify us promptly at{" "}
              <a
                href="mailto:support@oni.bot"
                className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
              >
                support@oni.bot
              </a>{" "}
              if you suspect unauthorized access.
            </p>
            <p>
              You may not create accounts on behalf of others without their
              consent, or create multiple free accounts to circumvent plan
              limits.
            </p>
          </Section>

          {/* 4 */}
          <Section id="acceptable-use" heading="4. Acceptable Use">
            <p>You agree not to use the Service to:</p>
            <ul className="list-disc list-inside space-y-2">
              <li>
                Violate any applicable law, regulation, or third-party right.
              </li>
              <li>
                Upload or index content that is unlawful, defamatory, obscene,
                or infringes on intellectual property rights.
              </li>
              <li>
                Attempt to gain unauthorized access to other tenants, accounts,
                or internal systems.
              </li>
              <li>
                Reverse-engineer, decompile, or disassemble any part of the
                Service.
              </li>
              <li>
                Interfere with or disrupt the integrity or performance of the
                Service, including through denial-of-service attacks, automated
                scraping beyond API rate limits, or injection of malicious
                payloads.
              </li>
              <li>
                Resell, sublicense, or redistribute access to the Service
                without prior written agreement.
              </li>
              <li>
                Use the Service to build a competing product that substantially
                replicates its core functionality.
              </li>
            </ul>
            <p>
              We reserve the right to suspend or terminate accounts that violate
              this policy, with or without notice depending on severity.
            </p>
          </Section>

          {/* 5 */}
          <Section id="data-handling" heading="5. Data Handling & Privacy">
            <p>
              <strong className="text-[var(--text-primary)]">Ownership.</strong>{" "}
              You retain all rights to your Customer Data. We do not claim
              ownership of any content you upload to the Service. By uploading
              data, you grant us a limited license to store, process, index, and
              retrieve that data solely to provide and improve the Service.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">Storage.</strong>{" "}
              Customer Data is stored in vector databases and relational
              databases within our infrastructure. Each tenant&rsquo;s data is
              logically isolated. We implement reasonable technical and
              organizational measures to protect your data, but no system is
              perfectly secure.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">
                No training on your data.
              </strong>{" "}
              We do not use Customer Data to train machine learning models or for
              any purpose unrelated to providing the Service.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">Deletion.</strong>{" "}
              When you delete data through the Service or close your account, we
              will remove your Customer Data from active systems within 30 days.
              Residual copies may persist in backups for up to 90 days before
              being purged.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">
                Disclosure.
              </strong>{" "}
              We will not disclose Customer Data to third parties except (a) with
              your consent, (b) to comply with a valid legal process, or (c) to
              protect the rights, safety, or property of ONI, our users, or the
              public.
            </p>
          </Section>

          {/* 6 */}
          <Section id="intellectual-property" heading="6. Intellectual Property">
            <p>
              The Service, including its design, source code, documentation,
              branding, and underlying technology, is owned by ONI and protected
              by applicable intellectual property laws. These Terms do not grant
              you any right, title, or interest in the Service beyond the limited
              right to use it in accordance with these Terms.
            </p>
            <p>
              You may use the ONI and ONI Cortex names solely to identify your
              use of the Service (for example, &ldquo;built with ONI
              Cortex&rdquo;). You may not use our trademarks in a way that
              suggests endorsement or affiliation without written permission.
            </p>
          </Section>

          {/* 7 */}
          <Section id="billing" heading="7. Billing, Plans & Refunds">
            <p>
              ONI Cortex offers five pricing tiers:
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="py-2 pr-4 text-[var(--text-primary)] font-medium">
                      Plan
                    </th>
                    <th className="py-2 pr-4 text-[var(--text-primary)] font-medium">
                      Price
                    </th>
                  </tr>
                </thead>
                <tbody className="text-[var(--text-secondary)]">
                  {[
                    ["Free", "$0/month"],
                    ["Pro", "$49/month"],
                    ["Team", "$149/month"],
                    ["Business", "$499/month"],
                    ["Enterprise", "Custom pricing"],
                  ].map(([plan, price]) => (
                    <tr key={plan} className="border-b border-[var(--border)]/50">
                      <td className="py-2 pr-4">{plan}</td>
                      <td className="py-2 pr-4">{price}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              <strong className="text-[var(--text-primary)]">
                Billing cycle.
              </strong>{" "}
              Paid plans are billed monthly in advance through Stripe. Your
              subscription renews automatically unless you cancel before the next
              billing date.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">
                Plan changes.
              </strong>{" "}
              You may upgrade or downgrade your plan at any time through the
              dashboard. Upgrades take effect immediately and are prorated for
              the remainder of the billing cycle. Downgrades take effect at the
              start of the next billing cycle.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">Refunds.</strong>{" "}
              We do not offer refunds for partial billing periods. If you cancel
              a paid plan, you will continue to have access to paid features
              until the end of your current billing cycle. In exceptional
              circumstances (such as extended unplanned outages), we may issue
              credits or refunds at our discretion.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">
                Failed payments.
              </strong>{" "}
              If a payment fails, we will attempt to charge the payment method on
              file up to three additional times over 14 days. If all retry
              attempts fail, your account may be downgraded to the Free tier or
              suspended.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">Taxes.</strong> All
              prices are exclusive of taxes. You are responsible for any
              applicable sales tax, VAT, or similar charges based on your
              jurisdiction.
            </p>
          </Section>

          {/* 8 */}
          <Section id="availability" heading="8. Service Availability">
            <p>
              We strive to maintain high availability but do not guarantee
              uninterrupted or error-free operation. The Service is provided on
              an &ldquo;as is&rdquo; and &ldquo;as available&rdquo; basis. We
              may perform scheduled maintenance with reasonable advance notice
              when possible.
            </p>
            <p>
              We reserve the right to modify, suspend, or discontinue any part
              of the Service at any time. If we discontinue the Service entirely,
              we will provide at least 30 days&rsquo; notice and a reasonable
              opportunity to export your data.
            </p>
          </Section>

          {/* 9 */}
          <Section id="liability" heading="9. Limitation of Liability">
            <p>
              To the maximum extent permitted by applicable law:
            </p>
            <ul className="list-disc list-inside space-y-2">
              <li>
                ONI shall not be liable for any indirect, incidental, special,
                consequential, or punitive damages, including but not limited to
                loss of profits, data, business opportunities, or goodwill,
                arising out of or related to your use of the Service.
              </li>
              <li>
                Our total aggregate liability for any claims arising under these
                Terms shall not exceed the greater of (a) the amount you paid us
                in the 12 months preceding the claim, or (b) $100.
              </li>
              <li>
                We are not liable for any loss or damage resulting from (i) your
                failure to maintain the security of your API keys, (ii) content
                or data you upload to the Service, or (iii) third-party services,
                integrations, or actions taken by AI agents using data retrieved
                from the Service.
              </li>
            </ul>
            <p>
              These limitations apply regardless of the legal theory (contract,
              tort, strict liability, or otherwise) and even if we have been
              advised of the possibility of such damages.
            </p>
          </Section>

          {/* 10 */}
          <Section id="indemnification" heading="10. Indemnification">
            <p>
              You agree to indemnify, defend, and hold harmless ONI, its
              officers, directors, employees, and agents from and against any
              claims, liabilities, damages, losses, and expenses (including
              reasonable legal fees) arising out of or related to:
            </p>
            <ul className="list-disc list-inside space-y-2">
              <li>Your use of the Service.</li>
              <li>Your violation of these Terms.</li>
              <li>
                Your Customer Data, including any claim that it infringes or
                misappropriates a third party&rsquo;s intellectual property or
                other rights.
              </li>
              <li>
                Actions taken by AI agents or automated systems using data
                retrieved through your account.
              </li>
            </ul>
          </Section>

          {/* 11 */}
          <Section id="termination" heading="11. Termination">
            <p>
              <strong className="text-[var(--text-primary)]">By you.</strong>{" "}
              You may cancel your account at any time through the dashboard or by
              contacting{" "}
              <a
                href="mailto:support@oni.bot"
                className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
              >
                support@oni.bot
              </a>
              . Cancellation takes effect at the end of your current billing
              cycle.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">By us.</strong> We
              may suspend or terminate your account if you breach these Terms, if
              required by law, or if we reasonably believe your use poses a risk
              to the Service or other users. Where practical, we will provide
              notice and an opportunity to cure the breach before termination.
            </p>
            <p>
              <strong className="text-[var(--text-primary)]">
                Effect of termination.
              </strong>{" "}
              Upon termination, your right to use the Service ceases immediately.
              We will retain your Customer Data for 30 days post-termination to
              allow for export, after which it will be deleted in accordance with
              Section 5.
            </p>
            <p>
              Sections 5 (Data Handling), 6 (Intellectual Property), 9
              (Limitation of Liability), 10 (Indemnification), and 13 (Governing
              Law) survive termination.
            </p>
          </Section>

          {/* 12 */}
          <Section id="changes" heading="12. Changes to These Terms">
            <p>
              We may update these Terms from time to time. When we make material
              changes, we will notify you by email or through a notice on the
              Service at least 14 days before the changes take effect. Your
              continued use of the Service after the effective date constitutes
              acceptance of the updated Terms. If you do not agree to the
              changes, you must stop using the Service and cancel your account.
            </p>
          </Section>

          {/* 13 */}
          <Section id="governing-law" heading="13. Governing Law">
            <p>
              These Terms are governed by and construed in accordance with the
              laws of the State of Delaware, United States, without regard to its
              conflict-of-law provisions. Any disputes arising under these Terms
              shall be resolved exclusively in the state or federal courts
              located in Delaware, and you consent to the personal jurisdiction
              of those courts.
            </p>
            <p>
              If any provision of these Terms is found to be unenforceable, the
              remaining provisions will continue in full force and effect. Our
              failure to enforce any right or provision does not constitute a
              waiver of that right or provision.
            </p>
          </Section>

          {/* 14 */}
          <Section id="contact" heading="14. Contact">
            <p>
              If you have questions about these Terms, please contact us:
            </p>
            <ul className="list-none space-y-1">
              <li>
                Email:{" "}
                <a
                  href="mailto:legal@oni.bot"
                  className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
                >
                  legal@oni.bot
                </a>
              </li>
              <li>
                Web:{" "}
                <a
                  href="https://oni.bot"
                  className="text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
                >
                  oni.bot
                </a>
              </li>
            </ul>
          </Section>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--border)] py-12 px-6">
        <div className="max-w-3xl mx-auto flex items-center justify-between text-sm text-[var(--text-secondary)]">
          <span>&copy; {new Date().getFullYear()} ONI</span>
          <div className="flex gap-6">
            <a
              href="https://oni.bot"
              className="hover:text-[var(--text-primary)] transition-colors"
            >
              oni.bot
            </a>
            <a
              href="https://cortex.oni.bot"
              className="hover:text-[var(--text-primary)] transition-colors"
            >
              Cortex
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
