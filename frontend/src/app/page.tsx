import LandingPage from "@/features/landing/landing-page";
import { redirectSignedInUser } from "@/lib/auth/server";
import { AuthEntrySession } from "@/components/auth-entry-session";

export default async function Home() {
  await redirectSignedInUser();
  return <><AuthEntrySession /><LandingPage /></>;
}
