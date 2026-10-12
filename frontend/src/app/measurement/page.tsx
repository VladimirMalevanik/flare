import type { Metadata } from "next";
import Link from "next/link";
import { LegalPage, LegalSection } from "@/components/legal-page";
import { AcquisitionPreferences } from "@/features/acquisition/preferences";

export const metadata: Metadata = { title: "Link Measurement — Flare" };
export default function MeasurementPage() {
  return <LegalPage title="Link Measurement" updated="October 10, 2026">
    <p>Optional link measurement helps us compare the links shared by our three X accounts. It is separate from <Link href="/analytics">website page-count analytics</Link> and accepting our Privacy Policy and Terms. You can use Flare without allowing link measurement.</p>
    <LegalSection title="After you allow link measurement">
      <p>We store approved campaign labels (source, medium, campaign, content and account label), the public landing route and the referring site’s domain. We exclude full URLs, arbitrary query values, email addresses and saved content. A random first-party cookie, flare_acquisition, connects those labels to your registration. This cookie is HttpOnly and is cleared when you register.</p>
      <p>Your first and most recent non-direct touch can be linked to your Flare account. Registration freezes those labels; signing in later does not assign a new campaign. We count committed captures/imports, completed manual Analyze runs, explicit Flare/evidence inspections and a later-day inspection. Optional observations can be missed, and these counts do not establish that every visitor is human.</p>
    </LegalSection>
    <LegalSection title="Retention and reports">
      <p>The link cookie and anonymous touch expire after at most 7 days. Account-linked attribution and action measurement are kept for at most 90 days. A scheduled cleanup job removes expired records. Data stays in Flare’s existing database; we do not send these campaign labels to Microsoft’s page-view analytics.</p>
      <p>Only a restricted reporting operator can produce an aggregate report. Groups with fewer than 5 accounts are hidden; a small group suppresses the entire attribution breakdown. Reports contain counts and approved campaign labels, not identities or note contents. They measure opted-in attribution among registered accounts, not total link clicks or visitor-to-registration conversion.</p>
    </LegalSection>
    <LegalSection title="Your choice">
      <p>Consent is saved for this tab’s browser session and tied to this notice’s revision. A new notice requires a new choice. Global Privacy Control and Do Not Track prevent new optional link collection. In Settings → Data &amp; Privacy, you can remove your account’s attribution and action measurement and stop future measurement. Your notes, Flares, subscription and account remain available. Reports already downloaded cannot be recalled.</p>
      <AcquisitionPreferences />
      <p>For questions, contact <a href="mailto:support@flare4u.tech">support@flare4u.tech</a>. Notice identifier: measurement-x-v1.</p>
    </LegalSection>
  </LegalPage>;
}
