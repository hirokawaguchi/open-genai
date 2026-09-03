import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type {
  EditorConfig,
  EditorConversion,
  EditorExportOptions,
  EditorFile,
  EditorFileContent,
  EditorProject,
} from './types';

const BASE = 'procuretech-editor';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

const enc = encodeURIComponent;

/** ExApp の有効状態・設定を取得する（未起動時は enabled:false）。 */
export const useEditorConfig = () => {
  // NOTE: SWR キーは可用性チェック（useProcuretechEditorAvailable は
  // `${BASE}/config` を boolean で返す）とキャッシュ衝突しないよう別名にする。
  // 実際のフェッチ URL はフェッチャ内で `${BASE}/config` に固定している。
  const { data, isLoading } = useSWR<EditorConfig>(
    `${BASE}/config:full`,
    async () => {
      try {
        return await teamApiFetcher<EditorConfig>(`${BASE}/config`);
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const d = e.data as EditorConfig | undefined;
          return {
            enabled: false,
            error: d?.error || errorMessage(e, '情報化企画書エディタに接続できません'),
          };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return { config: data, isLoading, unavailable: data?.enabled === false };
};

/** プロジェクト（案件フォルダ）一覧。 */
export const useEditorProjects = () => {
  const { data, error, isLoading, mutate } = useSWR<{ projects: EditorProject[] }>(
    `${BASE}/projects`,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return {
    projects: data?.projects ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'プロジェクト一覧の取得に失敗しました。') : null,
    mutate,
  };
};

/** 単一プロジェクトの詳細（メタ + ファイル一覧）。 */
export const useEditorProject = (projectId: string | null) => {
  const key = projectId ? `${BASE}/projects/${enc(projectId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<{
    project: EditorProject;
    files: EditorFile[];
  }>(key, teamApiFetcher, { revalidateOnFocus: false, shouldRetryOnError: false });
  return {
    project: data?.project ?? null,
    files: data?.files ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'プロジェクトの取得に失敗しました。') : null,
    mutate,
  };
};

/** 単一ファイルの内容（テキストは content、バイナリは download_url）。 */
export const fetchFileContent = (
  projectId: string,
  path: string,
): Promise<EditorFileContent> =>
  teamApiFetcher<EditorFileContent>(
    `${BASE}/projects/${enc(projectId)}/files/content?path=${enc(path)}`,
  );

/** 変換ステータスを 1 回取得する。 */
export const fetchConversion = (
  requestId: string,
  projectId?: string,
): Promise<EditorConversion> =>
  teamApiFetcher<EditorConversion>(
    `${BASE}/conversions/${enc(requestId)}` +
      (projectId ? `?project_id=${enc(projectId)}` : ''),
  );

/** プロジェクト/ファイルに対する各種 CRUD 操作。 */
export const useEditorActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async <T>(fn: () => Promise<T>, fallback: string): Promise<T | null> => {
      setSubmitting(true);
      setError(null);
      try {
        return await fn();
      } catch (e) {
        setError(errorMessage(e, fallback));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const createProject = useCallback(
    (name: string) =>
      run(async () => {
        const res = await teamApi.post<{ project: EditorProject }>(`${BASE}/projects`, {
          name,
        });
        return res.data?.project ?? null;
      }, 'プロジェクトの作成に失敗しました。'),
    [run],
  );

  const deleteProject = useCallback(
    (projectId: string) =>
      run(async () => {
        await teamApi.delete(`${BASE}/projects/${enc(projectId)}`);
        return true;
      }, 'プロジェクトの削除に失敗しました。'),
    [run],
  );

  const saveFile = useCallback(
    (projectId: string, path: string, content: string) =>
      run(async () => {
        const res = await teamApi.post<{ file: EditorFile }>(
          `${BASE}/projects/${enc(projectId)}/files/save`,
          { path, content },
        );
        return res.data?.file ?? null;
      }, 'ファイルの保存に失敗しました。'),
    [run],
  );

  const uploadFile = useCallback(
    (
      projectId: string,
      opts: {
        filename: string;
        content_b64: string;
        dir?: string;
        validate_type?: string;
      },
    ) =>
      run(async () => {
        const res = await teamApi.post<{ file: EditorFile }>(
          `${BASE}/projects/${enc(projectId)}/files/upload`,
          opts,
        );
        return res.data?.file ?? null;
      }, 'アップロードに失敗しました。'),
    [run],
  );

  const createDir = useCallback(
    (projectId: string, path: string) =>
      run(async () => {
        await teamApi.post(`${BASE}/projects/${enc(projectId)}/dir`, { path });
        return true;
      }, 'フォルダの作成に失敗しました。'),
    [run],
  );

  const renameFile = useCallback(
    (projectId: string, oldPath: string, newPath: string) =>
      run(async () => {
        const res = await teamApi.post<{ file: EditorFile }>(
          `${BASE}/projects/${enc(projectId)}/files/rename`,
          { old_path: oldPath, new_path: newPath },
        );
        return res.data?.file ?? null;
      }, 'リネームに失敗しました。'),
    [run],
  );

  const duplicateFile = useCallback(
    (projectId: string, path: string, newPath?: string) =>
      run(async () => {
        const res = await teamApi.post<{ file: EditorFile }>(
          `${BASE}/projects/${enc(projectId)}/files/duplicate`,
          { path, new_path: newPath },
        );
        return res.data?.file ?? null;
      }, '複製に失敗しました。'),
    [run],
  );

  const deleteFile = useCallback(
    (projectId: string, path: string) =>
      run(async () => {
        await teamApi.post(`${BASE}/projects/${enc(projectId)}/files/delete`, { path });
        return true;
      }, 'ファイルの削除に失敗しました。'),
    [run],
  );

  const exportProject = useCallback(
    (projectId: string, options?: EditorExportOptions) =>
      run(async () => {
        const res = await teamApi.post<EditorConversion>(
          `${BASE}/projects/${enc(projectId)}/export`,
          { options: options ?? {} },
        );
        return res.data ?? null;
      }, '書き出しに失敗しました。'),
    [run],
  );

  return {
    createProject,
    deleteProject,
    saveFile,
    uploadFile,
    createDir,
    renameFile,
    duplicateFile,
    deleteFile,
    exportProject,
    submitting,
    error,
    setError,
  };
};
