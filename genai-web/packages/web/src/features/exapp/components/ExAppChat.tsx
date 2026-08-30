import { Artifact, ExApp } from 'genai-web';
import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { Markdown } from '@/components/Markdown';
import { ButtonCopy } from '@/components/ui/ButtonCopy';
import { Button } from '@/components/ui/dads/Button';
import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { Textarea } from '@/components/ui/dads/Textarea';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { isApiError } from '@/lib/fetcher';
import { submitKeyHint, isSubmitKey } from '@/utils/keyboard';
import { ExAppConversation, useExAppConversations } from '../hooks/useExAppConversations';
import { useInvokeExApp } from '../hooks/useInvokeExApp';
import { processFormFiles } from '../utils/processFormFiles';
import { ExAppArtifactDownloads } from './ExAppArtifactDownloads';
import { ExAppCitations } from './ExAppCitations';
import { ExAppConversationList } from './ExAppConversationList';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  fileNames?: string[];
  artifacts?: Artifact[];
};

type Props = {
  exApp: ExApp;
  // アプリがファイル添付を受け付けられる場合のみ「ファイルを添付」を表示する。
  fileAttachEnabled?: boolean;
};

// 対話型 AI アプリ（Dify チャットフロー連携）。
// 1 回ごとの送信を exapps/invoke で行い、会話の継続は sessionId を固定して
// dify-app 側の session -> conversation_id 対応に委ねる。
const ACCEPT = 'image/*,.pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json';

const GENERIC_ERROR =
  '処理中にエラーが発生しました。時間をおいて再度お試しください。解消しない場合は管理者にお問い合わせください。';

// 履歴の inputs.files（processFormFiles の出力）から添付ファイル名を復元する。
// 本文（base64）は復元対象外で、表示用のファイル名のみ取り出す。
const extractFileNames = (inputs: Record<string, unknown>): string[] | undefined => {
  const files = inputs?.files;
  if (!Array.isArray(files)) {
    return undefined;
  }
  const names: string[] = [];
  for (const group of files) {
    const inner = (group as { files?: unknown })?.files;
    if (!Array.isArray(inner)) {
      continue;
    }
    for (const file of inner) {
      const filename = (file as { filename?: unknown })?.filename;
      if (typeof filename === 'string') {
        names.push(filename);
      }
    }
  }
  return names.length > 0 ? names : undefined;
};

