"use client";

// OxeePhone: report of a test execution (src/brand/tests).
import { notFound, useParams } from "next/navigation";

import { isBranded } from "@/brand/brand";
import { ExecutionPage } from "@/brand/tests/ExecutionPage";

export default function Page() {
  const { campaignId, executionId } = useParams<{ campaignId: string; executionId: string }>();
  if (!isBranded) notFound();
  return <ExecutionPage campaignId={campaignId} executionId={executionId} />;
}
