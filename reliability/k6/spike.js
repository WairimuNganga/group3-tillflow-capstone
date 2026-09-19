import http from "k6/http";
import { check } from "k6";

const baseUrl = (__ENV.API_ENDPOINT || "").replace(/\/$/, "");
if (!baseUrl) {
  throw new Error("Set API_ENDPOINT to the dev API Gateway URL");
}

// Short burst to observe throttle + autoscaling (T1.3). Run off-hours with team aware.
export const options = {
  stages: [
    { duration: "10s", target: 5 },
    { duration: "20s", target: 30 },
    { duration: "10s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.2"],
  },
};

export default function () {
  const res = http.get(`${baseUrl}/health`);
  check(res, { "health not 5xx": (r) => r.status < 500 });
}
