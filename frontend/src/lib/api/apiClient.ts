import axios from "axios";

import { env } from "@/config/env";
import { setupInterceptors } from "@/lib/api/interceptors";

const apiClient = axios.create({
  baseURL: `${env.API_BASE_URL}${env.API_PREFIX}`,
  timeout: 15_000,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

setupInterceptors(apiClient);

export { apiClient };
