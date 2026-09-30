"use client";
import type { ItemType } from "@/lib/data";
import { Icon, itemIcon } from "./icons";
import { useI18n } from "@/i18n/provider";
export function ItemType({ type }: { type: ItemType }) { const { label } = useI18n(); return <span className="inline-flex items-center gap-1.5 text-slate-500"><Icon name={itemIcon[type]} className="h-4 w-4"/><span className="capitalize">{type === "url" ? "URL" : label(type)}</span></span>; }
