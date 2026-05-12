import type { ParsedApiError } from '../../api/error';
import type { ConfigValidationIssue } from '../../types/systemConfig';

export type ToastState =
  | { type: 'success'; message: string }
  | { type: 'error'; error: ParsedApiError }
  | null;

export type RetryAction = 'load' | 'save' | null;

export interface SaveResult {
  success: boolean;
  message?: string;
  issues?: ConfigValidationIssue[];
}
