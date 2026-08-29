import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import type { Application, Procedure } from '../types';
import { usePatchformApi } from '../PatchformApiContext';
import { GuestLogin } from './GuestLogin';
import { readSession } from './guestSession';

// 庁外の新規プロジェクト作成。公開手続きを選び、空のプロジェクトを作って作業台へ。
// 案内（ナビ）フォームは作業台の先頭「記入必須」枠で回答し、必要書類が確定する。
export const GuestWizard = () => {
  const api = usePatchformApi();
  const session = readSession();
  const [procedures, setProcedures] = useState<Procedure[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      return;
    }
    void (async () => {
      try {
        const res = await api.get<{ procedures: Procedure[] }>('/public/api/procedures');
        setProcedures(res.data.procedures || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : '手続き一覧を取得できませんでした');
        setProcedures([]);
      }
    })();
  }, [api, session]);

  if (!session) {
    return <GuestLogin />;
  }

  const onStart = async (proc: Procedure) => {
    setBusyId(proc.id);
    setError(null);
    try {
      const res = await api.post<Application>('/public/api/applications', {
        procedure_id: proc.id,
      });
      const token = res.data.token;
      if (token) {
        location.href = `/public/p/${encodeURIComponent(token)}?from=my`;
        return;
      }
      setError('作成に失敗しました');
    } catch (e) {
      setError(e instanceof Error ? e.message : '作成に失敗しました');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h1 className='text-std-20B-160'>新しい手続きを始める</h1>
        <a href='/public/mine' className='text-blue-900 underline-offset-2 hover:underline'>
          マイ手続きに戻る
        </a>
      </div>
      <p className='mt-3 text-solid-gray-700'>
        始める手続きを選んでください。次の画面で案内に答えると、必要な書類が表示されます。
      </p>

      {error && (
        <p className='mt-4 text-error-1' role='alert'>
          {error}
        </p>
      )}

      {procedures === null ? (
        <p className='mt-6 hint text-solid-gray-700'>読み込み中...</p>
      ) : procedures.length === 0 ? (
        <p className='mt-6 text-solid-gray-700'>公開中の手続きがありません。</p>
      ) : (
        <ul className='mt-6 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
          {procedures.map((p) => (
            <li key={p.id} className='flex flex-wrap items-center justify-between gap-3 py-4'>
              <div>
                <p className='text-std-16B-150'>{p.name}</p>
                {p.description ? (
                  <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>{p.description}</p>
                ) : null}
              </div>
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={busyId === p.id}
                onClick={() => void onStart(p)}
              >
                {busyId === p.id ? '作成中...' : 'これを始める'}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
