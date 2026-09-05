import { Suspense } from "react";
import { VaultPage } from "@/features/vault/vault-page";
export default function Vault() { return <Suspense fallback={<div className="p-6">Loading vault…</div>}><VaultPage /></Suspense>; }
