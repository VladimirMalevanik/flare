import { VerifyEmail } from "@/features/auth/verify-email";

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string; pending?: string }>;
}) {
  const parameters = await searchParams;
  return (
    <VerifyEmail
      token={parameters.token ?? ""}
      awaitingEmail={parameters.pending === "1"}
    />
  );
}
