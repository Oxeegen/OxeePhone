import { describe, expect, it, vi } from "vitest";

import { openRow } from "./rowLink";

function click(target: HTMLElement, row: HTMLElement, extra: Partial<MouseEvent> = {}) {
  return { target, currentTarget: row, metaKey: false, ctrlKey: false, button: 0, ...extra } as unknown as React.MouseEvent<HTMLElement>;
}

describe("openRow", () => {
  it("opens the row's page, but not from a control inside the row", () => {
    document.body.innerHTML = '<table><tbody><tr id="r"><td id="c">x</td><td><button id="b">b</button><input id="i" type="checkbox"/></td></tr></tbody></table>';
    const row = document.getElementById("r")!;
    const push = vi.fn();
    const handler = openRow("/x", push);
    handler(click(document.getElementById("c")!, row));
    expect(push).toHaveBeenCalledWith("/x");
    handler(click(document.getElementById("b")!, row));
    handler(click(document.getElementById("i")!, row));
    expect(push).toHaveBeenCalledTimes(1);
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    handler(click(document.getElementById("c")!, row, { ctrlKey: true }));
    expect(open).toHaveBeenCalledWith("/x", "_blank");
    expect(push).toHaveBeenCalledTimes(1);
  });
});
