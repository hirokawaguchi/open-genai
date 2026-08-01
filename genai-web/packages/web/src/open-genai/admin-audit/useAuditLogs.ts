import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';
import type { AuditFilters, AuditQueryResult } from './types';

export const AUDIT_LOGS_KEY = 'admin/audit-logs';

/** YYYY-MM-DD（JST）を epoch ms へ。endOfDay=true なら当日 23:59:59.999（JST）。 */
const dateToMs = (date: string, endOfDay: boolean): number | undefined => {
  if (!date) {
    return undefined;
  }
  const suffix = endOfDay ? 'T23:59:59.999+09:00' : 'T00:00:00.000+09:00';
  const ms = Date.parse(`${date}${suffix}`);
  return Number.isNaN(ms) ? undefined : ms;
};

/** フィルタ＋offset を backend のクエリパラメータへ変換する。 */
const toParams = (
  filters: AuditFilters,
  offset: number,
): Record<string, string | number | undefined> => ({
  userId: filters.userId.trim() || undefined,
  action: filters.action && filters.action !== 'all' ? filters.action : undefined,
  q: filters.q.trim() || undefined,
  from: dateToMs(filters.fromDate, false),
  to: dateToMs(filters.toDate, true),
  limit: filters.limit,
  offset,
});

/** 監査ログを取得する（管理者限定 API）。フィルタ／offset が変わると再取得。 */
export const useAuditLogs = (filters: AuditFilters, offset: number) => {
  const params = toParams(filters, offset);
  const { data, error, isLoading, mutate } = useSWR<AuditQueryResult>(
    [AUDIT_LOGS_KEY, params],
    ([path, p]: [string, typeof params]) =>
      teamApi.get<AuditQueryResult>(path, { params: p }).then((res) => res.data),
    { revalidateOnFocus: false, keepPreviousData: true },
  );

  const forbidden = error instanceof ApiError && error.status === 403;

  return {
    result: data,
    total: data?.total ?? 0,
    items: data?.items ?? [],
    isLoading,
    forbidden,
    loadError:
      error && !forbidden
        ? '監査ログの取得に失敗しました。時間をおいて再度お試しください。'
        : null,
    mutate,
  };
};

/** 現在の from/to で JSONL をダウンロードする。 */
export const useAuditExport = (filters: AuditFilters) => {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportLogs = useCallback(async () => {
    setExporting(true);
    setExportError(null);
    try {
      const params = {
        from: dateToMs(filters.fromDate, false),
        to: dateToMs(filters.toDate, true),
      };
      const { blob } = await teamApi.getBlob(`${AUDIT_LOGS_KEY}/export`, { params });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'audit-logs.jsonl';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(
        e instanceof ApiError && e.status === 403
          ? 'エクスポートには管理者権限が必要です。'
          : 'エクスポートに失敗しました。時間をおいて再度お試しください。',
      );
    } finally {
      setExporting(false);
    }
  }, [filters.fromDate, filters.toDate]);

  return { exportLogs, exporting, exportError };
};
