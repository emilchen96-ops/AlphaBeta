import fs from "node:fs/promises";

const target = await fetch(
  "http://127.0.0.1:9223/json/new?http://localhost:5173/orders",
  { method: "PUT" },
).then((response) => response.json());
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});
let sequence = 0;
const pending = new Map();
const consoleErrors = [];
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error)));
    else resolve(message.result);
  }
  if (message.method === "Runtime.exceptionThrown") {
    const details = message.params.exceptionDetails;
    const sourceUrl =
      details.url ?? details.stackTrace?.callFrames?.[0]?.url ?? "";
    if (sourceUrl.includes("localhost:5173")) {
      consoleErrors.push(
        JSON.stringify({
          text: details.text,
          description: details.exception?.description,
          url: sourceUrl,
          lineNumber: details.lineNumber,
          columnNumber: details.columnNumber,
        }),
      );
    }
  }
  if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
    consoleErrors.push(message.params.entry.text);
  }
  if (
    message.method === "Runtime.consoleAPICalled" &&
    message.params.type === "error"
  ) {
    consoleErrors.push(message.params.args.map((item) => item.value ?? item.description).join(" "));
  }
};

function command(method, params = {}) {
  const id = ++sequence;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(
      result.exceptionDetails.exception?.description ?? result.exceptionDetails.text,
    );
  }
  return result.result.value;
}

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
await command("Page.enable");
await command("Runtime.enable");
await command("Log.enable");
await pause(3000);
if (consoleErrors.length) {
  throw new Error(`browser startup errors: ${consoleErrors.join(' | ')}`);
}

const heading = await evaluate(`document.querySelector('h2')?.textContent?.trim()`);
if (heading !== "订单中心") throw new Error(`unexpected heading: ${heading}`);

await evaluate(`(() => {
  const button = [...document.querySelectorAll('button')].find((item) => item.textContent.includes('创建订单'));
  button.click();
})()`);
await pause(500);
const modalTitle = await evaluate(`document.querySelector('.ant-modal-title')?.textContent?.trim()`);
if (modalTitle !== "创建人工订单意图") throw new Error(`create modal missing: ${modalTitle}`);

await evaluate(`(() => {
  const setValue = (name, value) => {
    const input = document.querySelector('input[id$="' + name + '"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  setValue('requested_quantity', '1000');
  setValue('limit_price', '9.10');
})()`);

async function selectForm(fieldName, optionFragment) {
  await evaluate(`(() => {
    const input = document.querySelector('input[id$="${fieldName}"]');
    const select = input.closest('.ant-select');
    select.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    select.click();
  })()`);
  await pause(300);
  await evaluate(`(() => {
    const option = [...document.querySelectorAll('.ant-select-item-option')].find((node) => node.textContent.includes(${JSON.stringify(optionFragment)}));
    if (!option) throw new Error('options=' + [...document.querySelectorAll('.ant-select-item-option')].map((node) => node.textContent).join('|'));
    option.click();
  })()`);
  await pause(300);
}

await selectForm("account_id", "DEMO-001");
await selectForm("instrument_id", "600000.SSE");
await evaluate(`(() => {
  const wrap = [...document.querySelectorAll('.ant-modal-wrap')].find((node) => getComputedStyle(node).display !== 'none');
  [...wrap.querySelectorAll('button')].at(-1).click();
})()`);
await pause(1500);
if (consoleErrors.length) {
  throw new Error(`browser first-create errors: ${consoleErrors.join(' | ')}`);
}

await evaluate(`(() => {
  const row = document.querySelector('.ant-table-tbody .ant-table-row');
  const button = [...row.querySelectorAll('button')].find((item) => item.textContent.includes('人工确认'));
  button.click();
})()`);
await pause(500);
const confirmWarning = await evaluate(`(() => {
  const wrap = [...document.querySelectorAll('.ant-modal-wrap')].find((node) => getComputedStyle(node).display !== 'none');
  return wrap?.querySelector('.ant-alert-description')?.textContent;
})()`);
if (!confirmWarning?.includes("Outbox PENDING")) throw new Error("confirmation warning missing");
await evaluate(`(() => {
  const wrap = [...document.querySelectorAll('.ant-modal-wrap')].find((node) => getComputedStyle(node).display !== 'none');
  [...wrap.querySelectorAll('button')].at(-1).click();
})()`);
await pause(1500);

await evaluate(`(() => {
  const row = [...document.querySelectorAll('.ant-table-tbody .ant-table-row')].find((item) => item.textContent.includes('本地指令事实已创建'));
  const button = row.querySelector('button');
  button.click();
})()`);
await pause(1000);
const drawerText = await evaluate(`document.querySelector('.ant-drawer')?.textContent`);
if (!drawerText?.includes("Timeline") || !drawerText?.includes("指令待发布")) {
  const bodyText = await evaluate(`document.body.innerText`);
  throw new Error(`detail/timeline/command summary missing: drawer=${drawerText}; body=${bodyText}`);
}

const screenshot = await command("Page.captureScreenshot", {
  format: "png",
  captureBeyondViewport: true,
});
await fs.writeFile("outputs/m05-orders-acceptance.png", Buffer.from(screenshot.data, "base64"));

await evaluate(`document.querySelector('.ant-drawer-close').click()`);
await pause(500);
await evaluate(`[...document.querySelectorAll('button')].find((item) => item.textContent.includes('创建订单')).click()`);
await pause(500);
await evaluate(`(() => {
  const setValue = (name, value) => {
    const input = document.querySelector('input[id$="' + name + '"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  setValue('requested_quantity', '1000');
  setValue('limit_price', '9.20');
})()`);
await selectForm("account_id", "DEMO-001");
await selectForm("instrument_id", "600000.SSE");
await evaluate(`(() => {
  const wrap = [...document.querySelectorAll('.ant-modal-wrap')].find((node) => getComputedStyle(node).display !== 'none');
  [...wrap.querySelectorAll('button')].at(-1).click();
})()`);
await pause(1500);
await evaluate(`(() => {
  const row = [...document.querySelectorAll('.ant-table-tbody .ant-table-row')].find((item) => item.textContent.includes('等待人工确认'));
  const button = row ? [...row.querySelectorAll('button')].at(-1) : undefined;
  if (!button) throw new Error('no cancellable order found: ' + document.body.innerText);
  button.click();
})()`);
await pause(1200);
const cancellationVerified = await evaluate(`[...document.querySelectorAll('.ant-table-tbody tr')].some((row) => row.textContent.includes('已取消'))`);
if (!cancellationVerified) throw new Error("browser cancellation was not reflected in the table");

if (consoleErrors.length) throw new Error(`browser console errors: ${consoleErrors.join(' | ')}`);
console.log(JSON.stringify({ heading, modalTitle, confirmWarning, detailVerified: true, cancellationVerified, consoleErrors }));
socket.close();
