import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = (__ENV.API_ENDPOINT || "").replace(/\/$/, "");
if (!baseUrl) {
  throw new Error("Set API_ENDPOINT (terraform api_endpoint, includes /v1)");
}

// ≥15m soak at moderate VUs (brief G3 requirement). Edge probes only.
export const options = {
  stages: [
    { duration: "2m", target: 5 },
    { duration: "15m", target: 10 },
    { duration: "1m", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
    checks: ["rate>0.99"],
  },
};

export default function () {
  const health = http.get(`${baseUrl}/health`);
  check(health, { "health 2xx": (r) => r.status >= 200 && r.status < 300 });

  const ready = http.get(`${baseUrl}/ready`);
  check(ready, { "ready 2xx": (r) => r.status >= 200 && r.status < 300 });

  sleep(1);
}
