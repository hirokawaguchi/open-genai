import { useEffect, useState } from 'react';
import type { Tenant, TenantMembership } from 'genai-web';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { useTeamAuth } from '@/features/teams/hooks/useTeamAuth';
import { LayoutBody } from '@/layout/LayoutBody';
import { isApiError } from '@/lib/fetcher';
import { OfficialAppRuntimeStatus } from '@/open-genai/official-apps/OfficialAppRuntimeStatus';
import { useOfficialAppRuntime } from '@/open-genai/official-apps/useOfficialAppRuntime';
import { useMyTenants, useTenantActions } from './useTenants';

const FEATURE_OPTIONS = [
  { id: 'chat', label: 'チャット' },
  { id: 'generate', label: '文章を生成' },
  { id: 'translate', label: '翻訳' },
  { id: 'image', label: '画像を生成' },
  { id: 'diagram', label: 'ダイアグラムを生成' },
  { id: 'whisper', label: '文字起こし' },
  { id: 'prompt', label: 'プロンプトテンプレート' },
  { id: 'chosei', label: '日程調整' },
  { id: 'doccheck', label: '書類読取とチェック' },
  { id: 'patchform', label: 'フォーム' },
  { id: 'docmaker', label: 'マイ手続き' },
  { id: 'procuretech-navigator', label: '情報化企画書ナビ' },
  { id: 'procuretech-editor', label: 'Markdown エディタ' },
  { id: 'knowledge', label: 'ナレッジ管理' },
  { id: 'rag', label: 'ナレッジ検索' },
  { id: 'notebook', label: 'ノートブック' },
  { id: 'ssh', label: 'SSH 端末' },
] as const;

const roleJa = (role: string) =>
  ({ primary: '主鍵', guest: '招待', shared: '共通鍵', admin: '管理' })[role] ?? role;

