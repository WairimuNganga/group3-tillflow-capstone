import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = (__ENV.API_ENDPOINT || "").replace(/\/$/, "");
if (!baseUrl) {
  throw new Error("Set API_ENDPOINT (terraform api_endpoint, includes /v1)");
}

// Stepped load — edge probes only (RED counters excluded on /health,/ready per ADR-008).
// Use for capacity envelope; add business routes when product paths are stable.
export const options = {
  stages: [
    { duration: "2m", target: 5 },
    { duration: "5m", target: 10 },
    { duration: "5m", target: 20 },
    { duration: "2m", target: 0 },
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

  sleep(0.5);
}
