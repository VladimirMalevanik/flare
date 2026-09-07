"use client";
export default function AppError({ reset }: { reset: () => void }) {
  return <main className="auth-page"><section className="auth-panel"><h1>Unable to open your workspace</h1><p>Please check your connection and try again.</p><button className="button primary" onClick={reset}>Try again</button></section></main>;
}
