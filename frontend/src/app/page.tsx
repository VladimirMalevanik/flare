import LandingPage from "@/features/landing/landing-page";
import { redirectSignedInUser } from "@/lib/auth/server";

export default async function Home() {
  await redirectSignedInUser();
  return <LandingPage />;
}
