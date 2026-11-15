import { useCallback, useEffect, useId, useRef, useState } from "react";

/**
 * A button that opens a panel (the app switcher, the account menu). Escape and a click
 * outside close it, and the focus goes back to the button (WCAG 2.2: 2.1.2, 2.4.3).
 */
export function useMenu() {
  const [open, setOpen] = useState(false);
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  const close = useCallback((returnFocus = true) => {
    setOpen(false);
    if (returnFocus) button.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const first = panel.current?.querySelector<HTMLElement>("a[href], button:not([disabled])");
    first?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) close(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, close]);

  return {
    open,
    close,
    buttonProps: {
      ref: button,
      "aria-expanded": open,
      "aria-controls": id,
      onClick: () => setOpen((value) => !value),
    },
    panelProps: { ref: panel, id, hidden: !open },
  };
}
