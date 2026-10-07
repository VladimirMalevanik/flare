import { AuthForm } from "@/features/auth/auth-form";
import { redirectSignedInUser } from "@/lib/auth/server";

export default async function LoginPage() {
  await redirectSignedInUser();
  return <AuthForm />;
}
