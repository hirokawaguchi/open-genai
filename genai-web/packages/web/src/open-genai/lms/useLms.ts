import { useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type { CourseDetail, Enrollment, LmsHome, Material, MaterialTranscript, ProgressRow } from './types';

export type MaterialUploadProgress = {
  phase: 'prepare' | 'upload' | 'convert' | 'store';
  label: string;
  detail: string;
  percent: number | null;
};

const formatBytes = (size: number) => {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

export const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useLmsConfig = () => {
  const { data, isLoading } = useSWR<{ enabled?: boolean; error?: string }>(
    'lms/config',
    async () => {
      try {
        return await teamApiFetcher<{ enabled?: boolean; error?: string }>('lms/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as { error?: string } | undefined;
          return { enabled: false, error: data?.error };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return { isLoading, unavailable: data?.enabled === false, error: data?.error };
};

export const useLmsHome = (enabled = true) => {
  const { data, error, isLoading, mutate } = useSWR<LmsHome>(
    enabled ? 'lms/home' : null,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  return { home: data, isLoading, error, mutate };
};

export const useLmsMaterials = (enabled = true, view: 'active' | 'trash' = 'active') => {
  const { data, error, isLoading, mutate } = useSWR<{ materials: Material[] }>(
    enabled ? (view === 'trash' ? 'lms/materials?view=trash' : 'lms/materials') : null,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  return { materials: data?.materials ?? [], isLoading, error, mutate };
};

export const useLmsCourse = (courseId: string | null) => {
  const { data, error, isLoading, mutate } = useSWR<CourseDetail>(
    courseId ? `lms/courses/${courseId}` : null,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  return { course: data, isLoading, error, mutate };
};

export const useLmsEnrollment = (enrollmentId: string | null) => {
  const { data, error, isLoading, mutate } = useSWR<Enrollment>(
    enrollmentId ? `lms/learn/${enrollmentId}` : null,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  return { enrollment: data, isLoading, error, mutate };
};

export const useLmsTranscript = (materialId: string | null) => {
  const { data, error, isLoading, mutate } = useSWR<MaterialTranscript>(
    materialId ? `lms/materials/${materialId}/transcript` : null,
    teamApiFetcher,
    {
      revalidateOnFocus: false,
      refreshInterval: (latest) => (latest?.status === 'running' ? 2000 : 0),
    },
  );
  return { transcript: data, isLoading, error, mutate };
};

export const useLmsProgress = (courseId: string | null) => {
  const { data, error, isLoading, mutate } = useSWR<{ title: string; rows: ProgressRow[] }>(
    courseId ? `lms/courses/${courseId}/progress` : null,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  return { progress: data, isLoading, error, mutate };
};

export const useLmsActions = () => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async <T>(work: () => Promise<T>, fallback: string): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (e) {
      setError(errorMessage(e, fallback));
      return null;
    } finally {
      setBusy(false);
    }
  };

  return {
    busy,
    error,
    setError,
    createCourse: (title: string) =>
      run(() => teamApi.post<CourseDetail>('lms/courses', { title }).then((r) => r.data), 'コースを作成できませんでした'),
    saveDraft: (courseId: string, body: unknown) =>
      run(
        () => teamApi.put<CourseDetail>(`lms/courses/${courseId}/draft`, body).then((r) => r.data),
        '下書きを保存できませんでした',
      ),
    deleteCourse: (courseId: string) =>
      run(
        () => teamApi.delete<{ ok: boolean }>(`lms/courses/${courseId}`).then((r) => r.data),
        'コースを削除できませんでした',
      ),
    publish: (courseId: string) =>
      run(
        () => teamApi.post<CourseDetail>(`lms/courses/${courseId}/publish`).then((r) => r.data),
        '公開できませんでした',
      ),
    setRole: (courseId: string, userId: string, role: string) =>
      run(
        () => teamApi.post<CourseDetail>(`lms/courses/${courseId}/roles`, { userId, role }).then((r) => r.data),
        '役割を追加できませんでした',
      ),
    removeRole: (courseId: string, userId: string, role: string) =>
      run(
        () =>
          teamApi
            .delete<CourseDetail>(`lms/courses/${courseId}/roles`, { params: { userId, role } })
            .then((r) => r.data),
        '役割を外せませんでした',
      ),
    setAssignment: (courseId: string, body: unknown) =>
      run(
        () => teamApi.post<CourseDetail>(`lms/courses/${courseId}/assignments`, body).then((r) => r.data),
        '受講対象者を保存できませんでした',
      ),
    removeAssignment: (courseId: string, assignmentId: string) =>
      run(
        () =>
          teamApi.delete<CourseDetail>(`lms/courses/${courseId}/assignments/${assignmentId}`).then((r) => r.data),
        '受講対象者を外せませんでした',
      ),
    start: (courseId: string) =>
      run(() => teamApi.post<Enrollment>(`lms/learn/${courseId}/start`).then((r) => r.data), '受講を開始できませんでした'),
    progress: (enrollmentId: string, lessonId: string, body: unknown) =>
      run(
        () =>
          teamApi
            .post<Enrollment>(`lms/learn/${enrollmentId}/lessons/${lessonId}/progress`, body)
            .then((r) => r.data),
        '視聴記録を保存できませんでした',
      ),
    quiz: (enrollmentId: string, lessonId: string, answers: number[]) =>
      run(
        () =>
          teamApi
            .post<Enrollment>(`lms/learn/${enrollmentId}/lessons/${lessonId}/quiz`, { answers })
            .then((r) => r.data),
        '回答を送れませんでした',
      ),
    grade: (enrollmentId: string, lessonId: string, lessonStatus: string, scoreRaw: string) =>
      run(
        () =>
          teamApi
            .post(`lms/learn/${enrollmentId}/lessons/${lessonId}/grade`, {
              lesson_status: lessonStatus,
              score_raw: scoreRaw === '' ? null : Number(scoreRaw),
            })
            .then((r) => r.data),
        '実技の合否を保存できませんでした',
      ),
    renameMaterial: (materialId: string, title: string) =>
      run(() => teamApi.patch(`lms/materials/${materialId}`, { title }).then((r) => r.data), '名前を変更できませんでした'),
    hideMaterial: (materialId: string) =>
      run(() => teamApi.post(`lms/materials/${materialId}/hide`).then((r) => r.data), 'ゴミ箱へ移せませんでした'),
    restoreMaterial: (materialId: string) =>
      run(
        () => teamApi.post<Material>(`lms/materials/${materialId}/restore`).then((r) => r.data),
        '教材を戻せませんでした',
      ),
    deleteMaterial: (materialId: string) =>
      run(
        () => teamApi.delete<{ ok: boolean }>(`lms/materials/${materialId}`).then((r) => r.data),
        '教材を削除できませんでした',
      ),
    uploadMaterial: async (file: File, title: string, onProgress: (progress: MaterialUploadProgress) => void) => {
      const ext = file.name.toLowerCase();
      const kind = ext.endsWith('.pdf') ? 'slides' : 'video';
      setBusy(true);
      setError(null);
      let poll: ReturnType<typeof setInterval> | null = null;
      try {
        onProgress({
          phase: 'prepare',
          label: 'アップロードの準備をしています',
          detail: file.name,
          percent: 0,
        });
        const started = await teamApi.post<{ id: string }>('lms/materials/sessions', {
          title,
          filename: file.name,
          kind,
          contentType: file.type || 'application/octet-stream',
          size: file.size,
        });
        const sessionId = started.data.id;
        const chunkSize = 5 * 1024 * 1024;
        const parts = Math.max(1, Math.ceil(file.size / chunkSize));
        let sent = 0;
        for (let index = 0; index < parts; index += 1) {
          const chunk = file.slice(index * chunkSize, Math.min(file.size, (index + 1) * chunkSize));
          sent += chunk.size;
          onProgress({
            phase: 'upload',
            label: 'ファイルを送っています',
            detail: `${formatBytes(sent)} / ${formatBytes(file.size)}（${index + 1}/${parts}）`,
            percent: Math.min(100, Math.round((sent / file.size) * 100)),
          });
          await teamApi.putBinary(`lms/materials/sessions/${sessionId}`, chunk, {
            'Content-Type': 'application/octet-stream',
            'x-part-index': String(index),
          });
        }
        onProgress({
          phase: kind === 'slides' ? 'convert' : 'store',
          label: kind === 'slides' ? 'PDF をページごとの画像にしています' : '教材庫に登録しています',
          detail: kind === 'slides' ? 'PDF に書かれた配置のまま、各ページを画像にします。' : file.name,
          percent: null,
        });
        if (kind === 'slides') {
          poll = setInterval(() => {
            void teamApi
              .get<{ progress?: string }>(`lms/materials/sessions/${sessionId}`)
              .then((res) => {
                const text = res.data.progress?.trim();
                if (!text) {
                  return;
                }
                onProgress({
                  phase: text.startsWith('教材庫') || text.startsWith('ページ画像を保存') || text.startsWith('ファイルを保存')
                    ? 'store'
                    : 'convert',
                  label: text,
                  detail: 'この処理が終わるまで、画面を閉じないでください。',
                  percent: null,
                });
              })
              .catch(() => undefined);
          }, 700);
        }
        const done = await teamApi.post<Material>(`lms/materials/sessions/${sessionId}/complete`);
        onProgress({
          phase: 'store',
          label: '教材庫に登録しました',
          detail: file.name,
          percent: 100,
        });
        return done.data;
      } catch (e) {
        setError(errorMessage(e, '教材を置けませんでした'));
        return null;
      } finally {
        if (poll) {
          clearInterval(poll);
        }
        setBusy(false);
      }
    },
  };
};
