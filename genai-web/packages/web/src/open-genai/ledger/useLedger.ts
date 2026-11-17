import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type { LedgerConfig, LedgerDef, LedgerField, LedgerRow } from './types';

const message = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useLedgerConfig = () => {
  const { data, isLoading } = useSWR<LedgerConfig>(
    'ledger/config',
    async () => {
      try {
        return await teamApiFetcher<LedgerConfig>('ledger/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as LedgerConfig | undefined;
          return { enabled: false, error: data?.error || message(e, '台帳に接続できません') };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    config: data,
    isLoading,
    unavailable: data?.enabled === false,
  };
};

export const useLedgers = (enabled: boolean) =>
  useSWR<{ ledgers: LedgerDef[] }>(enabled ? 'ledger/ledgers' : null, teamApiFetcher);

export const useLedger = (ledgerId: string | undefined) =>
  useSWR<LedgerDef>(ledgerId ? `ledger/ledgers/${ledgerId}` : null, teamApiFetcher);

export const useLedgerRows = (ledgerId: string | undefined, query: string) =>
  useSWR<{ rows: LedgerRow[] }>(
    ledgerId ? `ledger/ledgers/${ledgerId}/rows?${query}` : null,
    teamApiFetcher,
  );

export const useLedgerRow = (rowId: string | undefined) =>
  useSWR<LedgerRow>(rowId ? `ledger/rows/${rowId}` : null, teamApiFetcher);

export const ledgerError = message;

export const saveLedger = async (body: {
  name: string;
  statuses: string[];
  grants: { team_id: string; role: string }[];
  fields?: LedgerField[];
}) => {
  const res = await teamApi.post<LedgerDef>('ledger/ledgers', body);
  return res.data;
};

export const deleteLedger = async (ledgerId: string) => {
  await teamApi.post(`ledger/ledgers/${ledgerId}/delete`, {});
};

export const patchLedger = async (ledgerId: string, body: Partial<LedgerDef>) => {
  const res = await teamApi.patch<LedgerDef>(`ledger/ledgers/${ledgerId}`, body);
  return res.data;
};

export const saveRow = async (ledgerId: string, body: Record<string, unknown>) => {
  const res = await teamApi.post<LedgerRow>(`ledger/ledgers/${ledgerId}/rows`, body);
  return res.data;
};

export const updateRow = async (rowId: string, body: Record<string, unknown>) => {
  const res = await teamApi.post<LedgerRow>(`ledger/rows/${rowId}`, body);
  return res.data;
};
