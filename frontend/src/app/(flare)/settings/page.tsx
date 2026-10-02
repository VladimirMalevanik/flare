import { SettingsPage } from "@/features/settings/settings-page";
import { SubscriptionSection } from "@/features/subscription/subscription-section";
import { normalizeSupportEmail } from "@/lib/support";
import { connection } from "next/server";

export default async function Settings() {
  await connection();
  const supportEmail = normalizeSupportEmail(process.env.SUPPORT_EMAIL);
  return <SettingsPage supportEmail={supportEmail} subscription={<SubscriptionSection />} />;
}
