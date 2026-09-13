import { SettingsPage } from "@/features/settings/settings-page";
import { normalizeSupportEmail } from "@/lib/support";
import { connection } from "next/server";

export default async function Settings() {
  await connection();
  const supportEmail = normalizeSupportEmail(process.env.SUPPORT_EMAIL);
  return <SettingsPage supportEmail={supportEmail} />;
}
