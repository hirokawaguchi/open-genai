import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';
import { download } from '@/utils/createDownloadLink';
import { GuestApiError, usePatchformApi } from './PatchformApiContext';
import type { ImiSource } from './runtime/imiSuggest';
import { lookupPostalDirect } from './runtime/postalLookup';
import type {
  AssistGenerateResult,
  AssistInviteResult,
  AssistProcedureApply,
  AssistProcedurePreview,
  AssistProcedureResult,
  FormConfig,
  FormDefinition,
  FormDetail,
  FormSummary,
  FormVisibility,
  IdentityMode,
  Application,
  MyApplication,
  Inbox,
  PatchformExportBundle,
  Procedure,
  ProcedureCatalog,
  ProcedureResolvePreview,
  ProcedureShare,
  ProcedureVisibility,
  SlotTemplate,
  Submission,
  UploadedFile,
} from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError || e instanceof GuestApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

const statusOf = (e: unknown): number | null =>
  e instanceof ApiError || e instanceof GuestApiError ? e.status : null;

// データ取得を現在のモード（庁内=teamApi / 庁外=公開API Bearer）に束ねる薄い型。
// teamApi と PatchformApi はいずれもこの形を満たす。
type RuntimeApi = {
  get: <T>(
    path: string,
    options?: { params?: Record<string, string | number | boolean | undefined> },
  ) => Promise<{ data: T; status: number }>;
  post: <T>(
    path: string,
    body?: unknown,
    options?: { params?: Record<string, string | number | boolean | undefined> },
  ) => Promise<{ data: T; status: number }>;
  getBlob: (
    path: string,
    options?: { params?: Record<string, string | number | boolean | undefined> },
  ) => Promise<{ blob: Blob; disposition: string | null }>;
};

// SWR フェッチャを現在のモードに束ねる。既定は庁内（teamApi）。
const useApiFetcher = () => {
  const api = usePatchformApi();
  return useCallback(<T,>(path: string): Promise<T> => api.get<T>(path).then((r) => r.data), [api]);
};

export const usePatchformConfig = () => {
  const api = usePatchformApi();
  const { data, error, isLoading } = useSWR<FormConfig>(
    'patchform/config',
    async () => {
      try {
        return (await api.get<FormConfig>('patchform/config')).data;
      } catch (e) {
        const status = statusOf(e);
        if (status === 503 || status === 502) {
          const data = (e as { data?: FormConfig }).data;
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
  const fetcher = useApiFetcher();
  const { data, error, isLoading, mutate } = useSWR<{ forms: FormSummary[] }>(
    'patchform/forms',
    fetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    forms: data?.forms ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'フォーム一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export type TagUsage = { tag: string; count: number };

/** 編集権限のある様式に付いたタグ（使用件数付き・ゴミ箱分も含む）。 */
export const usePatchformTags = () => {
  const fetcher = useApiFetcher();
  const { data, error, isLoading, mutate } = useSWR<{ tags: TagUsage[] }>(
    'patchform/tags',
    fetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    tags: data?.tags ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'タグの取得に失敗しました。') : null,
    mutate,
  };
};

/** タグの改名・削除（編集権限のある全フォームに一括反映）。 */
export const usePatchformTagActions = () => {
  const api = usePatchformApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rename = useCallback(async (from: string, to: string): Promise<number | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ changed: number }>('patchform/tags/rename', {
        from,
        to,
      });
      return res.data?.changed ?? 0;
    } catch (e) {
      setError(errorMessage(e, 'タグの改名に失敗しました。'));
      return null;
    } finally {
      setBusy(false);
    }
  }, [api]);

  const remove = useCallback(async (tag: string): Promise<number | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ changed: number }>('patchform/tags/delete', { tag });
      return res.data?.changed ?? 0;
    } catch (e) {
      setError(errorMessage(e, 'タグの削除に失敗しました。'));
      return null;
    } finally {
      setBusy(false);
    }
  }, [api]);

  return { rename, remove, busy, error, setError };
};

