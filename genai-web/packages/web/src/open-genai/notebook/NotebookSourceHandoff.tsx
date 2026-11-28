import { useId, useState } from 'react';
import { useNavigate } from 'react-router';
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
import { Radio } from '@/components/ui/dads/Radio';
import { Select } from '@/components/ui/dads/Select';
import { useMyTenants } from '@/open-genai/tenants/useTenants';
import { useNotebookActions, useNotebookSessions } from './useNotebook';

type Props = {
  text?: string;
  filename?: string;
  titlePrefix: string;
  /** チャットの回答列は短い文字ボタン、それ以外は枠付き。 */
  appearance?: 'outline' | 'text';
  label?: string;
  /** 画像や図など、文章ファイル以外を置くとき。失敗したらエラー文を返す。 */
  commit?: (sessionId: string) => Promise<string | null>;
};

export const datedNoteTitle = (prefix: string) => {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${prefix} ${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const LEAD_CHARS = 20;

/** 種類のあとに本文の先頭を付け、同じノートでもファイルを見分ける。 */
export const sourceFilename = (filename: string, text: string) => {
  const slash = filename.replace(/\\/g, '/').split('/').pop() || '資料.md';
  const dot = slash.lastIndexOf('.');
  const ext = dot > 0 ? slash.slice(dot) : '.md';
  const base = (dot > 0 ? slash.slice(0, dot) : slash).trim() || '資料';
  const plain = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)]\([^)]*\)/g, '$1')
    .replace(/[#>*_`]/g, ' ')
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const head = Array.from(plain)
    .slice(0, LEAD_CHARS)
    .join('')
    .trim()
    .replace(/[.．。 ]+$/u, '');
  if (!head) return `${base}${ext}`;
  return `${base}-${head}${ext}`;
};

const textToBase64 = (text: string) => {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
};

/** 文章をノートの参考資料にして、そのノートを開く。 */
export const NotebookSourceHandoff = (props: Props) => {
  const {
    text = '',
    filename = '資料.md',
    titlePrefix,
    appearance = 'outline',
    label = 'ノートブックで扱う',
    commit,
  } = props;
  const navigate = useNavigate();
  const radioName = useId();
  const { tenants, activeTenantId, isLoading } = useMyTenants();
  const tenant = tenants.find((item) => item.tenantId === activeTenantId);
  const notebookOn = !isLoading && tenant?.features?.notebook !== false;
  const { sessions } = useNotebookSessions();
  const actions = useNotebookActions();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<'new' | 'existing'>('new');
  const [title, setTitle] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if ((!text.trim() && !commit) || !notebookOn) {
    return null;
  }

  const openDialog = () => {
    setTitle(datedNoteTitle(titlePrefix));
    setKind('new');
    setSessionId(sessions[0]?.id ?? '');
    setError('');
    setOpen(true);
  };

  const confirm = async () => {
    setBusy(true);
    setError('');
    try {
      const targetId =
        kind === 'existing'
          ? sessionId
          : (await actions.createSession(title.trim() || datedNoteTitle(titlePrefix)))?.id;
      if (!targetId) {
        setError('ノートを用意できませんでした。');
        return;
      }
      if (commit) {
        const failed = await commit(targetId);
        if (failed) {
          setError(failed);
          return;
        }
      } else {
        const saved = await actions.addFile(
          targetId,
          sourceFilename(filename, text),
          textToBase64(text),
        );
        if (!saved) {
          setError('ノートに追加できませんでした。');
          return;
        }
      }
      setOpen(false);
      navigate('/notebook', { state: { sessionId: targetId } });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button
        type='button'
        variant={appearance}
        size='sm'
        className={
          appearance === 'text' ? 'inline-flex items-center justify-center gap-x-1' : undefined
        }
        onClick={openDialog}
      >
        {label}
      </Button>
      <CustomDialog isOpen={open} onClose={() => (busy ? undefined : setOpen(false))}>
        <CustomDialogPanel>
          <CustomDialogHeader>ノートブックへ渡す</CustomDialogHeader>
          <CustomDialogBody>
            <fieldset className='flex flex-col gap-3'>
              <legend className='mb-2 text-dns-16B-130'>追加先</legend>
              <Radio
                size='lg'
                name={radioName}
                checked={kind === 'new'}
                onChange={() => setKind('new')}
              >
                新しいノート
              </Radio>
              {kind === 'new' ? (
                <div className='flex flex-col gap-1'>
                  <Label htmlFor={`${radioName}-title`}>タイトル</Label>
                  <Input
                    id={`${radioName}-title`}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </div>
              ) : null}
              <Radio
                size='lg'
                name={radioName}
                checked={kind === 'existing'}
                aria-disabled={sessions.length === 0 || undefined}
                onChange={() => {
                  if (sessions.length === 0) {
                    return;
                  }
                  setKind('existing');
                }}
              >
                既存のノートに追加
              </Radio>
              {sessions.length === 0 ? (
                <p className='text-dns-14N-130 text-solid-gray-600'>ノートがありません。</p>
              ) : null}
              {kind === 'existing' && sessions.length > 0 ? (
                <Select
                  blockSize='md'
                  value={sessionId}
                  onChange={(event) => setSessionId(event.target.value)}
                >
                  {sessions.map((session) => (
                    <option key={session.id} value={session.id}>
                      {session.title || '無題'}
                    </option>
                  ))}
                </Select>
              ) : null}
            </fieldset>
            {error ? <ErrorText className='mt-3'>{error}</ErrorText> : null}
            <div className='mt-4 flex flex-row-reverse justify-between gap-2'>
              <Button
                variant='solid-fill'
                size='md'
                type='button'
                aria-disabled={busy || undefined}
                onClick={() => void confirm()}
              >
                {busy ? '追加しています...' : '追加して開く'}
              </Button>
              <Button variant='text' size='md' type='button' onClick={() => setOpen(false)}>
                キャンセル
              </Button>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </>
  );
};
