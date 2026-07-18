import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const backendUrl = process.env.NEXT_PUBLIC_GPTR_API_URL || 'http://localhost:8000';

  try {
    const body = await request.json();

    const response = await fetch(`${backendUrl}/api/chat/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('POST /api/chat/export - Error proxying to backend:', error);
    return NextResponse.json(
      { ok: false, error: 'Failed to connect to backend service' },
      { status: 500 }
    );
  }
}
