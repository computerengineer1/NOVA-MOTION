import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, thumbnailUrl, videoFileUrl } from "../lib/api";

function mockResponse(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body == null ? "" : JSON.stringify(body)),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("parses successful JSON responses", async () => {
    vi.stubGlobal("fetch", mockResponse(200, { status: "ok", version: "1.0.0" }));
    const health = await api.health();
    expect(health.status).toBe("ok");
    expect(fetch).toHaveBeenCalledWith("/api/health", expect.objectContaining({
      headers: { "Content-Type": "application/json" },
    }));
  });

  it("maps backend error envelopes onto ApiError", async () => {
    vi.stubGlobal("fetch", mockResponse(409, {
      error: {
        code: "ENGINE_UNREACHABLE",
        summary: "Engine offline.",
        recovery: "Start the engine from the System page.",
        retryable: true,
      },
    }));
    const err = await api.engineStatus().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("ENGINE_UNREACHABLE");
    expect(err.recovery).toBe("Start the engine from the System page.");
    expect(err.retryable).toBe(true);
    expect(err.message).toBe("Engine offline.");
  });

  it("handles non-JSON error bodies without crashing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, text: async () => "<html>boom</html>",
    }));
    const err = await api.health().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("HTTP_500");
  });

  it("surfaces network failure as a NETWORK ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await api.system().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("NETWORK");
    expect(err.status).toBe(0);
  });

  it("builds video URLs with encoding", () => {
    expect(videoFileUrl("a/b c")).toBe("/api/videos/a%2Fb%20c/file");
    expect(thumbnailUrl("xyz")).toBe("/api/videos/xyz/thumbnail");
  });

  it("builds the videos query string only from provided filters", async () => {
    const f = mockResponse(200, []);
    vi.stubGlobal("fetch", f);
    await api.videos({ q: "a b", sort: "newest" });
    const url = String(f.mock.calls[0][0]);
    expect(url.startsWith("/api/videos?")).toBe(true);
    expect(url).toContain("q=a+b");
    expect(url).toContain("sort=newest");
    expect(url).not.toContain("model_id");
  });

  it("sends generation payloads as JSON bodies", async () => {
    const f = mockResponse(201, { id: "job1", status: "QUEUED" });
    vi.stubGlobal("fetch", f);
    await api.submitGeneration({
      prompt: "test", negative_prompt: "", model_id: "animatediff-sd15",
      duration_seconds: 8, aspect_ratio: "16:9", resolution_id: null,
      steps: 16, cfg: 7.5, sampler: "dpmpp_2m", scheduler: "karras",
      seed: null, random_seed: true, generation_mode: "auto",
      export_fps: 8, interpolation: "none", upscale_export: false,
    });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toMatchObject({ prompt: "test", duration_seconds: 8 });
  });
});
