export function LoadingState({ label = "Loading…" }: { label?: string }) { return <div className="animate-pulse p-6 text-sm text-slate-500">{label}</div>; }
export function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="p-8 text-center"><p className="font-medium">{title}</p><p className="mt-1 text-slate-500">{detail}</p></div>; }
export function ErrorState({ message }: { message: string }) { return <div role="alert" className="m-4 rounded-md border border-red-200 bg-red-50 p-3 text-red-800">{message}</div>; }
