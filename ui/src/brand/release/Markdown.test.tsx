import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown, parseBlocks } from "./Markdown";

const NOTES = `First OxeePhone release.

### Brand and privacy
- OxeePhone name, signal logo (three arcs on the
  gradient), favicon.
- No telemetry: see [the docs](https://github.com/Oxeegen/OxeePhone) and \`brand/README.md\`.

---
Deploy: **build** on the server.

\`\`\`bash
sudo ./brand/install.sh update
\`\`\`
`;

describe("release notes markdown", () => {
  it("parses headings, wrapped list items, rules, paragraphs and code", () => {
    const blocks = parseBlocks(NOTES);
    expect(blocks.map((b) => b.kind)).toEqual(["paragraph", "heading", "list", "rule", "paragraph", "code"]);
    const list = blocks[2] as { items: string[] };
    expect(list.items[0]).toBe("OxeePhone name, signal logo (three arcs on the gradient), favicon.");
  });

  it("renders safe inline elements and no raw HTML", () => {
    const { container } = render(<Markdown source={`${NOTES}\n<img src=x onerror=alert(1)> [bad](javascript:alert(1))`} />);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("https://github.com/Oxeegen/OxeePhone");
    expect(container.querySelectorAll("a")).toHaveLength(1);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("code")?.textContent).toBe("brand/README.md");
    expect(container.querySelector("strong")?.textContent).toBe("build");
  });
});
