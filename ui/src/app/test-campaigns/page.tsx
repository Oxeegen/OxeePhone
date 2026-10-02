"use client";

// OxeePhone: test campaigns (src/brand/tests).
import { notFound } from "next/navigation";

import { isBranded } from "@/brand/brand";
import { TestCampaignsPage } from "@/brand/tests/TestCampaignsPage";

export default function Page() {
  if (!isBranded) notFound();
  return <TestCampaignsPage />;
}
