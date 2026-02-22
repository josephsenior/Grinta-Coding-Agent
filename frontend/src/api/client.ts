import axios from "axios";
import { API_PREFIX } from "@/lib/constants";

const apiClient = axios.create({
  baseURL: API_PREFIX,
  headers: {
    "Content-Type": "application/json",
  },
});

export default apiClient;
