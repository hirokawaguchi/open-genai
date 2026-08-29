import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import type { MyApplication } from '../types';
import { usePatchformApi } from '../PatchformApiContext';
import { GuestLogin } from './GuestLogin';
import { clearSession, readSession } from './guestSession';

const statusStyle = (status: string): string => {
  switch (status) {
    case '提出済':
    case '完了':
      return 'border-green-600 text-green-800';
    case '準備完了':
      return 'border-blue-600 text-blue-900';
    case '作業中':
      return 'border-yellow-700 text-yellow-800';
    case '取下げ':
      return 'border-solid-gray-420 text-solid-gray-600';
    default:
      return 'border-solid-gray-420 text-solid-gray-600';
  }
};

// 庁外「マイ手続き」一覧。外部セッションが無ければログイン画面を出す。
export const GuestMine = () => {
  const api = usePatchformApi();
  const session = readSession();
  const [apps, setApps] = useState<MyApplication[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      return;
    }
    void (async () => {
      try {
        const res = await api.get<{ applications: MyApplication[] }>(
          '/public/api/applications/mine',
        );
        setApps(res.data.applications || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : '一覧を取得できませんでした');
        setApps([]);
      }
    })();
  }, [api, session]);

  if (!session) {
    return <GuestLogin />;
  }

  return (
    <div>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h1 className='text-std-20B-160'>マイ手続き</h1>
        <div className='flex items-center gap-3'>
          <span className='text-dns-14N-130 text-solid-gray-600'>{session.email}</span>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={() => {
              clearSession();
              location.replace('/public/mine');
            }}
          >
            ログアウト
          </Button>
        </div>
      </div>

      <div className='mt-4'>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          onClick={() => {
            location.href = '/public/new';
          }}
        >
          新しい手続きを始める
        </Button>
      </div>

      {error && (
        <p className='mt-4 text-error-1' role='alert'>
          {error}
        </p>
      )}

      {apps === null ? (
        <p className='mt-6 hint text-solid-gray-700'>読み込み中...</p>
      ) : apps.length === 0 ? (
        <p className='mt-6 text-solid-gray-700'>
          まだ手続きがありません。「新しい手続きを始める」から作成してください。
        </p>
      ) : (
        <ul className='mt-6 divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
          {apps.map((a) => (
            <li key={a.id} className='py-3'>
              <div className='flex flex-wrap items-baseline justify-between gap-2'>
                <a
                  href={`/public/p/${encodeURIComponent(a.token)}?from=my`}
                  className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                >
                  {a.title || a.procedure_name}
                </a>
                <span
                  className={`inline-block whitespace-nowrap rounded-4 border px-2 py-0.5 text-dns-14N-130 ${statusStyle(a.status.effective)}`}
                >
                  {a.status.effective}
                </span>
              </div>
              <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                {a.procedure_name}
                {a.total > 0 ? ` ・ 提出 ${a.done}/${a.total}` : ''}
                {a.deadline ? ` ・ 期限 ${a.deadline}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
