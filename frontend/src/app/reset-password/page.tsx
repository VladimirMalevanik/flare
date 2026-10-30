import { PasswordRecovery } from "@/features/auth/password-recovery";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Choose a new password · Flare", referrer: "no-referrer", robots: { index: false, follow: false } };

export default function ResetPasswordPage() {
  return <PasswordRecovery key="reset" reset />;
}
