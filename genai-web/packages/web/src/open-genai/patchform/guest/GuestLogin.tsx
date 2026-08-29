import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { usePatchformApi } from '../PatchformApiContext';

// 庁外「マイ手続き」のログイン。メールにマジックリンクを送る。
export const GuestLogin = () => {
  const api = usePatchformApi();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);

  const onSubmit = async () => {
    const value = email.trim();
    if (!value) {
      setError('メールアドレスを入力してください');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ dev_link?: string }>('/public/api/auth/request', {
        email: value,
      });
      setDevLink(res.data?.dev_link ?? null);
      setSent(true);
    } catch {
      // 列挙防止のためサーバは常に成功を返す。ネットワーク障害時のみここに来る。
      setError('送信に失敗しました。時間をおいて再度お試しください。');
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div>
        <h1 className='text-std-20B-160'>メールを確認してください</h1>
        <p className='mt-3 text-solid-gray-700'>
          {email} 宛にログイン用のリンクを送信しました。メール内のリンクを開くとログインが完了します。
        </p>
        <p className='mt-2 text-solid-gray-700'>リンクの有効期限は短めです。届かない場合は迷惑メールもご確認ください。</p>
        {devLink && (
          <div className='mt-4 rounded-8 border border-dashed border-amber-700 bg-amber-50 p-3'>
            <p className='text-dns-14N-130 text-solid-gray-700'>
              開発モード: メール未連携のため、下のリンクからログインできます。
            </p>
            <a
              href={devLink}
              className='mt-1 inline-block break-all text-blue-900 underline underline-offset-2'
            >
              このリンクでログイン
            </a>
          </div>
        )}
        <div className='mt-6'>
          <Button type='button' variant='outline' size='md' onClick={() => setSent(false)}>
            別のメールアドレスで送り直す
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className='text-std-20B-160'>マイ手続きにログイン</h1>
      <p className='mt-3 text-solid-gray-700'>
        メールアドレスを入力してください。ログイン用のリンクをお送りします。
      </p>
      <form
        className='mt-6'
        onSubmit={(e) => {
          e.preventDefault();
          void onSubmit();
        }}
      >
        <Label htmlFor='pf-ext-email' size='sm'>
          メールアドレス
        </Label>
        <input
          id='pf-ext-email'
          type='email'
          autoComplete='email'
          className='mt-1 w-full max-w-96 rounded-4 border border-solid-gray-420 px-3 py-2'
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        {error && (
          <p className='mt-2 text-error-1' role='alert'>
            {error}
          </p>
        )}
        <div className='mt-6'>
          <Button type='submit' variant='solid-fill' size='md' aria-disabled={busy}>
            {busy ? '送信中...' : 'ログイン用リンクを送る'}
          </Button>
        </div>
      </form>
    </div>
  );
};
