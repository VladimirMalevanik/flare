import type { Metadata } from "next";
import { LegalPage, LegalSection } from "@/components/legal-page";

export const metadata: Metadata = { title: "Terms of Service — Flare" };

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" updated="September 15, 2026">
      <p>These terms govern access to Flare’s early-access website and application (the “Service”). Flare is currently an unincorporated project in active development. By creating an account, you agree to these terms and the Privacy Policy.</p>
      <LegalSection title="1. Eligibility and accounts">
        <p>You must be at least 18 and able to enter a binding agreement. Provide accurate registration information, protect your credentials, and notify support@flare4u.tech if you believe your account has been compromised.</p>
      </LegalSection>
      <LegalSection title="2. Your content">
        <p>You keep ownership of content you upload. You grant Flare a limited, non-exclusive license to host, store, process, transmit, and display that content only as needed to operate the Service. You must have the rights required to provide the content and connect any external source.</p>
      </LegalSection>
      <LegalSection title="3. Acceptable use">
        <ul>
          <li>Do not violate laws or third-party rights.</li>
          <li>Do not access another account, workspace, or infrastructure without permission.</li>
          <li>Do not upload malware, disrupt the Service, or evade usage and security controls.</li>
          <li>Do not scrape or reverse engineer the Service except where applicable law expressly permits it.</li>
        </ul>
      </LegalSection>
      <LegalSection title="4. AI-generated output">
        <p>Flares, summaries, and suggestions may be inaccurate or incomplete. They are informational product output, not professional financial, legal, medical, or investment advice. Review the cited source material and use independent judgment before making consequential decisions.</p>
      </LegalSection>
      <LegalSection title="5. Early access and availability">
        <p>The Service may change, experience interruptions, or remove experimental features. We may impose reasonable limits to protect users and infrastructure. Features described as coming soon or demo-only are not commitments to deliver them.</p>
      </LegalSection>
      <LegalSection title="6. Fees">
        <p>No charge applies unless a paid plan is clearly offered and you expressly agree to it. Any future price, renewal, refund, and cancellation terms will be shown before payment.</p>
      </LegalSection>
      <LegalSection title="7. Suspension and termination">
        <p>You may stop using the Service at any time and may request account deletion through support@flare4u.tech. We may suspend access to protect the Service or other users, comply with law, or address a material breach of these terms.</p>
      </LegalSection>
      <LegalSection title="8. Disclaimers and liability">
        <p>To the extent permitted by applicable law, the Service is provided “as is” and “as available,” without warranties that it will be uninterrupted, error-free, or suitable for a particular purpose. Flare is not liable for indirect or consequential loss caused by use of the Service. Nothing in these terms excludes rights or liability that cannot legally be excluded.</p>
      </LegalSection>
      <LegalSection title="9. Applicable law and disputes">
        <p>Applicable law governs these terms. The court or forum with lawful jurisdiction will hear a dispute unless the parties agree to another permitted process. This section does not remove consumer protections that apply where you live.</p>
      </LegalSection>
      <LegalSection title="10. Changes and contact">
        <p>We may update these terms as the Service changes. We will post the revised date and provide additional notice where required. Questions may be sent to support@flare4u.tech.</p>
      </LegalSection>
    </LegalPage>
  );
}
