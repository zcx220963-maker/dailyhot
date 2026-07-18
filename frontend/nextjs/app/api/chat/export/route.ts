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

    // MD 返回 JSON；PDF / DOCX 返回二进制流。根据 Content-Type 透传。
    const contentType = response.headers.get('Content-Type') || 'application/json';

    if (contentType.includes('application/json')) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }

    // 二进制流（PDF / DOCX）：直接透传 body + 相关 headers
    const arrayBuffer = await response.arrayBuffer();
    const headers = new Headers();
    headers.set('Content-Type', contentType);
    const disposition = response.headers.get('Content-Disposition');
    if (disposition) headers.set('Content-Disposition', disposition);
    return new NextResponse(Buffer.from(arrayBuffer), {
      status: response.status,
      headers,
    });
  } catch (error: any) {
    console.error('POST /api/chat/export - Error proxying to backend:', error);
    return NextResponse.json(
      { ok: false, error: 'Failed to connect to backend service' },
      { status: 500 }
    );
  }
}
