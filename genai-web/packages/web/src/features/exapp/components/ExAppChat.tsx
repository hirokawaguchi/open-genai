import { ExApp } from 'genai-web';
import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { Markdown } from '@/components/Markdown';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { Textarea } from '@/components/ui/dads/Textarea';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useInvokeExApp } from '../hooks/useInvokeExApp';
import { processFormFiles } from '../utils/processFormFiles';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  fileNames?: string[];
};

type Props = {
  exApp: ExApp;
};

// 対話型 AI アプリ（Dify チャットフロー連携）。
// 1 回ごとの送信を exapps/invoke で行い、会話の継続は sessionId を固定して
// dify-app 側の session -> conversation_id 対応に委ねる。
const ACCEPT = 'image/*,.pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json';

export const ExAppChat = ({ exApp }: Props) => {
  const { invokeExApp } = useInvokeExApp();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const isComposing = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const send = async () => {
    const text = input.trim();
    if ((!text && files.length === 0) || isLoading) {
      return;
    }
    setError('');
    const sendingFiles = files;
    const userMessage: ChatMessage = {
      role: 'user',
      content: text,
      fileNames: sendingFiles.map((f) => f.name),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setFiles([]);
    setIsLoading(true);

    try {
      const inputs: Record<string, unknown> = { query: text };
      if (sendingFiles.length > 0) {
        inputs.files = await processFormFiles({ files: sendingFiles });
      }
      const res = await invokeExApp({
        teamId: exApp.teamId,
        exAppId: exApp.exAppId,
        inputs,
        sessionId,
      });
      setMessages((prev) => [...prev, { role: 'assistant', content: res.outputs ?? '' }]);
    } catch {
      setError('応答の取得に失敗しました。時間をおいて再度お試しください。');
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposing.current) {
      e.preventDefault();
      void send();
    }
  };

  const startNewConversation = () => {
    setMessages([]);
    setInput('');
    setFiles([]);
    setError('');
    setSessionId(crypto.randomUUID());
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className='min-h-[40vh] rounded-8 border border-solid-gray-420 p-4'>
        {messages.length === 0 && !isLoading && (
          <p className='leading-175 text-solid-gray-536'>
            メッセージを入力して会話を始めましょう。
          </p>
        )}

        <div className='flex flex-col gap-3'>
          {messages.map((m, i) => (
            <div
              key={i}
              className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
            >
              <div
                className={`max-w-[85%] rounded-8 px-4 py-3 ${
                  m.role === 'user'
                    ? 'bg-blue-50 text-solid-gray-800'
                    : 'border border-solid-gray-420 bg-white'
                }`}
              >
                {m.role === 'assistant' ? (
                  <Markdown>{m.content}</Markdown>
                ) : (
                  <div className='whitespace-pre-wrap break-words text-std-16N-170'>
                    {m.content}
                  </div>
                )}
                {m.fileNames && m.fileNames.length > 0 && (
                  <div className='mt-1 text-dns-14N-130 text-solid-gray-536'>
                    添付: {m.fileNames.join(', ')}
                  </div>
                )}
              </div>
            </div>
          ))}

          {isLoading && (
            <div className='flex justify-start'>
              <div className='rounded-8 border border-solid-gray-420 bg-white px-4 py-3'>
                <ProgressIndicator className='my-0.5' />
              </div>
            </div>
          )}
        </div>
        <div ref={bottomRef} />
      </div>

      {error && <p className='text-error-2'>{error}</p>}

      <div className='flex flex-col gap-2'>
        {files.length > 0 && (
          <div className='flex items-center gap-2 text-dns-14N-130 text-solid-gray-700'>
            <span>添付: {files.map((f) => f.name).join(', ')}</span>
            <Button variant='text' size='sm' onClick={() => setFiles([])}>
              クリア
            </Button>
          </div>
        )}

        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => (isComposing.current = true)}
          onCompositionEnd={() => (isComposing.current = false)}
          rows={2}
          placeholder='メッセージを入力（Enter で送信 / Shift+Enter で改行）'
          className='w-full'
        />

        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-2'>
            <input
              ref={fileInputRef}
              type='file'
              multiple
              accept={ACCEPT}
              className='hidden'
              onChange={(e) => {
                setFiles(Array.from(e.target.files ?? []));
                e.target.value = '';
              }}
            />
            <Button
              variant='outline'
              size='md'
              onClick={() => fileInputRef.current?.click()}
            >
              ファイルを添付
            </Button>
            <Button variant='text' size='md' onClick={startNewConversation}>
              新しい会話
            </Button>
          </div>
          <LoadingButton variant='solid-fill' size='md' loading={isLoading} onClick={send}>
            送信
          </LoadingButton>
        </div>
      </div>
    </div>
  );
};
