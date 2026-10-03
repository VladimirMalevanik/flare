"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
  description?: string;
};

export type SelectProps = {
  value: string;
  options: readonly SelectOption[];
  onValueChange: (value: string) => void;
  id?: string;
  disabled?: boolean;
  placeholder?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
  variant?: "field" | "compact";
  align?: "start" | "end";
  className?: string;
  icon?: ReactNode;
  name?: string;
};

/** A select-only combobox. Its top-layer menu keeps the trigger in the page's tab order. */
export function Select({
  value, options, onValueChange, id, disabled = false, placeholder,
  "aria-label": ariaLabel, "aria-labelledby": ariaLabelledBy,
  "aria-describedby": ariaDescribedBy, variant = "field", align = "start",
  className = "", icon, name,
}: SelectProps) {
  const generatedId = useId();
  const triggerId = id ?? `select-${generatedId}`;
  const menuId = `${triggerId}-options`;
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const typeahead = useRef({ text: "", time: 0 });
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const selected = options.findIndex((option) => option.value === value);
  const enabled = options.flatMap((option, index) => option.disabled ? [] : [index]);
  const label = options[selected]?.label ?? placeholder ?? "";
  const isOpen = open && !disabled && enabled.length > 0;

  function close(returnFocus = false) {
    setOpen(false);
    typeahead.current = { text: "", time: 0 };
    if (returnFocus) trigger.current?.focus({ preventScroll: true });
  }

  function show(index = selected) {
    if (disabled || !enabled.length) return;
    setActive(enabled.includes(index) ? index : enabled[0]);
    setOpen(true);
  }

  function choose(index: number, returnFocus = true) {
    const option = options[index];
    if (!option || option.disabled) return;
    if (option.value !== value) onValueChange(option.value);
    close(returnFocus);
  }

  function move(distance: number) {
    const position = enabled.indexOf(active);
    const next = Math.max(0, Math.min(enabled.length - 1, position + distance));
    setActive(enabled[next]);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      event.stopPropagation();
      close(true);
      return;
    }
    if (event.key === "Tab") {
      if (isOpen) choose(active, false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      event.stopPropagation();
      if (isOpen && event.altKey && event.key === "ArrowUp") choose(active);
      else if (!isOpen) show(event.key === "ArrowUp" ? enabled[0] : selected);
      else move(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      event.stopPropagation();
      show(event.key === "Home" ? enabled[0] : enabled[enabled.length - 1]);
      return;
    }
    if (isOpen && (event.key === "PageUp" || event.key === "PageDown")) {
      event.preventDefault();
      move(event.key === "PageDown" ? 10 : -10);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      if (isOpen) choose(active);
      else show();
      return;
    }
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    const now = Date.now();
    const previous = now - typeahead.current.time < 650 ? typeahead.current.text : "";
    const text = (previous + event.key).toLocaleLowerCase();
    typeahead.current = { text, time: now };
    const repeated = [...text].every((character) => character === text[0]);
    const query = repeated ? text[0] : text;
    const start = repeated ? enabled.indexOf(isOpen ? active : selected) + 1 : 0;
    const ordered = [...enabled.slice(start), ...enabled.slice(0, start)];
    const match = ordered.find((index) => options[index].label.toLocaleLowerCase().startsWith(query));
    show(match ?? (isOpen ? active : selected));
  }

  useLayoutEffect(() => {
    if (!isOpen || !menu.current || !trigger.current) return;
    const popup = menu.current;
    const button = trigger.current;
    // Native popovers escape overflow clipping and remain usable inside a modal dialog.
    const nativePopover = typeof popup.showPopover === "function";
    if (nativePopover) popup.showPopover();
    else popup.dataset.fallbackOpen = "true";

    function place() {
      const rect = button.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = (viewport?.offsetLeft ?? 0) + 12;
      const topEdge = (viewport?.offsetTop ?? 0) + 12;
      const rightEdge = (viewport?.offsetLeft ?? 0) + (viewport?.width ?? window.innerWidth) - 12;
      const bottomEdge = (viewport?.offsetTop ?? 0) + (viewport?.height ?? window.innerHeight) - 12;
      const width = Math.min(Math.max(rect.width, 180), Math.max(1, rightEdge - leftEdge));
      popup.style.width = `${width}px`;
      const below = bottomEdge - rect.bottom - 6;
      const above = rect.top - topEdge - 6;
      const desiredHeight = Math.min(popup.scrollHeight, 320);
      const bottom = below >= Math.min(desiredHeight, 180) || below >= above;
      popup.style.maxHeight = `${Math.max(1, Math.min(320, bottom ? below : above))}px`;
      const height = popup.getBoundingClientRect().height;
      const left = align === "end" ? rect.right - width : rect.left;
      const top = bottom ? rect.bottom + 6 : rect.top - height - 6;
      popup.style.left = `${Math.max(leftEdge, Math.min(left, rightEdge - width))}px`;
      popup.style.top = `${Math.max(topEdge, Math.min(top, bottomEdge - height))}px`;
      popup.dataset.side = bottom ? "bottom" : "top";
    }

    place();
    const observer = new ResizeObserver(place);
    observer.observe(button);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
      if (nativePopover && popup.matches(":popover-open")) popup.hidePopover();
      else delete popup.dataset.fallbackOpen;
    };
  }, [isOpen, align, variant, options]);

  useLayoutEffect(() => {
    if (isOpen && active >= 0) {
      menu.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
    }
  }, [isOpen, active]);

  useEffect(() => {
    if (!isOpen) return;
    function outside(event: PointerEvent) {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !menu.current?.contains(target)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [isOpen]);

  return (
    <span className={`flare-select flare-select--${variant} ${className}`}>
      {name && <input type="hidden" name={name} value={value} disabled={disabled} />}
      <button
        ref={trigger} id={triggerId} type="button" role="combobox" className="flare-select-trigger"
        disabled={disabled} aria-label={ariaLabel} aria-labelledby={ariaLabelledBy}
        aria-describedby={ariaDescribedBy} aria-haspopup="listbox" aria-expanded={isOpen}
        aria-controls={menuId} aria-activedescendant={isOpen && active >= 0 ? `${menuId}-${active}` : undefined}
        onKeyDown={onKeyDown} onClick={() => isOpen ? close() : show()}
        onBlur={() => { if (isOpen) choose(active, false); }}
      >
        {icon && <span className="flare-select-icon" aria-hidden="true">{icon}</span>}
        <span className={`flare-select-value${selected < 0 ? " is-placeholder" : ""}`}>{label}</span>
        <svg className="flare-select-chevron" aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m4.5 6 3.5 3.5L11.5 6" /></svg>
      </button>
      <div
        ref={menu} id={menuId} role="listbox" popover="manual" className="flare-select-menu"
        aria-label={ariaLabel} aria-labelledby={ariaLabelledBy ?? (!ariaLabel ? triggerId : undefined)}
        onPointerDown={(event) => event.preventDefault()}
        onClick={(event) => { event.preventDefault(); event.stopPropagation(); }}
      >
        {options.map((option, index) => (
          <div
            key={option.value} id={`${menuId}-${index}`} role="option"
            aria-selected={option.value === value} aria-disabled={option.disabled || undefined}
            aria-label={option.label} data-index={index} data-active={isOpen && active === index || undefined}
            className="flare-select-option"
            onPointerMove={() => { if (!option.disabled) setActive(index); }}
            onClick={() => choose(index)}
          >
            <span className="flare-select-option-copy"><span>{option.label}</span>{option.description && <small>{option.description}</small>}</span>
            <svg className="flare-select-check" aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m3.5 8 3 3 6-6" /></svg>
          </div>
        ))}
      </div>
    </span>
  );
}
