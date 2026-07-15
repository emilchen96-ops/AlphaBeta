import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { AppProviders } from "../src/app/providers";
import { routes } from "../src/app/router";

export const healthyStatus = {
  api: "online",
  postgresql: "online",
  redis: "online",
  environment: "development",
  version: "0.1.0",
  server_time: "2026-07-15T08:00:00+00:00",
  correlation_id: "test-correlation-id",
};

export function mockStatusSuccess() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(healthyStatus), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "X-Correlation-ID": "test-id",
        },
      }),
    ),
  );
}

export function renderRoute(initialEntry = "/") {
  const router = createMemoryRouter(routes, { initialEntries: [initialEntry] });
  return render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}
