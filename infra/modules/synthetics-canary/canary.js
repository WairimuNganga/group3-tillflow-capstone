/**
 * CloudWatch Synthetics — public edge probe (ADR-008 probe paths).
 * HEALTH_URL and READY_URL are injected by Terraform (API Gateway /v1/...).
 */
const http = require("http");
const https = require("https");
const synthetics = require("@aws/synthetics-puppeteer");
const log = require("@aws/synthetics-logger");

async function expect200(url, label) {
  await synthetics.executeStep(label, async () => {
    const statusCode = await requestStatusCode(url);
    log.info(`${label} HTTP ${statusCode} ${url}`);
    if (statusCode !== 200) {
      throw new Error(`${label} returned ${statusCode}`);
    }
  });
}

function requestStatusCode(url) {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const client = parsedUrl.protocol === "https:" ? https : http;
    const request = client.request(
      parsedUrl,
      {
        method: "GET",
        timeout: 30000,
        headers: {
          "User-Agent": "devops-g3-edge-health-canary",
        },
      },
      (response) => {
        response.resume();
        response.on("end", () => resolve(response.statusCode));
      },
    );

    request.on("timeout", () => {
      request.destroy(new Error(`${url} timed out`));
    });
    request.on("error", reject);
    request.end();
  });
}

exports.handler = async () => {
  const healthUrl = process.env.HEALTH_URL;
  const readyUrl = process.env.READY_URL;
  if (!healthUrl || !readyUrl) {
    throw new Error("HEALTH_URL and READY_URL must be set");
  }

  await expect200(healthUrl, "health");
  await expect200(readyUrl, "ready");
};
