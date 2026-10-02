"use client";

// OxeePhone: comparison of two test executions (src/brand/tests).
import { notFound, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { isBranded } from "@/brand/brand";
import { ComparePage } from "@/brand/tests/ComparePage";

function Compare() {
  const params = useSearchParams();
  return <ComparePage a={params.get("a") ?? ""} b={params.get("b") ?? ""} />;
}

export default function Page() {
  if (!isBranded) notFound();
  return (
    <Suspense>
      <Compare />
    </Suspense>
  );
}
