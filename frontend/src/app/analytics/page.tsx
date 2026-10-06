import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage, LegalSection } from "@/components/legal-page";
import { AnalyticsPreferences } from "@/features/telemetry/analytics-preferences";

export const metadata: Metadata = { title: "Website Analytics & Cookies — Flare" };

export default function AnalyticsPage() {
  return (
    <LegalPage title="Website Analytics & Cookies" updated="October 6, 2026">
      <p>
        This notice explains Flare&apos;s optional website analytics. You can use Flare
        without allowing it. This choice is separate from accepting our{` `}
        <Link href="/privacy">Privacy Policy</Link> and Terms of Service.
      </p>
      <LegalSection title="What we collect after you allow analytics">
        <p>
          We use Microsoft Azure Application Insights to count page views, visits,
          and returning browsers. Events contain a fixed page name and address, a
          timestamp, and random browser and session identifiers. These identifiers
          do not identify your Flare account, but distinguish visits from this browser.
        </p>
        <p>
          We do not include your email, account or workspace ID, saved content,
          page titles, link query parameters, fragments, or referring-page addresses
          in these events. Automatic click, error, and network-request tracking is off.
        </p>
      </LegalSection>
      <LegalSection title="Cookies and your choice">
        <p>
          Analytics stays off until you select Allow analytics. The optional cookies
          ai_user_flare_site_analytics and ai_session_flare_site_analytics contain
          random identifiers. Your choice and browser identifier expire after 30
          days; the session identifier expires after 30 minutes of inactivity or 24
          hours, whichever comes first. Cookies never outlive your consent.
        </p>
        <p>
          Reject stops future collection and removes these two cookies. It does not
          sign you out or affect your subscription. We respect Global Privacy Control
          and Do Not Track signals. Essential authentication cookies and interface
          preferences work independently of this choice.
        </p>
        <AnalyticsPreferences compact={false} />
      </LegalSection>
      <LegalSection title="Where data goes and how long it stays">
        <p>
          Microsoft processes these events in our Azure monitoring workspace in the
          United States. Page-view records are retained for 30 days. IP masking is
          enabled: Microsoft receives the connection IP to process the request before
          masking it in stored telemetry. Ordinary HTTP connection metadata may still
          be processed by the hosting and analytics providers.
        </p>
        <p>
          Rejecting or withdrawing consent stops future collection; it cannot recall events
          already received by Microsoft. We use the counts to understand website
          usage, not for advertising or account profiling.
        </p>
      </LegalSection>
      <LegalSection title="Change your choice or contact us">
        <p>
          Return to this page or Settings → Data &amp; Privacy to change your choice
          at any time. For privacy questions or data requests, contact{` `}
          <a href="mailto:support@flare4u.tech">support@flare4u.tech</a>.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
