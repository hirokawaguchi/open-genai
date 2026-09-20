import { useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { useMyTenants } from '@/open-genai/tenants/useTenants';
import type { ApplyResult } from './types';
import { useUserMgmtActions } from './useUserMgmt';

type Props = {
  onCreated: () => void;
};

/** CSV フィールドを 1 つ安全に囲う（カンマ・引用符・改行を含む値に対応）。 */
const csvCell = (value: string): string => {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
};

const GROUP_OPTIONS = [
  { id: 'UserGroup', label: '一般利用者（UserGroup）' },
  { id: 'SystemAdminGroup', label: 'システム管理者（SystemAdminGroup）' },
];

/**
 * 利用者登録（単一）。棟を必須指定して 1 名を登録する。
 * 内部は CSV 一括処理と同じ apply 経路（backend が Keycloak 反映後に棟の主鍵を付ける）。
 */
export const UserCreateSection = ({ onCreated }: Props) => {
  const { orgTenants } = useMyTenants();
  const { apply, submitting, error, setError } = useUserMgmtActions();

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [group, setGroup] = useState('UserGroup');
  const [tenantId, setTenantId] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<ApplyResult | null>(null);

  const canSubmit = username.trim() !== '' && tenantId !== '' && !submitting;

  const buildCsv = (): string => {
    const header = 'action,username,email,name,password,groups,enabled,tenant';
    const row = [
      'create',
      username.trim(),
      email.trim(),
      name.trim(),
      password,
      group,
      'true',
      tenantId,
    ]
      .map(csvCell)
      .join(',');
    return `${header}\n${row}`;
  };

  const handleCreate = async () => {
    setConfirmOpen(false);
    setResult(null);
    const res = await apply(buildCsv());
    if (res && res.results[0]) {
      setResult(res.results[0]);
    }
  };

  const succeeded = result?.result === '作成' || result?.result === '更新';

  return (
    <div className='flex flex-col gap-5'>
      <SupportText>
        1 名を登録します。棟は必須です（先に「棟の管理」で棟を作成してください）。共有棟へは登録後に招待で付けます。
      </SupportText>

      <div className='grid gap-4 sm:grid-cols-2'>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='u-username' size='sm'>
            ユーザー名（ログイン ID）<RequirementBadge>※必須</RequirementBadge>
          </Label>
          <Input
            id='u-username'
            blockSize='md'
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='u-email' size='sm'>
            メールアドレス
          </Label>
          <Input
            id='u-email'
            type='email'
            blockSize='md'
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='u-name' size='sm'>
            氏名（姓 名）
          </Label>
          <Input id='u-name' blockSize='md' value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='u-password' size='sm'>
            初期パスワード
          </Label>
          <Input
            id='u-password'
            type='password'
            blockSize='md'
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='u-group' size='sm'>
            権限グループ
          </Label>
          <Select
            id='u-group'
            blockSize='md'
            value={group}
            onChange={(e) => setGroup(e.target.value)}
          >
            {GROUP_OPTIONS.map((g) => (
              <option key={g.id} value={g.id}>
                {g.label}
              </option>
            ))}
          </Select>
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='u-tenant' size='sm'>
            棟（所属先）<RequirementBadge>※必須</RequirementBadge>
          </Label>
          <Select
            id='u-tenant'
            blockSize='md'
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          >
            <option value=''>選択してください</option>
            {orgTenants.map((t) => (
              <option key={t.tenantId} value={t.tenantId}>
                {t.tenantName}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {error && <ErrorText>＊{error}</ErrorText>}

      <div className='flex flex-wrap items-center gap-3'>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          onClick={() => {
            setError(null);
            setConfirmOpen(true);
          }}
          aria-disabled={!canSubmit || undefined}
        >
          登録する
        </Button>
      </div>

      {result && (
        <div
          className={`rounded-8 border p-4 ${
            succeeded ? 'border-solid-gray-300' : 'border-error-1'
          }`}
          role='status'
        >
          <p className={succeeded ? 'text-std-16N-170' : 'text-std-16N-170 text-error-1'}>
            {succeeded
              ? `登録しました（${result.result}）。棟: ${result.tenantName || '-'}`
              : `登録できませんでした: ${result.note || result.result}`}
          </p>
          {succeeded && (
            <div className='mt-3'>
              <Button type='button' variant='outline' size='md' onClick={onCreated}>
                利用者一覧へ
              </Button>
            </div>
          )}
        </div>
      )}

      <CustomDialog isOpen={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setConfirmOpen(false)}>
            利用者を登録
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170 text-solid-gray-800'>
              「{username || '(未入力)'}」を Keycloak に作成し、選択した棟の一員にします。よろしいですか？
            </p>
            <div className='mt-6 flex justify-end gap-3'>
              <Button type='button' variant='outline' size='md' onClick={() => setConfirmOpen(false)}>
                キャンセル
              </Button>
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                onClick={handleCreate}
                aria-disabled={submitting || undefined}
              >
                {submitting ? '登録中...' : '登録する'}
              </Button>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </div>
  );
};
