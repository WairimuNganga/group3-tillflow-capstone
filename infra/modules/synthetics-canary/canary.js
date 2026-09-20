/**
 * CloudWatch Synthetics — public edge probe (ADR-008 probe paths).
 * HEALTH_URL and READY_URL are injected by Terraform (API Gateway /v1/...).
 */
const synthetics = require("Synthetics");
const log = require("SyntheticsLogger");

async function expect200(url, label) {
  const response = await synthetics.getRequest({ url });
  log.info(`${label} HTTP ${response.statusCode} ${url}`);
  if (response.statusCode !== 200) {
    throw new Error(`${label} returned ${response.statusCode}`);
  }
}

exports.handler = async () => {
  const healthUrl = process.env.HEALTH_URL;
  const readyUrl = process.env.READY_URL;
  if (!healthUrl || !readyUrl) {
    throw new Error("HEALTH_URL and READY_URL must be set");
  }

  await synthetics.executeStep("health", async () => {
    await expect200(healthUrl, "health");
  });
  await synthetics.executeStep("ready", async () => {
    await expect200(readyUrl, "ready");
  });
};
