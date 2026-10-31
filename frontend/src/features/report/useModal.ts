import { useEffect, type RefObject } from "react";

/** A modal dialog's keyboard: Escape closes, Tab cycles inside it, and focus returns to where it was. */
export function useModal(dialog: RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") return onClose();
      if (event.key !== "Tab") return;
      // The dialog is modal: Tab cycles inside it and never reaches the page behind.
      const inside = [...(dialog.current?.querySelectorAll<HTMLElement>("button, a[href]") ?? [])];
      const [first, last] = [inside[0], inside[inside.length - 1]];
      const edge = event.shiftKey ? first : last;
      if (document.activeElement === edge || !dialog.current?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus(); // keyboard users return to where they were
    };
  }, [dialog, onClose]);
}
