import { useEffect, useMemo, useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { SupportText } from '@/components/ui/dads/SupportText';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { ADMIN_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useTeamAuth } from '@/features/teams/hooks/useTeamAuth';
import { LayoutBody } from '@/layout/LayoutBody';
import { MODELPOLICY_EXAPP_ID } from '@/layout/navItems';
import { PageTitle } from '@/components/PageTitle';
import type { ModelPolicyConfig } from './types';
import { useModelPolicy, useModelPolicyActions } from './useModelPolicy';

const uniq = (list: string[]): string[] => Array.from(new Set(list.filter(Boolean)));

const toggle = (list: string[], value: string): string[] =>
  list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

export const ModelPolicyPage = () => {
  const { isSystemAdminGroup } = useTeamAuth();
  const { config, isLoading, forbidden, loadError, mutate } = useModelPolicy();
  const { save, submitting, error, setError } = useModelPolicyActions(mutate);

  const header = (
    <ManagedAppHeader
      teamId={ADMIN_EXAPPS_TEAM_ID}
      exAppId={MODELPOLICY_EXAPP_ID}
      fallbackTitle='モデル利用制御'
      fallbackDescription='利用可能な LLM をチーム単位で管理します（システム管理者のみ）。利用者は所属する各チームの許可モデルの和集合を使えます。'
      fallbackHowTo={
        <>
          <p>・「制御」を有効にすると、許可したモデルのみ利用できます（無効の間は全モデル利用可）。</p>
          <p>・「全ユーザー共通で許可」は全員が使えるモデルです。</p>
          <p>・「チーム別の追加許可」は各チームに追加で許可するモデルです。</p>
          <p>・システム管理者は常に全モデルを利用できます。</p>
        </>
      }
    />
  );

  if (!isSystemAdminGroup) {
    return (
      <LayoutBody>
        <PageTitle title='モデル利用制御' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          {header}
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には管理者権限が必要です。
          </p>
        </div>
      </LayoutBody>
    );
  }

  return (
    <LayoutBody>
      <PageTitle title='モデル利用制御' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        {header}

        {isLoading ? (
          <p className='text-std-16N-170 text-solid-gray-600'>読み込み中...</p>
        ) : forbidden ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には管理者権限が必要です。
          </p>
        ) : loadError || !config ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            {loadError ?? 'ポリシーを取得できませんでした。'}
          </p>
        ) : (
          <PolicyEditor
            config={config}
            submitting={submitting}
            error={error}
            setError={setError}
            onSave={save}
          />
        )}
      </div>
    </LayoutBody>
  );
};

type EditorProps = {
  config: ModelPolicyConfig;
  submitting: boolean;
  error: string | null;
  setError: (v: string | null) => void;
  onSave: (policy: ModelPolicyConfig['policy']) => Promise<boolean>;
};

