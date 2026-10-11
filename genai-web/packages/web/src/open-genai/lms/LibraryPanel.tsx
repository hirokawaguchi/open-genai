import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { MaterialWizard } from './MaterialWizard';
import { transcriptStatusLabel } from './labels';
import type { Material } from './types';
import { useLmsActions } from './useLms';

type Props = {
  materials: Material[];
  trashedMaterials: Material[];
  onChanged: () => void;
  onOpenTranscript: (materialId: string) => void;
};

export const LibraryPanel = ({ materials, trashedMaterials, onChanged, onOpenTranscript }: Props) => {
  const actions = useLmsActions();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [trashView, setTrashView] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState('');
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  const shown = trashView ? trashedMaterials : materials;

  useEffect(() => {
    const ids = new Set(shown.map((item) => item.id));
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [shown]);

  const selectedCount = selected.size;
  const allSelected = shown.length > 0 && selectedCount === shown.length;

  const showTrash = (next: boolean) => {
    setTrashView(next);
    setSelected(new Set());
    setBulkAction('');
    setBulkResult(null);
    actions.setError(null);
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(shown.map((item) => item.id)));
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const runBulk = async () => {
    if (!bulkAction || selectedCount === 0 || actions.busy) {
      return;
    }
    if (
      bulkAction === 'delete' &&
      !window.confirm(`${selectedCount} 件を削除しますか。コースで使っていない教材だけ、ファイルごと消えます。`)
    ) {
      return;
    }
    let ok = 0;
    let failed = 0;
    for (const id of selected) {
      const saved =
        bulkAction === 'delete'
          ? await actions.deleteMaterial(id)
          : bulkAction === 'restore'
            ? await actions.restoreMaterial(id)
            : await actions.hideMaterial(id);
      if (saved) {
        ok += 1;
      } else {
        failed += 1;
      }
    }
    const verb =
      bulkAction === 'delete' ? '削除しました' : bulkAction === 'restore' ? '戻しました' : 'ゴミ箱へ移しました';
    const failedVerb =
      bulkAction === 'delete' ? '削除できませんでした' : bulkAction === 'restore' ? '戻せませんでした' : '移せませんでした';
    setBulkResult(failed > 0 ? `${ok} 件を${verb}。${failed} 件は${failedVerb}。` : `${ok} 件を${verb}。`);
    setSelected(new Set());
    setBulkAction('');
    onChanged();
  };

  return (
    <div className='flex flex-col gap-4'>
      <section className='flex flex-col gap-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-std-18B-160 text-solid-gray-900'>教材一覧</h2>
          <Button type='button' variant='solid-fill' size='sm' onClick={() => setWizardOpen(true)}>
            教材を置く
          </Button>
        </div>
        <fieldset className='m-0 flex min-w-0 flex-wrap gap-2 border-0 p-0' aria-label='一覧の切り替え'>
          <button
            type='button'
            onClick={() => showTrash(false)}
            className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
              trashView ? 'border-solid-gray-420 text-solid-gray-700' : 'border-blue-900 bg-blue-50 text-blue-900'
            }`}
          >
            教材（{materials.length}）
          </button>
          <button
            type='button'
            onClick={() => showTrash(true)}
            className={`rounded-4 border px-3 py-1 text-dns-16N-130 ${
              trashView ? 'border-blue-900 bg-blue-50 text-blue-900' : 'border-solid-gray-420 text-solid-gray-600'
            }`}
          >
            ゴミ箱（{trashedMaterials.length}）
          </button>
        </fieldset>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          {trashView
            ? '戻すと教材一覧に戻ります。コースで使っていない教材は、ここで削除するとファイルごと消えます。'
            : '「本文」で、PDF はページごと、動画は発話ごとに文字を直せます。ゴミ箱へ移すと一覧から隠れ、新しいコースでは選べなくなります。ゴミ箱から戻せます。公開済みコースの再生は残ります。'}
        </p>
        {shown.length === 0 ? (
          <p className='text-solid-gray-600'>
            {trashView ? (
              'ゴミ箱は空です。'
            ) : (
              <>
                まだ教材がありません。
                <button
                  type='button'
                  className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                  onClick={() => setWizardOpen(true)}
                >
                  教材を置く
                </button>
              </>
            )}
          </p>
        ) : (
          <>
            <div className='flex flex-wrap items-center gap-3 rounded-4 border border-solid-gray-300 bg-solid-gray-50 px-3 py-2'>
              <label className='flex items-center gap-2 text-dns-16N-130 text-solid-gray-700'>
                <input
                  type='checkbox'
                  className='size-5'
                  checked={allSelected}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate = selectedCount > 0 && !allSelected;
                    }
                  }}
                  onChange={toggleAll}
                />
                すべて選択
              </label>
              <span className='text-dns-14N-130 text-solid-gray-600'>
                {selectedCount > 0 ? `${selectedCount} 件を選択中` : '選択して一括処理できます'}
              </span>
              <div className='flex flex-wrap items-center gap-2'>
                <select
                  className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-16N-130'
                  value={bulkAction}
                  onChange={(e) => setBulkAction(e.target.value)}
                  aria-label='一括処理を選ぶ'
                >
                  <option value=''>一括処理を選ぶ…</option>
                  {trashView ? (
                    <>
                      <option value='restore'>戻す</option>
                      <option value='delete'>削除する</option>
                    </>
                  ) : (
                    <option value='hide'>ゴミ箱へ移す</option>
                  )}
                </select>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={actions.busy || selectedCount === 0 || !bulkAction}
                  onClick={() => void runBulk()}
                >
                  {actions.busy ? '処理中...' : '実行'}
                </Button>
              </div>
            </div>
            {bulkResult && (
              <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
                {bulkResult}
              </p>
            )}
            <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
              <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
                <thead>
                  <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                    <th className='w-10 px-3 py-2'>
                      <span className='sr-only'>選択</span>
                    </th>
                    <th className='px-3 py-2'>名前</th>
                    <th className='px-3 py-2'>種別</th>
                    <th className='px-3 py-2 text-right'>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((material) => (
                    <tr key={material.id} className='border-b border-solid-gray-200 last:border-b-0'>
                      <td className='px-3 py-2'>
                        <input
                          type='checkbox'
                          className='size-5'
                          checked={selected.has(material.id)}
                          onChange={() => toggleOne(material.id)}
                          aria-label={`「${material.title}」を選択`}
                        />
                      </td>
                      <td className='px-3 py-2 text-std-16N-170 text-solid-gray-900'>{material.title}</td>
                      <td className='px-3 py-2 text-solid-gray-600'>
                        {material.kind === 'video' ? '動画' : `テキスト ${material.slideCount} ページ`}
                        {(material.transcriptStatus ?? 'none') !== 'none'
                          ? ` / ${transcriptStatusLabel(material.transcriptStatus ?? '')}`
                          : ''}
                      </td>
                      <td className='px-3 py-2 text-right'>
                        <span className='inline-flex gap-2'>
                          {!trashView && (
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              onClick={() => onOpenTranscript(material.id)}
                            >
                              本文
                            </Button>
                          )}
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            onClick={async () => {
                              const next = window.prompt('名前', material.title);
                              if (!next || next === material.title) {
                                return;
                              }
                              const saved = await actions.renameMaterial(material.id, next);
                              if (saved) {
                                onChanged();
                              }
                            }}
                          >
                            名前
                          </Button>
                          {trashView ? (
                            <>
                              <Button
                                type='button'
                                variant='outline'
                                size='sm'
                                onClick={async () => {
                                  const saved = await actions.restoreMaterial(material.id);
                                  if (saved) {
                                    onChanged();
                                  }
                                }}
                              >
                                戻す
                              </Button>
                              <Button
                                type='button'
                                variant='outline'
                                size='sm'
                                onClick={async () => {
                                  if (
                                    !window.confirm(
                                      `「${material.title}」を削除しますか。コースで使っていなければ、ファイルも消えます。`,
                                    )
                                  ) {
                                    return;
                                  }
                                  const saved = await actions.deleteMaterial(material.id);
                                  if (saved) {
                                    onChanged();
                                  }
                                }}
                              >
                                削除
                              </Button>
                            </>
                          ) : (
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              onClick={async () => {
                                const saved = await actions.hideMaterial(material.id);
                                if (saved) {
                                  onChanged();
                                }
                              }}
                            >
                              ゴミ箱へ移す
                            </Button>
                          )}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      {actions.error && !wizardOpen && (
        <p className='text-dns-14N-130 text-error-1' role='alert'>
          {actions.error}
        </p>
      )}
      <MaterialWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={onChanged}
      />
    </div>
  );
};
