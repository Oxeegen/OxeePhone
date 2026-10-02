"use client";

// OxeePhone: new test campaign (src/brand/tests).
import { notFound } from "next/navigation";

import { isBranded } from "@/brand/brand";
import { NewCampaignPage } from "@/brand/tests/NewCampaignPage";

export default function Page() {
  if (!isBranded) notFound();
  return <NewCampaignPage />;
}
