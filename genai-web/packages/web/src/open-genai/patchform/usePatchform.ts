import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import { lookupPostalDirect } from './runtime/postalLookup';
import type {
  AssistGenerateResult,
  AssistInviteResult,
  AuditEvent,
  FormConfig,
  FormDefinition,
  FormDetail,
  FormSummary,
  FormVisibility,
  IdentityMode,
  Submission,
  UploadedFile,
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

export const usePatchformConfig = () => {
  const { data, error, isLoading } = useSWR<FormConfig>(
    'patchform/config',
    async () => {
      try {
        return await teamApiFetcher<FormConfig>('patchform/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as FormConfig | undefined;
          return {
            enabled: false,
            error: data?.error || errorMessage(e, 'フォームサービスに接続できません'),
          };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    config: data,
    isLoading,
    loadError: error ? 'フォームの設定取得に失敗しました。時間をおいて再度お試しください。' : null,
    unavailable: data?.enabled === false,
  };
};

export const usePatchformList = () => {
  const { data, error, isLoading, mutate } = useSWR<{ forms: FormSummary[] }>(
    'patchform/forms',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    forms: data?.forms ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'フォーム一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformDetail = (formId: string | undefined) => {
  const key = formId ? `patchform/forms/${encodeURIComponent(formId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<FormDetail>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    form: data ?? null,
    isLoading,
    loadError: error ? errorMessage(error, 'フォームの取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformSubmissions = (formId: string | undefined) => {
  const key = formId ? `patchform/forms/${encodeURIComponent(formId)}/submissions` : null;
  const { data, error, isLoading, mutate } = useSWR<{ submissions: Submission[] }>(
    key,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    submissions: data?.submissions ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '回答一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(
    async (input: {
      title: string;
      description?: string;
      visibility?: FormVisibility;
      definition?: FormDefinition;
      pin?: string;
    }): Promise<FormDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<FormDetail>('patchform/forms', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'フォームの作成に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const update = useCallback(
    async (
      formId: string,
      input: {
        title?: string;
        description?: string;
        visibility?: FormVisibility;
        definition?: FormDefinition;
        pin?: string;
        retention_days?: number;
        allow_draft?: boolean;
        allow_multiple?: boolean;
        identity_mode?: IdentityMode;
        editor_user_ids?: string[];
        viewer_user_ids?: string[];
      },
    ): Promise<FormDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.put<FormDetail>(
          `patchform/forms/${encodeURIComponent(formId)}`,
          input,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'フォームの更新に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const setStatus = useCallback(async (formId: string, status: string): Promise<FormDetail | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<FormDetail>(
        `patchform/forms/${encodeURIComponent(formId)}/status`,
        { status },
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '状態の変更に失敗しました。'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const remove = useCallback(async (formId: string): Promise<boolean> => {
    setSubmitting(true);
    setError(null);
    try {
      await teamApi.delete(`patchform/forms/${encodeURIComponent(formId)}`);
      return true;
    } catch (e) {
      setError(errorMessage(e, 'フォームの削除に失敗しました。'));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const submitAnswers = useCallback(
    async (
      formId: string,
      input: {
        answers: Record<string, unknown>;
        submitter_name?: string;
        is_draft?: boolean;
        resume_token?: string;
      },
    ): Promise<{ receipt_code?: string; is_draft?: boolean } | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<{ receipt_code?: string; is_draft?: boolean }>(
          `patchform/forms/${encodeURIComponent(formId)}/submissions`,
          input,
        );
        return res.data ?? {};
      } catch (e) {
        setError(errorMessage(e, input.is_draft ? '下書きの保存に失敗しました。' : '回答の送信に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const loadDraft = useCallback(async (formId: string) => {
    try {
      const res = await teamApi.get<{
        answers?: Record<string, unknown>;
        receipt_code?: string | null;
        submitter_name?: string | null;
      }>(`patchform/forms/${encodeURIComponent(formId)}/draft`);
      return res.data ?? null;
    } catch {
      return null;
    }
  }, []);

  const setWithdrawn = useCallback(
    async (formId: string, submissionId: string, withdrawn: boolean): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        await teamApi.post(
          `patchform/forms/${encodeURIComponent(formId)}/submissions/${encodeURIComponent(submissionId)}/withdraw`,
          { withdrawn },
        );
        return true;
      } catch (e) {
        setError(errorMessage(e, withdrawn ? '取下げに失敗しました。' : '取下げの取消に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const revealSubmission = useCallback(async (formId: string, submissionId: string) => {
    try {
      const res = await teamApi.get<Submission>(
        `patchform/forms/${encodeURIComponent(formId)}/submissions/${encodeURIComponent(submissionId)}`,
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '個人番号の表示に失敗しました。'));
      return null;
    }
  }, []);

  return {
    create,
    update,
    setStatus,
    remove,
    submitAnswers,
    loadDraft,
    setWithdrawn,
    revealSubmission,
    submitting,
    error,
    setError,
  };
};

export const usePatchformAudit = (formId: string | undefined) => {
  const key = formId ? `patchform/forms/${encodeURIComponent(formId)}/audit` : null;
  const { data, error, isLoading, mutate } = useSWR<{ events: AuditEvent[] }>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    events: data?.events ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '監査ログの取得に失敗しました。') : null,
    mutate,
  };
};

const parseFilename = (disposition: string | null): string | null => {
  if (!disposition) return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      return utf8[1];
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(disposition);
  return ascii?.[1] ?? null;
};

export const downloadPatchformCsv = async (
  formId: string,
  format: 'csv' | 'jsonl' = 'csv',
  reveal = false,
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/forms/${encodeURIComponent(formId)}/export`,
    { params: { format, ...(reveal ? { reveal: '1' } : {}) } },
  );
  const filename = parseFilename(disposition) ?? `patchform_${formId}.${format}`;
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};

export const usePatchformAssist = () => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(
    async (input: {
      text: string;
      visibility?: FormVisibility;
      definition?: FormDefinition;
    }): Promise<AssistGenerateResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<AssistGenerateResult>('patchform/assist/generate', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'フォームの生成に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const draftInvite = useCallback(
    async (input: { title: string; public_url: string; tone?: string }): Promise<AssistInviteResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<AssistInviteResult>('patchform/assist/invite', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '案内文の作成に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return { generate, draftInvite, busy, error, setError };
};

const fileToDataUrl = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

export const lookupPatchformPostal = async (
  zip: string,
): Promise<{ prefecture?: string; city?: string; street?: string } | null> => {
  try {
    const res = await teamApi.get<{ prefecture?: string; city?: string; street?: string }>(
      'patchform/lookup/postal',
      { params: { zip } },
    );
    return res.data ?? null;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 502 || e.status === 503)) {
      return lookupPostalDirect(zip);
    }
    throw new Error(errorMessage(e, '住所の検索に失敗しました。'));
  }
};

export const lookupPatchformCorporate = async (
  number: string,
): Promise<{ company_name?: string } | null> => {
  try {
    const res = await teamApi.get<{ company_name?: string }>('patchform/lookup/corporate', {
      params: { number },
    });
    return res.data ?? null;
  } catch (e) {
    if (e instanceof ApiError && e.status >= 500) {
      return { company_name: '' };
    }
    throw new Error(errorMessage(e, '法人番号の検索に失敗しました。'));
  }
};

export const extractPatchformFile = async (
  kind: 'image' | 'document',
  file: File,
): Promise<{ extracted: string }> => {
  const data = await fileToDataUrl(file);
  const res = await teamApi.post<{ extracted?: string; notes?: string }>(
    'patchform/extract',
    { kind, filename: file.name, data },
  );
  return { extracted: res.data?.extracted || '' };
};

export const uploadPatchformFile = async (
  formId: string,
  file: File,
  kind: 'file' | 'signature' = 'file',
): Promise<UploadedFile> => {
  const data = await fileToDataUrl(file);
  const res = await teamApi.post<UploadedFile>(`patchform/forms/${encodeURIComponent(formId)}/files`, {
    filename: file.name,
    data,
    kind,
  });
  if (!res.data?.file_id) {
    throw new Error('アップロードに失敗しました');
  }
  return res.data;
};

export const downloadPatchformFile = async (
  formId: string,
  fileId: string,
  filename?: string,
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/forms/${encodeURIComponent(formId)}/files/${encodeURIComponent(fileId)}`,
  );
  const name = parseFilename(disposition) ?? filename ?? fileId;
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};

export const downloadPatchformCarrier = async (
  formId: string,
  format: 'txt' | 'html' = 'txt',
): Promise<void> => {
  const res = await teamApi.get<{ filename: string; content: string }>(
    `patchform/forms/${encodeURIComponent(formId)}/carrier`,
    { params: { format } },
  );
  const data = res.data;
  if (!data) return;
  const blob = new Blob([data.content], {
    type: format === 'html' ? 'text/html;charset=utf-8' : 'text/plain;charset=utf-8',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = data.filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};