export const TenantsPage = () => {
  const { isSystemAdminGroup } = useTeamAuth();
  const { tenants, isLoading, isSystemAdmin, error: loadError } = useMyTenants();
  const actions = useTenantActions();
  const superAdmin = isSystemAdminGroup || isSystemAdmin;
  const adminTenants = superAdmin ? tenants : tenants.filter((t) => t.isAdmin);
  const canOpen = superAdmin || adminTenants.length > 0;
  const [selectedId, setSelectedId] = useState('');
  const [newName, setNewName] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteAdmin, setInviteAdmin] = useState(false);
  const [members, setMembers] = useState<TenantMembership[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const selected = adminTenants.find((t) => t.tenantId === selectedId) ?? adminTenants[0];

  useEffect(() => {
    if (selected && selected.tenantId !== selectedId) {
      setSelectedId(selected.tenantId);
    }
  }, [selected, selectedId]);

  useEffect(() => {
    if (!selected) {
      setMembers([]);
      return;
    }
    void actions.listMembers(selected.tenantId).then(setMembers).catch(() => setMembers([]));
  }, [selected?.tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn: () => Promise<void>) => {
    try {
      setError('');
      setBusy(true);
      await fn();
    } catch (e) {
      setError(
        isApiError(e)
          ? ((e.data as { error?: string })?.error ?? '操作に失敗しました')
          : '操作に失敗しました',
      );
    } finally {
      setBusy(false);
    }
  };

  if (isLoading && !canOpen) {
    return (
      <LayoutBody>
        <PageTitle title='棟の管理' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          <p>読み込み中...</p>
        </div>
      </LayoutBody>
    );
  }

  if (!canOpen) {
    return (
      <LayoutBody>
        <PageTitle title='棟の管理' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には棟の管理者権限が必要です。
          </p>
        </div>
      </LayoutBody>
    );
  }

  return (
    <LayoutBody>
      <PageTitle title='棟の管理' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-8 p-6 lg:p-8'>
        <p className='text-dns-16N-170 text-solid-gray-800'>
          テナント（棟）ごとにチームとナレッジを分けます。スーパー管理者は全棟を見られます。棟の管理者は、その棟の招待・機能・ナレッジ・アプリだけを扱います。
          棟を自分で作らなくても、「デフォルト」（今の組織）と「共有」は最初からあります。
        </p>
        {(error || loadError) && (
          <ErrorText>
            {error || '棟の一覧を取得できませんでした。ページを再読み込みしてください。'}
          </ErrorText>
        )}

        {superAdmin && (
          <section className='flex flex-col gap-3'>
            <h2 className='text-std-20B-150'>棟を追加</h2>
            <div className='flex flex-wrap items-end gap-3'>
              <div className='flex flex-col gap-1'>
                <Label htmlFor='new-tenant-name'>棟の名前</Label>
                <Input
                  id='new-tenant-name'
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
              </div>
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={busy || !newName.trim() || undefined}
                onClick={() =>
                  run(async () => {
                    const t = await actions.createTenant(newName.trim());
                    setNewName('');
                    setSelectedId(t.tenantId);
                  })
                }
              >
                作成
              </Button>
            </div>
          </section>
        )}

        {isLoading ? (
          <p>読み込み中...</p>
        ) : (
          <section className='flex flex-col gap-3'>
            <Label htmlFor='tenant-select'>編集する棟</Label>
            <Select
              id='tenant-select'
              value={selected?.tenantId ?? ''}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {adminTenants.length === 0 && (
                <option value=''>棟が読み込めていません</option>
              )}
              {adminTenants.map((t) => (
                <option key={t.tenantId} value={t.tenantId}>
                  {t.tenantName}
                  {t.kind === 'shared' ? '（共有）' : ''}
                </option>
              ))}
            </Select>
          </section>
        )}

        {selected && (
          <>
            <FeatureEditor
              tenant={selected}
              busy={busy}
              onSave={(features) =>
                run(async () => {
                  await actions.updateTenant(selected.tenantId, { features });
                })
              }
            />
            <section className='flex flex-col gap-3'>
              <h2 className='text-std-20B-150'>鍵を渡す</h2>
              <SupportText>
                メールで招待します。共有棟は共通鍵、ほかの棟は招待鍵になります。
              </SupportText>
              <div className='flex flex-wrap items-end gap-3'>
                <div className='flex flex-col gap-1'>
                  <Label htmlFor='invite-email'>メール</Label>
                  <Input
                    id='invite-email'
                    type='email'
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                  />
                </div>
                <label className='flex items-center gap-2 text-dns-16N-130'>
                  <input
                    type='checkbox'
                    checked={inviteAdmin}
                    onChange={(e) => setInviteAdmin(e.target.checked)}
                  />
                  棟の管理者にする
                </label>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='md'
                  aria-disabled={busy || !inviteEmail.trim() || undefined}
                  onClick={() =>
                    run(async () => {
                      await actions.inviteMember(selected.tenantId, inviteEmail.trim(), {
                        isAdmin: inviteAdmin,
                      });
                      setInviteEmail('');
                      setInviteAdmin(false);
                      setMembers(await actions.listMembers(selected.tenantId));
                    })
                  }
                >
                  招待
                </Button>
              </div>
              <ul className='flex flex-col gap-2'>
                {members.map((m) => (
                  <li
                    key={`${m.tenantId}-${m.userId}`}
                    className='flex flex-wrap items-center justify-between gap-2 rounded-8 border border-solid-gray-420 px-3 py-2'
                  >
                    <span>
                      {m.userId}（{roleJa(m.role)}
                      {m.isAdmin ? '・管理者' : ''}）
                    </span>
                    <Button
                      type='button'
                      size='sm'
                      variant='outline'
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await actions.removeMember(selected.tenantId, m.userId);
                          setMembers(await actions.listMembers(selected.tenantId));
                        })
                      }
                    >
                      鍵を回収
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </LayoutBody>
  );
};

const FeatureEditor = ({
  tenant,
  busy,
  onSave,
}: {
  tenant: Tenant;
  busy: boolean;
  onSave: (features: Record<string, boolean>) => void;
}) => {
  const [features, setFeatures] = useState<Record<string, boolean>>(tenant.features ?? {});
  const { running } = useOfficialAppRuntime();
  useEffect(() => {
    setFeatures(tenant.features ?? {});
  }, [tenant.tenantId, tenant.features]);

  return (
    <section className='flex flex-col gap-3'>
      <h2 className='text-std-20B-150'>この棟で出す機能</h2>
      <SupportText>
        オフにすると、この棟のカタログとメニューから隠れます。未設定はすべて出します。ここには存在する公式アプリをすべて出します。未起動は利用者のメニューには出ません。監査などの管理者ツールは対象外です。
      </SupportText>
      <div className='flex flex-col gap-2'>
        {FEATURE_OPTIONS.map((opt) => (
          <label key={opt.id} className='flex items-center gap-2 text-dns-16N-130'>
            <input
              type='checkbox'
              checked={features[opt.id] !== false}
              onChange={(e) =>
                setFeatures((prev) => ({ ...prev, [opt.id]: e.target.checked }))
              }
            />
            <span>{opt.label}</span>
            <OfficialAppRuntimeStatus id={opt.id} running={running} />
          </label>
        ))}
      </div>
      <Button
        type='button'
        variant='solid-fill'
        size='md'
        aria-disabled={busy || undefined}
        onClick={() => onSave(features)}
      >
        機能の設定を保存
      </Button>
    </section>
  );
};
