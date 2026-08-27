import { Suspense } from "react";

import { MarketDataExplorerView } from "@/features/admin/market-data/MarketDataExplorerView";

export default function AdminMarketDataPage() {
  return (
    <Suspense fallback={null}>
      <MarketDataExplorerView />
    </Suspense>
  );
}
