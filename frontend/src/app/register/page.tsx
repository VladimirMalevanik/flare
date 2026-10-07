import { AuthForm } from "@/features/auth/auth-form";
import { redirectSignedInUser } from "@/lib/auth/server";

export default async function RegisterPage() {
  await redirectSignedInUser();
  return <AuthForm register />;
}
