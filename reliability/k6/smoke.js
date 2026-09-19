import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = (__ENV.API_ENDPOINT || "").replace(/\/$/, "");
if (!baseUrl) {
  throw new Error("Set API_ENDPOINT to the dev API Gateway URL");
}

export const options = {
  vus: 2,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<2000"],
  },
};

export default function () {
  const health = http.get(`${baseUrl}/health`);
  check(health, { "health 2xx": (r) => r.status >= 200 && r.status < 300 });

  const ready = http.get(`${baseUrl}/ready`);
  check(ready, { "ready 2xx": (r) => r.status >= 200 && r.status < 300 });

  sleep(1);
}
