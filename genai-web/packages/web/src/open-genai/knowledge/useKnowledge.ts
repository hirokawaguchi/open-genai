import useSWR from 'swr';
import { teamApi, teamApiFetcher } from '@/lib/fetcher';
import type {
  DocsResponse,
  KnowledgeDoc,
  KnowledgeScope,
  KnowledgeTag,
  RegisterMode,
  RegisterResult,
  ScopesResponse,
  TagsResponse,
  UploadFile,
} from './types';

/** 操作可能なスコープ一覧（共有 + 所属チーム）。 */
export const useScopes = () => {
  const { data, error, isLoading } = useSWR<ScopesResponse>('knowledge/scopes', teamApiFetcher, {
    revalidateOnFocus: false,
  });
  return {
    scopes: (data?.scopes ?? []) as KnowledgeScope[],
    isSystemAdmin: data?.isSystemAdmin ?? false,
    error,
    isLoading,
  };
};

/** スコープ内のタグ一覧。scope 未指定時は取得しない。 */
export const useTags = (scope: string | undefined) => {
  const key = scope ? (['knowledge/tags', scope] as const) : null;
  const { data, error, isLoading, mutate } = useSWR<TagsResponse>(
    key,
    () => teamApi.get<TagsResponse>('knowledge/tags', { params: { scope: scope! } }).then((r) => r.data),
    { revalidateOnFocus: false },
  );
  return { tags: (data?.tags ?? []) as KnowledgeTag[], error, isLoading, mutate };
};

/** スコープ内のドキュメント一覧（任意でタグ絞り込み）。 */
export const useDocs = (scope: string | undefined, tags?: string[]) => {
  const tagParam = (tags ?? []).filter(Boolean).join(',');
  const key = scope ? (['knowledge/docs', scope, tagParam] as const) : null;
  const { data, error, isLoading, mutate } = useSWR<DocsResponse>(
    key,
    () =>
      teamApi
        .get<DocsResponse>('knowledge/docs', {
          params: { scope: scope!, ...(tagParam ? { tags: tagParam } : {}) },
        })
        .then((r) => r.data),
    {
      revalidateOnFocus: false,
      // 登録中・PII 検査中がある間だけ短間隔で再取得
      refreshInterval: (latest) => {
        const docs = latest?.documents ?? [];
        const busy = docs.some(
          (d) =>
            d.ingest_status === 'queued' ||
            d.ingest_status === 'processing' ||
            d.pii_status === 'pending',
        );
        return busy ? 2000 : 0;
      },
    },
  );
  return { docs: (data?.documents ?? []) as KnowledgeDoc[], error, isLoading, mutate };
};

// ---- 変更系（すべて backend が認可のうえ rag-app へプロキシ）----

export const createTag = (scope: string, tag: string) =>
  teamApi.post('knowledge/tags', { scope, tag }).then((r) => r.data);

export const renameTag = (scope: string, tag: string, renameTo: string) =>
  teamApi.post('knowledge/tags/rename', { scope, tag, rename_to: renameTo }).then((r) => r.data);

export const deleteTag = (scope: string, tag: string) =>
  teamApi.post('knowledge/tags/delete', { scope, tag }).then((r) => r.data);

export const registerFiles = (
  scope: string,
  mode: RegisterMode,
  tags: string[],
  files: UploadFile[],
): Promise<RegisterResult> =>
  teamApi
    .post<RegisterResult>('knowledge/register', { scope, mode, tags, files })
    .then((r) => r.data);

export const registerUrl = (scope: string, url: string, tags: string[]) =>
  teamApi.post('knowledge/urls', { scope, url, tags }).then((r) => r.data);

export const deleteUrl = (scope: string, url: string) =>
  teamApi.post('knowledge/urls/delete', { scope, url }).then((r) => r.data);

export const refreshUrls = (scope: string) =>
  teamApi.post('knowledge/urls/refresh', { scope }).then((r) => r.data);

export const deleteDoc = (scope: string, source: string) =>
  teamApi.post('knowledge/docs/delete', { scope, source }).then((r) => r.data);

export const retagDoc = (scope: string, source: string, tags: string[]) =>
  teamApi.post('knowledge/docs/retag', { scope, source, tags }).then((r) => r.data);

export const clearScope = (scope: string) =>
  teamApi.post('knowledge/clear', { scope }).then((r) => r.data);
