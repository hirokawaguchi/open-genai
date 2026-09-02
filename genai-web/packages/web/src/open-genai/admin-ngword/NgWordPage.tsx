import { useEffect, useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Label } from '@/components/ui/dads/Label';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Textarea } from '@/components/ui/dads/Textarea';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { ADMIN_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useTeamAuth } from '@/features/teams/hooks/useTeamAuth';
import { LayoutBody } from '@/layout/LayoutBody';
import { NGWORD_EXAPP_ID } from '@/layout/navItems';
import { PageTitle } from '@/components/PageTitle';
import type { NgWordRules } from './types';
import { useNgword, useNgwordActions } from './useNgword';

const toLines = (text: string): string[] =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

/** 各行の正規表現を検証し、不正なものがあれば最初の行を返す。 */
const findInvalidPattern = (text: string): string | null => {
  for (const line of toLines(text)) {
    try {
      new RegExp(line);
    } catch {
      return line;
    }
  }
  return null;
};

export const NgWordPage = () => {
  const { isSystemAdminGroup } = useTeamAuth();
  const { rules, isLoading, forbidden, loadError, mutate } = useNgword();
  const { save, submitting, error, setError } = useNgwordActions(mutate);

  const header = (
    <ManagedAppHeader
      teamId={ADMIN_EXAPPS_TEAM_ID}
      exAppId={NGWORD_EXAPP_ID}
      fallbackTitle='入力制限（禁止ワード・機密情報）'
      fallbackDescription='チャット・AIアプリの入力に対する禁止ワード・機密情報の制限を設定します（システム管理者のみ）。有効時、推論前に入力を検査し該当時はブロックします。'
      fallbackHowTo={
        <>
          <p>・「入力制限」を有効にすると、禁止ワード・機密情報を含む入力をブロックします。</p>
          <p>・禁止ワードは1行に1語、機密情報パターンは1行に1つの正規表現で入力します。</p>
          <p>・マイナンバー検査は検査用数字が一致する12桁のみブロックします（単なる12桁数字では止めません）。</p>
          <p>・添付アップロード時の警告とナレッジ登録時の検知は、氏名・住所・電話・マイナンバーを種別付きで表示します（ブロックしません）。</p>
          <p>・システム管理者による管理系アプリの実行は本制限の対象外です。</p>
        </>
      }
    />
  );

  if (!isSystemAdminGroup) {
    return (
      <LayoutBody>
        <PageTitle title='入力制限（禁止ワード）' />
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
      <PageTitle title='入力制限（禁止ワード）' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        {header}

        {isLoading ? (
          <p className='text-std-16N-170 text-solid-gray-600'>読み込み中...</p>
        ) : forbidden ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧には管理者権限が必要です。
          </p>
        ) : loadError || !rules ? (
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            {loadError ?? 'ルールを取得できませんでした。'}
          </p>
        ) : (
          <RulesEditor
            rules={rules}
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
  rules: NgWordRules;
  submitting: boolean;
  error: string | null;
  setError: (v: string | null) => void;
  onSave: (rules: NgWordRules) => Promise<boolean>;
};

const RulesEditor = ({ rules, submitting, error, setError, onSave }: EditorProps) => {
  const [enabled, setEnabled] = useState(rules.enabled);
  const [caseSensitive, setCaseSensitive] = useState(rules.case_sensitive);
  const [checkMynumber, setCheckMynumber] = useState(rules.check_mynumber);
  const [warnAttachments, setWarnAttachments] = useState(rules.warn_attachments ?? true);
  const [scanKnowledgePii, setScanKnowledgePii] = useState(rules.scan_knowledge_pii ?? true);
  const [checkPiiNer, setCheckPiiNer] = useState(rules.check_pii_ner ?? true);
  const [words, setWords] = useState((rules.words ?? []).join('\n'));
  const [patterns, setPatterns] = useState((rules.patterns ?? []).join('\n'));
  const [localError, setLocalError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setEnabled(rules.enabled);
    setCaseSensitive(rules.case_sensitive);
    setCheckMynumber(rules.check_mynumber);
    setWarnAttachments(rules.warn_attachments ?? true);
    setScanKnowledgePii(rules.scan_knowledge_pii ?? true);
    setCheckPiiNer(rules.check_pii_ner ?? true);
    setWords((rules.words ?? []).join('\n'));
    setPatterns((rules.patterns ?? []).join('\n'));
    setDone(false);
  }, [rules]);

  const openConfirm = () => {
    setLocalError(null);
    setDone(false);
    const invalid = findInvalidPattern(patterns);
    if (invalid) {
      setLocalError(`正規表現が不正です: ${invalid}`);
      return;
    }
    setConfirmOpen(true);
  };

  const handleSave = async () => {
    setConfirmOpen(false);
    const ok = await onSave({
      enabled,
      case_sensitive: caseSensitive,
      check_mynumber: checkMynumber,
      warn_attachments: warnAttachments,
      scan_knowledge_pii: scanKnowledgePii,
      check_pii_ner: checkPiiNer,
      words: toLines(words),
      patterns: toLines(patterns),
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
          入力制限を有効にする（禁止ワード・機密情報を含む入力をブロック）
        </label>
        {!enabled && <SupportText>無効の間は入力を制限しません。</SupportText>}
      </fieldset>

      <fieldset className='flex flex-col gap-2'>
        <legend className='mb-1 text-std-16B-150'>検査オプション</legend>
        <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'>
          <input
            type='checkbox'
            className='size-5'
            checked={caseSensitive}
            onChange={(e) => setCaseSensitive(e.target.checked)}
          />
          禁止ワードの大文字小文字を区別する
        </label>
        <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'>
          <input
            type='checkbox'
            className='size-5'
            checked={checkMynumber}
            onChange={(e) => setCheckMynumber(e.target.checked)}
          />
          マイナンバー検査を行う（検査用数字が一致する12桁のみ）
        </label>
        <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'>
          <input
            type='checkbox'
            className='size-5'
            checked={warnAttachments}
            onChange={(e) => setWarnAttachments(e.target.checked)}
          />
          添付アップロード時に個人情報を警告する（氏名・住所・電話・マイナンバー）
        </label>
        <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'>
          <input
            type='checkbox'
            className='size-5'
            checked={scanKnowledgePii}
            onChange={(e) => setScanKnowledgePii(e.target.checked)}
          />
          ナレッジ登録時に個人情報を検知する（管理画面にラベル表示）
        </label>
        <label className='flex items-center gap-2 text-std-16N-170 text-solid-gray-900'>
          <input
            type='checkbox'
            className='size-5'
            checked={checkPiiNer}
            onChange={(e) => setCheckPiiNer(e.target.checked)}
          />
          氏名・住所の NER 検知を行う（GiNZA。未導入時は電話・マイナンバーと住所パターンのみ）
        </label>
      </fieldset>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='ng-words' size='sm'>
          禁止ワード（1行に1語）
        </Label>
        <SupportText>入力に含まれるとブロックする語を改行区切りで指定します。</SupportText>
        <Textarea
          id='ng-words'
          rows={6}
          value={words}
          onChange={(e) => setWords(e.target.value)}
        />
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='ng-patterns' size='sm'>
          機密情報パターン（1行に1正規表現）
        </Label>
        <SupportText>
          任意の正規表現。マイナンバーは上の専用検査を使ってください（{'\\d{12}'} 単体は専用検査へ委譲されます）。
        </SupportText>
        <Textarea
          id='ng-patterns'
          rows={6}
          value={patterns}
          onChange={(e) => setPatterns(e.target.value)}
          className='font-mono'
        />
      </div>

      {(localError || error) && <ErrorText>＊{localError ?? error}</ErrorText>}
      {done && (
        <p className='text-dns-16N-130 text-green-900' role='status'>
          入力制限ルールを保存しました。
        </p>
      )}

      <div>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          onClick={openConfirm}
          aria-disabled={submitting || undefined}
        >
          {submitting ? '保存中...' : '設定を保存'}
        </Button>
      </div>

      <CustomDialog isOpen={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setConfirmOpen(false)}>
            入力制限ルールを保存
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170 text-solid-gray-800'>
              入力制限ルールを上書き保存します。よろしいですか？
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
