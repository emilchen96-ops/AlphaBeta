import type { ParameterGridValue } from "../types/strategies";

export function estimateCombinationCount(
  grid: Record<string, ParameterGridValue[]>,
) {
  return Object.values(grid).reduce(
    (total, values) => total * Math.max(values.length, 1),
    1,
  );
}
