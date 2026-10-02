"use client";

// OxeePhone: one test campaign (src/brand/tests).
import { notFound, useParams } from "next/navigation";

import { isBranded } from "@/brand/brand";
import { CampaignPage } from "@/brand/tests/CampaignPage";

export default function Page() {
  const { campaignId } = useParams<{ campaignId: string }>();
  if (!isBranded) notFound();
  return <CampaignPage campaignId={campaignId} />;
}
