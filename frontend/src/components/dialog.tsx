"use client";
import { useEffect, useRef, type ReactNode } from "react";
export function Dialog({
  title,
  onClose,
  children,
  className = "",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  // Capture before mounting the dialog can disable or blur its launcher.
  const launcher = useRef<HTMLElement | null>(
    typeof document !== "undefined" ? document.activeElement as HTMLElement | null : null,
  );
  useEffect(() => {
    const node = ref.current;
    const returnTo = launcher.current;
    node?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      node?.close();
      document.body.style.overflow = previous;
      if (returnTo?.isConnected) returnTo.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      className={`sheet ${className}`}
      onKeyDown={(e) => { if (e.key === "Escape") e.stopPropagation(); }}
      onCancel={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      {children}
    </dialog>
  );
}
