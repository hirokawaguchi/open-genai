import { useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Checkbox } from '@/components/ui/dads/Checkbox';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import type { ManagedUser } from './types';
import { useUserMgmtActions } from './useUserMgmt';

type Props = {
  user: ManagedUser;
  isSystemAdmin: boolean;
  onClose: () => void;
  onSaved: () => void;
};

const GROUP_OPTIONS = [
  { id: 'UserGroup', label: '一般利用者（UserGroup）' },
  { id: 'SystemAdminGroup', label: 'システム管理者（SystemAdminGroup）' },
];

/** 姓・名が別々に無ければ、表示名「姓 名」を分けて初期値にする。 */
const namesOf = (user: ManagedUser): { lastName: string; firstName: string } => {
  const last = (user.lastName ?? '').trim();
  const first = (user.firstName ?? '').trim();
  if (last || first) {
    return { lastName: last, firstName: first };
  }
  const parts = (user.name ?? '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return { lastName: '', firstName: '' };
  }
  if (parts.length === 1) {
    return { lastName: parts[0], firstName: '' };
  }
  return { lastName: parts[0], firstName: parts.slice(1).join(' ') };
};

/** CSV フィールドを 1 つ安全に囲う（カンマ・引用符・改行を含む値に対応）。 */
const csvCell = (value: string): string => {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
};

/**
 * 利用者 1 名の変更。ログイン名とメールアドレスは表示のみ。
 * 権限グループは UserGroup と SystemAdminGroup を入れ替える（CSV の足すだけとは別）。
 */
export const UserEditDialog = ({ user, isSystemAdmin, onClose, onSaved }: Props) => {
  const { apply, submitting, error, setError } = useUserMgmtActions();
  const groupOptions = isSystemAdmin
    ? GROUP_OPTIONS
    : GROUP_OPTIONS.filter((g) => g.id === 'UserGroup');
  const initialNames = namesOf(user);
  const email = (user.email || '').trim();
  const [lastName, setLastName] = useState(initialNames.lastName);
  const [firstName, setFirstName] = useState(initialNames.firstName);
  const [group, setGroup] = useState(
    isSystemAdmin && user.groups.includes('SystemAdminGroup') ? 'SystemAdminGroup' : 'UserGroup',
  );
  const [enabled, setEnabled] = useState(user.enabled);
  const [password, setPassword] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  const buildCsv = (): string => {
    const header =
      'action,username,email,lastName,firstName,password,groups,enabled,groupsMode';
    const row = [
      'update',
      user.username,
      email,
      lastName.trim(),
      firstName.trim(),
      password,
      group,
      enabled ? 'true' : 'false',
      'replace',
    ]
      .map(csvCell)
      .join(',');
    return `${header}\n${row}`;
  };

  const handleSave = async () => {
    if (!lastName.trim()) {
      setLocalError('姓を入力してください。');
      return;
    }
    setLocalError(null);
    setError(null);
    const res = await apply(buildCsv());
    const row = res?.results[0];
    if (!row) {
      return;
    }
    if (row.result === '更新') {
      onSaved();
      return;
    }
    setLocalError(row.note || row.result || '変更できませんでした。');
  };

  return (
    <CustomDialog isOpen onClose={onClose}>
      <CustomDialogPanel>
        <CustomDialogHeader hasClose onClose={onClose}>
          利用者を変更
        </CustomDialogHeader>
        <CustomDialogBody>
          <div className='grid gap-4 sm:grid-cols-2'>
            <div className='flex flex-col gap-1.5'>
              <Label size='sm'>ユーザー名（ログイン ID）</Label>
              <p className='text-std-16N-170 text-solid-gray-800'>{user.username || '-'}</p>
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label size='sm'>メールアドレス</Label>
              <p className='text-std-16N-170 text-solid-gray-800'>{email || '-'}</p>
              <SupportText>メールアドレスは変更できません。</SupportText>
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='edit-last' size='sm'>
                姓<RequirementBadge>※必須</RequirementBadge>
              </Label>
              <Input
                id='edit-last'
                blockSize='md'
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
              />
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='edit-first' size='sm'>
                名
              </Label>
              <Input
                id='edit-first'
                blockSize='md'
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
              />
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='edit-group' size='sm'>
                権限グループ
              </Label>
              <Select
                id='edit-group'
                blockSize='md'
                value={group}
                onChange={(e) => setGroup(e.target.value)}
              >
                {groupOptions.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='edit-password' size='sm'>
                初期パスワード
              </Label>
              <Input
                id='edit-password'
                type='password'
                blockSize='md'
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <SupportText>空欄のままなら変更しません。</SupportText>
            </div>
            <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)}>
              有効
            </Checkbox>
          </div>

          {(localError || error) && <ErrorText>＊{localError || error}</ErrorText>}

          <div className='mt-6 flex justify-end gap-3'>
            <Button type='button' variant='outline' size='md' onClick={onClose}>
              キャンセル
            </Button>
            <Button
              type='button'
              variant='solid-fill'
              size='md'
              onClick={handleSave}
              aria-disabled={submitting || undefined}
            >
              {submitting ? '保存中...' : '保存する'}
            </Button>
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
