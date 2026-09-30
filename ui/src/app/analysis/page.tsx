"use client";

// OxeePhone: configuration analysis (src/brand/analysis).
import { notFound } from "next/navigation";

import { AnalysisPage } from "@/brand/analysis/AnalysisPage";
import { isBranded } from "@/brand/brand";

export default function Page() {
  if (!isBranded) notFound();
  return <AnalysisPage />;
}