export const ExAppChat = ({ exApp, fileAttachEnabled = false }: Props) => {
  const { invokeExAppStream } = useInvokeExApp();
  const { conversations, mutate: mutateConversations } = useExAppConversations(
    exApp.teamId,
    exApp.exAppId,
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const isComposing = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // ユーザーが最下部付近にいるときだけ自動追尾する（上へ読み返し中は追尾しない）。
  const stickToBottomRef = useRef(true);
  // 逐次トークンごとの scrollIntoView 連打を rAF で 1 フレームに間引く。
  const scrollRafRef = useRef<number | null>(null);

  useEffect(() => {
    // ページ（ウィンドウ）スクロールを監視し、最下部付近にいるかを記録する。
    const handleScroll = () => {
      const distanceFromBottom =
        document.documentElement.scrollHeight - (window.scrollY + window.innerHeight);
      stickToBottomRef.current = distanceFromBottom < 120;
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    // 初期表示（会話が空）では自動スクロールしない。開いた直後に入力欄（最下部）へ
    // 飛んでページが上に流れるのを防ぐ。会話が始まってから最新メッセージを追う。
    if (messages.length === 0) {
      return;
    }
    // 上へ読み返している間は追尾しない。
    if (!stickToBottomRef.current) {
      return;
    }
    if (scrollRafRef.current != null) {
      cancelAnimationFrame(scrollRafRef.current);
    }
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      // 配信中は smooth を使わず即時追従（トークンごとにアニメを再起動しないため
      // カクつきを防ぐ）。完了時のみ smooth で最後をなめらかに寄せる。
      bottomRef.current?.scrollIntoView({
        behavior: isLoading ? 'auto' : 'smooth',
        block: 'end',
      });
    });
    return () => {
      if (scrollRafRef.current != null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, [messages, isLoading]);

  const send = async () => {
    const text = input.trim();
    if ((!text && files.length === 0) || isLoading) {
      return;
    }
    setError('');
    // 送信直後は最新へ追尾する。また、送信ボタンにフォーカスが残ると配信中の
    // 再描画で見た目が落ち着かないため、フォーカスを外す。
    stickToBottomRef.current = true;
    if (typeof document !== 'undefined') {
      (document.activeElement as HTMLElement | null)?.blur?.();
    }
    const sendingFiles = files;
    const userMessage: ChatMessage = {
      role: 'user',
      content: text,
      fileNames: sendingFiles.map((f) => f.name),
    };
    // ユーザー発話に続けて、逐次追記する空のアシスタント枠を先に置く。
    setMessages((prev) => [...prev, userMessage, { role: 'assistant', content: '' }]);
    setInput('');
    setFiles([]);
    setIsLoading(true);

    // 最後のアシスタントメッセージだけを更新するヘルパ。
    const updateAssistant = (fn: (m: ChatMessage) => ChatMessage) => {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === 'assistant') {
          next[next.length - 1] = fn(last);
        }
        return next;
      });
    };

    // 内容が空のアシスタント枠を取り除く（エラー時・空応答時）。
    const dropEmptyAssistant = () => {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === 'assistant' && !last.content) {
          next.pop();
        }
        return next;
      });
    };

    try {
      const inputs: Record<string, unknown> = { query: text };
      if (sendingFiles.length > 0) {
        inputs.files = await processFormFiles({ files: sendingFiles });
      }
      await invokeExAppStream(
        {
          teamId: exApp.teamId,
          exAppId: exApp.exAppId,
          inputs,
          sessionId,
        },
        {
          onDelta: (chunk) => {
            updateAssistant((m) => ({ ...m, content: m.content + chunk }));
          },
          onDone: ({ outputs, artifacts }) => {
            // done の outputs が確定値。断片の積み上げを最終全文で置き換える。
            updateAssistant((m) => ({
              ...m,
              content: outputs || m.content,
              artifacts,
            }));
            // 完了時点でサーバ側の履歴保存が済んでいるため、
            // 「過去の会話」一覧を再取得して今の会話を反映する。
            void mutateConversations();
          },
          onError: (message) => {
            dropEmptyAssistant();
            setError(message || GENERIC_ERROR);
          },
        },
      );
    } catch (error: unknown) {
      dropEmptyAssistant();
      if (isApiError(error)) {
        const data = error.data as { error?: string };
        setError(data?.error || GENERIC_ERROR);
      } else {
        setError(GENERIC_ERROR);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isSubmitKey(e) && !isComposing.current) {
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

  // 「過去の会話」を選ぶと、その sessionId とやり取りを復元する。
  // sessionId を引き継ぐことで dify-app 側の会話（conversation_id）も継続できる。
  const restoreConversation = (conversation: ExAppConversation) => {
    const restored: ChatMessage[] = [];
    for (const history of conversation.histories) {
      const query = typeof history.inputs?.query === 'string' ? history.inputs.query : '';
      restored.push({
        role: 'user',
        content: query,
        fileNames: extractFileNames(history.inputs),
      });
      if (history.outputs) {
        restored.push({
          role: 'assistant',
          content: history.outputs,
          artifacts: history.artifacts ?? undefined,
        });
      }
    }
    setMessages(restored);
    setSessionId(conversation.sessionId);
    setInput('');
    setFiles([]);
    setError('');
  };

  // 逐次描画前の空アシスタント枠は描画しない（下のスピナーで代替）。
  const visibleMessages = messages.filter(
    (m) => !(m.role === 'assistant' && m.content.length === 0 && !m.artifacts),
  );

  return (
    <div className='flex flex-col gap-4'>
      <ExAppConversationList
        conversations={conversations}
        activeSessionId={sessionId}
        onSelect={restoreConversation}
      />

      <div className='min-h-[40vh] rounded-8 border border-solid-gray-420 p-4'>
        {messages.length === 0 && !isLoading && (
          <p className='leading-175 text-solid-gray-536'>
            メッセージを入力して会話を始めましょう。
          </p>
        )}

        <div className='flex flex-col gap-3'>
          {visibleMessages.map((m, i) => (
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
                  <>
                    <Markdown>{m.content}</Markdown>
                    <ExAppCitations artifacts={m.artifacts} />
                    <ExAppArtifactDownloads artifacts={m.artifacts} />
                    {/* 生成完了後のみコピーを表示（配信途中の部分テキストは対象外） */}
                    {m.content.length > 0 &&
                      !(isLoading && i === visibleMessages.length - 1) && (
                        <div className='mt-1 flex justify-end'>
                          <ButtonCopy text={m.content} />
                        </div>
                      )}
                  </>
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

          {/* 生成中は常にスピナーを出す。回答がまだ完了していない（続きがある）
              ことを示すため、トークン到着後も表示し続ける。 */}
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
        {fileAttachEnabled && files.length > 0 && (
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
          placeholder={`メッセージを入力（${submitKeyHint}）`}
          className='w-full'
        />

        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-2'>
            {fileAttachEnabled && (
              <>
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
              </>
            )}
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
