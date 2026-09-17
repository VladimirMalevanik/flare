import type { Metadata } from "next";
import { LegalPage, LegalSection } from "@/components/legal-page";

export const metadata: Metadata = { title: "Privacy Policy — Flare" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="September 17, 2026">
      <p>
        This Privacy Policy explains how Flare (“Flare,” “we,” “us,” or “our”)
        collects, uses, discloses, and safeguards information when you use our
        website and web application (the “Service”).
      </p>

      <LegalSection title="1. Information we collect">
        <h3>1.1 Information you provide</h3>
        <ul>
          <li><strong>Account information:</strong> your name, email address, password hash, verification state, legal acceptance, and workspace membership.</li>
          <li><strong>User Content:</strong> notes, links, imported text and spreadsheets, voice transcripts, connected-repository metadata, and other materials you add to your workspace. User Content may contain personal data about you or other people.</li>
          <li><strong>Communications:</strong> messages you send for support or feedback.</li>
        </ul>
        <h3>1.2 Information collected automatically</h3>
        <ul>
          <li><strong>Usage data:</strong> product actions and timestamps used to operate, secure, and improve the Service.</li>
          <li><strong>Operational data:</strong> request method, route template, status, duration, and security records. Our application logs are designed to omit request bodies, query values, cookies, and secrets. Our hosting provider may process connection data such as IP address and device or browser information.</li>
          <li><strong>Browser storage:</strong> an essential session cookie and local interface preferences. We do not currently use advertising cookies.</li>
        </ul>
      </LegalSection>

      <LegalSection title="2. How we use information">
        <p>We use information to:</p>
        <ul>
          <li>provide, operate, and maintain the Service, including storing, selecting, and analyzing User Content;</li>
          <li>generate AI-powered observations and evidence-backed insights;</li>
          <li>personalize and improve product features;</li>
          <li>communicate about your account, updates, support, and feedback;</li>
          <li>monitor reliability, detect abuse, and secure the Service; and</li>
          <li>comply with legal obligations.</li>
        </ul>
        <h3>2.1 AI processing and Groq</h3>
        <p>
          When you start or schedule analysis, Flare selects a bounded set of workspace
          content and sends it to Groq, our AI provider, for inference. Groq processes that content to
          extract observations and generate candidate Flares. Flare validates the
          returned structure and supporting evidence before publishing a result.
        </p>
        <p>
          Groq states that it does not use API inputs or outputs to train models unless
          the customer explicitly permits it. Groq also states that inference data is
          not retained by default, except in limited circumstances for service reliability
          or abuse monitoring, which may last up to 30 days. Groq organization administrators
          can enable Zero Data Retention in Groq Data Controls. See Groq&apos;s current{` `}
          <a href="https://console.groq.com/docs/your-data">data documentation</a> for details.
        </p>
        <p>Flare does not use your User Content to train third-party foundation models.</p>
        <h3>2.2 Automated decision-making</h3>
        <p>
          Flare does not use automated decision-making that produces legal or similarly
          significant effects. AI-generated Flares are informational. You decide whether
          and how to act on them, and you should review the cited evidence first.
        </p>
      </LegalSection>

      <LegalSection title="3. Legal bases for processing">
        <p>
          Where the GDPR, UK GDPR, or similar law applies, we rely on performance of a
          contract to provide the Service; legitimate interests to secure and improve it;
          consent where specifically requested; and legal obligation where required.
          You may object to or withdraw consent from processing that relies on consent.
          Withdrawal does not affect processing already carried out lawfully.
        </p>
      </LegalSection>

      <LegalSection title="4. How we share information">
        <ul>
          <li><strong>Service providers:</strong> cloud hosting, databases, AI processing including Groq, email delivery, analytics, support, and integrations you connect. They receive information needed to provide their function.</li>
          <li><strong>Legal requirements:</strong> where disclosure is required to comply with law, legal process, or a valid governmental request.</li>
          <li><strong>Business transfers:</strong> in connection with a merger, financing, acquisition, or sale of assets, subject to appropriate protections.</li>
          <li><strong>With your direction:</strong> when you ask or authorize us to share information.</li>
        </ul>
        <p>We do not sell personal information or share it for cross-context behavioral advertising.</p>
      </LegalSection>

      <LegalSection title="5. Your rights and choices">
        <p>
          Depending on where you live, you may have rights to access, correct, delete,
          restrict, object to processing, or receive a portable copy of personal information.
          California residents may also request information about categories collected and
          disclosed and may exercise applicable correction, deletion, opt-out, limitation,
          and non-discrimination rights. We do not sell or share personal information for
          cross-context behavioral advertising.
        </p>
        <p>
          Send a request to <a href="mailto:support@flare4u.tech">support@flare4u.tech</a>.
          We may verify your identity before fulfilling it and will respond within the
          period required by applicable law.
        </p>
      </LegalSection>

      <LegalSection title="6. Children’s privacy">
        <p>
          The Service is not intended for anyone under 16, or the higher age of digital
          consent required in their jurisdiction. We do not knowingly collect personal
          information from children. Contact us if you believe a child has provided data.
        </p>
      </LegalSection>

      <LegalSection title="7. Data retention">
        <p>
          We retain account information and active User Content while needed to provide
          the Service. Analysis jobs, generated results, security records, and operational
          logs are retained only as needed for product operation, reliability, abuse
          prevention, and legal obligations. Deleted information may remain temporarily
          in restricted backups. To request account and User Content deletion, contact{` `}
          <a href="mailto:support@flare4u.tech">support@flare4u.tech</a>. We may retain
          limited records where required for security, dispute resolution, fraud prevention,
          or law.
        </p>
      </LegalSection>

      <LegalSection title="8. Cookies and similar technologies">
        <p>
          We use an essential HttpOnly cookie for authentication and local browser storage
          for interface preferences. Product activity events may be used for service
          analytics. You can control cookies through browser settings, but disabling the
          session cookie prevents authenticated features from working.
        </p>
      </LegalSection>

      <LegalSection title="9. Data security">
        <p>
          Flare uses safeguards including password hashing, restricted HttpOnly sessions,
          encrypted transport, secret management, database role separation, workspace
          isolation, and limited application logging. No transmission or storage system is
          completely secure, and we cannot guarantee absolute security.
        </p>
      </LegalSection>

      <LegalSection title="10. International users and transfers">
        <p>
          Flare&apos;s production infrastructure is hosted in the United States. If you use the
          Service elsewhere, information may be transferred to and processed in the United
          States, where laws may differ. Where required, we rely on contractual or other
          legally recognized safeguards offered by our service providers for international
          transfers.
        </p>
      </LegalSection>

      <LegalSection title="11. Changes to this policy">
        <p>
          We may update this Policy as the Service changes. We will post the new effective
          date and provide additional notice or request renewed acceptance when required.
        </p>
      </LegalSection>

      <LegalSection title="12. Contact us">
        <p>
          Data controller: Flare, United States. Questions, privacy requests, and data
          protection inquiries may be sent to{` `}
          <a href="mailto:support@flare4u.tech">support@flare4u.tech</a>.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
