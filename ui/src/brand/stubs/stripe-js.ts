// Inert stand-in for @stripe/stripe-js (aliased in next.config.ts when the
// brand cuts Dograh services).
//
// @stackframe/stack (Dograh Cloud's auth provider) imports `loadStripe` for its
// account payments panel. Importing the real package injects js.stripe.com —
// and Stripe's device fingerprinting (m.stripe.com) — as a side effect on every
// page whose bundle references Stack, even with local auth where Stack is never
// used. OxeePhone runs local auth only, so Stripe is never needed.

export const loadStripe = async (): Promise<null> => null;
