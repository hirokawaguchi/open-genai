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
import { Switch } from '@/components/ui/Switch';
import { toolLabels } from './toolLabels';
import type { NotebookMcp } from './types';

type Props = {
  open: boolean;
  mcps: NotebookMcp[];
  submitting: boolean;
  onClose: () => void;
  onUpdateMcp: (
    id: string,
    body: { connected?: boolean; prompt?: string; reset_prompt?: boolean },
  ) => Promise<boolean>;
  onCreateMcp: (name: string, url: string, prompt: string) => Promise<boolean>;
  onDeleteMcp: (id: string) => Promise<void>;
};

export const NotebookManageDialog = ({
  open,
  mcps,
  submitting,
  onClose,
  onUpdateMcp,
  onCreateMcp,
  onDeleteMcp,
}: Props) => {
  const [tab, setTab] = useState<'list' | 'add'>('list');
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
          MCP
        </CustomDialogHeader>
        <CustomDialogBody>
          <div className='mb-4 flex gap-1 border-b border-solid-gray-300' role='tablist'>
            <button
              type='button'
              role='tab'
              aria-selected={tab === 'list'}
              className={
                tab === 'list'
                  ? 'border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                  : 'px-3 py-2 text-std-16N-170 text-solid-gray-700'
              }
              onClick={() => setTab('list')}
            >
              登録済み
            </button>
            <button
              type='button'
              role='tab'
              aria-selected={tab === 'add'}
              className={
                tab === 'add'
                  ? 'border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                  : 'px-3 py-2 text-std-16N-170 text-solid-gray-700'
              }
              onClick={() => setTab('add')}
            >
              追加
            </button>
          </div>

          {tab === 'list' && (
            <div className='flex flex-col gap-3 text-dns-14N-130'>
              <p className='text-solid-gray-600'>
                エージェントで使う MCP です。On にすると接続され、Off
                にすると外れます。プロンプトは、その MCP をいつ呼ぶかです。
              </p>
              <ul className='flex flex-col gap-2'>
                {mcps.map((m) => {
                  const draft = promptDrafts[m.id] ?? m.prompt;
                  const promptOpen = openPromptId === m.id;
                  return (
                    <li
                      key={m.id}
                      className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 px-3 py-3'
                    >
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
                            {m.available
                              ? m.connected
                                ? '接続中'
                                : 'オフ'
                              : '接続先がありません'}
                            {m.tools.length ? ` ／ ${toolLabels(m.tools)}` : ''}
                          </p>
                        </div>
                        <div className='flex shrink-0 flex-col items-end gap-2'>
                          {m.available ? (
                            <Switch
                              checked={m.connected}
                              label={m.connected ? 'On' : 'Off'}
                              onSwitch={(next) => {
                                if (submitting) return;
                                void onUpdateMcp(m.id, { connected: next });
                              }}
                            />
                          ) : null}
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
            </div>
          )}

          {tab === 'add' && (
            <div className='flex flex-col gap-2 text-dns-14N-130'>
              <p className='text-std-16B-150'>MCP を追加</p>
              <p className='text-solid-gray-600'>
                Open GENAI のアプリを MCP
                にしたものや、公開されている MCP を、URL で登録します。庁内ポリシーに従ってください。
              </p>
              <Label htmlFor='notebook-mcp-new-name'>名前</Label>
              <Input
                id='notebook-mcp-new-name'
                value={mcpName}
                placeholder='例: 文書'
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
                className='w-fit'
                aria-disabled={submitting || !mcpName.trim() || !mcpUrl.trim() || undefined}
                onClick={() => {
                  if (submitting || !mcpName.trim() || !mcpUrl.trim()) return;
                  void onCreateMcp(mcpName.trim(), mcpUrl.trim(), mcpPrompt.trim()).then((ok) => {
                    if (!ok) return;
                    setMcpName('');
                    setMcpUrl('');
                    setMcpPrompt('');
                    setTab('list');
                  });
                }}
              >
                接続して追加
              </Button>
            </div>
          )}
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
