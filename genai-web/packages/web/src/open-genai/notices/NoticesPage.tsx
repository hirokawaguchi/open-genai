import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router';
import useSWR from 'swr';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { isApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import { LayoutBody } from '@/layout/LayoutBody';

export type NoticeItem = {
  noticeId: string;
  scope: string;
  title?: string;
  body: string;
  createdDate?: string;
  updatedDate?: string;
  readOnly?: boolean;
};

export type NoticesResponse = {
  items?: NoticeItem[];
  canPostAll?: boolean;
  canPostTenant?: boolean;
};

const MAX_TITLE = 80;
const MAX_BODY = 4000;
const BANNER_LIMIT = 5;

const when = (value: string | undefined) => {
  const ms = Number(value);
  if (!ms) {
    return '';
  }
  return new Date(ms).toLocaleString('ja-JP', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  });
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

const scopeHint = (scope: 'all' | 'tenant') =>
  scope === 'all'
    ? 'すべての棟のトップページに出ます。'
    : 'いま開いている棟のトップページに出ます。';

const displayTitle = (item: NoticeItem) => {
  const title = (item.title || '').trim();
  if (title) {
    return title;
  }
  const line = item.body
    .split('\n')
    .map((part) => part.trim())
    .find(Boolean);
  return line || 'お知らせ';
};

const apiMessage = (err: unknown, fallback: string) => {
  const text =
    isApiError(err) && err.data && typeof err.data === 'object' && 'error' in err.data
      ? String((err.data as { error?: unknown }).error || '')
      : '';
  return text || fallback;
};

const canManage = (item: NoticeItem, data: NoticesResponse | undefined) =>
  !item.readOnly &&
  ((item.scope === 'all' && Boolean(data?.canPostAll)) ||
    (item.scope === 'tenant' && Boolean(data?.canPostTenant)));

export const useNotices = () =>
  useSWR<NoticesResponse>('notices', teamApiFetcher, { shouldRetryOnError: false });

const Composer = ({
  canAll,
  canTenant,
  onPosted,
}: {
  canAll: boolean;
  canTenant: boolean;
  onPosted: () => void;
}) => {
  const [scope, setScope] = useState<'all' | 'tenant'>(canTenant ? 'tenant' : 'all');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const choices: { value: 'all' | 'tenant'; label: string }[] = [];
  if (canTenant) {
    choices.push({ value: 'tenant', label: 'この棟' });
  }
  if (canAll) {
    choices.push({ value: 'all', label: '全体' });
  }

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await teamApi.post('notices', { scope, title, body });
      setTitle('');
      setBody('');
      onPosted();
    } catch (err) {
      setError(apiMessage(err, 'お知らせを保存できませんでした。'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className='rounded-8 border border-solid-gray-420 bg-white p-5'>
      <h2 className='text-std-18B-160 text-solid-gray-900'>新しく掲載</h2>
      {choices.length > 1 && (
        <div className='mt-4 flex flex-wrap gap-2' role='group' aria-label='掲載先'>
          {choices.map((choice) => (
            <button
              key={choice.value}
              type='button'
              aria-pressed={scope === choice.value}
              className={`min-h-9 rounded-8 border px-3 text-oln-16B-100 ${
                scope === choice.value
                  ? 'border-blue-900 bg-blue-50 text-blue-900'
                  : 'border-solid-gray-420 bg-white text-solid-gray-800'
              }`}
              onClick={() => setScope(choice.value)}
            >
              {choice.label}
            </button>
          ))}
        </div>
      )}
      {choices.length === 1 && (
        <p className='mt-3 text-dns-14B-130 text-solid-gray-800'>{choices[0]?.label}へのお知らせ</p>
      )}
      <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>{scopeHint(scope)}</p>
      <label className='mt-3 block text-dns-14B-130 text-solid-gray-800' htmlFor='notice-title'>
        タイトル
      </label>
      <input
        id='notice-title'
        className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2 text-dns-16N-170'
        value={title}
        maxLength={MAX_TITLE}
        onChange={(event) => setTitle(event.target.value)}
      />
      <label className='mt-3 block text-dns-14B-130 text-solid-gray-800' htmlFor='notice-body'>
        本文
      </label>
      <textarea
        id='notice-body'
        className='mt-1 min-h-28 w-full rounded-8 border border-solid-gray-420 p-3 text-dns-16N-170'
        value={body}
        maxLength={MAX_BODY}
        onChange={(event) => setBody(event.target.value)}
      />
      {error && <p className='mt-2 text-dns-14N-130 text-red-800'>{error}</p>}
      <div className='mt-3'>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          disabled={busy || !title.trim() || !body.trim()}
          onClick={() => void submit()}
        >
          掲載する
        </Button>
      </div>
    </section>
  );
};

export const NoticeBanner = () => {
  const { data } = useNotices();
  const items = data?.items ?? [];
  if (!items.length) {
    return null;
  }
  const shown = items.slice(0, BANNER_LIMIT);
  const rest = items.length - shown.length;
  return (
    <section className='mt-4 mb-4 rounded-8 border border-solid-gray-420 border-l-4 border-l-yellow-400 bg-yellow-50 px-4 py-2'>
      <div className='flex items-baseline justify-between gap-4'>
        <h2 className='text-dns-14B-130 text-solid-gray-800'>お知らせ</h2>
        <Link className='text-dns-14N-130 text-blue-900 underline' to='/notices'>
          一覧
        </Link>
      </div>
      <ul className='mt-1'>
        {shown.map((item) => (
          <li key={item.noticeId} className='flex min-w-0 items-baseline gap-3 py-1'>
            <span className='shrink-0 text-dns-14N-130 text-solid-gray-600'>{scopeLabel(item.scope)}</span>
            <Link
              className='min-w-0 truncate text-dns-16N-130 text-blue-900 underline'
              to={`/notices#${item.noticeId}`}
            >
              {displayTitle(item)}
            </Link>
            {when(item.createdDate) && (
              <span className='ml-auto shrink-0 text-dns-14N-130 text-solid-gray-600'>
                {when(item.createdDate)}
              </span>
            )}
          </li>
        ))}
      </ul>
      {rest > 0 && (
        <p className='py-1'>
          <Link className='text-dns-14N-130 text-blue-900 underline' to='/notices'>
            ほか {rest} 件
          </Link>
        </p>
      )}
    </section>
  );
};

export const NoticesPage = () => {
  const { data, mutate } = useNotices();
  const location = useLocation();
  const [error, setError] = useState('');
  const [openId, setOpenId] = useState('');
  const [editingId, setEditingId] = useState('');
  const [titleDraft, setTitleDraft] = useState('');
  const [bodyDraft, setBodyDraft] = useState('');
  const [confirmId, setConfirmId] = useState('');
  const [busyId, setBusyId] = useState('');
  const items = data?.items ?? [];

  useEffect(() => {
    const id = location.hash.replace(/^#/, '');
    if (id) {
      setOpenId(id);
    }
  }, [location.hash]);

  const save = async (noticeId: string) => {
    setBusyId(noticeId);
    setError('');
    try {
      await teamApi.put(`notices/${noticeId}`, { title: titleDraft, body: bodyDraft });
      setEditingId('');
      await mutate();
    } catch (err) {
      setError(apiMessage(err, 'お知らせを保存できませんでした。'));
    } finally {
      setBusyId('');
    }
  };

  const remove = async (noticeId: string) => {
    setBusyId(noticeId);
    setError('');
    try {
      await teamApi.delete(`notices/${noticeId}`);
      setConfirmId('');
      setOpenId('');
      await mutate();
    } catch (err) {
      setError(apiMessage(err, 'お知らせを削除できませんでした。'));
    } finally {
      setBusyId('');
    }
  };

  return (
    <LayoutBody>
      <PageTitle title='お知らせ' />
      <div className='mx-auto flex max-w-(--page-width) flex-col gap-8 px-6 py-8 lg:px-8'>
        <div>
          <h1 className='text-std-22B-150 text-solid-gray-900'>お知らせ</h1>
          <p className='mt-2 text-dns-16N-170 text-solid-gray-700'>
            トップページにはタイトルだけ出ます。本文はタイトルから開きます。
          </p>
        </div>
        {error && <p className='text-dns-14N-130 text-red-800'>{error}</p>}
        <ul className='overflow-hidden rounded-8 border border-solid-gray-300 bg-white'>
          {items.map((item) => {
            const manageable = canManage(item, data);
            const open = openId === item.noticeId;
            const editing = editingId === item.noticeId;
            return (
              <li key={item.noticeId} id={item.noticeId} className='border-b border-solid-gray-300 last:border-b-0'>
                <button
                  type='button'
                  className='flex w-full items-baseline gap-3 px-4 py-3 text-left hover:bg-solid-gray-50'
                  aria-expanded={open}
                  onClick={() => {
                    setOpenId(open ? '' : item.noticeId);
                    setConfirmId('');
                    if (editingId !== item.noticeId) {
                      setEditingId('');
                    }
                  }}
                >
                  <span className='shrink-0 text-dns-14N-130 text-solid-gray-600'>{scopeLabel(item.scope)}</span>
                  <span className='min-w-0 flex-1 truncate text-dns-16N-170 text-solid-gray-900'>
                    {displayTitle(item)}
                  </span>
                  {when(item.createdDate) && (
                    <span className='shrink-0 text-dns-14N-130 text-solid-gray-600'>{when(item.createdDate)}</span>
                  )}
                </button>
                {open && (
                  <div className='px-4 pb-4'>
                    {editing ? (
                      <div>
                        <label className='block text-dns-14B-130 text-solid-gray-800' htmlFor={`title-${item.noticeId}`}>
                          タイトル
                        </label>
                        <input
                          id={`title-${item.noticeId}`}
                          className='mt-1 w-full rounded-8 border border-solid-gray-420 px-3 py-2 text-dns-16N-170'
                          value={titleDraft}
                          maxLength={MAX_TITLE}
                          onChange={(event) => setTitleDraft(event.target.value)}
                        />
                        <label className='mt-3 block text-dns-14B-130 text-solid-gray-800' htmlFor={`body-${item.noticeId}`}>
                          本文
                        </label>
                        <textarea
                          id={`body-${item.noticeId}`}
                          className='mt-1 min-h-28 w-full rounded-8 border border-solid-gray-420 p-3 text-dns-16N-170'
                          value={bodyDraft}
                          maxLength={MAX_BODY}
                          onChange={(event) => setBodyDraft(event.target.value)}
                        />
                        <div className='mt-3 flex flex-wrap gap-2'>
                          <Button
                            type='button'
                            variant='solid-fill'
                            size='sm'
                            disabled={busyId === item.noticeId || !titleDraft.trim() || !bodyDraft.trim()}
                            onClick={() => void save(item.noticeId)}
                          >
                            保存する
                          </Button>
                          <Button type='button' variant='outline' size='sm' onClick={() => setEditingId('')}>
                            やめる
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <p className='whitespace-pre-wrap text-dns-16N-170 text-solid-gray-900'>{item.body}</p>
                    )}
                    {manageable && !editing && confirmId !== item.noticeId && (
                      <div className='mt-4 flex flex-wrap gap-2'>
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          onClick={() => {
                            setEditingId(item.noticeId);
                            setTitleDraft(item.title?.trim() ? item.title : displayTitle(item));
                            setBodyDraft(item.body);
                            setConfirmId('');
                          }}
                        >
                          編集
                        </Button>
                        <Button
                          type='button'
                          variant='text'
                          size='sm'
                          onClick={() => {
                            setConfirmId(item.noticeId);
                            setEditingId('');
                          }}
                        >
                          削除
                        </Button>
                      </div>
                    )}
                    {manageable && confirmId === item.noticeId && (
                      <div className='mt-4 flex flex-wrap items-center gap-3'>
                        <p className='text-dns-14N-130 text-solid-gray-800'>このお知らせを削除しますか。</p>
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          disabled={busyId === item.noticeId}
                          onClick={() => void remove(item.noticeId)}
                        >
                          削除する
                        </Button>
                        <Button type='button' variant='text' size='sm' onClick={() => setConfirmId('')}>
                          やめる
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
          {data && items.length === 0 && (
            <li className='px-4 py-5 text-dns-16N-170 text-solid-gray-600'>お知らせはありません。</li>
          )}
        </ul>
        {(data?.canPostAll || data?.canPostTenant) && (
          <Composer
            canAll={Boolean(data?.canPostAll)}
            canTenant={Boolean(data?.canPostTenant)}
            onPosted={() => void mutate()}
          />
        )}
      </div>
    </LayoutBody>
  );
};
