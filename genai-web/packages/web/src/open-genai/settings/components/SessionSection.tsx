import { useEffect, useState } from 'react';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { SupportText } from '@/components/ui/dads/SupportText';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError, teamApi } from '@/lib/fetcher';
import { signOut } from '@/local/localAuth';

type SessionInfo = {
  authTime: number;
  absoluteExpiresAt: number;
  expiresAt?: number;
};

type RevokeResult = {
  revoked: number;
  identityProvider: 'ended' | 'skipped' | 'error';
};

const formatTime = (epochSec: number): string =>
  new Date(epochSec * 1000).toLocaleString('ja-JP', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

const errorText = (e: unknown, fallback: string): string => {
  if (isApiError(e)) {
    const data = e.data as { error?: string } | undefined;
    return data?.error || fallback;
  }
  return fallback;
};

/**
 * ログインの絶対期限と、コピーされたログインを切る操作。
 * 作業中の延長はサーバが期限の中だけで行う。
 */
export const SessionSection = () => {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [loadError, setLoadError] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void teamApi
      .get<SessionInfo>('auth/session')
      .then((res) => {
        if (!cancelled) {
          setInfo(res.data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError('ログイン期限を読み込めませんでした。');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const cutOthers = async () => {
    if (
      !window.confirm(
        'このブラウザ以外のログインを切ります。コピーされたログインも切れます。よろしいですか？',
      )
    ) {
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const res = await teamApi.post<RevokeResult>('auth/sessions/revoke-others');
      const revoked = res.data?.revoked ?? 0;
      const base =
        revoked > 0
          ? `${revoked}件のログインを切りました。このブラウザはそのまま使えます。`
          : 'ほかに切るログインはありませんでした。';
      const idp =
        res.data?.identityProvider === 'error'
          ? '庁内アカウントのセッションは切れませんでした。もう一度お試しください。'
          : '';
      setMessage(`${base}${idp}`);
    } catch (e) {
      setError(errorText(e, 'ログインを切れませんでした。'));
    } finally {
      setBusy(false);
    }
  };

  const cutAll = async () => {
    if (
      !window.confirm(
        'すべての端末のログインを切り、このブラウザもサインアウトします。よろしいですか？',
      )
    ) {
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const res = await teamApi.post<RevokeResult>('auth/sessions/revoke-all');
      if (res.data?.identityProvider === 'error') {
        window.alert(
          'アプリのログインは切りました。庁内アカウントのセッションは切れませんでした。サインアウトしたあと、もう一度ログインしてからやり直してください。',
        );
      }
      signOut();
    } catch (e) {
      if (isApiError(e) && e.status === 401) {
        signOut();
        return;
      }
      setError(errorText(e, 'ログインを切れませんでした。'));
      setBusy(false);
    }
  };

  return (
    <section className='flex flex-col gap-4 rounded-8 border border-solid-gray-300 bg-white p-5'>
      <div className='flex flex-col gap-1'>
        <h2 className='text-std-18B-160 text-solid-gray-900'>ログイン</h2>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          ログインは、利用者の少ない日本時間の午前4時に切れます。日中の作業の途中では切れません。午前4時の直前にログインしたときは、その次の午前4時まで有効です。
        </p>
      </div>
      {info && (
        <p className='text-std-16N-170 text-solid-gray-800'>
          このブラウザのログインは{' '}
          <span className='font-bold'>{formatTime(info.absoluteExpiresAt)}</span> まで有効です。
        </p>
      )}
      {loadError && <SupportText>{loadError}</SupportText>}
      <div className='flex flex-col gap-3'>
        <div className='flex flex-col gap-1'>
          <LoadingButton
            type='button'
            variant='outline'
            size='md'
            className='w-fit'
            loading={busy}
            disabled={busy}
            onClick={() => {
              void cutOthers();
            }}
          >
            ほかのログインを切る
          </LoadingButton>
          <SupportText>
            このブラウザはサインインしたまま、ほかの端末と、コピーされたログインを切ります。
          </SupportText>
        </div>
        <div className='flex flex-col gap-1'>
          <LoadingButton
            type='button'
            variant='outline'
            size='md'
            className='w-fit'
            loading={busy}
            disabled={busy}
            onClick={() => {
              void cutAll();
            }}
          >
            すべての端末からサインアウト
          </LoadingButton>
          <SupportText>このブラウザも含め、ログインをすべて切ります。</SupportText>
        </div>
      </div>
      {message && <p className='text-dns-16N-130 text-solid-gray-800'>{message}</p>}
      {error && <ErrorText>＊{error}</ErrorText>}
    </section>
  );
};
