"use client";
import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { apiBaseUrl } from "@/lib/auth/session";
import { captureAcquisition } from "@/lib/auth/acquisition";

export function AcquisitionCapture() {
  const pathname = usePathname();
  const query = useSearchParams().toString();
  useEffect(() => {
    if (["/", "/login", "/register"].includes(pathname)) void captureAcquisition(apiBaseUrl);
  }, [pathname, query]);
  return null;
}
