"use client";
import { useI18n } from "@/i18n/provider";
import { Suspense } from "react";
import { VaultPage } from "@/features/vault/vault-page";
export default function Vault() {
  const { t } = useI18n();
 return <Suspense fallback={<div className="p-6">{t("Loading vault…")}</div>}><VaultPage /></Suspense>; }
