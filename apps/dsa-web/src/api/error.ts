import axios from 'axios';

/**
 * Numeric error codes mirrored from ``api/v1/schemas/envelope.py``
 * (``ApiErrorCode``). Treat the values as part of the wire contract.
 */
export const ApiErrorCode = {
  SUCCESS: 0,
  VALIDATION_ERROR: 1001,
  NOT_FOUND: 1002,
  UNAUTHORIZED: 1003,
  FORBIDDEN: 1004,
  HTTP_ERROR: 1099,
  RATE_LIMIT: 2001,
  NETWORK_ERROR: 2002,
  DATA_SOURCE_UNAVAILABLE: 2003,
  INTERNAL_ERROR: 9000,
  UNKNOWN_ERROR: 9999,
} as const;

export type ApiErrorCodeValue = typeof ApiErrorCode[keyof typeof ApiErrorCode];

export type ApiErrorCategory =
  // Categories backed by backend ``ApiErrorCode`` (preferred fast-path).
  | 'rate_limit'
  | 'upstream_network'
  | 'data_source_unavailable'
  | 'validation_error'
  | 'unauthorized'
  | 'not_found'
  | 'forbidden'
  | 'internal_error'
  // Semantic categories detected via response payload text (LLM / agent
  // specifics not represented in the numeric taxonomy).
  | 'agent_disabled'
  | 'missing_params'
  | 'llm_not_configured'
  | 'model_tool_incompatible'
  | 'invalid_tool_call'
  | 'upstream_llm_400'
  | 'upstream_timeout'
  | 'local_connection_failed'
  | 'http_error'
  | 'unknown';

const CODE_CATEGORY: Record<number, ApiErrorCategory> = {
  [ApiErrorCode.RATE_LIMIT]: 'rate_limit',
  [ApiErrorCode.NETWORK_ERROR]: 'upstream_network',
  [ApiErrorCode.DATA_SOURCE_UNAVAILABLE]: 'data_source_unavailable',
  [ApiErrorCode.VALIDATION_ERROR]: 'validation_error',
  [ApiErrorCode.UNAUTHORIZED]: 'unauthorized',
  [ApiErrorCode.NOT_FOUND]: 'not_found',
  [ApiErrorCode.FORBIDDEN]: 'forbidden',
  [ApiErrorCode.HTTP_ERROR]: 'http_error',
  [ApiErrorCode.INTERNAL_ERROR]: 'internal_error',
  [ApiErrorCode.UNKNOWN_ERROR]: 'unknown',
};

const CODE_TITLE: Record<number, string> = {
  [ApiErrorCode.RATE_LIMIT]: '请求频率受限',
  [ApiErrorCode.NETWORK_ERROR]: '服务端无法访问外部依赖',
  [ApiErrorCode.DATA_SOURCE_UNAVAILABLE]: '数据源暂时不可用',
  [ApiErrorCode.VALIDATION_ERROR]: '请求参数校验失败',
  [ApiErrorCode.UNAUTHORIZED]: '需要登录',
  [ApiErrorCode.NOT_FOUND]: '资源不存在',
  [ApiErrorCode.FORBIDDEN]: '没有权限访问该资源',
  [ApiErrorCode.HTTP_ERROR]: '请求失败',
  [ApiErrorCode.INTERNAL_ERROR]: '服务端错误',
  [ApiErrorCode.UNKNOWN_ERROR]: '未知错误',
};

export interface ParsedApiError {
  title: string;
  message: string;
  rawMessage: string;
  status?: number;
  category: ApiErrorCategory;
}

type ResponseLike = {
  status?: number;
  data?: unknown;
  statusText?: string;
};

type ErrorCarrier = {
  response?: ResponseLike;
  code?: string;
  message?: string;
  parsedError?: ParsedApiError;
  cause?: unknown;
};

type CreateParsedApiErrorOptions = {
  title: string;
  message: string;
  rawMessage?: string;
  status?: number;
  category?: ApiErrorCategory;
};

/**
 * Context passed to every semantic-rule predicate. Pre-computed once per
 * parseApiError call so individual rules stay declarative.
 */
interface MatchContext {
  matchText: string;
  status?: number;
  code?: string;
}

