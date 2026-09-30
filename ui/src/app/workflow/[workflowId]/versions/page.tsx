"use client";

// OxeePhone: agent versions (src/brand/versions).
import { notFound, useParams } from "next/navigation";

import { isBranded } from "@/brand/brand";
import { VersionsPage } from "@/brand/versions/VersionsPage";

export default function Page() {
  const params = useParams();
  if (!isBranded) notFound();
  return <VersionsPage workflowId={Number(params.workflowId)} />;
}
