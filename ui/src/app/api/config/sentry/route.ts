import { NextResponse } from 'next/server';

import { hideDograhServices } from '@/brand/brand';

export async function GET() {
  return NextResponse.json({
    enabled: !hideDograhServices && process.env.ENABLE_TELEMETRY === 'true',
    dsn: process.env.SENTRY_DSN || '',
    environment: process.env.NODE_ENV || 'development',
  });
}