interface SemanticRule {
  category: ApiErrorCategory;
  title: string;
  message: string;
  match: (ctx: MatchContext) => boolean;
}

/**
 * Ordered list of semantic classifiers. Order matters: the first rule whose
 * `match` returns true wins. Each rule maps a heuristic over the error text
 * to a user-facing title/message + machine-readable category. Adding a new
 * detected scenario means appending one entry here, not another if-block.
 */
const SEMANTIC_RULES: SemanticRule[] = [
  {
    category: 'agent_disabled',
    title: 'Agent 模式未开启',
    message: '当前功能依赖 Agent 模式，请先开启后再重试。',
    match: ({ matchText }) =>
      includesAny(matchText, ['agent mode is not enabled', 'agent_mode']),
  },
  {
    category: 'missing_params',
    title: '请求缺少必要参数',
    message: '请先补充股票代码或必要输入后再试。',
    match: ({ matchText }) =>
      includesAny(matchText, ['stock_code', 'stock_codes']) &&
      includesAny(matchText, ['必须提供 stock_code 或 stock_codes', 'missing', 'required']),
  },
  {
    category: 'llm_not_configured',
    title: '系统没有配置可用的 LLM 模型',
    message: '请先在系统设置中配置主模型、可用渠道或相关 API Key 后再重试。',
    match: ({ matchText }) =>
      (includesAny(matchText, ['all llm models failed']) &&
        includesAny(matchText, ['last error: none'])) ||
      includesAny(matchText, [
        'no llm configured',
        'litellm_model not configured',
        'ai analysis will be unavailable',
      ]),
  },
  {
    category: 'model_tool_incompatible',
    title: '当前模型不兼容工具调用',
    message: '当前模型不适合 Agent / 工具调用场景，请更换支持工具调用的模型后重试。',
    match: ({ matchText }) =>
      includesAny(matchText, [
        'tool call',
        'function call',
        'does not support tools',
        'tools is not supported',
        'reasoning',
      ]),
  },
  {
    category: 'invalid_tool_call',
    title: '上游模型返回的数据结构不完整',
    message: '上游模型返回的工具调用结构不符合要求，请更换模型或关闭相关推理模式后重试。',
    match: ({ matchText }) =>
      includesAny(matchText, [
        'thought_signature',
        'missing function',
        'missing tool',
        'invalid tool call',
        'invalid function call',
      ]),
  },
  {
    category: 'upstream_timeout',
    title: '连接上游服务超时',
    message: '服务端访问外部依赖时超时，请稍后重试，或检查当前网络与代理设置。',
    // ECONNABORTED is an axios-level signal with no backend envelope.
    match: ({ matchText, code }) =>
      includesAny(matchText, ['timeout', 'timed out', 'read timeout', 'connect timeout']) ||
      code === 'ECONNABORTED',
  },
];

// Runs after the semantic rules above (those capture sub-cases the numeric
// taxonomy cannot distinguish).
const POST_ENVELOPE_RULES: SemanticRule[] = [
  {
    category: 'upstream_llm_400',
    title: '上游模型接口拒绝了当前请求',
    message: '本地服务正常，但上游模型接口拒绝了请求，请检查模型名称、参数格式或工具调用兼容性。',
    match: ({ matchText, status }) => {
      const hasLlmProviderHint = includesAny(matchText, [
        'chat/completions',
        'generativelanguage',
        'openai',
        'gemini',
        'dashscope',
        'anthropic',
      ]);
      return (status === 400 || includesAny(matchText, ['bad request'])) && hasLlmProviderHint;
    },
  },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function pickString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function stringifyValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function getResponse(error: unknown): ResponseLike | undefined {
  if (!isRecord(error)) return undefined;
  const response = (error as ErrorCarrier).response;
  return response && typeof response === 'object' ? response : undefined;
}

function getErrorCode(error: unknown): string | undefined {
  return isRecord(error) && typeof (error as ErrorCarrier).code === 'string'
    ? (error as ErrorCarrier).code
    : undefined;
}

function getErrorMessage(error: unknown): string | null {
  if (typeof error === 'string') return error.trim() || null;
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  if (isRecord(error) && typeof (error as ErrorCarrier).message === 'string') {
    return (error as ErrorCarrier).message?.trim() || null;
  }
  return null;
}

function getCauseMessage(error: unknown): string | null {
  if (!isRecord(error)) return null;
  return getErrorMessage((error as ErrorCarrier).cause);
}

function buildMatchText(parts: Array<string | undefined | null>): string {
  return parts
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .join(' | ')
    .toLowerCase();
}

function includesAny(haystack: string, needles: string[]): boolean {
  return needles.some((needle) => haystack.includes(needle.toLowerCase()));
}

function extractValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  const parts = detail
    .map((item) => {
      if (!isRecord(item)) return stringifyValue(item);
      const location = Array.isArray(item.loc)
        ? item.loc.map((segment) => String(segment)).join('.')
        : null;
      const message = pickString(item.msg, item.message, item.error);
      if (!location && !message) return stringifyValue(item);
      return [location, message].filter(Boolean).join(': ');
    })
    .filter((entry): entry is string => Boolean(entry));
  return parts.length > 0 ? parts.join('; ') : null;
}

