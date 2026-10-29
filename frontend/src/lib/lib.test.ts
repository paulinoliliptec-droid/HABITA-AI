import { describe, expect, it } from "vitest";
import { ApiError, parseErrorResponse } from "./api";
import { cycleIndex } from "./cycleIndex";

describe("parseErrorResponse", () => {
  it("reads the structured backend error", async () => {
    const res = new Response(JSON.stringify({ error: { code: "address_not_found", message: "Not found." } }), {
      status: 422,
    });
    const err = await parseErrorResponse(res);
    expect(err).toBeInstanceOf(ApiError);
    expect([err.code, err.message, err.status]).toEqual(["address_not_found", "Not found.", 422]);
  });

  it("falls back for non-JSON bodies", async () => {
    const err = await parseErrorResponse(new Response("<html>Bad gateway</html>", { status: 502 }));
    expect([err.code, err.status]).toEqual(["internal_error", 502]);
  });
});

describe("cycleIndex", () => {
  it("moves down through options then back to the input", () => {
    expect([cycleIndex(-1, 1, 3), cycleIndex(0, 1, 3), cycleIndex(2, 1, 3)]).toEqual([0, 1, -1]);
  });

  it("moves up from the input to the last option", () => {
    expect([cycleIndex(-1, -1, 3), cycleIndex(0, -1, 3)]).toEqual([2, -1]);
  });

  it("stays on the input with no options", () => {
    expect(cycleIndex(-1, 1, 0)).toBe(-1);
  });
});
