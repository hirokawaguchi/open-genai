import { useState } from 'react';
import { Link } from 'react-router';
import useSWR from 'swr';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { isApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import { LayoutBody } from '@/layout/LayoutBody';

export type NoticeItem = {
  noticeId: string;
  scope: string;
  body: string;
  createdDate?: string;
  readOnly?: boolean;
};

export type NoticesResponse = {
  items?: NoticeItem[];
  canPostAll?: boolean;
  canPostTenant?: boolean;
};

const when = (value: string | undefined) => {
  const ms = Number(value);
  if (!ms) {
    return '';
  }
  return new Date(ms).toLocaleString('ja-JP');
};

const scopeLabel = (scope: string) => {
  if (scope === 'all') {
    return '全体';
  }
  if (scope === 'tenant') {
    return 'この棟';
  }
  return '案内';
};

export const useNotices = () =>
  useSWR<NoticesResponse>('notices', teamApiFetcher, { shouldRetryOnError: false });

const Composer = ({
  scope,
  label,
  onPosted,
}: {
  scope: 'all' | 'tenant';
  label: string;
  onPosted: () => void;
}) => {
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await teamApi.post('notices', { scope, body });
      setBody('');
      onPosted();
    } catch (err) {
      const text =
        isApiError(err) && err.data && typeof err.data === 'object' && 'error' in err.data
          ? String((err.data as { error?: unknown }).error || '')
          : '';
      setError(text || 'お知らせを保存できませんでした。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className='flex flex-col gap-2'>
      <p className='text-dns-14B-130 text-solid-gray-800'>{label}</p>
      <textarea
        className='min-h-24 rounded-8 border border-solid-gray-420 p-3 text-dns-16N-130'
        value={body}
        maxLength={4000}
        onChange={(event) => setBody(event.target.value)}
      />
      {error && <p className='text-dns-14N-130 text-red-800'>{error}</p>}
      <div>
        <Button type='button' variant='solid-fill' size='md' disabled={busy || !body.trim()} onClick={() => void submit()}>
          掲載する
        </Button>
      </div>
    </div>
  );
};

export const NoticeBanner = () => {
  const { data } = useNotices();
  if (!data?.items?.length) {
    return null;
  }
  return (
    <p className='mb-6 rounded-8 border border-solid-gray-420 bg-yellow-50 px-4 py-3 text-dns-16N-130 text-solid-gray-900'>
      <Link className='underline' to='/notices'>
        お知らせがあります
      </Link>
    </p>
  );
};

export const NoticesPage = () => {
  const { data, mutate } = useNotices();
  const [error, setError] = useState('');

  const remove = async (noticeId: string) => {
    setError('');
    try {
      await teamApi.delete(`notices/${noticeId}`);
      await mutate();
    } catch {
      setError('お知らせを削除できませんでした。');
    }
  };

  return (
    <LayoutBody>
      <PageTitle title='お知らせ' />
      <div className='mx-auto flex max-w-(--page-width) flex-col gap-6 px-6 py-8 lg:px-8'>
        <h1 className='text-std-22B-150 text-solid-gray-900'>お知らせ</h1>
        {error && <p className='text-dns-14N-130 text-red-800'>{error}</p>}
        <ul className='flex flex-col gap-3'>
          {(data?.items ?? []).map((item) => (
            <li key={item.noticeId} className='rounded-8 border border-solid-gray-300 bg-white p-5'>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                {scopeLabel(item.scope)}
                {when(item.createdDate) ? ` ・ ${when(item.createdDate)}` : ''}
              </p>
              <p className='mt-2 whitespace-pre-wrap text-dns-16N-170 text-solid-gray-900'>{item.body}</p>
              {!item.readOnly &&
                ((item.scope === 'all' && data?.canPostAll) ||
                  (item.scope === 'tenant' && data?.canPostTenant)) && (
                <div className='mt-3'>
                  <Button type='button' variant='outline' size='sm' onClick={() => void remove(item.noticeId)}>
                    削除
                  </Button>
                </div>
              )}
            </li>
          ))}
          {data && (data.items ?? []).length === 0 && (
            <li className='text-dns-16N-130 text-solid-gray-600'>お知らせはありません。</li>
          )}
        </ul>
        {data?.canPostAll && (
          <Composer scope='all' label='全体へのお知らせ' onPosted={() => void mutate()} />
        )}
        {data?.canPostTenant && (
          <Composer scope='tenant' label='この棟へのお知らせ' onPosted={() => void mutate()} />
        )}
      </div>
    </LayoutBody>
  );
};
