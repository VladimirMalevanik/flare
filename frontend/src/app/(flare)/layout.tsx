import { AppShell } from "@/components/app-shell";
import { AuthSession } from "@/components/auth-session";
import { requireSession } from "@/lib/auth/server";

export default async function FlareLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const session = await requireSession();
  return <AuthSession session={session}><AppShell>{children}</AppShell></AuthSession>;
}
