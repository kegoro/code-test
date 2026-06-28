const DEFAULT_BACKEND = "http://localhost:8000";

export function getSimBackendUrl(): string {
  return process.env.SIM_BACKEND_URL ?? DEFAULT_BACKEND;
}

export function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Unexpected error";
}
