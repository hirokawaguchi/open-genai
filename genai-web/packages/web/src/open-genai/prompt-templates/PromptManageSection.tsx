import { useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { SupportText } from '@/components/ui/dads/SupportText';
import { TemplateKindChip } from './TemplateKindChip';
import type { PromptTemplate } from './types';

type Props = {
  templates: PromptTemplate[];
  submitting: boolean;
  error: string | null;
  onDelete: (id: string) => Promise<boolean>;
};

/** 「管理」: 自分が削除できるテンプレートを一覧し、確認のうえ削除する。 */
export const PromptManageSection = ({ templates, submitting, error, onDelete }: Props) => {
  const [target, setTarget] = useState<PromptTemplate | null>(null);

  const handleConfirm = async () => {
    if (!target) {
      return;
    }
    const ok = await onDelete(target.id);
    if (ok) {
      setTarget(null);
    }
  };

  return (
    <div className='flex flex-col gap-3'>
      <SupportText>
        削除できるのは、自分が作成したテンプレート（管理者は標準・全チーム分）です。削除は元に戻せません。
      </SupportText>
      {error && <ErrorText>＊{error}</ErrorText>}
      {templates.length === 0 ? (
        <SupportText>テンプレートがありません。</SupportText>
      ) : (
        <ul className='flex flex-col divide-y divide-solid-gray-300 rounded-8 border border-solid-gray-300'>
          {templates.map((t) => (
            <li key={t.id} className='flex items-center justify-between gap-4 px-4 py-3'>
              <span className='flex min-w-0 items-center gap-2'>
                <TemplateKindChip kind={t.kind} />
                <span className='truncate text-std-16N-170 text-solid-gray-900'>{t.title}</span>
              </span>
              {t.canDelete ? (
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => setTarget(t)}
                  className='flex-none text-error-1'
                >
                  削除
                </Button>
              ) : (
                <span className='flex-none text-dns-14N-130 text-solid-gray-500'>削除不可</span>
              )}
            </li>
          ))}
        </ul>
      )}

      <CustomDialog isOpen={target !== null} onClose={() => setTarget(null)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setTarget(null)}>
            テンプレートを削除
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170 text-solid-gray-800'>
              「{target?.title}」を削除します。元に戻せません。よろしいですか？
            </p>
            <div className='mt-6 flex justify-end gap-3'>
              <Button type='button' variant='outline' size='md' onClick={() => setTarget(null)}>
                キャンセル
              </Button>
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                onClick={handleConfirm}
                aria-disabled={submitting || undefined}
              >
                {submitting ? '削除中...' : '削除する'}
              </Button>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </div>
  );
};
