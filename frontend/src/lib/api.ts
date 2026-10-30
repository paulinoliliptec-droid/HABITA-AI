import { config } from "@/lib/config";

export type ApiErrorCode =
  | "validation_error"
  | "address_not_found"
  | "not_found"
  | "rate_limited"
  | "storage_unavailable"
  | "service_not_configured"
  | "upstream_error"
  | "network_error"
  | "internal_error";

export class ApiError extends Error {
  constructor(
    readonly code: ApiErrorCode,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FALLBACK_MESSAGE = "Something went wrong. Please try again.";

export async function parseErrorResponse(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    if (body.error?.code) {
      return new ApiError(body.error.code as ApiErrorCode, body.error.message ?? FALLBACK_MESSAGE, response.status);
    }
  } catch {
    // Non-JSON body (proxy error page, etc.): fall through.
  }
  return new ApiError("internal_error", FALLBACK_MESSAGE, response.status);
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network_error", "HABITA can't reach its server right now. Check your connection and try again.", 0);
  }
  if (!response.ok) throw await parseErrorResponse(response);
  return (await response.json()) as T;
}
