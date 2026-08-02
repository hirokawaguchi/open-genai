import { useEffect, useState } from 'react';
import { teamApi } from '@/lib/fetcher';
import { GovAIFormUIJson } from '../types';

export type ExAppSchemaFeatures = {
  file_attach?: boolean;
};

type SchemaResponse = {
  placeholder: GovAIFormUIJson;
  features?: ExAppSchemaFeatures;
};

/**
 * AI アプリの入力フォーム定義(placeholder)と機能フラグ(features)を実行時に取得する。
 * Dify 連携アプリなどで、データ形式(JSON)未設定時に endpoint の /schema から
 * 入力スキーマを動的取得してフォームを生成したり、ファイル添付の可否を判定するために使う。
 */
export const useFetchExAppSchema = (teamId: string, exAppId: string, enabled: boolean) => {
  const [uiJson, setUiJson] = useState<GovAIFormUIJson>({});
  const [features, setFeatures] = useState<ExAppSchemaFeatures>({});
  // 初回レンダーで空フォームが一瞬出るのを防ぐ（effect より先に loading 表示）
  const [isLoading, setIsLoading] = useState(enabled);

  useEffect(() => {
    if (!enabled || !teamId || !exAppId) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    teamApi
      .post<SchemaResponse>('exapps/schema', { teamId, exAppId })
      .then((res) => {
        if (!cancelled) {
          setUiJson(res.data?.placeholder ?? {});
          setFeatures(res.data?.features ?? {});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUiJson({});
          setFeatures({});
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

  return { uiJson, features, isLoading };
};
