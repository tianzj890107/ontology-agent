const NON_NUMERIC_HEADER_PATTERN = /(编码|编号|id$|_id$|code$|日期|时间|年份|月份|是否|is[A-Z])/i;
const MONEY_HEADER_PATTERN = /(金额|总额|含税|未税|单价|价格|成本|费用|收入|支出|利润|余额|预算|amount|price|cost|fee|revenue|expense|profit|balance|budget)/i;

function numericValue(value) {
  const raw = String(value ?? "").trim();
  const text = raw.replace(/[¥￥$€£]/g, "").replace(/,/g, "");
  if (!text || !/^[+-]?\d+(?:\.\d+)?$/.test(text)) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

export function isMoneyHeader(header = "") {
  return MONEY_HEADER_PATTERN.test(String(header || ""));
}

export function isNumericDisplayValue(value, header = "") {
  if (value === null || value === undefined || value === "") return false;
  if (NON_NUMERIC_HEADER_PATTERN.test(String(header || ""))) return false;
  return numericValue(value) !== null;
}

export function formatNumber(value, { currency = false, compact = false } = {}) {
  const number = numericValue(value);
  if (number === null) return String(value ?? "");
  const absolute = Math.abs(number);
  const sign = number < 0 ? "-" : "";
  const prefix = currency ? "¥" : "";

  // Compact notation is only for genuinely large amounts. Never render a
  // zero or a sub-unit value as 0万; use the normal amount representation.
  if (currency && compact && absolute >= 10000) {
    const wan = new Intl.NumberFormat("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(absolute / 10000);
    return `${sign}${prefix}${wan}万`;
  }

  const formatted = new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: currency ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(absolute);
  return `${sign}${prefix}${formatted}`;
}

export function formatDisplayValue(value, header = "") {
  if (!isNumericDisplayValue(value, header)) return String(value ?? "");
  return formatNumber(value, { currency: isMoneyHeader(header) });
}

export function formatCompactAmount(value) {
  return formatNumber(value, { currency: true, compact: true });
}
