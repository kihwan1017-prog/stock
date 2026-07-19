import "@testing-library/jest-dom/vitest";

process.env.NEXT_PUBLIC_APP_NAME = "KIKI AI Trading Platform";
process.env.NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000";
process.env.NEXT_PUBLIC_API_PREFIX = "/api/v1";
process.env.NEXT_PUBLIC_WS_BASE_URL = "ws://127.0.0.1:8000";
process.env.NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS = "false";
process.env.NEXT_PUBLIC_AUTH_MODE = "backend";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
