type LogLevel = "debug" | "info" | "warn" | "error";

function writeLog(level: LogLevel, message: string, meta?: unknown): void {
  if (process.env.NODE_ENV === "production" && level === "debug") {
    return;
  }

  const prefix = `[kiki-admin][${level}]`;
  const method = level === "debug" ? "log" : level;

  if (meta === undefined) {
    console[method](prefix, message);
    return;
  }

  console[method](prefix, message, meta);
}

export const logger = {
  debug: (message: string, meta?: unknown) => writeLog("debug", message, meta),
  info: (message: string, meta?: unknown) => writeLog("info", message, meta),
  warn: (message: string, meta?: unknown) => writeLog("warn", message, meta),
  error: (message: string, meta?: unknown) => writeLog("error", message, meta),
};
