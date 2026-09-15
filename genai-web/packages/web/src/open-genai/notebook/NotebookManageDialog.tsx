import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Textarea } from '@/components/ui/dads/Textarea';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { toolLabels } from './toolLabels';
import type { NotebookMcp, NotebookSkill } from './types';

type Props = {
  open: boolean;
  skills: NotebookSkill[];
  mcps: NotebookMcp[];
  submitting: boolean;
  onClose: () => void;
  onCreate: (name: string, instructions: string) => Promise<boolean>;
  onDelete: (id: string) => Promise<void>;
  onUpdateMcp: (
    id: string,
    body: { connected?: boolean; prompt?: string; reset_prompt?: boolean },
  ) => Promise<boolean>;
  onCreateMcp: (name: string, url: string, prompt: string) => Promise<boolean>;
  onDeleteMcp: (id: string) => Promise<void>;
};

export const NotebookManageDialog = ({
  open,
  skills,
  mcps,
  submitting,
  onClose,
  onCreate,
  onDelete,
  onUpdateMcp,
  onCreateMcp,
  onDeleteMcp,
}: Props) => {
  const [tab, setTab] = useState<'skills' | 'mcp'>('skills');
  const [name, setName] = useState('');
  const [instructions, setInstructions] = useState('');
  const [mcpName, setMcpName] = useState('');
  const [mcpUrl, setMcpUrl] = useState('');
  const [mcpPrompt, setMcpPrompt] = useState('');
  const [promptDrafts, setPromptDrafts] = useState<Record<string, string>>({});
  const [openPromptId, setOpenPromptId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPromptDrafts(Object.fromEntries(mcps.map((m) => [m.id, m.prompt])));
  }, [open, mcps]);

  return (
    <CustomDialog isOpen={open} onClose={onClose}>
      <CustomDialogPanel className='max-w-2xl'>
        <CustomDialogHeader hasClose onClose={onClose}>
          AIタイプとMCP
        </CustomDialogHeader>
        <CustomDialogBody>
          <div className='mb-4 flex gap-1 border-b border-solid-gray-300' role='tablist'>
            <button
              type='button'
              role='tab'
              aria-selected={tab === 'skills'}
              className={
                tab === 'skills'
                  ? 'border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                  : 'px-3 py-2 text-std-16N-170 text-solid-gray-700'
              }
              onClick={() => setTab('skills')}
            >
              AIタイプ
            </button>
            <button
              type='button'
              role='tab'
              aria-selected={tab === 'mcp'}
              className={
                tab === 'mcp'
                  ? 'border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                  : 'px-3 py-2 text-std-16N-170 text-solid-gray-700'
              }
              onClick={() => setTab('mcp')}
            >
              MCP
            </button>
          </div>

          {tab === 'skills' && (
            <div className='flex flex-col gap-3'>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                対話のAIタイプ（システムプロンプト）です。ノートをまたいで使えます。
              </p>
              <ul className='flex flex-col gap-2'>
                {skills.map((s) => (
                  <li
                    key={s.id}
                    className='flex flex-col gap-1 rounded-8 border border-solid-gray-300 px-3 py-2'
                  >
                    <div className='flex items-start justify-between gap-2'>
                      <p className='text-std-16B-150'>{s.name}</p>
                      <Button
                        type='button'
                        variant='outline'
                        size='xs'
                        aria-disabled={submitting || undefined}
                        onClick={() => {
                          if (submitting) return;
                          void onDelete(s.id);
                        }}
                      >
                        削除
                      </Button>
                    </div>
                    <p className='text-dns-14N-130 text-solid-gray-800'>
                      {s.instructions.trim() || '手順の指定なし'}
                    </p>
                    {!!s.tools.length && (
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        使うもの: {toolLabels(s.tools)}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 p-3'>
                <p className='text-std-16B-150'>AIタイプを追加</p>
                <Label htmlFor='notebook-skill-new'>名前</Label>
                <Input
                  id='notebook-skill-new'
                  value={name}
                  placeholder='例: チェックリスト係'
                  onChange={(e) => setName(e.target.value)}
                />
                <Label htmlFor='notebook-skill-instructions'>手順</Label>
                <Textarea
                  id='notebook-skill-instructions'
                  rows={3}
                  value={instructions}
                  placeholder='例: 不足資料と確認事項を箇条書きにする'
                  onChange={(e) => setInstructions(e.target.value)}
                />
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  aria-disabled={submitting || !name.trim() || undefined}
                  onClick={() => {
                    if (submitting || !name.trim()) return;
                    void onCreate(name.trim(), instructions.trim()).then((ok) => {
                      if (!ok) return;
                      setName('');
                      setInstructions('');
                    });
                  }}
                >
                  作成
                </Button>
              </div>
            </div>
          )}

          {tab === 'mcp' && (
            <div className='flex flex-col gap-3 text-dns-14N-130'>
              <p className='text-solid-gray-600'>
                接続の追加・切り離しと、MCP を使うときのプロンプトです。通常は既定のまま使います。
                ノートごとに使うかどうかは、参考資料タブの On/Off で切り替えます。
              </p>
              <ul className='flex flex-col gap-2'>
                {mcps.map((m) => {
                  const draft = promptDrafts[m.id] ?? m.prompt;
                  const promptOpen = openPromptId === m.id;
                  return (
                    <li key={m.id} className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 px-3 py-3'>
                      <div className='flex items-start justify-between gap-2'>
                        <div>
                          <p className='text-std-16B-150 text-solid-gray-900'>{m.name}</p>
                          <p className='mt-1 text-solid-gray-700'>{m.description}</p>
                          {m.catalog_id === 'knowledge' && (
                            <p className='mt-1 text-solid-gray-600'>
                              読む対象は共有ナレッジ（共通チーム）です。ノートの参考資料には入りません。
                            </p>
                          )}
                          <p className='mt-1 text-solid-gray-600'>
                            {m.connected
                              ? '接続済み'
                              : m.available
                                ? '未接続'
                                : '未接続（接続先がありません）'}
                            {m.tools.length ? ` ／ ${toolLabels(m.tools)}` : ''}
                          </p>
                        </div>
                        <div className='flex shrink-0 flex-col gap-1'>
                          <Button
                            type='button'
                            variant={m.connected ? 'outline' : 'solid-fill'}
                            size='xs'
                            aria-disabled={submitting || !m.available || undefined}
                            onClick={() => {
                              if (submitting || !m.available) return;
                              void onUpdateMcp(m.id, { connected: !m.connected });
                            }}
                          >
                            {m.connected ? '切り離す' : '接続する'}
                          </Button>
                          {!m.builtin && (
                            <Button
                              type='button'
                              variant='outline'
                              size='xs'
                              aria-disabled={submitting || undefined}
                              onClick={() => {
                                if (submitting) return;
                                void onDeleteMcp(m.id);
                              }}
                            >
                              削除
                            </Button>
                          )}
                        </div>
                      </div>
                      <button
                        type='button'
                        className='w-fit text-blue-900 underline'
                        onClick={() => setOpenPromptId(promptOpen ? null : m.id)}
                      >
                        {promptOpen ? 'プロンプトを閉じる' : 'プロンプトを編集'}
                      </button>
                      {promptOpen && (
                        <div className='flex flex-col gap-2'>
                          <Label htmlFor={`notebook-mcp-prompt-${m.id}`}>利用時のプロンプト</Label>
                          <Textarea
                            id={`notebook-mcp-prompt-${m.id}`}
                            rows={4}
                            value={draft}
                            onChange={(e) =>
                              setPromptDrafts((prev) => ({ ...prev, [m.id]: e.target.value }))
                            }
                          />
                          <div className='flex flex-wrap gap-2'>
                            <Button
                              type='button'
                              variant='solid-fill'
                              size='xs'
                              aria-disabled={submitting || draft === m.prompt || undefined}
                              onClick={() => {
                                if (submitting || draft === m.prompt) return;
                                void onUpdateMcp(m.id, { prompt: draft });
                              }}
                            >
                              プロンプトを保存
                            </Button>
                            <Button
                              type='button'
                              variant='outline'
                              size='xs'
                              aria-disabled={submitting || m.prompt_is_default || undefined}
                              onClick={() => {
                                if (submitting || m.prompt_is_default) return;
                                void onUpdateMcp(m.id, { reset_prompt: true });
                              }}
                            >
                              既定に戻す
                            </Button>
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
              <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 p-3'>
                <p className='text-std-16B-150'>MCP を追加</p>
                <p className='text-solid-gray-600'>
                  Streamable HTTP の公開 MCP など、URL で追加できます。庁内ポリシーに従ってください。
                </p>
                <Label htmlFor='notebook-mcp-new-name'>名前</Label>
                <Input
                  id='notebook-mcp-new-name'
                  value={mcpName}
                  placeholder='例: 公開ドキュメント検索'
                  onChange={(e) => setMcpName(e.target.value)}
                />
                <Label htmlFor='notebook-mcp-new-url'>URL</Label>
                <Input
                  id='notebook-mcp-new-url'
                  value={mcpUrl}
                  placeholder='https://example.com/mcp'
                  onChange={(e) => setMcpUrl(e.target.value)}
                />
                <Label htmlFor='notebook-mcp-new-prompt'>プロンプト（任意）</Label>
                <Textarea
                  id='notebook-mcp-new-prompt'
                  rows={2}
                  value={mcpPrompt}
                  placeholder='この MCP をいつ呼ぶか'
                  onChange={(e) => setMcpPrompt(e.target.value)}
                />
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  aria-disabled={submitting || !mcpName.trim() || !mcpUrl.trim() || undefined}
                  onClick={() => {
                    if (submitting || !mcpName.trim() || !mcpUrl.trim()) return;
                    void onCreateMcp(mcpName.trim(), mcpUrl.trim(), mcpPrompt.trim()).then((ok) => {
                      if (!ok) return;
                      setMcpName('');
                      setMcpUrl('');
                      setMcpPrompt('');
                    });
                  }}
                >
                  接続して追加
                </Button>
              </div>
            </div>
          )}
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
