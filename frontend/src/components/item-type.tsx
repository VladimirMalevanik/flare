import type { ItemType } from "@/lib/data";
import { Icon, itemIcon } from "./icons";
export function ItemType({ type }: { type: ItemType }) { return <span className="inline-flex items-center gap-1.5 text-slate-500"><Icon name={itemIcon[type]} className="h-4 w-4"/><span className="capitalize">{type === "url" ? "URL" : type}</span></span>; }
