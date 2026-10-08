import { AuthForm } from "@/features/auth/auth-form";
import { redirectSignedInUser } from "@/lib/auth/server";
import { AuthEntrySession } from "@/components/auth-entry-session";

export default async function RegisterPage() {
  await redirectSignedInUser();
  return <><AuthEntrySession /><AuthForm register /></>;
}
