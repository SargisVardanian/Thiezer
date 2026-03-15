const API_ROOT = "https://api.telegram.org";

export async function callBotApi(token, method, payload = {}) {
  const response = await fetch(`${API_ROOT}/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });

  const body = await response.json();
  if (!body.ok) {
    throw new Error(`${method} failed: ${body.description ?? "Unknown error"}`);
  }

  return body.result;
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
