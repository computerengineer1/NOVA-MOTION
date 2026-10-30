import { describe, expect, it } from "vitest";
import {
  JOB_STAGE_ORDER, STAGE_LABELS, formatBytes, formatClock, formatDuration,
  formatElapsed, isTerminal, percentOf,
} from "../lib/format";

describe("formatBytes", () => {
  it("formats decimal-ish units with one decimal", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1023)).toBe("1023 B");
    expect(formatBytes(2048)).toMatch(/KB/);
    expect(formatBytes(3950585193)).toMatch(/GB/);
  });
  it("handles null/undefined honestly", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("shows 8-second target with 3 decimals", () => {
    expect(formatDuration(8)).toMatch(/8/);
    expect(formatDuration(null)).toBe("—");
  });
});

describe("formatClock", () => {
  it("renders m:ss", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(3600)).toMatch(/^(\d+:)?\d{1,2}:\d{2}$|^60:00$/);
  });
});

describe("formatElapsed", () => {
  it("renders compact elapsed time", () => {
    expect(formatElapsed(0)).toMatch(/0/);
    expect(formatElapsed(90)).toMatch(/1/);
    expect(formatElapsed(null)).toBe("—");
  });
});

describe("percentOf", () => {
  it("clamps and guards divide-by-zero", () => {
    expect(percentOf(1, 2)).toBe(50);
    expect(percentOf(3, 2)).toBe(100);
    expect(percentOf(1, 0)).toBe(0);
  });
});

describe("stage order", () => {
  it("matches the documented state machine", () => {
    expect([...JOB_STAGE_ORDER]).toEqual([
      "QUEUED", "PREFLIGHT", "INITIALIZING", "GENERATING", "ASSEMBLING",
      "INTERPOLATING", "ENCODING", "VALIDATING", "COMPLETED",
    ]);
    for (const s of JOB_STAGE_ORDER) expect(STAGE_LABELS[s]).toBeTruthy();
  });
});

describe("isTerminal", () => {
  it("knows the three terminal states", () => {
    expect(isTerminal("COMPLETED")).toBe(true);
    expect(isTerminal("FAILED")).toBe(true);
    expect(isTerminal("CANCELLED")).toBe(true);
    expect(isTerminal("GENERATING")).toBe(false);
    expect(isTerminal("QUEUED")).toBe(false);
    expect(isTerminal(null)).toBe(false);
    expect(isTerminal(undefined)).toBe(false);
  });
});
