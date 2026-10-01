import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";
import path from "path";

import { hideDograhServices } from "./src/brand/brand";

// OxeePhone: Stack Auth pulls @stripe/stripe-js, whose import side effect loads
// js.stripe.com (+ fingerprinting) even with local auth. Swap it for a stub.
const BRAND_ALIASES: Record<string, string> = hideDograhServices
  ? { "@stripe/stripe-js": "./src/brand/stubs/stripe-js.ts" }
  : {};

const nextConfig: NextConfig = {
  /* config options here */
  output: 'standalone',
  turbopack: { resolveAlias: BRAND_ALIASES },
  webpack: (config) => {
    for (const [name, target] of Object.entries(BRAND_ALIASES)) {
      config.resolve.alias[name] = path.resolve(__dirname, target);
    }
    return config;
  },
  experimental: {
    serverSourceMaps: true,
  },
  async rewrites() {
    return [
      {
        source: "/ingest/static/:path*",
        destination: "https://us-assets.i.posthog.com/static/:path*",
      },
      {
        source: "/ingest/:path*",
        destination: "https://us.i.posthog.com/:path*",
      },
      {
        source: "/ingest/decide",
        destination: "https://us.i.posthog.com/decide",
      },
    ];
  },
  // This is required to support PostHog trailing slash API requests
  skipTrailingSlashRedirect: true,
};

export default withSentryConfig(nextConfig, {
  // For all available options, see:
  // https://www.npmjs.com/package/@sentry/webpack-plugin#options

  org: "dograh",
  project: "javascript-nextjs",

  // Only print logs for uploading source maps in CI
  silent: !process.env.CI,

  // For all available options, see:
  // https://docs.sentry.io/platforms/javascript/guides/nextjs/manual-setup/

  // Upload a larger set of source maps for prettier stack traces (increases build time)
  widenClientFileUpload: true,

  // Route browser requests to Sentry through a Next.js rewrite to circumvent ad-blockers.
  // This can increase your server load as well as your hosting bill.
  // Note: Check that the configured route will not match with your Next.js middleware, otherwise reporting of client-
  // side errors will fail.
  tunnelRoute: "/monitoring",

  webpack: {
    // Automatically tree-shake Sentry logger statements to reduce bundle size
    treeshake: {
      removeDebugLogging: true,
    },

    // Enables automatic instrumentation of Vercel Cron Monitors. (Does not yet work with App Router route handlers.)
    // See the following for more information:
    // https://docs.sentry.io/product/crons/
    // https://vercel.com/docs/cron-jobs
    automaticVercelMonitors: true,
  },
});