export function extractErrorPayloadText(data: unknown): string | null {
  if (typeof data === 'string') return data.trim() || null;
  if (Array.isArray(data)) return extractValidationDetail(data) ?? stringifyValue(data);
  if (!isRecord(data)) return stringifyValue(data);

  const detail = data.detail;
  if (isRecord(detail)) {
    return (
      pickString(detail.message, detail.error) ??
      extractValidationDetail(detail.detail) ??
      stringifyValue(detail)
    );
  }
  return (
    pickString(detail, data.message, data.error, data.title, data.reason, data.description, data.msg) ??
    extractValidationDetail(detail) ??
    stringifyValue(data)
  );
}

export function createParsedApiError(options: CreateParsedApiErrorOptions): ParsedApiError {
  return {
    title: options.title,
    message: options.message,
    rawMessage: options.rawMessage?.trim() || options.message,
    status: options.status,
    category: options.category ?? 'unknown',
  };
}

export function isParsedApiError(value: unknown): value is ParsedApiError {
  return (
    isRecord(value) &&
    typeof value.title === 'string' &&
    typeof value.message === 'string' &&
    typeof value.rawMessage === 'string' &&
    typeof value.category === 'string'
  );
}

export function isApiRequestError(
  value: unknown,
): value is Error & ErrorCarrier & { parsedError: ParsedApiError } {
  return (
    value instanceof Error &&
    isRecord(value) &&
    isParsedApiError((value as ErrorCarrier).parsedError)
  );
}

export function formatParsedApiError(parsed: ParsedApiError): string {
  if (!parsed.title.trim()) return parsed.message;
  if (parsed.title === parsed.message) return parsed.title;
  return `${parsed.title}：${parsed.message}`;
}

export function getParsedApiError(error: unknown): ParsedApiError {
  if (isParsedApiError(error)) return error;
  if (isRecord(error) && isParsedApiError((error as ErrorCarrier).parsedError)) {
    return (error as ErrorCarrier).parsedError as ParsedApiError;
  }
  return parseApiError(error);
}

export function createApiError(
  parsed: ParsedApiError,
  extra: { response?: ResponseLike; code?: string; cause?: unknown } = {},
): Error & ErrorCarrier & { status?: number; category: ApiErrorCategory; rawMessage: string } {
  const apiError = new Error(formatParsedApiError(parsed)) as Error & ErrorCarrier & {
    status?: number;
    category: ApiErrorCategory;
    rawMessage: string;
  };
  apiError.name = 'ApiRequestError';
  apiError.parsedError = parsed;
  apiError.response = extra.response;
  apiError.code = extra.code;
  apiError.status = parsed.status;
  apiError.category = parsed.category;
  apiError.rawMessage = parsed.rawMessage;
  if (extra.cause !== undefined) apiError.cause = extra.cause;
  return apiError;
}

export function attachParsedApiError(error: unknown): ParsedApiError {
  const parsed = parseApiError(error);
  if (isRecord(error)) (error as ErrorCarrier).parsedError = parsed;
  if (error instanceof Error) {
    error.name = 'ApiRequestError';
    error.message = formatParsedApiError(parsed);
  }
  return parsed;
}