const PolicyEditor = ({ config, submitting, error, setError, onSave }: EditorProps) => {
  const { policy, availableModels, teams } = config;

  const [enabled, setEnabled] = useState(policy.enabled);
  const [defaultModels, setDefaultModels] = useState<string[]>(policy.default);
  const [teamModels, setTeamModels] = useState<Record<string, string[]>>(policy.teams ?? {});
  const [extraModels, setExtraModels] = useState<string[]>([]);
  const [newModel, setNewModel] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [done, setDone] = useState(false);

  // config が変わった（保存後の再取得含む）ら編集状態を同期する。
  useEffect(() => {
    setEnabled(policy.enabled);
    setDefaultModels(policy.default);
    setTeamModels(policy.teams ?? {});
    setExtraModels([]);
    setDone(false);
  }, [policy]);

  const modelOptions = useMemo(() => {
    const configured = [
      ...availableModels,
      ...policy.default,
      ...Object.values(policy.teams ?? {}).flat(),
      ...extraModels,
    ];
    return uniq(configured).sort((a, b) => a.localeCompare(b));
  }, [availableModels, policy, extraModels]);

  const addModel = () => {
    const id = newModel.trim();
    if (id && !modelOptions.includes(id)) {
      setExtraModels((cur) => [...cur, id]);
    }
    setNewModel('');
  };

  const handleSave = async () => {
    setConfirmOpen(false);
    const cleanedTeams: Record<string, string[]> = {};
    for (const [tid, models] of Object.entries(teamModels)) {
      if (models.length > 0) {
        cleanedTeams[tid] = models;
      }
    }
    const ok = await onSave({
      ...policy,
      enabled,
      default: defaultModels,
      teams: cleanedTeams,
    });
    if (ok) {
      setDone(true);
    }
  };

  return (
    <div className='flex flex-col gap-6'>
      <fieldset className='flex flex-col gap-2'>
        <legend className='mb-1 text-std-16B-150'>制御</legend>
        <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'>
          <input
            type='checkbox'
            className='size-5'
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
              setError(null);
            }}
          />
          モデル利用制御を有効にする（許可モデルのみ利用可）
        </label>
        {!enabled && (
          <SupportText>無効の間は全ユーザーが全モデルを利用できます。</SupportText>
        )}
      </fieldset>

      <div className='flex flex-col gap-2'>
        <h2 className='text-std-16B-150'>全ユーザー共通で許可するモデル</h2>
        <ModelCheckboxGroup
          options={modelOptions}
          selected={defaultModels}
          onToggle={(m) => setDefaultModels((cur) => toggle(cur, m))}
        />
      </div>

      <div className='flex flex-col gap-3'>
        <h2 className='text-std-16B-150'>チーム別の追加許可</h2>
        {teams.length === 0 ? (
          <SupportText>
            設定対象のチームがありません。先に「チーム管理」でチームを作成してください。
          </SupportText>
        ) : (
          teams.map((team) => (
            <Disclosure
              key={team.id}
              className='rounded-8 border border-solid-gray-300 px-4 py-3'
            >
              <DisclosureSummary>
                <span className='text-std-16B-150'>
                  {team.name}
                  <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>
                    （{(teamModels[team.id] ?? []).length} モデル許可）
                  </span>
                </span>
              </DisclosureSummary>
              <div className='mt-3'>
                <ModelCheckboxGroup
                  options={modelOptions}
                  selected={teamModels[team.id] ?? []}
                  onToggle={(m) =>
                    setTeamModels((cur) => ({
                      ...cur,
                      [team.id]: toggle(cur[team.id] ?? [], m),
                    }))
                  }
                />
              </div>
            </Disclosure>
          ))
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='extra-model' size='sm'>
          一覧にないモデルIDを追加
        </Label>
        <SupportText>
          利用可能モデル一覧を取得できない場合などに、モデルIDを直接追加できます。
        </SupportText>
        <div className='flex gap-2'>
          <Input
            id='extra-model'
            blockSize='md'
            value={newModel}
            onChange={(e) => setNewModel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addModel();
              }
            }}
            className='flex-1'
          />
          <Button type='button' variant='outline' size='md' onClick={addModel}>
            追加
          </Button>
        </div>
      </div>

      {error && <ErrorText>＊{error}</ErrorText>}
      {done && (
        <p className='text-dns-16N-130 text-green-900' role='status'>
          ポリシーを保存しました。
        </p>
      )}

      <div>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          onClick={() => setConfirmOpen(true)}
          aria-disabled={submitting || undefined}
        >
          {submitting ? '保存中...' : '設定を保存'}
        </Button>
      </div>

      <CustomDialog isOpen={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setConfirmOpen(false)}>
            モデル利用ポリシーを保存
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170 text-solid-gray-800'>
              モデル利用ポリシーを上書き保存します。よろしいですか？
            </p>
            <div className='mt-6 flex justify-end gap-3'>
              <Button type='button' variant='outline' size='md' onClick={() => setConfirmOpen(false)}>
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
    </div>
  );
};

type GroupProps = {
  options: string[];
  selected: string[];
  onToggle: (model: string) => void;
};

const ModelCheckboxGroup = ({ options, selected, onToggle }: GroupProps) => {
  if (options.length === 0) {
    return <SupportText>選択できるモデルがありません。下の欄からモデルIDを追加してください。</SupportText>;
  }
  return (
    <div className='grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3'>
      {options.map((model) => (
        <label
          key={model}
          className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'
        >
          <input
            type='checkbox'
            className='size-5 flex-none'
            checked={selected.includes(model)}
            onChange={() => onToggle(model)}
          />
          <span className='truncate' title={model}>
            {model}
          </span>
        </label>
      ))}
    </div>
  );
};
