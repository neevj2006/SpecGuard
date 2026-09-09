import { NextRequest } from "next/server";

async function forward(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  if (path.some((p) => !/^[a-zA-Z0-9_-]+$/.test(p)) || path[0] !== "v1")
    return new Response("Not found", { status: 404 });
  const origin = request.headers.get("origin");
  if (origin && new URL(origin).host !== request.headers.get("host"))
    return new Response("Forbidden", { status: 403 });
  const body = ["GET", "HEAD"].includes(request.method)
    ? undefined
    : await request.text();
  if (body && body.length > 250000)
    return new Response("Request too large", { status: 413 });
  try {
    const result = await fetch(
      `http://127.0.0.1:8000/${path.join("/")}${request.nextUrl.search}`,
      {
        method: request.method,
        body,
        cache: "no-store",
        signal: AbortSignal.timeout(240000),
        headers: {
          "Content-Type": "application/json",
          Authorization: request.headers.get("authorization") ?? "",
        },
      },
    );
    return new Response(result.status === 204 ? null : await result.text(), {
      status: result.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json(
      {
        detail:
          "Analysis service unavailable. Start the local API on port 8000.",
      },
      { status: 503 },
    );
  }
}
export const GET = forward;
export const POST = forward;
export const DELETE = forward;