export const usePatchformDetail = (formId: string | undefined) => {
  const fetcher = useApiFetcher();
  const key = formId ? `patchform/forms/${encodeURIComponent(formId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<FormDetail>(key, fetcher, {
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

export const usePatchformActions = () => {
  const api = usePatchformApi();
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
        const res = await api.post<FormDetail>('patchform/forms', input);
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
        const res = await api.put<FormDetail>(
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
      const res = await api.post<FormDetail>(
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
      await api.delete(`patchform/forms/${encodeURIComponent(formId)}`);
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
            await api.delete(`patchform/forms/${encodeURIComponent(id)}`);
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
            await api.post(`patchform/forms/${encodeURIComponent(id)}/status`, {
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
            await api.post(`patchform/forms/${encodeURIComponent(entry.id)}/tags`, {
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
        const res = await api.post<{
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
      const res = await api.get<{
        answers?: Record<string, unknown>;
        receipt_code?: string | null;
        submitter_name?: string | null;
      }>(`patchform/forms/${encodeURIComponent(formId)}/draft`);
      return res.data ?? null;
    } catch {
      return null;
    }
  }, [api]);

  const setWithdrawn = useCallback(
    async (formId: string, submissionId: string, withdrawn: boolean): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        await api.post(
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
      const res = await api.get<Submission>(
        `patchform/forms/${encodeURIComponent(formId)}/submissions/${encodeURIComponent(submissionId)}`,
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '個人番号の表示に失敗しました。'));
      return null;
    }
  }, []);

  const importForm = useCallback(
    async (bundle: PatchformExportBundle): Promise<FormDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await api.post<FormDetail>('patchform/forms/import', { bundle });
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'フォームの取り込みに失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [api],
  );

  const duplicate = useCallback(
    async (formId: string): Promise<FormDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await api.post<FormDetail>(
          `patchform/forms/${encodeURIComponent(formId)}/duplicate`,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'フォームの複製に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [api],
  );

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
    importForm,
    duplicate,
    submitting,
    error,
    setError,
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

/** フォームの定義とひな型を可搬なJSONとして書き出す（庁内）。 */
export const downloadFormPortable = async (formId: string): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/forms/${encodeURIComponent(formId)}/portable`,
  );
  saveBlob(blob, parseFilename(disposition) ?? `form_${formId}.json`);
};

