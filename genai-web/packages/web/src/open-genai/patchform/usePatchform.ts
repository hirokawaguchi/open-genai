import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import { lookupPostalDirect } from './runtime/postalLookup';
import type {
  AssistGenerateResult,
  AssistInviteResult,
  AssistProcedureApply,
  AssistProcedurePreview,
  AssistProcedureResult,
  AuditEvent,
  FormConfig,
  FormDefinition,
  FormDetail,
  FormSummary,
  FormVisibility,
  IdentityMode,
  Application,
  Inbox,
  Procedure,
  ProcedureCatalog,
  ProcedureShare,
  SlotTemplate,
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
      tags?: string[];
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
        tags?: string[];
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

  const setStatus = useCallback(async (
    formId: string,
    status: string,
    extra?: { locked?: boolean },
  ): Promise<FormDetail | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<FormDetail>(
        `patchform/forms/${encodeURIComponent(formId)}/status`,
        { status, ...(extra?.locked === undefined ? {} : { locked: extra.locked }) },
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

  const removeMany = useCallback(
    async (
      formIds: string[],
    ): Promise<{ id: string; ok: boolean; error?: string }[]> => {
      setSubmitting(true);
      setError(null);
      const results: { id: string; ok: boolean; error?: string }[] = [];
      try {
        for (const id of formIds) {
          try {
            await teamApi.delete(`patchform/forms/${encodeURIComponent(id)}`);
            results.push({ id, ok: true });
          } catch (e) {
            results.push({ id, ok: false, error: errorMessage(e, '削除できませんでした。') });
          }
        }
        return results;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const setStatusMany = useCallback(
    async (
      formIds: string[],
      status: string,
      extra?: { locked?: boolean },
    ): Promise<{ id: string; ok: boolean; error?: string }[]> => {
      setSubmitting(true);
      setError(null);
      const results: { id: string; ok: boolean; error?: string }[] = [];
      try {
        for (const id of formIds) {
          try {
            await teamApi.post(`patchform/forms/${encodeURIComponent(id)}/status`, {
              status,
              ...(extra?.locked === undefined ? {} : { locked: extra.locked }),
            });
            results.push({ id, ok: true });
          } catch (e) {
            results.push({ id, ok: false, error: errorMessage(e, '変更できませんでした。') });
          }
        }
        return results;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const applyTagsMany = useCallback(
    async (
      entries: { id: string; tags: string[] }[],
    ): Promise<{ id: string; ok: boolean; error?: string }[]> => {
      setSubmitting(true);
      setError(null);
      const results: { id: string; ok: boolean; error?: string }[] = [];
      try {
        for (const entry of entries) {
          try {
            await teamApi.post(`patchform/forms/${encodeURIComponent(entry.id)}/tags`, {
              tags: entry.tags,
            });
            results.push({ id: entry.id, ok: true });
          } catch (e) {
            results.push({ id: entry.id, ok: false, error: errorMessage(e, 'タグを変更できませんでした。') });
          }
        }
        return results;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const submitAnswers = useCallback(
    async (
      formId: string,
      input: {
        answers: Record<string, unknown>;
        submitter_name?: string;
        is_draft?: boolean;
        resume_token?: string;
        application_token?: string;
        application_item_id?: string;
      },
    ): Promise<{ receipt_code?: string; is_draft?: boolean; application?: Application } | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<{
          receipt_code?: string;
          is_draft?: boolean;
          application?: Application;
        }>(
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
    setStatusMany,
    applyTagsMany,
    remove,
    removeMany,
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

const saveBlob = (blob: Blob, filename: string) => {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
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
  saveBlob(blob, parseFilename(disposition) ?? `patchform_${formId}.${format}`);
};

export const downloadProcedureExport = async (
  procedureId: string,
  format: 'csv' | 'jsonl' | 'aligned' = 'csv',
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/procedures/${encodeURIComponent(procedureId)}/export`,
    { params: { format } },
  );
  const ext = format === 'jsonl' ? 'jsonl' : 'csv';
  saveBlob(blob, parseFilename(disposition) ?? `procedure_${procedureId}_${format}.${ext}`);
};

/** 職員が手続きの様式ひな型をダウンロードする（庁内用）。 */
export const downloadProcedureTemplate = async (
  procedureId: string,
  file: SlotTemplate,
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/procedures/${encodeURIComponent(procedureId)}/templates/${encodeURIComponent(file.file_id)}/download`,
  );
  saveBlob(blob, parseFilename(disposition) ?? file.filename);
};

export const downloadApplicationExport = async (
  applicationId: string,
  format: 'csv' | 'jsonl' = 'csv',
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/applications/${encodeURIComponent(applicationId)}/export`,
    { params: { format } },
  );
  saveBlob(blob, parseFilename(disposition) ?? `application_${applicationId}.${format}`);
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

  const previewProcedure = useCallback(
    async (input: { text: string; visibility?: FormVisibility }): Promise<AssistProcedurePreview | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<AssistProcedurePreview>('patchform/assist/procedure', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '手引きから候補を出せませんでした。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const applyProcedureDraft = useCallback(
    async (input: {
      draft: Record<string, unknown>;
      apply: AssistProcedureApply;
      form_keys?: string[];
      visibility?: FormVisibility;
    }): Promise<AssistProcedureResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<AssistProcedureResult>('patchform/assist/procedure/apply', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '選んだ候補を下書きできませんでした。'));
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

  return { generate, draftInvite, previewProcedure, applyProcedureDraft, busy, error, setError };
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
): Promise<{ extracted: string; notes?: string }> => {
  const data = await fileToDataUrl(file);
  const res = await teamApi.post<{ extracted?: string; notes?: string }>(
    'patchform/extract',
    { kind, filename: file.name, data },
  );
  return { extracted: res.data?.extracted || '', notes: res.data?.notes };
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

export const downloadProcedureLinkFile = (
  name: string,
  urls: { internal?: string | null; external?: string | null },
) => {
  const lines = [`手続き: ${name}`, ''];
  if (urls.internal) {
    lines.push('庁内から申請するURL:', urls.internal, '');
  }
  if (urls.external) {
    lines.push(
      '外部から回答するURL:',
      urls.external,
      '',
      'LGWAN 端末から外部 URL を開けない場合は、このファイルを持ち出してインターネット接続端末で開いてください。',
      '',
    );
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const href = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = `${name}_patchform_link.txt`;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(href), 1000);
};

export const downloadProcedureQr = (filename: string, svg: string) => {
  const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
  const href = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(href), 1000);
};

export const usePatchformProcedureShare = (procedureId: string | undefined, enabled: boolean) => {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  const key =
    procedureId && enabled && origin
      ? `patchform/procedures/${encodeURIComponent(procedureId)}/share?origin=${encodeURIComponent(origin)}`
      : null;
  const { data, error, isLoading } = useSWR<ProcedureShare>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    share: data,
    isLoading,
    loadError: error ? errorMessage(error, '申請用リンクの取得に失敗しました。') : null,
  };
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

export const usePatchformProcedures = () => {
  const { data, error, isLoading, mutate } = useSWR<{ procedures: Procedure[] }>(
    'patchform/procedures',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    procedures: data?.procedures ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '手続き一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformProcedure = (procedureId: string | undefined) => {
  const key = procedureId ? `patchform/procedures/${encodeURIComponent(procedureId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<Procedure>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    procedure: data,
    isLoading,
    loadError: error ? errorMessage(error, '手続きの取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformInbox = (procedureId?: string) => {
  const qs = procedureId ? `?procedure_id=${encodeURIComponent(procedureId)}` : '';
  const { data, error, isLoading, mutate } = useSWR<Inbox>(`patchform/inbox${qs}`, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    inbox: data,
    items: data?.items ?? [],
    openings: data?.openings ?? [],
    procedures: data?.procedures ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '申請受付の取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformApplications = (procedureId: string | undefined) => {
  const key = procedureId
    ? `patchform/procedures/${encodeURIComponent(procedureId)}/applications`
    : null;
  const { data, error, isLoading, mutate } = useSWR<{ applications: Application[] }>(
    key,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    applications: data?.applications ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '申請一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformApplication = (applicationId: string | undefined) => {
  const key = applicationId ? `patchform/applications/${encodeURIComponent(applicationId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<Application>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    application: data,
    isLoading,
    loadError: error ? errorMessage(error, '申請の取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformProcedureCatalog = (procedureId: string | undefined) => {
  const key = procedureId
    ? `patchform/procedures/${encodeURIComponent(procedureId)}/catalog`
    : null;
  const { data, error, isLoading } = useSWR<ProcedureCatalog>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    catalog: data,
    slots: data?.slots ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '手続きの枠一覧を取得できませんでした。') : null,
  };
};

export const usePatchformApplicationItems = () => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addItem = useCallback(
    async (
      applicationId: string,
      input: {
        duplicate_of?: string;
        form_id?: string;
        slot_id?: string;
        title?: string;
        kind?: string;
      },
    ): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/items`,
          input,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '枠を足せませんでした。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const fulfillWithFile = useCallback(
    async (applicationId: string, itemId: string, file: File): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const data = await fileToDataUrl(file);
        const res = await teamApi.post<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/items/${encodeURIComponent(itemId)}/file`,
          { filename: file.name, data },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'ファイルの添付に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const clearFile = useCallback(
    async (applicationId: string, itemId: string): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.delete<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/items/${encodeURIComponent(itemId)}/file`,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '添付の取消に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return { addItem, fulfillWithFile, clearFile, busy, error, setError };
};

/** 手続き編集で枠ごとの様式ひな型を登録・削除する（職員のみ）。 */
export const usePatchformProcedureTemplates = (procedureId: string | undefined) => {
  const key = procedureId
    ? `patchform/procedures/${encodeURIComponent(procedureId)}/templates`
    : null;
  const { data, isLoading, mutate } = useSWR<{
    procedure_id: string;
    templates: Record<string, SlotTemplate>;
  }>(key, teamApiFetcher, { revalidateOnFocus: false, shouldRetryOnError: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = useCallback(
    async (slotId: string, file: File): Promise<boolean> => {
      if (!procedureId) return false;
      setBusy(true);
      setError(null);
      try {
        const data = await fileToDataUrl(file);
        await teamApi.post(
          `patchform/procedures/${encodeURIComponent(procedureId)}/templates`,
          { slot_id: slotId, filename: file.name, data },
        );
        await mutate();
        return true;
      } catch (e) {
        setError(errorMessage(e, 'ひな型の登録に失敗しました。'));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [procedureId, mutate],
  );

  const remove = useCallback(
    async (fileId: string): Promise<boolean> => {
      if (!procedureId) return false;
      setBusy(true);
      setError(null);
      try {
        await teamApi.delete(
          `patchform/procedures/${encodeURIComponent(procedureId)}/templates/${encodeURIComponent(fileId)}`,
        );
        await mutate();
        return true;
      } catch (e) {
        setError(errorMessage(e, 'ひな型の削除に失敗しました。'));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [procedureId, mutate],
  );

  return {
    templates: data?.templates ?? {},
    isLoading,
    upload,
    remove,
    busy,
    error,
    setError,
    mutate,
  };
};

export const usePatchformProcedureActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(
    async (input: {
      name: string;
      description?: string;
      guide_form_id: string;
    }): Promise<Procedure | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<Procedure>('patchform/procedures', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '手続きの作成に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const save = useCallback(async (procedureId: string, input: Partial<Procedure>) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.put<Procedure>(
        `patchform/procedures/${encodeURIComponent(procedureId)}`,
        input,
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '手続きの保存に失敗しました。'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const setStatus = useCallback(
    async (procedureId: string, status: 'draft' | 'published' | 'archived') => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<Procedure>(
          `patchform/procedures/${encodeURIComponent(procedureId)}/status`,
          { status },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '手続きの公開状態を変更できませんでした。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const setStatusMany = useCallback(
    async (
      procedureIds: string[],
      status: 'draft' | 'published' | 'archived',
    ): Promise<{ id: string; ok: boolean; error?: string }[]> => {
      setSubmitting(true);
      setError(null);
      const results: { id: string; ok: boolean; error?: string }[] = [];
      try {
        for (const id of procedureIds) {
          try {
            await teamApi.post(`patchform/procedures/${encodeURIComponent(id)}/status`, {
              status,
            });
            results.push({ id, ok: true });
          } catch (e) {
            results.push({ id, ok: false, error: errorMessage(e, '変更できませんでした。') });
          }
        }
        return results;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const remove = useCallback(async (procedureId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await teamApi.delete(`patchform/procedures/${encodeURIComponent(procedureId)}`);
      return true;
    } catch (e) {
      setError(errorMessage(e, '手続きの削除に失敗しました。'));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const removeMany = useCallback(
    async (
      procedureIds: string[],
    ): Promise<{ id: string; ok: boolean; error?: string }[]> => {
      setSubmitting(true);
      setError(null);
      const results: { id: string; ok: boolean; error?: string }[] = [];
      try {
        for (const id of procedureIds) {
          try {
            await teamApi.delete(`patchform/procedures/${encodeURIComponent(id)}`);
            results.push({ id, ok: true });
          } catch (e) {
            results.push({ id, ok: false, error: errorMessage(e, '削除できませんでした。') });
          }
        }
        return results;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  return { create, save, setStatus, setStatusMany, remove, removeMany, submitting, error, setError };
};
