import type { MouseEvent } from "react";

// OxeePhone: a whole table row opens its page. Clicks on controls inside the
// row (buttons, links, checkboxes, menus…) keep their own behaviour; a text
// selection does not navigate; Ctrl / Cmd / middle click opens a new tab.

const INTERACTIVE =
  "button, a, input, select, textarea, label, [role=menuitem], [role=checkbox], [role=switch], [role=dialog], [data-row-ignore]";

export function openRow(href: string, push: (href: string) => void) {
  return (event: MouseEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest(INTERACTIVE) && target.closest(INTERACTIVE) !== event.currentTarget) return;
    if (typeof window !== "undefined" && window.getSelection()?.toString()) return;
    if (event.metaKey || event.ctrlKey || event.button === 1) window.open(href, "_blank");
    else push(href);
  };
}

export const ROW_CLASS = "cursor-pointer";
