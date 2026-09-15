import type { Metadata } from "next";
import { LegalPage, LegalSection } from "@/components/legal-page";

export const metadata: Metadata = { title: "Privacy Policy — Flare" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="September 15, 2026">
      <p>This policy explains how Flare collects, uses, shares, and protects information when you use our early-access website and application (the “Service”).</p>
      <LegalSection title="1. Information we collect">
        <ul>
          <li><strong>Account data:</strong> your name, email address, password hash, verification state, and workspace membership.</li>
          <li><strong>Workspace content:</strong> notes, links, imported text, generated Flares, evidence references, and repository metadata you choose to connect.</li>
          <li><strong>Service activity:</strong> feature events and timestamps used to operate and improve the product.</li>
          <li><strong>Operational data:</strong> request method, route template, status, duration, and security records. Application logs are designed to omit request bodies, query values, cookies, and secrets.</li>
          <li><strong>Browser storage:</strong> an essential session cookie and local interface preferences. We do not currently use advertising cookies.</li>
        </ul>
      </LegalSection>
      <LegalSection title="2. How we use information">
        <p>We use this information to create and secure accounts, store and retrieve workspace content, run the analysis you request or schedule, provide evidence-backed results, support users, diagnose failures, prevent abuse, and meet legal obligations.</p>
      </LegalSection>
      <LegalSection title="3. AI processing">
        <p>When you start or schedule analysis, selected workspace content may be sent to an AI provider to produce a result. Flare validates the returned structure and evidence before publishing a Flare. AI output can still be incomplete or wrong, so review its evidence before relying on it.</p>
      </LegalSection>
      <LegalSection title="4. When we share information">
        <p>We may use service providers for cloud hosting, databases, AI processing, email delivery, and integrations you connect. They receive only the information needed to provide that function. We may also disclose information when required by law, during a business transfer, or when you direct us to do so. We do not sell personal information.</p>
      </LegalSection>
      <LegalSection title="5. Retention and deletion">
        <p>Account information and active workspace content are retained while needed to provide the Service. Deleted items may remain in restricted backups or audit records for a limited period. To request account or personal-data deletion, contact support@flare4u.tech. Some records may be retained where required for security, dispute resolution, or law.</p>
      </LegalSection>
      <LegalSection title="6. Security">
        <p>Flare uses technical and organizational safeguards including password hashing, restricted sessions, encrypted transport in production, database role separation, workspace isolation, and limited logging. No internet service can guarantee absolute security.</p>
      </LegalSection>
      <LegalSection title="7. Your choices and rights">
        <p>Depending on where you live, you may have rights to access, correct, delete, restrict, or receive a copy of your personal information, and to object to certain processing. Send requests to support@flare4u.tech. We may need to verify your identity before completing a request.</p>
      </LegalSection>
      <LegalSection title="8. International processing">
        <p>Our providers may process information in countries other than your own. Those countries may have different data-protection laws. We use provider and access controls intended to protect information throughout that processing.</p>
      </LegalSection>
      <LegalSection title="9. Children">
        <p>The Service is intended for adults and is not directed to children under 18. Contact us if you believe a child has provided personal information.</p>
      </LegalSection>
      <LegalSection title="10. Changes and contact">
        <p>We may update this policy as the Service changes. We will post the revised date and provide additional notice when required. Questions and privacy requests may be sent to support@flare4u.tech.</p>
      </LegalSection>
    </LegalPage>
  );
}
