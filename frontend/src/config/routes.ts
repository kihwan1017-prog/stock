export const routes = {
  home: "/",
  login: "/login",
  dashboard: "/dashboard",
  market: "/market",
  ai: "/ai",
  trading: "/trading",
  orders: "/orders",
  positions: "/positions",
  risk: "/risk",
  strategies: "/strategies",
  news: "/news",
  disclosures: "/disclosures",
  backtests: "/backtests",
  operations: "/operations",
  settings: "/settings",
} as const;

export type AppRoute = (typeof routes)[keyof typeof routes];

export const routeTitles: Record<AppRoute, string> = {
  [routes.home]: "Home",
  [routes.login]: "Login",
  [routes.dashboard]: "Dashboard",
  [routes.market]: "Market",
  [routes.ai]: "AI Center",
  [routes.trading]: "Trading",
  [routes.orders]: "Orders",
  [routes.positions]: "Positions",
  [routes.risk]: "Risk",
  [routes.strategies]: "Strategy",
  [routes.news]: "News",
  [routes.disclosures]: "Disclosure",
  [routes.backtests]: "Backtest",
  [routes.operations]: "Operations",
  [routes.settings]: "Settings",
};

export function getRouteTitle(pathname: string): string {
  const matched = Object.entries(routeTitles).find(([path]) => path === pathname);
  return matched?.[1] ?? "KIKI Admin";
}
