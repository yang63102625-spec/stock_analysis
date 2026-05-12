import type { SystemConfigItem } from '../../types/systemConfig';

export const CATEGORY_DISPLAY_ORDER: Record<string, number> = {
  base: 10,
  ai_model: 20,
  data_source: 30,
  notification: 40,
  system: 50,
  backtest: 60,
  uncategorized: 99,
};

export function sortItemsByOrder(items: SystemConfigItem[]): SystemConfigItem[] {
  return [...items].sort((a, b) => {
    const left = a.schema?.displayOrder ?? 9999;
    const right = b.schema?.displayOrder ?? 9999;
    if (left !== right) return left - right;
    return a.key.localeCompare(b.key);
  });
}

export function isMultiValueSchema(schema: SystemConfigItem['schema'] | undefined): boolean {
  const validation = (schema?.validation ?? {}) as Record<string, unknown>;
  return Boolean(validation.multiValue ?? validation.multi_value);
}

export function normalizeFieldValue(value: string, schema: SystemConfigItem['schema'] | undefined): string {
  if (!isMultiValueSchema(schema)) return value;
  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .join(',');
}
