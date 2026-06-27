import { useEffect, useState } from 'react';
import { teamApi } from '@/lib/fetcher';
import { GovAIFormUIJson } from '../types';

type SchemaResponse = {
  placeholder: GovAIFormUIJson;
};

/**
 * AI アプリの入力フォーム定義(placeholder)を実行時に取得する。
 * Dify 連携アプリなどで、データ形式(JSON)未設定時に endpoint の /schema から
 * 入力スキーマを動的取得してフォームを生成するために使う。
 */
export const useFetchExAppSchema = (teamId: string, exAppId: string, enabled: boolean) => {
  const [uiJson, setUiJson] = useState<GovAIFormUIJson>({});
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !teamId || !exAppId) {
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    teamApi
      .post<SchemaResponse>('exapps/schema', { teamId, exAppId })
      .then((res) => {
        if (!cancelled) {
          setUiJson(res.data?.placeholder ?? {});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUiJson({});
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [teamId, exAppId, enabled]);

  return { uiJson, isLoading };
};
