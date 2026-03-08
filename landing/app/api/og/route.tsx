import { ImageResponse } from "next/og";

export const runtime = "edge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const variant = searchParams.get("variant") ?? "brand";

  const title = variant === "cortex" ? "ONI Cortex" : "ONI";
  const subtitle =
    variant === "cortex"
      ? "MCP Retrieval for AI Agents"
      : "Agent Infrastructure";
  const tagline =
    variant === "cortex"
      ? "Plug your agent into everything it needs to know"
      : "Tools for building, running, and scaling AI agents";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#0a0a0a",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "8px",
            marginBottom: "16px",
          }}
        >
          <span
            style={{
              fontSize: "72px",
              fontWeight: 800,
              color: "#6366f1",
              letterSpacing: "-2px",
            }}
          >
            {title.split(" ")[0]}
          </span>
          {title.split(" ")[1] && (
            <span
              style={{
                fontSize: "72px",
                fontWeight: 300,
                color: "#fafafa",
                letterSpacing: "-2px",
              }}
            >
              {title.split(" ")[1]}
            </span>
          )}
        </div>
        <div
          style={{
            fontSize: "28px",
            color: "#a1a1a1",
            marginBottom: "48px",
          }}
        >
          {subtitle}
        </div>
        <div
          style={{
            fontSize: "20px",
            color: "#71717a",
            maxWidth: "600px",
            textAlign: "center",
          }}
        >
          {tagline}
        </div>
        <div
          style={{
            position: "absolute",
            bottom: "32px",
            fontSize: "16px",
            color: "#52525b",
          }}
        >
          oni.bot
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
    }
  );
}
