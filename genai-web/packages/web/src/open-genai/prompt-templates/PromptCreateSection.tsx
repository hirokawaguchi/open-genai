import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Textarea } from '@/components/ui/dads/Textarea';
import { extractVariables } from './templateVars';
import type { CreateTemplateInput, PromptShare, PromptTarget, PromptTeam } from './types';

type Props = {
  teams: PromptTeam[];
  canCreateStandard: boolean;
  submitting: boolean;
  error: string | null;
  onSubmit: (input: CreateTemplateInput) => Promise<boolean>;
};

/** 「作成」: 個人／チーム共有／全体公開／標準のテンプレートを追加する。 */
export const PromptCreateSection = ({
  teams,
  canCreateStandard,
  submitting,
  error,
  onSubmit,
}: Props) => {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [target, setTarget] = useState<PromptTarget>('content');
  const [share, setShare] = useState<PromptShare>('personal');
  const [shareTeam, setShareTeam] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const variables = extractVariables(body);

  const handleSubmit = async () => {
    setLocalError(null);
    setDone(false);
    if (!title.trim() || !body.trim()) {
      setLocalError('タイトルと本文を入力してください。');
      return;
    }
    if (share === 'team' && !shareTeam) {
      setLocalError('共有先チームを選択してください。');
      return;
    }
    const ok = await onSubmit({
      title: title.trim(),
      body,
      target,
      share,
      share_team: share === 'team' ? shareTeam : undefined,
    });
    if (ok) {
      setTitle('');
      setBody('');
      setTarget('content');
      setShare('personal');
      setShareTeam('');
      setDone(true);
    }
  };

  return (
    <div className='flex max-w-3xl flex-col gap-5'>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='create-title' size='sm'>
          タイトル
        </Label>
        <Input
          id='create-title'
          blockSize='md'
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='create-body' size='sm'>
          本文
        </Label>
        <SupportText>{'{{メモ}} のように {{ }} で変数を埋め込めます。'}</SupportText>
        <Textarea
          id='create-body'
          rows={8}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        {variables.length > 0 && (
          <SupportText>変数: {variables.map((v) => `{{${v}}}`).join(', ')}</SupportText>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='create-target' size='sm'>
          挿入先
        </Label>
        <Select
          id='create-target'
          blockSize='md'
          value={target}
          onChange={(e) => setTarget(e.target.value as PromptTarget)}
        >
          <option value='content'>入力欄（チャット本文）</option>
          <option value='system'>システムプロンプト</option>
        </Select>
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='create-share' size='sm'>
          共有範囲
        </Label>
        <Select
          id='create-share'
          blockSize='md'
          value={share}
          onChange={(e) => setShare(e.target.value as PromptShare)}
        >
          <option value='personal'>個人（自分のみ）</option>
          <option value='team'>チームで共有</option>
          <option value='public'>全体公開</option>
          {canCreateStandard && <option value='standard'>標準（管理者のみ）</option>}
        </Select>
      </div>

      {share === 'team' && (
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='create-share-team' size='sm'>
            共有先チーム
          </Label>
          {teams.length === 0 ? (
            <SupportText>所属しているチームがありません。</SupportText>
          ) : (
            <Select
              id='create-share-team'
              blockSize='md'
              value={shareTeam}
              onChange={(e) => setShareTeam(e.target.value)}
            >
              <option value=''>選択してください</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </Select>
          )}
        </div>
      )}

      {(localError || error) && <ErrorText>＊{localError ?? error}</ErrorText>}
      {done && (
        <p className='text-dns-16N-130 text-green-900' role='status'>
          テンプレートを作成しました。「使う」「管理」から確認できます。
        </p>
      )}

      <div>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          onClick={handleSubmit}
          aria-disabled={submitting || undefined}
        >
          {submitting ? '作成中...' : 'テンプレートを作成'}
        </Button>
      </div>
    </div>
  );
};
