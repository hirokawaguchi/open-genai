import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { SupportText } from '@/components/ui/dads/SupportText';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useChat } from '@/hooks/useChat';
import { useUsecasePath } from '@/hooks/useUsecasePath';

type Props = {
  currentSystemContext: string;
  setShowSystemContextDialog: (show: boolean) => void;
  setShowPromptListDialog: (show: boolean) => void;
};

export const SystemPrompt = (props: Props) => {
  const { currentSystemContext, setShowSystemContextDialog, setShowPromptListDialog } = props;

  const { usecase, chatId } = useUsecasePath();

  const { loadingMessages, isEmpty } = useChat(usecase, chatId);

  const { inputSystemContext, setInputSystemContext, setSaveSystemContext, systemContextTitle } =
    useChatStore();

  const canEdit = isEmpty && !chatId;
  const isNewChat = !loadingMessages && canEdit;
  const isCurrentChat = !loadingMessages && !canEdit;

  return (
    <div className='border-b border-b-solid-gray-800 pb-1'>
      <Disclosure key={`${usecase}-${chatId ?? 'new'}`} className='relative'>
        <DisclosureSummary id='system-prompt-input-label' className='font-700'>
          <span>
            システムプロンプト
            <span className='font-400'>
              {systemContextTitle
                ? `（このチャットの役割：${systemContextTitle}）`
                : '（このチャットの役割）'}
            </span>
          </span>
        </DisclosureSummary>
        <div>
          {loadingMessages && <p>システムプロンプトを読み込み中...</p>}

          {isNewChat && (
            <div className='flex flex-col gap-2 py-2 lg:pt-0 lg:pb-3'>
              <div className='self-end'>
                <Button
                  variant='outline'
                  size='sm'
                  aria-haspopup='dialog'
                  onClick={() => setShowPromptListDialog(true)}
                >
                  プロンプト一覧から選ぶ
                </Button>
              </div>
              <div>
                <AutoResizeTextarea
                  id='system-prompt-input'
                  className='resize-none'
                  placeholder='システムプロンプトを入力'
                  value={inputSystemContext}
                  aria-labelledby='system-prompt-input-label'
                  onChange={(e) => {
                    setInputSystemContext(e.target.value);
                  }}
                />
              </div>
              <div className='flex justify-center mt-2'>
                <Button
                  variant='outline'
                  size='md'
                  aria-haspopup='dialog'
                  onClick={() => {
                    setSaveSystemContext(inputSystemContext);
                    setShowSystemContextDialog(true);
                  }}
                >
                  このプロンプトを保存
                </Button>
              </div>
            </div>
          )}

          {isCurrentChat && (
            <div className='flex flex-col gap-2 py-2 lg:pb-3'>
              <div className='flex flex-col gap-2'>
                <SupportText id='system-prompt-input-support' className='text-dns-14N-130!'>
                  会話を開始したチャットのシステムプロンプトは編集できません
                </SupportText>
                <AutoResizeTextarea
                  id='current-system-prompt-input'
                  className='resize-none'
                  value={currentSystemContext}
                  aria-labelledby='system-prompt-input-label'
                  aria-describedby='system-prompt-input-support'
                  readOnly
                />
              </div>
              <div className='flex justify-center mt-2'>
                <Button
                  variant='outline'
                  size='md'
                  onClick={() => {
                    setSaveSystemContext(currentSystemContext);
                    setShowSystemContextDialog(true);
                  }}
                >
                  このプロンプトを保存
                </Button>
              </div>
            </div>
          )}
        </div>
      </Disclosure>
    </div>
  );
};
