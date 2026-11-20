import { useState } from 'react';
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
import { useNotebookActions, useNotebookSessions } from '@/open-genai/notebook/useNotebook';
import { useMyTenants } from '@/open-genai/tenants/useTenants';

type Props = {
  text: string;
};

const defaultNoteTitle = () => {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `文字起こし ${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const textToBase64 = (text: string) => {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
};

export const WhisperHandoff = (props: Props) => {
  const { text } = props;
  const navigate = useNavigate();
  const { tenants, activeTenantId, isLoading } = useMyTenants();
  const tenant = tenants.find((item) => item.tenantId === activeTenantId);
  const features = tenant?.features ?? {};
  const chatOn = !isLoading && features.chat !== false;
  const notebookOn = !isLoading && features.notebook !== false;
  const { sessions } = useNotebookSessions();
  const actions = useNotebookActions();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<'new' | 'existing'>('new');
  const [title, setTitle] = useState(defaultNoteTitle);
  const [sessionId, setSessionId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (!text.trim() || (!chatOn && !notebookOn)) {
    return null;
  }

  const openNotebook = () => {
    setTitle(defaultNoteTitle());
    setKind(sessions.length > 0 ? 'new' : 'new');
    setSessionId(sessions[0]?.id ?? '');
    setError('');
    setOpen(true);
  };

  const confirmNotebook = async () => {
    setBusy(true);
    setError('');
    try {
      const targetId =
        kind === 'existing'
          ? sessionId
          : (await actions.createSession(title.trim() || defaultNoteTitle()))?.id;
      if (!targetId) {
        setError('ノートを用意できませんでした。');
        return;
      }
      const saved = await actions.addFile(targetId, '文字起こし.md', textToBase64(text));
      if (!saved) {
        setError('ノートに追加できませんでした。');
        return;
      }
      setOpen(false);
      navigate('/notebook', { state: { sessionId: targetId } });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {chatOn ? (
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={() => navigate('/chat', { state: { content: text } })}
        >
          チャットで扱う
        </Button>
      ) : null}
      {notebookOn ? (
        <Button type='button' variant='outline' size='sm' onClick={openNotebook}>
          ノートブックで扱う
        </Button>
      ) : null}
      <CustomDialog isOpen={open} onClose={() => (busy ? undefined : setOpen(false))}>
        <CustomDialogPanel>
          <CustomDialogHeader>ノートブックへ渡す</CustomDialogHeader>
          <CustomDialogBody>
            <fieldset className='flex flex-col gap-3'>
              <legend className='mb-2 text-dns-16B-130'>追加先</legend>
              <Radio
                size='lg'
                name='whisper-note-kind'
                checked={kind === 'new'}
                onChange={() => setKind('new')}
              >
                新しいノート
              </Radio>
              {kind === 'new' ? (
                <div className='flex flex-col gap-1'>
                  <Label htmlFor='whisper-note-title'>タイトル</Label>
                  <Input
                    id='whisper-note-title'
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </div>
              ) : null}
              <Radio
                size='lg'
                name='whisper-note-kind'
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
                onClick={() => void confirmNotebook()}
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
