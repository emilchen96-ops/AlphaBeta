import { apiRequest } from "./client";
import type {
  InformationDetail,
  InformationPage,
  InformationSource,
} from "../types/information";

const jsonHeaders = { "Content-Type": "application/json" };

export const getInformationSources = () =>
  apiRequest<InformationSource[]>("/api/v1/information-sources");

export function addManualInformation(body: Record<string, unknown>) {
  return apiRequest<InformationDetail>("/api/v1/information/manual", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body),
  });
}

function page(
  path: string,
  params: Record<string, string | number | undefined>,
) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return apiRequest<InformationPage>(`${path}?${query}`);
}

export const getInformationItems = (
  params: Record<string, string | number | undefined>,
) => page("/api/v1/information-items", params);

export const getInformationItem = (id: string) =>
  apiRequest<InformationDetail>(`/api/v1/information-items/${id}`);

export const getMarketEvents = (
  params: Record<string, string | number | undefined>,
) => page("/api/v1/market-events", params);

export const getMarketEvent = (id: string) =>
  apiRequest<InformationDetail>(`/api/v1/market-events/${id}`);
