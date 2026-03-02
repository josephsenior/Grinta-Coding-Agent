import axios from "axios";
import { toast } from "sonner";
import { API_PREFIX } from "@/lib/constants";

const apiClient = axios.create({
  baseURL: API_PREFIX,
  timeout: 30_000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isCancel(error)) return Promise.reject(error);

    const status = error.response?.status;
    if (status === 401 || status === 403) {
      toast.error("Authentication error — please check your credentials.");
    } else if (status === 500 || status === 502 || status === 503) {
      toast.error("Server error — the backend may be restarting.");
    } else if (error.code === "ECONNABORTED") {
      toast.error("Request timed out — the server did not respond in time.");
    }

    return Promise.reject(error);
  },
);

export default apiClient;
