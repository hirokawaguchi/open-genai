import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type {
  ArbitrationItem,
  BatchSummary,
  CheckTask,
  DoccheckConfig,
  DoccheckOcrMode,
  DocumentDetail,
  DocumentSummary,
  FormTemplate,
  RegionTemplate,
  UserScore,
} from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useDoccheckConfig = () => {
  const { data, error, isLoading, mutate } = useSWR<DoccheckConfig>(
    'doccheck/config',
    async () => {
      try {
        return await teamApiFetcher<DoccheckConfig>('doccheck/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as DoccheckConfig | undefined;
          return {
            enabled: false,
            error: data?.error || errorMessage(e, '書類読取とチェックサービスに接続できません'),
          };
        }
        throw e;
      }
    },
    {
      revalidateOnFocus: true,
      shouldRetryOnError: false,
      // ダッシュボードの件数は操作後すぐ古くなりやすいので軽くポーリング
      refreshInterval: 15000,
    },
  );

  return {
    config: data,
    isLoading,
    unavailable: data?.enabled === false,
    mutate,
  };
};

export const useDoccheckTemplates = () => {
  const { data, error, isLoading, mutate } = useSWR<{ templates: FormTemplate[] }>(
    'doccheck/templates',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    templates: data?.templates ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'テンプレート取得に失敗しました') : null,
    mutate,
  };
};

export const useDoccheckDocuments = () => {
  const { data, error, isLoading, mutate } = useSWR<{ documents: DocumentSummary[] }>(
    'doccheck/documents',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    documents: data?.documents ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '書類一覧の取得に失敗しました') : null,
    mutate,
  };
};

export const useDoccheckScore = () => {
  const { data, mutate } = useSWR<UserScore>('doccheck/scores/me', teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  const { data: board } = useSWR<{ leaderboard: UserScore[] }>(
    'doccheck/scores/leaderboard',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    score: data,
    leaderboard: board?.leaderboard ?? [],
    mutate,
  };
};

export const useDoccheckBatches = () => {
  const { data, error, isLoading, mutate } = useSWR<{ batches: BatchSummary[] }>(
    'doccheck/batches',
    teamApiFetcher,
    { revalidateOnFocus: true, shouldRetryOnError: false, refreshInterval: 5000 },
  );
  return {
    batches: data?.batches ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'バッチ一覧の取得に失敗しました') : null,
    mutate,
  };
};

export const useDoccheckArbitration = (enabled = true) => {
  const { data, error, isLoading, mutate } = useSWR<{ items: ArbitrationItem[] }>(
    enabled ? 'doccheck/arbitration' : null,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    items: data?.items ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '裁定一覧の取得に失敗しました') : null,
    mutate,
  };
};

