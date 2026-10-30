import { PasswordRecovery } from "@/features/auth/password-recovery";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Reset your password · Flare", referrer: "no-referrer", robots: { index: false, follow: false } };

export default function ForgotPasswordPage() {
  return <PasswordRecovery key="forgot" />;
}
