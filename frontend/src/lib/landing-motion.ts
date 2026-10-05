/** Progressive enhancement: no hidden server content and no scroll frame handlers. */
export function attachLandingMotion(root: HTMLElement, view: Window = window) {
  const doc = root.ownerDocument;
  const media = view.matchMedia("(prefers-reduced-motion: reduce)");
  const animations = new Set<Animation>();
  const revealed = new WeakSet<Element>();
  let disposed = false;

  function cancelAnimations() {
    animations.forEach((animation) => animation.cancel());
    animations.clear();
  }

  function refresh() {
    root.dataset.motion = media.matches ? "reduced" : doc.hidden ? "paused" : "running";
    if (media.matches || doc.hidden) cancelAnimations();
  }

  function reveal(element: HTMLElement) {
    if (revealed.has(element)) return;
    revealed.add(element);
    if (media.matches || doc.hidden || typeof element.animate !== "function") return;
    const annotation = element.matches("[data-motion-annotation]");
    const frames = annotation
      ? [{ strokeDashoffset: "1", opacity: 0.2 }, { strokeDashoffset: "0", opacity: 1 }]
      : [{ opacity: 0.2, transform: "translateY(22px)", clipPath: "inset(0 0 28% 0)" },
        { opacity: 1, transform: "translateY(0)", clipPath: "inset(0 0 0% 0)" }];
    const animation = element.animate(frames, {
      duration: annotation ? 700 : 760,
      delay: Math.min(Number(element.dataset.motionDelay) || 0, 240),
      easing: "cubic-bezier(.16,1,.3,1)",
      // No forwards fill: the underlying DOM always contains the final, readable state.
    });
    animations.add(animation);
    animation.finished.then(() => animations.delete(animation), () => animations.delete(animation));
  }

  const Observer = (view as Window & { IntersectionObserver?: typeof IntersectionObserver }).IntersectionObserver;
  const observer = Observer ? new Observer((entries) => {
    if (disposed) return;
    for (const entry of entries) {
      const element = entry.target as HTMLElement;
      if (element.hasAttribute("data-motion-loop")) {
        element.dataset.inView = String(entry.isIntersecting);
      } else if (entry.isIntersecting) {
        reveal(element);
        observer?.unobserve(element);
      }
    }
  }, { threshold: 0.12 }) : undefined;

  root.querySelectorAll<HTMLElement>("[data-motion-reveal], [data-motion-annotation], [data-motion-loop]")
    .forEach((element) => {
      if (observer) observer.observe(element);
      else if (element.hasAttribute("data-motion-loop")) element.dataset.inView = "true";
    });
  media.addEventListener("change", refresh);
  doc.addEventListener("visibilitychange", refresh);
  refresh();

  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      observer?.disconnect();
      media.removeEventListener("change", refresh);
      doc.removeEventListener("visibilitychange", refresh);
      cancelAnimations();
      delete root.dataset.motion;
      root.querySelectorAll<HTMLElement>("[data-motion-loop]").forEach((element) => delete element.dataset.inView);
    },
  };
}