export const useDoccheckActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createBatch = useCallback(
    async (input: {
      name?: string;
      template_id: string;
      images: Array<{ data: string; name: string }>;
      pages_per_document?: number;
      auto_dispatch?: boolean;
      assignees?: number;
      dpi?: number;
    }) => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<BatchSummary>('doccheck/batches', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'バッチ投入に失敗しました'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const getBatch = useCallback(async (batchId: string) => {
    try {
      return await teamApiFetcher<BatchSummary>(
        `doccheck/batches/${encodeURIComponent(batchId)}`,
      );
    } catch (e) {
      setError(errorMessage(e, 'バッチ詳細の取得に失敗しました'));
      return null;
    }
  }, []);

  const dispatchBatch = useCallback(async (batchId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<BatchSummary>(
        `doccheck/batches/${encodeURIComponent(batchId)}/dispatch`,
        {},
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, 'バッチ配信に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const downloadBatchExport = useCallback(
    async (
      batchId: string,
      format: 'csv' | 'jsonl' | 'json' = 'csv',
      status = 'completed',
    ) => {
      setError(null);
      try {
        const { blob, disposition } = await teamApi.getBlob(
          `doccheck/batches/${encodeURIComponent(batchId)}/export`,
          { params: { format, status } },
        );
        const ascii = /filename="?([^";]+)"?/i.exec(disposition || '');
        const filename = ascii?.[1] ?? `doccheck_batch.${format}`;
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
        return true;
      } catch (e) {
        setError(errorMessage(e, 'エクスポートに失敗しました'));
        return false;
      }
    },
    [],
  );

  const seedDemo = useCallback(async (dispatch = true) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<DocumentDetail>('doccheck/demo/seed', { dispatch });
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, 'デモデータの投入に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const createTemplate = useCallback(
    async (input: {
      name: string;
      description?: string;
      regions?: RegionTemplate[];
      ocr_mode?: DoccheckOcrMode;
    }) => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<FormTemplate>('doccheck/templates', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'テンプレート作成に失敗しました'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const updateTemplateMeta = useCallback(
    async (templateId: string, input: { ocr_mode?: DoccheckOcrMode }) => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.put<FormTemplate>(
          `doccheck/templates/${encodeURIComponent(templateId)}`,
          input,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'テンプレート設定の保存に失敗しました'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const getTemplate = useCallback(async (templateId: string, includeSample = true) => {
    try {
      return await teamApiFetcher<FormTemplate>(
        `doccheck/templates/${encodeURIComponent(templateId)}${
          includeSample ? '?include_sample=1' : ''
        }`,
      );
    } catch (e) {
      setError(errorMessage(e, 'テンプレート取得に失敗しました'));
      return null;
    }
  }, []);

  const uploadSample = useCallback(async (templateId: string, dataUrl: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<FormTemplate>(
        `doccheck/templates/${encodeURIComponent(templateId)}/sample`,
        { data: dataUrl },
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '見本画像のアップロードに失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const saveRegions = useCallback(async (templateId: string, regions: RegionTemplate[]) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.put<FormTemplate>(
        `doccheck/templates/${encodeURIComponent(templateId)}/regions`,
        { regions },
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '領域の保存に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const deleteTemplate = useCallback(async (templateId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.delete<{ ok: boolean }>(
        `doccheck/templates/${encodeURIComponent(templateId)}`,
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, 'テンプレートの削除に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const createDocument = useCallback(
    async (input: {
      template_id: string;
      title: string;
      pages: string[];
      auto_dispatch?: boolean;
      assignees?: number;
    }) => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<DocumentDetail>('doccheck/documents', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '書類の投入に失敗しました'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const dispatch = useCallback(async (docId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<DocumentDetail>(
        `doccheck/documents/${encodeURIComponent(docId)}/dispatch`,
        {},
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '配信に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const deleteDocument = useCallback(async (docId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.delete<{ ok: boolean }>(
        `doccheck/documents/${encodeURIComponent(docId)}`,
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '書類の削除に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const deleteBatch = useCallback(async (batchId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.delete<{ ok: boolean }>(
        `doccheck/batches/${encodeURIComponent(batchId)}`,
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, 'バッチの削除に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const getDocument = useCallback(async (docId: string) => {
    try {
      return await teamApiFetcher<DocumentDetail>(
        `doccheck/documents/${encodeURIComponent(docId)}`,
      );
    } catch (e) {
      setError(errorMessage(e, '書類の取得に失敗しました'));
      return null;
    }
  }, []);

  const exportDocument = useCallback(async (docId: string) => {
    try {
      return await teamApiFetcher<Record<string, unknown>>(
        `doccheck/documents/${encodeURIComponent(docId)}/export`,
      );
    } catch (e) {
      setError(errorMessage(e, 'エクスポートに失敗しました'));
      return null;
    }
  }, []);

  const nextTask = useCallback(async () => {
    setError(null);
    try {
      const res = await teamApiFetcher<{ task: CheckTask | null; message?: string }>(
        'doccheck/queue/next',
      );
      return res;
    } catch (e) {
      setError(errorMessage(e, 'キュー取得に失敗しました'));
      return null;
    }
  }, []);

  const answerTask = useCallback(
    async (
      token: string,
      input: { answer_text: string; is_unreadable?: boolean; is_blank?: boolean },
    ) => {
      setSubmitting(true);
      setError(null);
      try {
        return await teamApi.post<Record<string, unknown>>(
          `doccheck/tasks/${encodeURIComponent(token)}/answer`,
          input,
        );
      } catch (e) {
        setError(errorMessage(e, '回答の送信に失敗しました'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const arbitrate = useCallback(
    async (regionId: string, adopted_text: string, is_blank = false) => {
    setSubmitting(true);
    setError(null);
    try {
      return await teamApi.post(
        `doccheck/arbitration/${encodeURIComponent(regionId)}`,
        { adopted_text, is_blank },
      );
    } catch (e) {
      setError(errorMessage(e, '裁定に失敗しました'));
      return null;
    } finally {
      setSubmitting(false);
    }
    },
    [],
  );

  return {
    submitting,
    error,
    setError,
    seedDemo,
    createBatch,
    getBatch,
    dispatchBatch,
    downloadBatchExport,
    createTemplate,
    updateTemplateMeta,
    getTemplate,
    uploadSample,
    saveRegions,
    deleteTemplate,
    createDocument,
    dispatch,
    deleteDocument,
    deleteBatch,
    getDocument,
    exportDocument,
    nextTask,
    answerTask,
    arbitrate,
  };
};

export const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('ファイル読み込みに失敗しました'));
    reader.readAsDataURL(file);
  });