export function isLocalConnectionFailure(error: unknown): boolean {
  return parseApiError(error).category === 'local_connection_failed';
}

function extractEnvelopeCode(data: unknown): number | null {
  if (!isRecord(data)) return null;
  const code = (data as { code?: unknown }).code;
  return typeof code === 'number' ? code : null;
}

function extractEnvelopeMessage(data: unknown): string | null {
  if (!isRecord(data)) return null;
  const message = (data as { message?: unknown }).message;
  return typeof message === 'string' && message.trim() ? message.trim() : null;
}

function applyRules(
  rules: SemanticRule[],
  ctx: MatchContext,
  rawMessage: string,
): ParsedApiError | null {
  for (const rule of rules) {
    if (rule.match(ctx)) {
      return createParsedApiError({
        title: rule.title,
        message: rule.message,
        rawMessage,
        status: ctx.status,
        category: rule.category,
      });
    }
  }
  return null;
}

export function parseApiError(error: unknown): ParsedApiError {
  const response = getResponse(error);
  const status = response?.status;
  const payloadText = extractErrorPayloadText(response?.data);
  const errorMessage = getErrorMessage(error);
  const causeMessage = getCauseMessage(error);
  const code = getErrorCode(error);
  const rawMessage =
    pickString(payloadText, response?.statusText, errorMessage, causeMessage, code) ??
    '请求未成功完成，请稍后重试。';
  const matchText = buildMatchText([rawMessage, errorMessage, causeMessage, code, response?.statusText]);
  const ctx: MatchContext = { matchText, status, code };

  // 1) Semantic rules first — capture LLM/agent sub-cases the numeric
  //    taxonomy cannot distinguish.
  const semanticMatch = applyRules(SEMANTIC_RULES, ctx, rawMessage);
  if (semanticMatch) return semanticMatch;

  // 2) Envelope-code fast-path for categories backed by the numeric taxonomy.
  const envelopeCode = extractEnvelopeCode(response?.data);
  if (envelopeCode !== null && envelopeCode !== ApiErrorCode.SUCCESS) {
    const category = CODE_CATEGORY[envelopeCode] ?? 'unknown';
    const title = CODE_TITLE[envelopeCode] ?? '请求失败';
    return createParsedApiError({
      title,
      message: extractEnvelopeMessage(response?.data) ?? title,
      rawMessage,
      status,
      category,
    });
  }

  // 3) Post-envelope rules — e.g. 400 from an LLM provider that did not use
  //    the envelope (raw upstream proxy responses).
  const postMatch = applyRules(POST_ENVELOPE_RULES, ctx, rawMessage);
  if (postMatch) return postMatch;

  // 4) Local connection failure (no response object at all).
  const localConnectionFailed =
    !response &&
    (includesAny(matchText, [
      'fetch failed',
      'failed to fetch',
      'network error',
      'connection refused',
      'econnrefused',
    ]) ||
      code === 'ERR_NETWORK' ||
      code === 'ECONNREFUSED');
  if (localConnectionFailed) {
    return createParsedApiError({
      title: '无法连接到本地服务',
      message: '浏览器当前无法连接到本地 Web 服务，请检查服务是否启动、监听地址是否正确、端口是否开放。',
      rawMessage,
      status,
      category: 'local_connection_failed',
    });
  }

  // 5) Generic HTTP fallback.
  if (payloadText || status) {
    return createParsedApiError({
      title: '请求失败',
      message: payloadText ?? `请求未成功完成（HTTP ${status}）。`,
      rawMessage,
      status,
      category: 'http_error',
    });
  }

  return createParsedApiError({
    title: '请求失败',
    message: rawMessage,
    rawMessage,
    status,
    category: 'unknown',
  });
}

export function toApiErrorMessage(error: unknown, fallback = '请求未成功完成，请稍后重试。'): string {
  const parsed = getParsedApiError(error);
  const message = formatParsedApiError(parsed);
  return message.trim() || fallback;
}

export function isAxiosApiError(error: unknown): boolean {
  return axios.isAxiosError(error);
}
