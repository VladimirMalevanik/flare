/** Bound UI waits even when an underlying request does not honor cancellation. */
export async function withRequestDeadline<T>(
  request: () => Promise<T>,
  controller: AbortController,
  timeoutMs = 30_000,
): Promise<T> {
  const signal = controller.signal;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const clear = () => clearTimeout(timer);
  signal.addEventListener("abort", clear, { once: true });
  try {
    return await new Promise<T>((resolve, reject) => {
      const cancelled = () => { signal.removeEventListener("abort", cancelled); reject(new Error("cancelled")); };
      signal.addEventListener("abort", cancelled, { once: true });
      const finish = () => signal.removeEventListener("abort", cancelled);
      if (signal.aborted) { finish(); cancelled(); return; }
      try {
        Promise.resolve(request()).then(
          (value) => { finish(); if (signal.aborted) cancelled(); else resolve(value); },
          (error) => { finish(); reject(error); },
        );
      } catch (error) { finish(); reject(error); }
    });
  } finally {
    clear();
    signal.removeEventListener("abort", clear);
  }
}