/** 手続き（案内＋全構成様式を同梱）を可搬なJSONとして書き出す（庁内）。 */
export const downloadProcedurePortable = async (procedureId: string): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/procedures/${encodeURIComponent(procedureId)}/portable`,
  );
  saveBlob(blob, parseFilename(disposition) ?? `procedure_${procedureId}.json`);
};

/** アップロードされたJSONファイルを読み、書き出しバンドルとしてパースする。 */
export const readExportBundleFile = async (file: File): Promise<PatchformExportBundle> => {
  const text = await file.text();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error('JSONファイルとして読み取れませんでした。');
  }
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('取り込みデータが不正です。');
  }
  return parsed as PatchformExportBundle;
};

/** 申請束のアイテムに紐づく様式ひな型をDLする（庁内=teamApi / 庁外=公開API）。 */
const downloadItemTemplateWith = async (
  api: RuntimeApi,
  applicationId: string,
  itemId: string,
  fallbackName?: string,
): Promise<void> => {
  const { blob, disposition } = await api.getBlob(
    `patchform/applications/${encodeURIComponent(applicationId)}/items/${encodeURIComponent(itemId)}/template`,
  );
  saveBlob(blob, parseFilename(disposition) ?? fallbackName ?? 'template');
};

/** 成果物DLリンクを記載した「リンクファイル」(carrier)を取得して保存する（LGWAN想定）。 */
export const downloadArtifactCarrier = async (objectKey: string): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob('/exapps/artifact-carrier', {
    params: { objectKey },
  });
  const filename =
    parseFilename(disposition) ?? `${objectKey.split('/').pop() ?? 'download'}_link.txt`;
  saveBlob(blob, filename);
};

/** 申請束のアイテムに添付された、申請者アップロードのファイルをDLする。
 *
 * 庁内: 庁外由来の添付は backend が SeaweedFS へ再ホストし、署名付きURL（carrierモードでは
 * リンクファイル）を JSON で返す。庁内由来はバイナリをそのままストリームする。
 * 庁外: 本人のファイルなので越境せず、常にバイナリを直接返す。
 */
const downloadItemFileWith = async (
  api: RuntimeApi,
  applicationId: string,
  itemId: string,
  fallbackName?: string,
): Promise<void> => {
  const { blob, disposition } = await api.getBlob(
    `patchform/applications/${encodeURIComponent(applicationId)}/items/${encodeURIComponent(itemId)}/file`,
  );
  if (blob.type.includes('application/json')) {
    let info: {
      rehosted?: boolean;
      delivery?: string;
      file_url?: string;
      object_key?: string;
      display_name?: string;
      error?: string;
    } = {};
    try {
      info = JSON.parse(await blob.text());
    } catch {
      info = {};
    }
    if (info.rehosted) {
      if (info.delivery === 'carrier' && info.object_key) {
        await downloadArtifactCarrier(info.object_key);
        return;
      }
      if (info.file_url) {
        download(info.file_url, info.display_name ?? fallbackName ?? 'attachment');
        return;
      }
    }
    throw new Error(info.error ?? 'ダウンロードに失敗しました');
  }
  saveBlob(blob, parseFilename(disposition) ?? fallbackName ?? 'attachment');
};

/** 作成画面で様式フォーム自身のひな型をDLする。 */
export const downloadFormTemplate = async (
  formId: string,
  file: SlotTemplate,
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `patchform/forms/${encodeURIComponent(formId)}/templates/${encodeURIComponent(file.file_id)}/download`,
  );
  saveBlob(blob, parseFilename(disposition) ?? file.filename);
};

/** 様式フォーム自身のひな型を登録・差し替え・削除する（作成者/編集者）。 */
export const usePatchformFormTemplate = () => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setTemplate = useCallback(
    async (formId: string, file: File): Promise<SlotTemplate | null> => {
      setBusy(true);
      setError(null);
      try {
        const data = await fileToDataUrl(file);
        const res = await teamApi.post<SlotTemplate>(
          `patchform/forms/${encodeURIComponent(formId)}/template`,
          { filename: file.name, data },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'ひな型の登録に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const removeTemplate = useCallback(async (formId: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await teamApi.delete(`patchform/forms/${encodeURIComponent(formId)}/template`);
      return true;
    } catch (e) {
      setError(errorMessage(e, 'ひな型の削除に失敗しました。'));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  return { setTemplate, removeTemplate, busy, error };
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

const lookupPostalWith = async (
  api: RuntimeApi,
  zip: string,
): Promise<{ prefecture?: string; city?: string; street?: string } | null> => {
  try {
    const res = await api.get<{ prefecture?: string; city?: string; street?: string }>(
      'patchform/lookup/postal',
      { params: { zip } },
    );
    return res.data ?? null;
  } catch (e) {
    const s = statusOf(e);
    if (s === 404 || s === 502 || s === 503) {
      return lookupPostalDirect(zip);
    }
    throw new Error(errorMessage(e, '住所の検索に失敗しました。'));
  }
};

export const lookupPatchformPostal = (zip: string) => lookupPostalWith(teamApi, zip);

const lookupCorporateWith = async (
  api: RuntimeApi,
  number: string,
): Promise<{ company_name?: string } | null> => {
  try {
    const res = await api.get<{ company_name?: string }>('patchform/lookup/corporate', {
      params: { number },
    });
    return res.data ?? null;
  } catch (e) {
    const s = statusOf(e);
    if (s !== null && s >= 500) {
      return { company_name: '' };
    }
    throw new Error(errorMessage(e, '法人番号の検索に失敗しました。'));
  }
};

export const lookupPatchformCorporate = (number: string) => lookupCorporateWith(teamApi, number);

const extractPatchformFileWith = async (
  api: RuntimeApi,
  kind: 'image' | 'document',
  file: File,
): Promise<{ extracted: string; notes?: string }> => {
  const data = await fileToDataUrl(file);
  const res = await api.post<{ extracted?: string; notes?: string }>('patchform/extract', {
    kind,
    filename: file.name,
    data,
  });
  return { extracted: res.data?.extracted || '', notes: res.data?.notes };
};

export const extractPatchformFile = (kind: 'image' | 'document', file: File) =>
  extractPatchformFileWith(teamApi, kind, file);

const uploadPatchformFileWith = async (
  api: RuntimeApi,
  formId: string,
  file: File,
  kind: 'file' | 'signature' = 'file',
): Promise<UploadedFile> => {
  const data = await fileToDataUrl(file);
  const res = await api.post<UploadedFile>(`patchform/forms/${encodeURIComponent(formId)}/files`, {
    filename: file.name,
    data,
    kind,
  });
  if (!res.data?.file_id) {
    throw new Error('アップロードに失敗しました');
  }
  return res.data;
};

export const uploadPatchformFile = (
  formId: string,
  file: File,
  kind: 'file' | 'signature' = 'file',
) => uploadPatchformFileWith(teamApi, formId, file, kind);

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
  const fetcher = useApiFetcher();
  const key =
    procedureId && enabled && origin
      ? `patchform/procedures/${encodeURIComponent(procedureId)}/share?origin=${encodeURIComponent(origin)}`
      : null;
  const { data, error, isLoading, mutate } = useSWR<ProcedureShare>(key, fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    share: data,
    isLoading,
    loadError: error ? errorMessage(error, '申請用リンクの取得に失敗しました。') : null,
    mutate,
  };
};

export const usePatchformProcedures = () => {
  const fetcher = useApiFetcher();
  const { data, error, isLoading, mutate } = useSWR<{ procedures: Procedure[] }>(
    'patchform/procedures',
    fetcher,
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
  const fetcher = useApiFetcher();
  const key = procedureId ? `patchform/procedures/${encodeURIComponent(procedureId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<Procedure>(key, fetcher, {
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
  const fetcher = useApiFetcher();
  const qs = procedureId ? `?procedure_id=${encodeURIComponent(procedureId)}` : '';
  const { data, error, isLoading, mutate } = useSWR<Inbox>(`patchform/inbox${qs}`, fetcher, {
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

export const usePatchformApplication = (applicationId: string | undefined) => {
  const fetcher = useApiFetcher();
  const key = applicationId ? `patchform/applications/${encodeURIComponent(applicationId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<Application>(key, fetcher, {
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

/** マイ手続き一覧（庁内: 自分が所有するプロジェクト）。 */
export const usePatchformMyApplications = () => {
  const fetcher = useApiFetcher();
  const { data, error, isLoading, mutate } = useSWR<{ applications: MyApplication[] }>(
    'patchform/applications/mine',
    fetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    applications: data?.applications ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'マイ手続きの取得に失敗しました。') : null,
    mutate,
  };
};

/** 記入時の横断 IMI 候補源（本人の他プロジェクトの記入済み様式）。 */
export const usePatchformApplicationImiSources = (applicationId: string | undefined) => {
  const fetcher = useApiFetcher();
  const key = applicationId
    ? `patchform/applications/${encodeURIComponent(applicationId)}/imi-sources`
    : null;
  const { data } = useSWR<{ sources: ImiSource[] }>(key, fetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return { sources: data?.sources ?? [] };
};

/** プロジェクト（申請束）の作成・状態変更・改名。 */
export const usePatchformProjectActions = () => {
  const api = usePatchformApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(
    async (procedureId: string, title?: string): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.post<Application>('patchform/applications', {
          procedure_id: procedureId,
          ...(title ? { title } : {}),
        });
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '手続きの作成に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const setStatus = useCallback(
    async (applicationId: string, status: string): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.post<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/status`,
          { status },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '状態の変更に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const updateMeta = useCallback(
    async (
      applicationId: string,
      patch: {
        title?: string;
        assignee?: string;
        deadline?: string;
        next_action_date?: string;
      },
    ): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.patch<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}`,
          patch,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '案件の更新に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  const rename = useCallback(
    (applicationId: string, title: string): Promise<Application | null> =>
      updateMeta(applicationId, { title }),
    [updateMeta],
  );

  const remove = useCallback(async (applicationId: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await api.delete(
        `patchform/applications/${encodeURIComponent(applicationId)}`,
      );
      return true;
    } catch (e) {
      setError(errorMessage(e, '申請の削除に失敗しました。'));
      return false;
    } finally {
      setBusy(false);
    }
  }, [api]);

  return { create, setStatus, rename, updateMeta, remove, busy, error, setError };
};

/** 作成ウィザード用: 案内回答から必要書類を dry-run で解決してプレビューする。 */
const resolveProcedurePreviewWith = async (
  api: RuntimeApi,
  procedureId: string,
  answers: Record<string, unknown>,
): Promise<ProcedureResolvePreview | null> => {
  try {
    const res = await api.post<ProcedureResolvePreview>(
      `patchform/procedures/${encodeURIComponent(procedureId)}/resolve`,
      { answers },
    );
    return res.data ?? null;
  } catch {
    return null;
  }
};

export const resolveProcedurePreview = (
  procedureId: string,
  answers: Record<string, unknown>,
): Promise<ProcedureResolvePreview | null> =>
  resolveProcedurePreviewWith(teamApi, procedureId, answers);

export const usePatchformProcedureCatalog = (procedureId: string | undefined) => {
  const fetcher = useApiFetcher();
  const key = procedureId
    ? `patchform/procedures/${encodeURIComponent(procedureId)}/catalog`
    : null;
  const { data, error, isLoading } = useSWR<ProcedureCatalog>(key, fetcher, {
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
  const api = usePatchformApi();
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
        const res = await api.post<Application>(
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
        const res = await api.post<Application>(
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
        const res = await api.delete<Application>(
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

  const setSource = useCallback(
    async (
      applicationId: string,
      itemId: string,
      source: 'form' | 'file',
    ): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.post<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/items/${encodeURIComponent(itemId)}/source`,
          { source },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '採用する申請データの切り替えに失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const reorder = useCallback(
    async (applicationId: string, order: string[]): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.post<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/items/order`,
          { order },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '並び順の変更に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const removeItem = useCallback(
    async (applicationId: string, itemId: string): Promise<Application | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await api.delete<Application>(
          `patchform/applications/${encodeURIComponent(applicationId)}/items/${encodeURIComponent(itemId)}`,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '枠の削除に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return {
    addItem,
    fulfillWithFile,
    clearFile,
    setSource,
    reorder,
    removeItem,
    busy,
    error,
    setError,
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

  // 手続きの公開範囲を変更する（庁内のみ / 庁内と外部）。公開中は案内＋全様式の
  // 受付にも即時反映され、既存の共有URL・QRへ反映される。
  const setProcedureVisibility = useCallback(
    async (
      procedureId: string,
      visibility: ProcedureVisibility,
    ): Promise<Procedure | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<Procedure>(
          `patchform/procedures/${encodeURIComponent(procedureId)}/visibility`,
          { visibility },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '公開範囲を変更できませんでした。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const importProcedure = useCallback(
    async (bundle: PatchformExportBundle): Promise<Procedure | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<Procedure>('patchform/procedures/import', { bundle });
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '手続きの取り込みに失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  // 手続きを複製する（構成フォームも独立したコピーとして作られる）。
  const duplicate = useCallback(
    async (procedureId: string): Promise<Procedure | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<Procedure>(
          `patchform/procedures/${encodeURIComponent(procedureId)}/duplicate`,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '手続きの複製に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  return {
    create,
    save,
    setStatus,
    setStatusMany,
    setProcedureVisibility,
    remove,
    removeMany,
    importProcedure,
    duplicate,
    submitting,
    error,
    setError,
  };
};

/**
 * FillForm / ワークベンチが使う「その場の入出力」関数群を、現在のモード
 * （庁内=teamApi / 庁外=公開API Bearer）に束ねて返す。庁外ページ（DocmakerPage /
 * PatchformApplicationPage / PatchformWizardPage / PatchformFillModal）はこれを使う。
 */
export const usePatchformRuntime = () => {
  const api = usePatchformApi();
  return {
    extract: useCallback(
      (kind: 'image' | 'document', file: File) => extractPatchformFileWith(api, kind, file),
      [api],
    ),
    upload: useCallback(
      (formId: string, file: File, kind: 'file' | 'signature' = 'file') =>
        uploadPatchformFileWith(api, formId, file, kind),
      [api],
    ),
    postalLookup: useCallback((zip: string) => lookupPostalWith(api, zip), [api]),
    corporateLookup: useCallback((number: string) => lookupCorporateWith(api, number), [api]),
    resolvePreview: useCallback(
      (procedureId: string, answers: Record<string, unknown>) =>
        resolveProcedurePreviewWith(api, procedureId, answers),
      [api],
    ),
    downloadItemFile: useCallback(
      (applicationId: string, itemId: string, fallbackName?: string) =>
        downloadItemFileWith(api, applicationId, itemId, fallbackName),
      [api],
    ),
    downloadItemTemplate: useCallback(
      (applicationId: string, itemId: string, fallbackName?: string) =>
        downloadItemTemplateWith(api, applicationId, itemId, fallbackName),
      [api],
    ),
  };
};
