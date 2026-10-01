import { BRAND } from "@/brand/brand";
import { cn } from "@/lib/utils";

// OxeePhone lockup: the signal tile (three arcs) + "Oxee" in the foreground colour
// and "Phone" in brand violet. Same props as the upstream BrandLogo (height via
// className, `inverse` for always-dark surfaces, `mark` for the square mark).
// Inline SVG so the wordmark uses the app font; `textLength` pins its width so
// the viewBox never clips whatever font actually resolves.
export function OxeeBrandLogo({
  className,
  inverse = false,
  mark = false,
}: {
  className?: string;
  inverse?: boolean;
  mark?: boolean;
}) {
  if (mark) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={BRAND.assets.mark} alt={BRAND.productName} className={cn("w-auto select-none", className)} />
    );
  }

  return (
    <svg
      viewBox="0 0 484 100"
      role="img"
      aria-label={BRAND.productName}
      className={cn("w-auto select-none", className)}
    >
      <image href={BRAND.assets.mark} x="0" y="0" width="100" height="100" />
      <text
        x="124"
        y="72"
        fontSize="68"
        fontWeight="600"
        letterSpacing="-2"
        textLength="356"
        lengthAdjust="spacingAndGlyphs"
        style={{ fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif" }}
      >
        <tspan className={inverse ? "fill-zinc-50" : "fill-zinc-900 dark:fill-zinc-50"}>Oxee</tspan>
        <tspan className={inverse ? "fill-[#8E80FF]" : "fill-[#5E4AF5] dark:fill-[#8E80FF]"}>Phone</tspan>
      </text>
    </svg>
  );
}
