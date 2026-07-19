import axios from "axios";

import { env } from "@/config/env";
import { setupInterceptors } from "@/lib/api/interceptors";

/**
 * /health 등 API prefix 밖의 루트 엔드포인트용 클라이언트
 * baseURL = API_BASE_URL only (NOT + /api/v1)
 */
const rootClient = axios.create({
  baseURL: env.API_BASE_URL,
  timeout: 15_000,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

setupInterceptors(rootClient);

export { rootClient };
