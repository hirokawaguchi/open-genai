import { useState } from 'react';
import useSWR from 'swr';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { ApiError, teamApi } from '@/lib/fetcher';
import { useUsers } from './useUserMgmt';

type TokenRow = {
  id: string;
  userId: string;
  label: string;
  createdAt: number;
  revokedAt: number | null;
  lastUsedAt: number | null;
};

const when = (unix: number | null): string => {
  if (!unix) {
    return '—';
  }
  return new Date(unix * 1000).toLocaleString('ja-JP');
};

const messageOf = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

/**
 * 外部システムが台帳だけを呼ぶためのトークン。
 * 発行した文字列はこの画面で一度だけ見せる。公開の手順書には載せない。
 */
export const ServiceTokenSection = () => {
  const { users, isLoading } = useUsers('', 200);
  const { data, mutate } = useSWR<{ tokens: TokenRow[] }>(
    'admin/users/service-tokens',
    (path: string) => teamApi.get<{ tokens: TokenRow[] }>(path).then((res) => res.data),
    { revalidateOnFocus: false },
  );
  const [email, setEmail] = useState('');
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const candidates = users.filter((user) => user.enabled && !user.groups.includes('SystemAdminGroup'));

  const issue = async () => {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const user = candidates.find((row) => row.email === email);
      const res = await teamApi.post<{ token: string }>('admin/users/service-tokens', {
        email,
        label,
        groups: user?.groups ?? [],
      });
      setIssued(res.data.token);
      setLabel('');
      await mutate();
    } catch (e) {
      setError(messageOf(e, '発行できませんでした。'));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    setError(null);
    try {
      await teamApi.post(`admin/users/service-tokens/${id}/revoke`, {});
      await mutate();
    } catch (e) {
      setError(messageOf(e, '失効できませんでした。'));
    }
  };

  const copy = async () => {
    if (!issued) {
      return;
    }
    await navigator.clipboard.writeText(issued);
    setCopied(true);
  };

  return (
    <div className='flex flex-col gap-8'>
      <div className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-800'>
        <p>外部のシステムが、ブラウザを開かずに台帳を読む・書くためのトークンです。</p>
        <p>1. 利用者登録で、一般利用者としてアカウントを作ります。システム管理者にはしません。</p>
        <p>2. その利用者を対象のチームに入れ、台帳のアクセス権設定で読み書きか読み取りを付けます。</p>
        <p>3. ここで名前を付けて発行します。文字列は今だけ表示します。外部システムは Authorization の Bearer に載せて /ledger を呼びます。</p>
        <p>台帳以外には使えません。漏れたらその1枚を失効し、新しい1枚を渡します。</p>
      </div>

      <div className='flex max-w-xl flex-col gap-4'>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='service-token-user'>利用者</Label>
          <Select
            id='service-token-user'
            blockSize='md'
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          >
            <option value=''>{isLoading ? '読み込み中' : '選んでください'}</option>
            {candidates.map((user) => (
              <option key={user.id} value={user.email}>
                {user.name || user.username}（{user.email}）
              </option>
            ))}
          </Select>
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='service-token-label'>名前</Label>
          <Input
            id='service-token-label'
            blockSize='md'
            value={label}
            maxLength={80}
            placeholder='財務システムの取込'
            onChange={(e) => setLabel(e.target.value)}
          />
          <SupportText>どのシステム用か分かる名前にします。</SupportText>
        </div>
        <div>
          <Button
            type='button'
            size='md'
            variant='solid-fill'
            aria-disabled={busy || !email || !label.trim() ? true : undefined}
            onClick={() => {
              if (busy || !email || !label.trim()) {
                return;
              }
              void issue();
            }}
          >
            発行する
          </Button>
        </div>
        {error ? <ErrorText>{error}</ErrorText> : null}
      </div>

      {issued ? (
        <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-420 bg-solid-gray-50 p-4'>
          <p className='text-std-16B-160 text-solid-gray-900'>発行したトークン</p>
          <p className='text-dns-14N-130 text-solid-gray-700'>この画面を離れると、もう表示できません。</p>
          <p className='break-all font-mono text-dns-14N-130 text-solid-gray-900'>{issued}</p>
          <div>
            <Button type='button' size='sm' variant='outline' onClick={() => void copy()}>
              {copied ? 'コピーしました' : 'コピーする'}
            </Button>
          </div>
        </div>
      ) : null}

      <div className='flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>発行済み</h3>
        <div className='overflow-x-auto border border-solid-gray-420'>
          <table className='w-full min-w-[40rem] border-collapse text-left'>
            <thead className='bg-solid-gray-50 text-dns-14B-130 text-solid-gray-700'>
              <tr>
                <th className='px-3 py-2 font-normal'>名前</th>
                <th className='px-3 py-2 font-normal'>利用者</th>
                <th className='px-3 py-2 font-normal'>発行</th>
                <th className='px-3 py-2 font-normal'>最終利用</th>
                <th className='px-3 py-2 font-normal'>状態</th>
                <th className='px-3 py-2 font-normal' />
              </tr>
            </thead>
            <tbody>
              {(data?.tokens ?? []).map((row) => (
                <tr key={row.id} className='border-t border-solid-gray-420 text-dns-14N-130'>
                  <td className='px-3 py-2'>{row.label}</td>
                  <td className='px-3 py-2'>{row.userId}</td>
                  <td className='px-3 py-2'>{when(row.createdAt)}</td>
                  <td className='px-3 py-2'>{when(row.lastUsedAt)}</td>
                  <td className='px-3 py-2'>{row.revokedAt ? '失効' : '有効'}</td>
                  <td className='px-3 py-2 text-right'>
                    {row.revokedAt ? null : (
                      <Button type='button' size='sm' variant='outline' onClick={() => void revoke(row.id)}>
                        失効する
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {(data?.tokens ?? []).length === 0 ? (
                <tr>
                  <td className='px-3 py-4 text-solid-gray-600' colSpan={6}>
                    まだありません。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
