// OxeePhone brand layer (Oxeegen fork of Dograh).
//
// Everything brand-specific in the UI lives under src/brand. Upstream files only
// read BRAND flags from here, so each patch stays a small, clearly-gated change
// that is easy to re-apply after an upstream merge. Flip `enabled` to false to
// get the upstream Dograh behaviour back.

export const BRAND = {
  enabled: true,

  productName: "OxeePhone",
  upstreamName: "Dograh",
  description: "Oxeegen voice agent platform",

  assets: {
    mark: "/brand/oxeephone-mark.svg",
    imprintLight: "/brand/oxeephone-imprint-light.svg",
    imprintDark: "/brand/oxeephone-imprint-dark.svg",
  },

  auth: {
    headline: "Oxeegen's voice agent platform.",
    highlights: ["Self-hosted models", "Visual agent builder", "Telephony & web"],
  },

  // Hide every link to docs.dograh.com / dograh.com (see brand.css).
  hideDocs: true,
  // No calls to Dograh-hosted services: PostHog, Sentry, Chatwoot, lead
  // forms (api-leads.dograh.com), GitHub star badge, release-version check.
  disableDograhServices: true,
  // Models: BYOK pipeline only, every service on the self-hosted
  // OpenAI-compatible provider ("speaches", shown as Local Models). Must match
  // the API's OXEE_LOCAL_MODELS_ONLY.
  localModelsOnly: true,
} as const;

export const isBranded = BRAND.enabled;
export const hideDograhServices = BRAND.enabled && BRAND.disableDograhServices;
export const localModelsOnly = BRAND.enabled && BRAND.localModelsOnly;
